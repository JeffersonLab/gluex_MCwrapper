#!/usr/bin/env python3
##########################################################################################################################
#
# MCFailedLogs.py -- collect the stdout/stderr of failed attempts
#
#   Finds attempts that failed inside a time window (default: the last 24 hours), asks condor_history where each one's
#   stdout/stderr went, and copies them into a folder as P<project>_J<job>_A<attempt>.out / .err, plus a manifest.tsv.
#   Failure modes match the Dashboard Health tab: condor, missing output, randoms (retried), lost (status N),
#   the failing program (hd_root, mcsmear, ...) or "exit N".
#
#   Run on the submit host (it needs condor_history and the schedd's history). Logs that are no longer on /osgpool
#   are fetched from dtn1902 the same way FastOverlord does.
#
#   Examples:
#     MCFailedLogs.py                                      all failures in the last 24 h
#     MCFailedLogs.py --list-modes                         failure modes and counts only, copies nothing
#     MCFailedLogs.py --hours 6 --mode hd_root             hd_root failures in the last 6 h
#     MCFailedLogs.py --since "2026-10-14 00:00" --until "2026-10-15 00:00" --exit-code 255 --project 4944
#     MCFailedLogs.py --mode condor --mode "missing output" --group-by-mode --out /tmp/failures
#
##########################################################################################################################
import argparse
import csv
import json
import os
import pwd
import re
import shutil
import socket
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import MySQLdb
import MySQLdb.cursors

dbhost = "hallddb.jlab.org"
dbuser = "mcuser"
dbname = "gluex_mc"

runner_name = pwd.getpwuid(os.getuid())[0]
DTN_PREFIX = runner_name + "@dtn1902:/cache/halld/gluex_simulations/REQUESTED_MC/"
HISTORY_ATTRS = ["ClusterId", "ProcId", "Out", "Err", "Iwd", "ExitCode", "JobStatus", "EnteredCurrentStatus"]
HISTORY_SINCE_MARGIN = 2 * 86400  # seconds of slack before the oldest attempt's Creation_Time
MAX_EXPLICIT_CLUSTERS = 200       # above this the condor_history constraint becomes a ClusterId range
TIME_FMT = "%Y-%m-%d %H:%M"


def log(*a):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), *a, flush=True)


def run_cmd(args, timeout=None):
    """Returns (returncode, stdout, stderr); returncode -1 on timeout/launch failure."""
    try:
        p = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, universal_newlines=True)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "timeout after %ss" % timeout
    except OSError as e:
        return -1, "", str(e)


######################################################### DATABASE #########################################################

def failure_mode(status, exit_code, program_failed):
    """Same buckets as the Dashboard Health tab (php/health.php failureCause)."""
    if exit_code is None:
        return "lost (status %s)" % status
    exit_code = int(exit_code)
    if exit_code == 999:
        return "condor"
    if exit_code == 404:
        return "missing output"
    if exit_code == -232:
        return "randoms (retried)"
    if program_failed:
        return str(program_failed)
    return "exit %d" % exit_code


def first_id_since(cur, max_id, when):
    """Smallest Attempts.ID created at or after `when`: binary search on the primary key (Attempts has no time index)."""
    lo, hi = 1, max_id + 1
    while lo < hi:
        mid = (lo + hi) // 2
        cur.execute("SELECT ID, Creation_Time FROM Attempts WHERE ID >= %s ORDER BY ID LIMIT 1", (mid,))
        row = cur.fetchone()
        if row is None or (row["Creation_Time"] is not None and row["Creation_Time"] >= when):
            hi = mid
        else:
            lo = row["ID"] + 1
    return lo


def fetch_failed(cur, args, since, until, db_now):
    cur.execute("SELECT MAX(ID) m FROM Attempts")
    max_id = int(cur.fetchone()["m"])
    scan_from = first_id_since(cur, max_id, since - timedelta(days=args.scan_days))
    # attempts created after the window closed cannot have failed inside it
    to_id = max_id + 1 if until >= db_now - timedelta(minutes=1) else first_id_since(cur, max_id, until)

    sql = ("SELECT a.ID, a.Job_ID, j.Project_ID, a.BatchJobID, a.SubmitHost, a.Status, a.ExitCode, a.ProgramFailed, "
           "a.Creation_Time, a.Completed_Time "
           "FROM Attempts a JOIN Jobs j ON j.ID = a.Job_ID "
           "WHERE a.ID >= %s AND a.ID < %s AND a.BatchSystem = 'OSG' AND a.Status != '3' "
           "AND a.Completed_Time >= %s AND a.Completed_Time <= %s "
           "AND ((a.ExitCode IS NOT NULL AND a.ExitCode != 0) OR a.Status = '6')")
    params = [scan_from, to_id, since, until]
    if not args.any_host:
        sql += " AND a.SubmitHost = %s"
        params.append(socket.gethostname())
    if args.project:
        sql += " AND j.Project_ID IN (" + ",".join(["%s"] * len(args.project)) + ")"
        params += args.project
    if args.exit_code:
        sql += " AND a.ExitCode IN (" + ",".join(["%s"] * len(args.exit_code)) + ")"
        params += args.exit_code
    sql += " ORDER BY a.ID DESC"
    cur.execute(sql, params)

    rows = []
    wanted = [m.lower() for m in args.mode or []]
    for r in cur.fetchall():
        r["Mode"] = failure_mode(r["Status"], r["ExitCode"], r["ProgramFailed"])
        if wanted and not any(w in r["Mode"].lower() for w in wanted):
            continue
        rows.append(r)
    return rows


########################################################## CONDOR ##########################################################

def parse_bid(bid):
    """BatchJobID -> (cluster, proc or None); None if unparseable."""
    try:
        parts = str(bid).strip().split(".")
        return int(parts[0]), (int(parts[1]) if len(parts) > 1 and parts[1] != "" else None)
    except (ValueError, TypeError):
        return None


def condor_json(args, timeout):
    rc, out, err = run_cmd(args, timeout)
    if rc != 0:
        raise RuntimeError("%s failed (rc=%s): %s" % (args[0], rc, err.strip()[:500]))
    out = out.strip()
    return json.loads(out) if out else []


def lookup_ad(by_id, by_cluster, bid):
    parsed = parse_bid(bid)
    if parsed is None:
        return None
    c, p = parsed
    return by_cluster.get(c) if p is None else by_id.get("%d.%d" % (c, p))


def history_ads(attempts, workers, confirm):
    """attempt ID -> condor_history ad, from one bulk query plus per-job retries for anything it missed."""
    clusters = sorted(set(p[0] for p in (parse_bid(a["BatchJobID"]) for a in attempts) if p is not None))
    if not clusters:
        return {}
    if len(clusters) <= MAX_EXPLICIT_CLUSTERS:
        constraint = " || ".join("ClusterId == %d" % c for c in clusters)
    else:
        constraint = "ClusterId >= %d && ClusterId <= %d" % (clusters[0], clusters[-1])
    args = ["condor_history", "-json", "-attributes", ",".join(HISTORY_ATTRS), "-constraint", constraint]
    ctimes = [a["Creation_Time"] for a in attempts if a["Creation_Time"] is not None]
    if ctimes:
        since = int(time.mktime(min(ctimes).timetuple())) - HISTORY_SINCE_MARGIN
        args += ["-since", "EnteredCurrentStatus < %d" % since]

    t0 = time.time()
    by_id, by_cluster = {}, {}
    for ad in condor_json(args, 3600):
        c, p = ad.get("ClusterId"), ad.get("ProcId") or 0
        if c is None:
            continue
        by_id.setdefault("%d.%d" % (c, p), ad)  # history is newest-first
        if c not in by_cluster or p < (by_cluster[c].get("ProcId") or 0):
            by_cluster[c] = ad
    log("condor_history: %d ads in %.1fs" % (len(by_id), time.time() - t0))

    found, missing = {}, []
    for a in attempts:
        ad = lookup_ad(by_id, by_cluster, a["BatchJobID"])
        if ad is not None:
            found[a["ID"]] = ad
        elif parse_bid(a["BatchJobID"]) is not None:
            missing.append(a)

    if missing and confirm:
        log("retrying %d attempts individually" % len(missing))

        def one(a):
            try:
                ads = condor_json(["condor_history", "-limit", "1", "-json", "-attributes", ",".join(HISTORY_ATTRS),
                                   str(a["BatchJobID"]).strip()], 600)
            except (RuntimeError, ValueError):
                return None
            return ads[0] if ads else None

        with ThreadPoolExecutor(max_workers=workers) as pool:
            for a, ad in zip(missing, pool.map(one, missing)):
                if ad is not None:
                    found[a["ID"]] = ad
    return found


########################################################### COPY ###########################################################

def log_path(ad, key):
    path = ad.get(key)
    if not path or path == "/dev/null":
        return None
    path = str(path)
    if not os.path.isabs(path) and ad.get("Iwd"):
        path = os.path.join(str(ad["Iwd"]), path)
    return path


def fetch(src, dest):
    """Copy src to dest. Returns 'local', 'dtn' or 'missing'."""
    if src is None:
        return "missing"
    if os.path.isfile(src):
        shutil.copy2(src, dest)
        return "local"
    if "REQUESTEDMC_OUTPUT" in src:
        remote = DTN_PREFIX + src.split("REQUESTEDMC_OUTPUT", 1)[1].lstrip("/")
        rc, out, err = run_cmd(["scp", "-q", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", remote, dest], 300)
        if rc == 0 and os.path.isfile(dest):
            return "dtn"
    return "missing"


def safe_name(s):
    return re.sub(r"[^A-Za-z0-9_.()-]+", "_", s).strip("_") or "unknown"


########################################################### MAIN ###########################################################

def parse_time(s):
    try:
        return datetime.strptime(s, TIME_FMT)
    except ValueError:
        raise argparse.ArgumentTypeError("expected \"YYYY-MM-DD HH:MM\" (JLab local time), got %r" % s)


def main():
    ap = argparse.ArgumentParser(description="Copy stdout/stderr of failed attempts into a folder, named P<project>_J<job>_A<attempt>.")
    win = ap.add_argument_group("time window (JLab local time; default: the last 24 hours)")
    win.add_argument("--hours", type=float, default=24, help="look back this many hours from --until (default 24)")
    win.add_argument("--since", type=parse_time, help="window start, \"YYYY-MM-DD HH:MM\" (overrides --hours)")
    win.add_argument("--until", type=parse_time, help="window end, \"YYYY-MM-DD HH:MM\" (default now)")
    flt = ap.add_argument_group("filters")
    flt.add_argument("--mode", action="append",
                     help="failure mode to keep, case-insensitive substring (e.g. hd_root, condor, \"missing output\", \"exit 255\"); repeatable")
    flt.add_argument("--exit-code", type=int, action="append", help="exit code to keep; repeatable")
    flt.add_argument("--project", type=int, action="append", help="project ID to keep; repeatable")
    flt.add_argument("--any-host", action="store_true", help="include attempts submitted from other hosts (their history may not be here)")
    flt.add_argument("--limit", type=int, default=0, help="only the N most recent failures (default all)")
    out = ap.add_argument_group("output")
    out.add_argument("--out", help="destination folder (default ./failed_logs_<since>_to_<until>)")
    out.add_argument("--group-by-mode", action="store_true", help="put each failure mode in its own subfolder")
    out.add_argument("--list-modes", action="store_true", help="print failure modes and counts, copy nothing")
    out.add_argument("--dry-run", action="store_true", help="resolve log locations and print them, copy nothing")
    ap.add_argument("--workers", type=int, default=8, help="parallel copies / condor_history retries (default 8)")
    ap.add_argument("--no-confirm", action="store_true", help="skip per-job condor_history retries for jobs the bulk query missed")
    ap.add_argument("--scan-days", type=int, default=10,
                    help="attempts created this many days before the window start are still considered (default 10)")
    args = ap.parse_args()

    cnx = MySQLdb.connect(host=dbhost, user=dbuser, db=dbname)
    cur = cnx.cursor(MySQLdb.cursors.DictCursor)
    cur.execute("SELECT NOW() n")
    db_now = cur.fetchone()["n"]
    until = min(args.until or db_now, db_now)
    since = args.since or (until - timedelta(hours=args.hours))
    if since >= until:
        sys.exit("window start must be before its end")
    log("failed attempts completed %s .. %s" % (since.strftime(TIME_FMT), until.strftime(TIME_FMT)))

    attempts = fetch_failed(cur, args, since, until, db_now)
    cnx.close()
    if args.limit:
        attempts = attempts[:args.limit]
    modes = Counter(a["Mode"] for a in attempts)
    log("%d failed attempts in %d modes" % (len(attempts), len(modes)))
    for mode, n in modes.most_common():
        print("  %7d  %s" % (n, mode))
    if args.list_modes or not attempts:
        return

    if shutil.which("condor_history") is None:
        sys.exit("condor_history not found: run this on the submit host")
    ads = history_ads(attempts, args.workers, not args.no_confirm)

    dest_root = args.out or "failed_logs_%s_to_%s" % (since.strftime("%Y%m%d-%H%M"), until.strftime("%Y%m%d-%H%M"))
    plan = []
    for a in attempts:
        ad = ads.get(a["ID"], {})
        folder = os.path.join(dest_root, safe_name(a["Mode"])) if args.group_by_mode else dest_root
        stem = os.path.join(folder, "P%s_J%s_A%s" % (a["Project_ID"], a["Job_ID"], a["ID"]))
        plan.append((a, folder, stem, log_path(ad, "Out"), log_path(ad, "Err"), bool(ad)))

    if args.dry_run:
        for a, folder, stem, out_src, err_src, in_hist in plan:
            print("%s\t%s\tout=%s\terr=%s" % (os.path.basename(stem), a["Mode"], out_src or "-", err_src or "-"))
        log("dry run: %d attempts, %d without a condor_history record" % (len(plan), sum(1 for p in plan if not p[5])))
        return

    for folder in set(p[1] for p in plan):
        os.makedirs(folder, exist_ok=True)

    def copy_one(p):
        a, folder, stem, out_src, err_src, in_hist = p
        return fetch(out_src, stem + ".out"), fetch(err_src, stem + ".err")

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(copy_one, plan))

    manifest = os.path.join(dest_root, "manifest.tsv")
    with open(manifest, "w", newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(["file", "project", "job", "attempt", "batch_job_id", "mode", "exit_code", "status", "completed",
                    "in_condor_history", "out_source", "out_copied", "err_source", "err_copied"])
        for (a, folder, stem, out_src, err_src, in_hist), (out_res, err_res) in zip(plan, results):
            w.writerow([os.path.relpath(stem, dest_root), a["Project_ID"], a["Job_ID"], a["ID"], a["BatchJobID"],
                        a["Mode"], a["ExitCode"], a["Status"], a["Completed_Time"], "yes" if in_hist else "no",
                        out_src or "", out_res, err_src or "", err_res])

    got = Counter()
    for out_res, err_res in results:
        got[out_res] += 1
        got[err_res] += 1
    log("copied in %.1fs: %d local, %d from dtn1902, %d missing (of %d files)"
        % (time.time() - t0, got["local"], got["dtn"], got["missing"], 2 * len(results)))
    log("output: %s (see %s)" % (os.path.abspath(dest_root), manifest))


if __name__ == "__main__":
    main()
