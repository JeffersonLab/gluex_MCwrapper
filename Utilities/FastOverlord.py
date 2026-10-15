#!/usr/bin/env python3
##########################################################################################################################
#
# FastOverlord.py -- bulk replacement for MCOverlord.py
#
#   MCOverlord ran one condor_q (and, once a job left the queue, one condor_history) subprocess per tracked job and
#   committed one UPDATE per job.  FastOverlord instead, per pass:
#     * pulls every tracked job's ClassAd with ONE condor_q call
#     * pulls every job that left the queue with ONE condor_history call bounded by -since
#       (jobs still not found are confirmed individually, exactly as MCOverlord did, before being marked 999/condor)
#     * derives the Attempts columns with the same rules as MCOverlord.checkOSG
#     * writes only rows whose values changed, batched, parameterized, a few commits per pass
#     * lists each project's output directory once instead of one `pelican object ls` per expected file
#     * runs the per-project `du` calls in parallel; du and completion checks run every --heavy-every passes
#
#   Loops forever with no sleep between passes. Cron it every minute as a watchdog: a copy that finds one already
#   running exits silently, and any copy exits if MCOverlord.py is running.
#     * * * * * python3 /scigroup/mcwrapper/gluex_MCwrapper/Utilities/FastOverlord.py >> ~/FastOverlord.log 2>&1
#
#   Testing:
#     FastOverlord.py --once --dry-run            one full pass, write nothing, print what would change
#     FastOverlord.py --validate 200              compare bulk ClassAd matching vs. MCOverlord-style per-job queries
#
##########################################################################################################################
import argparse
import fcntl
import json
import os
import pwd
import random
import shlex
import shutil
import smtplib
import socket
import subprocess
import sys
import tempfile
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from email.message import EmailMessage
from subprocess import PIPE

import MySQLdb
import MySQLdb.cursors

MCWRAPPER_BOT_HOST_NAME = socket.gethostname()
dbhost = "hallddb.jlab.org"
dbuser = 'mcuser'
dbname = 'gluex_mc'

runner_name = pwd.getpwuid(os.getuid())[0]

PELICAN_OUTPUT = "osdf://jlab-osdf/gluex/osgpool/REQUESTEDMC_OUTPUT/"
PELICAN_RANDOMS = "osdf://jlab-osdf/gluex/osgpool/random_triggers/"
PELICAN_SCRUB = "osdf://jlab-osdf/gluex/osgpool/to_be_scrubbed/"
OSGPOOL_OUTPUT = "/osgpool/halld/" + runner_name + "/REQUESTEDMC_OUTPUT/"

CONDOR_ATTRS = [
    "ClusterId", "ProcId", "JobStatus", "NumJobStarts", "ExitCode", "JobFinishedHookDone",
    "RemoteWallClockTime", "RemoteUserCpu", "JobStartDate", "ImageSize_RAW", "ImageSize",
    "TransferInputSizeMB", "RemoteHost", "LastRemoteHost", "HoldReasonCode", "TransferInput",
    "LastPublicClaimId", "Out", "EnteredCurrentStatus",
]

# Attempts columns FastOverlord writes, and how to compare DB values against freshly derived ones
COLUMN_KIND = {
    "NumStarts": "int", "Status": "str", "ExitCode": "int", "Start_Time": "dt", "Completed_Time": "dt",
    "RunningLocation": "str", "WallTime": "time", "CPUTime": "time", "RAMUsed": "str", "Size_In": "int",
    "RunIP": "str", "ProgramFailed": "str",
}

HISTORY_SINCE_MARGIN = 2 * 86400  # seconds of slack before the oldest missing attempt's Creation_Time
DB_BATCH = 1000

# Old Tested values that mean "already past completion bookkeeping"
TESTED_NO_REBUNDLE = (100, 21, 41, 40, 400, 20)


def log(*a):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), *a, flush=True)


def db_connect(autocommit=False):
    cnx = MySQLdb.connect(host=dbhost, user=dbuser, db=dbname)
    cnx.autocommit(autocommit)
    return cnx, cnx.cursor(MySQLdb.cursors.DictCursor)


def run_cmd(args, timeout=None, env=None):
    """Returns (returncode, stdout, stderr); returncode -1 on timeout/launch failure."""
    try:
        p = subprocess.run(args, stdout=PIPE, stderr=PIPE, timeout=timeout, env=env, universal_newlines=True)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "timeout after %ss: %s" % (timeout, " ".join(args))
    except OSError as e:
        return -1, "", str(e)


def pelican_env():
    env = os.environ.copy()
    env["BEARER_TOKEN_FILE"] = "/var/run/user/10967/bt_u10967"
    env["XDG_RUNTIME_DIR"] = "/run/user/10967"
    return env


def pelican_has(server, relpath, name, timeout=120):
    """MCOverlord's file test: no 'Failure getting <server>' on stderr and the name appears on stdout."""
    rc, out, err = run_cmd(["pelican", "object", "ls", server + relpath], timeout, pelican_env())
    return ("Failure getting " + server) not in err and name in out


def pelican_listing(server, relpath, timeout=300):
    """Basenames in a pelican collection, or None if it could not be listed."""
    rc, out, err = run_cmd(["pelican", "object", "ls", server + relpath], timeout, pelican_env())
    if rc != 0 or "Failure getting" in err:
        return None
    return set(os.path.basename(tok.rstrip("/")) for tok in out.split())


class Writer:
    """All DB writes go through here so --dry-run can suppress them."""

    def __init__(self, cnx, cur, dry):
        self.cnx, self.cur, self.dry = cnx, cur, dry
        self.dry_shown = 0

    def _show(self, sql, params):
        if self.dry_shown < 25:
            log("DRY-RUN would execute:", sql, params)
        self.dry_shown += 1

    def execute(self, sql, params=()):
        if self.dry:
            self._show(sql, params)
            return
        self.cur.execute(sql, params)
        self.cnx.commit()

    def executemany(self, sql, rows):
        if not rows:
            return
        if self.dry:
            self._show(sql, "%d rows, first: %s" % (len(rows), rows[0]))
            return
        for i in range(0, len(rows), DB_BATCH):
            self.cur.executemany(sql, rows[i:i + DB_BATCH])
            self.cnx.commit()

    def update_attempts(self, updates):
        """updates: list of (attempt_id, {column: value}); grouped by column set so each group is one statement."""
        groups = {}
        for aid, fields in updates:
            cols = tuple(sorted(fields))
            groups.setdefault(cols, []).append(tuple(fields[c] for c in cols) + (aid,))
        for cols, rows in groups.items():
            sql = "UPDATE Attempts SET " + ", ".join("%s=%%s" % c for c in cols) + " WHERE ID=%s"
            self.executemany(sql, rows)


########################################################## CONDOR ##########################################################

def parse_bid(bid):
    """BatchJobID -> (cluster, proc or None); None if unparseable."""
    try:
        parts = str(bid).strip().split(".")
        return int(parts[0]), (int(parts[1]) if len(parts) > 1 and parts[1] != "" else None)
    except (ValueError, TypeError):
        return None


def index_ads(ads):
    """First ad per Cluster.Proc (condor_history is newest-first, matching -limit 1), and lowest proc per cluster."""
    by_id, by_cluster = {}, {}
    for ad in ads:
        c, p = ad.get("ClusterId"), ad.get("ProcId") or 0
        if c is None or "JobStatus" not in ad:
            continue
        by_id.setdefault("%d.%d" % (c, p), ad)
        prev = by_cluster.get(c)
        if prev is None or p < (prev.get("ProcId") or 0):
            by_cluster[c] = ad
    return by_id, by_cluster


def lookup(idx, bid):
    """Same ad `condor_q <BatchJobID> -json` would return first."""
    parsed = parse_bid(bid)
    if parsed is None:
        return None
    c, p = parsed
    if p is None:
        return idx[1].get(c)
    return idx[0].get("%d.%d" % (c, p))


def condor_json(args, timeout):
    rc, out, err = run_cmd(args, timeout)
    if rc != 0:
        raise RuntimeError("%s failed (rc=%s): %s" % (args[0], rc, err.strip()[:500]))
    out = out.strip()
    return json.loads(out) if out else []


def bulk_queue(min_cluster):
    args = ["condor_q", "-allusers", "-json", "-attributes", ",".join(CONDOR_ATTRS),
            "-constraint", "ClusterId >= %d" % min_cluster]
    return condor_json(args, 900)


def bulk_history(min_cluster, max_cluster, since_ts):
    base = ["condor_history", "-json", "-attributes", ",".join(CONDOR_ATTRS),
            "-constraint", "ClusterId >= %d && ClusterId <= %d" % (min_cluster, max_cluster)]
    if since_ts is not None:
        try:
            return condor_json(base + ["-since", "EnteredCurrentStatus < %d" % since_ts], 1800)
        except RuntimeError as e:
            log("condor_history -since failed, retrying unbounded:", e)
    return condor_json(base, 3600)


def single_history(bid):
    """MCOverlord's per-job history query. Returns ('ad', ad), ('empty', None) or ('skip', None)."""
    rc, out, err = run_cmd(["condor_history", "-limit", "1", str(bid), "-json"], 600)
    if rc != 0:
        return "skip", None
    if out == "[\n]\n":
        return "empty", None
    if out.strip() == "":
        return "skip", None
    try:
        ads = json.loads(out)
    except ValueError:
        return "skip", None
    return ("ad", ads[0]) if ads else ("skip", None)


def single_queue(bid):
    """MCOverlord's per-job queue query. Returns ad or None (not in queue) or 'error'."""
    rc, out, err = run_cmd(["condor_q", str(bid), "-json"], 300)
    if rc != 0:
        return "error"
    if out.strip() == "":
        return None
    ads = json.loads(out)
    return ads[0] if ads else None


#################################################### FIELD DERIVATION ######################################################
# Ported from MCOverlord.checkOSG; keep in sync with its semantics.

def fmt_hms(seconds):
    return time.strftime("%H:%M:%S", time.gmtime(timedelta(seconds=seconds).seconds))


def from_ts(v):
    return datetime.fromtimestamp(float(v))


def run_ip(ad):
    if "LastPublicClaimId" not in ad:
        return "NULL"
    ipstr = str(ad["LastPublicClaimId"]).split("#")[0]
    return ipstr[1:-1].split(":")[0]


def common_fields(ad):
    fields = {
        "NumStarts": int(ad.get("NumJobStarts", 0)),
        "Start_Time": from_ts(ad.get("JobStartDate", 0)),
        "WallTime": fmt_hms(ad.get("RemoteWallClockTime", 0)),
        "CPUTime": fmt_hms(ad.get("RemoteUserCpu", 0)),
        "RAMUsed": str(float(ad.get("ImageSize_RAW", ad.get("ImageSize", 0))) / float(1024)),
        "RunIP": str(run_ip(ad)),
    }
    if ad.get("TransferInputSizeMB") is not None:
        fields["Size_In"] = ad["TransferInputSizeMB"]
    if ad["JobStatus"] >= 3 and "JobFinishedHookDone" in ad:
        fields["Completed_Time"] = from_ts(ad["JobFinishedHookDone"])
    return fields


def queue_update(ad):
    """Job still in condor_q. Returns (fields, deactivate_job)."""
    status = ad["JobStatus"]
    exit_code = None
    if status != 3 and "ExitCode" in ad:
        exit_code = ad["ExitCode"]
    if status == 2:
        exit_code = None

    fields = common_fields(ad)
    fields["RunningLocation"] = str(ad.get("RemoteHost", "NA"))

    deactivate = False
    if status == 5:
        found = True
        for f in str(ad.get("TransferInput", "")).split(","):
            if "_random.hddm" in f:
                found = os.path.isfile(f)
        if not found:
            status = 6
            deactivate = True

    fields["Status"] = str(status)
    fields["ExitCode"] = exit_code
    return fields, deactivate


class PassContext:
    """Per-pass caches and scratch space for the I/O-bound parts of history processing."""

    def __init__(self):
        self.random_cache = {}
        self.tmpdir = tempfile.mkdtemp(prefix="fastoverlord_")

    def random_found(self, random_dir, run_number):
        key = (random_dir, run_number)
        if key not in self.random_cache:
            name = "run" + str(run_number).zfill(6) + "_random.hddm"
            try:
                self.random_cache[key] = pelican_has(PELICAN_RANDOMS, random_dir + "/" + name, name)
            except Exception as e:
                log("random check error:", e)
                self.random_cache[key] = False
        return self.random_cache[key]

    def failed_program(self, std_out_loc):
        """Last 'Something went wrong with X' token from the job stdout; 'Unidentified' if unreadable; None if absent."""
        std_out_loc = str(std_out_loc)
        if not os.path.isfile(std_out_loc) and "REQUESTEDMC_OUTPUT" in std_out_loc:
            local = os.path.join(self.tmpdir, std_out_loc.split("/")[-1])
            remote = runner_name + "@dtn1902:/cache/halld/gluex_simulations/REQUESTED_MC/" + std_out_loc.split("REQUESTEDMC_OUTPUT")[1]
            run_cmd(["scp", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", remote, local], 120)
            std_out_loc = local
        failed = None
        try:
            with open(std_out_loc) as fh:
                for line in fh:
                    if "Something went wrong with" in line:
                        failed = line.strip().split(" ")[-1]
        except Exception:
            failed = "Unidentified"
        return failed

    def close(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)


def history_update(ad, attempt, ctx):
    """Job has left the queue. Returns (fields, deactivate_job)."""
    status = ad["JobStatus"]
    exit_code = None
    if status != 3 and "ExitCode" in ad:
        exit_code = ad["ExitCode"]

    fields = common_fields(ad)
    fields["RunningLocation"] = str(ad.get("LastRemoteHost", "NULL"))

    if status == 5:
        found = False
        for f in str(ad.get("TransferInput", "")).split(","):
            if ".hddm" in f:
                found = os.path.isfile(f)
        if not found:
            status = 6

    deactivate = False
    if str(exit_code) in ("232", "1000") and attempt.get("RunNumber") is not None and attempt.get("BKG") is not None:
        bkg_parts = attempt["BKG"].split(":")
        if len(bkg_parts) != 1:
            if ctx.random_found(bkg_parts[1].split("+")[0], attempt["RunNumber"]):
                status = 4
                exit_code = -232
            else:
                status = 6
                deactivate = True

    if exit_code is not None and str(exit_code) != "0":
        failed = ctx.failed_program(ad.get("Out", ""))
        if failed is not None:
            fields["ProgramFailed"] = failed

    fields["Status"] = str(status)
    fields["ExitCode"] = exit_code
    return fields, deactivate


EMPTY_HISTORY_FIELDS = {"Status": "4", "ExitCode": 999, "ProgramFailed": "condor"}


def canon(kind, v):
    if v is None:
        return None
    if kind == "time":
        if isinstance(v, timedelta):
            s = int(v.total_seconds())
            return "%02d:%02d:%02d" % (s // 3600, (s % 3600) // 60, s % 60)
        return str(v)
    if kind == "dt":
        return v.replace(microsecond=0).isoformat(" ") if isinstance(v, datetime) else str(v)
    if kind == "int":
        try:
            return int(v)
        except (TypeError, ValueError):
            return str(v)
    return str(v)


def changed(fields, row):
    return any(canon(COLUMN_KIND[c], v) != canon(COLUMN_KIND[c], row.get(c)) for c, v in fields.items())


########################################################## OSG PASS ##########################################################

ACTIVE_ATTEMPTS_Q = (
    "SELECT a.ID, a.Job_ID, a.BatchJobID, a.Creation_Time, " + ", ".join("a." + c for c in COLUMN_KIND) +
    ", j.RunNumber, p.BKG FROM Attempts a "
    "LEFT JOIN Jobs j ON j.ID = a.Job_ID LEFT JOIN Project p ON p.ID = j.Project_ID "
    "WHERE a.BatchSystem='OSG' AND a.SubmitHost=%s AND a.Status!='4' AND a.Status!='3' AND a.Status!='6'"
)


def fetch_active_attempts(cur, sample=0):
    cur.execute(ACTIVE_ATTEMPTS_Q, (MCWRAPPER_BOT_HOST_NAME,))
    attempts = list(cur.fetchall())
    if sample and len(attempts) > sample:
        attempts = random.sample(attempts, sample)
    return attempts


def resolve_bulk(attempts, trust_bulk_history, workers):
    """attempt ID -> ('queue', ad) | ('history', ad) | ('empty', None). Attempts that cannot be resolved are omitted.
    Raises if condor_q fails, so a schedd outage never looks like every job vanished."""
    parsed = [parse_bid(a["BatchJobID"]) for a in attempts]
    clusters = [p[0] for p in parsed if p is not None]
    if not clusters:
        return {}
    t0 = time.time()
    qidx = index_ads(bulk_queue(min(clusters)))
    log("condor_q: %d ads in %.1fs" % (len(qidx[0]), time.time() - t0))

    resolved, missing = {}, []
    for a in attempts:
        ad = lookup(qidx, a["BatchJobID"])
        if ad is not None:
            resolved[a["ID"]] = ("queue", ad)
        elif parse_bid(a["BatchJobID"]) is not None:
            missing.append(a)
    if not missing:
        return resolved

    mclusters = [parse_bid(a["BatchJobID"])[0] for a in missing]
    ctimes = [a["Creation_Time"] for a in missing if a["Creation_Time"] is not None]
    since = int(time.mktime(min(ctimes).timetuple())) - HISTORY_SINCE_MARGIN if len(ctimes) == len(missing) else None
    t0 = time.time()
    try:
        hidx = index_ads(bulk_history(min(mclusters), max(mclusters), since))
    except RuntimeError as e:
        log("condor_history bulk failed; leaving %d out-of-queue attempts for next pass: %s" % (len(missing), e))
        return resolved
    log("condor_history: %d ads in %.1fs for %d out-of-queue attempts" % (len(hidx[0]), time.time() - t0, len(missing)))

    not_found = []
    for a in missing:
        ad = lookup(hidx, a["BatchJobID"])
        if ad is not None:
            resolved[a["ID"]] = ("history", ad)
        else:
            not_found.append(a)

    if not_found:
        if trust_bulk_history:
            for a in not_found:
                resolved[a["ID"]] = ("empty", None)
        else:
            log("confirming %d attempts absent from bulk history with per-job condor_history" % len(not_found))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                for a, (kind, ad) in zip(not_found, pool.map(lambda a: single_history(a["BatchJobID"]), not_found)):
                    if kind == "ad":
                        resolved[a["ID"]] = ("history", ad)
                    elif kind == "empty":
                        resolved[a["ID"]] = ("empty", None)
    return resolved


def resolve_per_job(attempts, workers):
    """MCOverlord-style resolution (one condor_q, then one condor_history, per attempt). Used by --validate."""
    def one(a):
        ad = single_queue(a["BatchJobID"])
        if ad == "error":
            return None
        if ad is not None:
            return ("queue", ad)
        kind, ad = single_history(a["BatchJobID"])
        if kind == "ad":
            return ("history", ad)
        if kind == "empty":
            return ("empty", None)
        return None

    resolved = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for a, r in zip(attempts, pool.map(one, attempts)):
            if r is not None:
                resolved[a["ID"]] = r
    return resolved


def build_updates(attempts, resolved, ctx, workers):
    """attempt ID -> (fields, deactivate_job)."""
    by_id = {a["ID"]: a for a in attempts}

    def one(aid):
        kind, ad = resolved[aid]
        try:
            if kind == "queue":
                return aid, queue_update(ad)
            if kind == "history":
                return aid, history_update(ad, by_id[aid], ctx)
            return aid, (dict(EMPTY_HISTORY_FIELDS), False)
        except Exception as e:
            log("could not derive fields for attempt", aid, by_id[aid]["BatchJobID"], ":", repr(e))
            return aid, None

    out = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for aid, r in pool.map(one, list(resolved)):
            if r is not None:
                out[aid] = r
    return out


def check_osg(cur, writer, args):
    t0 = time.time()
    attempts = fetch_active_attempts(cur, args.sample)
    log("tracking %d active OSG attempts on %s" % (len(attempts), MCWRAPPER_BOT_HOST_NAME))
    if not attempts:
        return
    resolved = resolve_bulk(attempts, args.trust_bulk_history, args.workers)
    ctx = PassContext()
    try:
        derived = build_updates(attempts, resolved, ctx, args.workers)
    finally:
        ctx.close()

    by_id = {a["ID"]: a for a in attempts}
    updates, deactivate = [], set()
    for aid, (fields, deact) in derived.items():
        if args.force_all or changed(fields, by_id[aid]):
            updates.append((aid, fields))
        if deact and by_id[aid]["Job_ID"] is not None:
            deactivate.add(by_id[aid]["Job_ID"])

    kinds = {}
    for kind, _ in resolved.values():
        kinds[kind] = kinds.get(kind, 0) + 1
    log("resolved %s; unresolved %d; %d rows changed; %d jobs to deactivate"
        % (kinds, len(attempts) - len(resolved), len(updates), len(deactivate)))

    writer.update_attempts(updates)
    writer.executemany("UPDATE Jobs SET IsActive=0 WHERE ID=%s", [(j,) for j in sorted(deactivate)])
    log("OSG pass done in %.1fs" % (time.time() - t0))


def validate(cur, args):
    """Compare bulk vs per-job resolution on a random sample; prints every field that differs."""
    attempts = fetch_active_attempts(cur, args.validate)
    log("validating %d attempts" % len(attempts))
    bulk = resolve_bulk(attempts, False, args.workers)
    single = resolve_per_job(attempts, args.workers)
    ctx = PassContext()
    try:
        b = build_updates(attempts, bulk, ctx, args.workers)
        s = build_updates(attempts, single, ctx, args.workers)
    finally:
        ctx.close()
    mism = 0
    for a in attempts:
        aid = a["ID"]
        bk, sk = bulk.get(aid, ("unresolved",))[0], single.get(aid, ("unresolved",))[0]
        bf, sf = b.get(aid, ({}, False))[0], s.get(aid, ({}, False))[0]
        diffs = {c: (bf.get(c), sf.get(c)) for c in set(bf) | set(sf)
                 if canon(COLUMN_KIND[c], bf.get(c)) != canon(COLUMN_KIND[c], sf.get(c))}
        if bk != sk or diffs:
            mism += 1
            log("MISMATCH attempt %s job %s: source bulk=%s per-job=%s diffs(bulk, per-job)=%s"
                % (aid, a["BatchJobID"], bk, sk, diffs))
    log("validation: %d/%d attempts differ (jobs changing state between the two queries can cause a few)"
        % (mism, len(attempts)))


###################################################### OUTPUT SIZES ######################################################

def update_output_sizes(cur, writer, workers):
    cur.execute("SELECT ID, OutputLocation, FinalDestination FROM Project WHERE Completed_Time IS NULL && "
                "Is_Dispatched != '0' && Tested != '4' && Tested != '3' && Notified IS NULL")
    projects = cur.fetchall()

    def du(p):
        location = p["OutputLocation"].replace("/lustre19/expphy/cache/halld/gluex_simulations/REQUESTED_MC/",
                                               "/work/osgpool/halld/REQUESTEDMC_OUTPUT/")
        if p["FinalDestination"]:
            location = p["FinalDestination"]
        rc, out, err = run_cmd(["ssh", "-o", "BatchMode=yes", runner_name + "@ifarm2401",
                                "du -sh --exclude '..*' --total " + shlex.quote(location)], 1800)
        if rc != 0 or not out.strip():
            return p["ID"], None
        return p["ID"], out.splitlines()[-1].strip().split()[0]

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        sizes = [(s, pid) for pid, s in pool.map(du, projects) if s is not None]
    writer.executemany("UPDATE Project SET TotalSizeOut=%s WHERE ID=%s", sizes)
    log("output sizes: %d/%d projects updated in %.1fs" % (len(sizes), len(projects), time.time() - t0))


################################################### PROJECT COMPLETION ###################################################

class OutputChecker:
    """Answers 'was this output file returned?' with one directory listing per subdir instead of one call per file."""

    def __init__(self, rootLoc):
        self.root = list(filter(None, rootLoc.split("/")))[-1]
        self.listings = {}

    def exists(self, expFile):
        subloc = "root/monitoring_hists" if expFile.split(".")[-1] == "root" else "hddm"
        rel = self.root + "/" + subloc
        if os.path.isfile(OSGPOOL_OUTPUT + rel + "/" + expFile):
            return True
        if subloc not in self.listings:
            self.listings[subloc] = pelican_listing(PELICAN_OUTPUT, rel)
        listing = self.listings[subloc]
        if listing is not None and expFile in listing:
            return True
        # not in (or no) listing: fall back to MCOverlord's exact per-file test before declaring it missing
        found = pelican_has(PELICAN_OUTPUT, rel + "/" + expFile, expFile)
        if not found:
            log(rel + "/" + expFile + "   NOT FOUND")
        return found


def last_walked_files(path):
    """Non-hidden, non-.log files of the LAST directory os.walk visits -- what MCOverlord's 'files to move' counted."""
    files = []
    for r, dirs, fs in os.walk(path):
        files = [f for f in fs if not f[0] == '.']
        dirs[:] = [d for d in dirs if not d[0] == '.']
    return [f for f in files if ".log" not in f]


def expected_files(proj, job):
    std = str(job['RunNumber']).zfill(6) + '_' + str(job['FileNumber']).zfill(3)
    if proj['Generator'] != "file:":
        std = proj['Generator'] + '_' + std
    post = ""
    if proj['GenPostProcessing'] is not None and proj['GenPostProcessing'] != "":
        post = "_" + proj['GenPostProcessing'].split(":")[0]
    files = []
    if str(proj['RunGeneration']) == "1" and str(proj['SaveGeneration']) == "1" and str(proj['Generator']) != "particle_gun":
        files.append(std + post + ".hddm")
    if str(proj['RunGeant']) == "1" and str(proj['SaveGeant']) == "1":
        files.append(std + post + '_geant' + str(proj['GeantVersion']) + '.hddm')
    if str(proj['RunSmear']) == "1" and str(proj['SaveSmear']) == "1":
        files.append(std + post + '_geant' + str(proj['GeantVersion']) + '_smeared' + '.hddm')
    if str(proj['RunReconstruction']) == "1" and str(proj['SaveReconstruction']) == "1":
        files.append('dana_rest_' + std + post + '.hddm')
        files.append('hd_root_' + std + post + '.root')
    return files


def recursivermdir(rootloc):
    try:
        sublocs = os.listdir(rootloc)
    except Exception as e:
        print(e)
        return
    for subloc in sublocs:
        if os.path.isdir(rootloc + "/" + subloc):
            recursivermdir(rootloc + "/" + subloc)
    try:
        print("Removing ", rootloc)
        if ".hdds" in rootloc:
            shutil.rmtree(rootloc)
        else:
            os.rmdir(rootloc)
    except Exception as e:
        print(e)


FULFILLED_COND = ("FROM Jobs INNER JOIN Attempts ON Attempts.Job_ID = Jobs.ID WHERE Project_ID=%s && IsActive=1 "
                  "AND Attempts.ExitCode = 0 && (Attempts.Status='4' || Attempts.Status='succeeded') "
                  "AND Attempts.ID = (SELECT MAX(ID) FROM Attempts Attempts2 WHERE Attempts2.Job_ID = Jobs.ID)")
FULFILLED_COUNT_Q = "SELECT COUNT(*) n " + FULFILLED_COND
UNVERIFIED_Q = "SELECT Jobs.* " + FULFILLED_COND + " AND Jobs.DataVerified = 0"


def check_project(proj, dry):
    cnx, cur = db_connect(autocommit=True)
    w = Writer(cnx, cur, dry)
    try:
        _check_project(proj, cur, w, dry)
    except Exception:
        log("completion check failed for project", proj["ID"])
        traceback.print_exc()
    finally:
        cnx.close()


def _check_project(proj, cur, w, dry):
    pid = proj['ID']
    if proj["Tested"] == 2 or proj["Tested"] == 3:
        return
    locparts = proj['OutputLocation'].split("/")
    filesToMove = len(last_walked_files(OSGPOOL_OUTPUT + locparts[-2]))

    cur.execute(FULFILLED_COUNT_Q, (pid,))
    fulfilled = cur.fetchone()["n"]
    # already-verified jobs are counted above but never re-checked
    cur.execute(UNVERIFIED_Q, (pid,))
    unverified = cur.fetchall()

    rootLoc = proj['OutputLocation'].split("REQUESTED_MC")[1]
    checker = OutputChecker(rootLoc)
    nullified = 0
    verified = []

    for job in unverified:
        missing = None
        for expFile in expected_files(proj, job):
            if not checker.exists(expFile):
                missing = expFile
                break
        if missing is None:
            verified.append((job["ID"],))
            continue

        log("project %s job %s: %s missing, flagging last attempt 404" % (pid, job["ID"], missing))
        cur.execute("SELECT ID FROM Attempts WHERE SubmitHost=%s && Job_ID=%s ORDER BY ID DESC LIMIT 1",
                    (MCWRAPPER_BOT_HOST_NAME, job["ID"]))
        last = cur.fetchone()
        if last is not None:
            w.execute("UPDATE Attempts SET ExitCode=404, ProgramFailed=%s WHERE ID=%s", ("[" + missing + "]", last["ID"]))
        nullified += 1

    w.executemany("UPDATE Jobs SET DataVerified=1 WHERE ID=%s", verified)

    cur.execute("SELECT COUNT(ID) n FROM Jobs WHERE Project_ID=%s && IsActive=1", (pid,))
    active = cur.fetchone()["n"]
    done_jobs = fulfilled - nullified
    if active == 0:
        log("project %s: no active jobs" % pid)
        return
    cur.execute("SELECT SUM(NumEvts) s FROM Jobs WHERE Project_ID=%s", (pid,))
    submitted = cur.fetchone()["s"] or 0
    # -active: per-run event counts round to nearest, not up
    complete = done_jobs == active and filesToMove == 0 and submitted >= proj["NumEvents"] - active
    log("project %s: fulfilled %d/%d, to move %d, events submitted %s/%s -> %s"
        % (pid, done_jobs, active, filesToMove, submitted, proj["NumEvents"], "DONE" if complete else "NOT DONE"))
    if not complete:
        return

    if proj["Tested"] not in TESTED_NO_REBUNDLE:
        w.execute("UPDATE Project SET Tested=20 WHERE ID=%s", (pid,))

    if proj["Tested"] != 100:
        return

    if dry:
        log("DRY-RUN would mark project %s to_be_scrubbed, set Completed_Time/Tested=1, email %s, Notified=1, clean %s"
            % (pid, proj['Email'], OSGPOOL_OUTPUT + rootLoc))
        return

    with tempfile.TemporaryDirectory() as td:
        marker = os.path.join(td, str(pid))
        open(marker, "w").close()
        rc, out, err = run_cmd(["pelican", "object", "put", marker, PELICAN_SCRUB + str(pid)], 300, pelican_env())
        if rc != 0:
            log("scrub marker upload failed for %s: %s" % (pid, err.strip()[:300]))

    cur.execute("SELECT MAX(Completed_Time) t FROM Attempts WHERE Job_ID IN (SELECT ID FROM Jobs WHERE Project_ID=%s)", (pid,))
    final_time = cur.fetchone()["t"]
    w.execute("UPDATE Project SET Completed_Time=%s, Tested=1 WHERE ID=%s", (final_time, pid))

    msg = EmailMessage()
    final_location = proj['OutputLocation'].replace("/lustre19/expphy/cache/halld/gluex_simulations/REQUESTED_MC/",
                                                    "/work/osgpool/halld/REQUESTED_MC/")
    msg.set_content('Your Project ID ' + str(pid) + ' has been completed.  While awaiting copy to tape output may be found here:\n'
                    + str(final_location) + '\n\n' + "After successful copy the data may be accessed from tape/cache through typical methods.")
    msg['Subject'] = 'GlueX MC Request #' + str(pid) + ' Completed'
    msg['From'] = 'MCwrapper-bot'
    msg['To'] = str(proj['Email'])
    s = smtplib.SMTP('localhost')
    s.send_message(msg)
    s.quit()

    w.execute("UPDATE Project SET Notified=1 WHERE ID=%s", (pid,))
    recursivermdir(OSGPOOL_OUTPUT + rootLoc)


def check_completion(cur, workers, dry):
    cur.execute("SELECT * FROM Project WHERE (Is_Dispatched != '0' && Tested != '-1' && Tested != '2') && Notified IS NULL")
    projects = cur.fetchall()
    log("checking %d projects for completion" % len(projects))
    if not projects:
        return
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=min(workers, len(projects))) as pool:
        list(pool.map(lambda p: check_project(p, dry), projects))
    log("completion checks done in %.1fs" % (time.time() - t0))


########################################################## MAIN ##########################################################

def acquire_lock():
    fh = open("/tmp/FastOverlord_%s.lock" % runner_name, "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return None
    return fh


def legacy_overlords():
    rc, out, err = run_cmd(["pgrep", "-u", runner_name, "-f", r"python[0-9.]* .*MCOverlord\.py"])
    return out.split()


def run_pass(args, heavy):
    cnx, cur = db_connect()
    writer = Writer(cnx, cur, args.dry_run)
    row_id = None
    try:
        if not args.dry_run:
            cur.execute("INSERT INTO MCOverlord (Host,StartTime,Status) VALUES (%s, NOW(), 'Running')", (socket.gethostname(),))
            cnx.commit()
            row_id = cur.lastrowid
        if not args.skip_osg:
            check_osg(cur, writer, args)
        if not args.skip_sizes and heavy:
            update_output_sizes(cur, writer, args.du_workers)
        if not args.skip_completion and heavy:
            check_completion(cur, args.completion_workers, args.dry_run)
        if row_id is not None:
            cur.execute("UPDATE MCOverlord SET EndTime=NOW(), Status='Success' WHERE ID=%s", (row_id,))
            cnx.commit()
        return True
    except Exception:
        traceback.print_exc()
        if row_id is not None:
            try:
                cnx.rollback()
                cur.execute("UPDATE MCOverlord SET Status='Fail' WHERE ID=%s", (row_id,))
                cnx.commit()
            except Exception:
                traceback.print_exc()
        return False
    finally:
        cnx.close()


def main():
    ap = argparse.ArgumentParser(description="Bulk HTCondor -> gluex_mc Attempts monitor (replacement for MCOverlord.py)")
    ap.add_argument("--once", action="store_true", help="run a single (full) pass and exit")
    ap.add_argument("--dry-run", action="store_true", help="compute everything, write nothing, send nothing")
    ap.add_argument("--validate", type=int, metavar="N", help="compare bulk vs per-job condor queries on N random attempts and exit")
    ap.add_argument("--sample", type=int, default=0, metavar="N", help="only process N random active attempts (testing)")
    ap.add_argument("--force-all", action="store_true", help="write every resolved attempt even if unchanged")
    ap.add_argument("--trust-bulk-history", action="store_true",
                    help="mark attempts absent from bulk condor_history as 999/condor without per-job confirmation")
    ap.add_argument("--skip-osg", action="store_true")
    ap.add_argument("--skip-sizes", action="store_true")
    ap.add_argument("--skip-completion", action="store_true")
    ap.add_argument("--workers", type=int, default=16, help="threads for history post-processing / confirmations")
    ap.add_argument("--du-workers", type=int, default=8)
    ap.add_argument("--completion-workers", type=int, default=4)
    ap.add_argument("--heavy-every", type=int, default=5, metavar="N",
                    help="run output sizes (du) and project completion checks every N passes (always on the first)")
    ap.add_argument("--fail-backoff", type=int, default=30, metavar="SEC", help="pause after a failed pass")
    args = ap.parse_args()

    if runner_name not in ("tbritton", "mcwrap"):
        print("ERROR: You must be tbritton or mcwrap to run this script")
        sys.exit(1)

    if args.validate:
        cnx, cur = db_connect()
        try:
            validate(cur, args)
        finally:
            cnx.close()
        return

    # silent: under cron this is the normal case whenever the previous pass is still running
    lock = acquire_lock()
    if lock is None:
        return
    legacy = legacy_overlords()
    if legacy:
        log("MCOverlord.py is running (pids %s); exiting" % " ".join(legacy))
        sys.exit(1)

    n = 0
    while True:
        heavy = n % max(args.heavy_every, 1) == 0
        t0 = time.time()
        ok = run_pass(args, heavy)
        log("pass %d (%s) %s in %.1fs" % (n, "full" if heavy else "jobs only", "succeeded" if ok else "FAILED", time.time() - t0))
        if args.once:
            sys.exit(0 if ok else 1)
        n += 1
        if not ok:
            time.sleep(args.fail_backoff)


if __name__ == "__main__":
    main()
