#!/usr/bin/env python3
##########################################################################################################################
#
# MCLogLibrarian.py -- fulfil LogRequests rows by running MCFailedLogs.py on this submit host
#
#   Polls gluex_mc.LogRequests for 'queued' rows whose SubmitHost is this host, claims each one atomically, turns its
#   validated columns into an MCFailedLogs.py argument list (never a shell string), runs it in its own work directory
#   and records the outcome (done/failed, counts, ResultPath = shipped tarball, Message = summary or log tail).
#
#   * up to --max-parallel requests run at once; each is killed after --max-runtime seconds
#   * a row set to 'cancelled' while running has its MCFailedLogs process group killed
#   * on startup, 'running' rows this host claimed earlier (librarian died) are requeued once, then failed
#   * on SIGTERM/SIGINT running requests are killed and requeued
#   * heartbeat: one MCLibrarian row per process, LastBeat/Busy updated every poll, Status='Stopped' on clean exit
#   * cleanup: tarballs of requests this host ran are deleted (ssh rm) --purge-after hours after downloadLogs.php
#     stamped Downloaded, or --expire-days after completion if never downloaded; Purged records when
#   * AnalysisRequested rows: once the tarball is shipped, MCAIanalysis.py is run on ANALYSIS_HOST over ssh in the
#     background and emails its report to RequestedBy@jlab.org (log: <workdir>/R<id>_analysis.log, kept on failure)
#
#   Loops forever. Cron it every minute as a watchdog (on each submit host, as the production account):
#     * * * * * python3 /scigroup/mcwrapper/gluex_MCwrapper/Utilities/MCLogLibrarian.py >> ~/MCLogLibrarian.log 2>&1
#
#   Testing:
#     MCLogLibrarian.py --once            handle what is queued now, wait for it to finish, exit
#
##########################################################################################################################
import argparse
import fcntl
import json
import os
import pwd
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import time
import traceback

import MySQLdb
import MySQLdb.cursors

dbhost = "hallddb.jlab.org"
dbuser = "mcuser"
dbname = "gluex_mc"

runner_name = pwd.getpwuid(os.getuid())[0]
MY_HOST = socket.gethostname()
HOSTNAMES = sorted({MY_HOST, MY_HOST.split(".")[0], socket.getfqdn()})
FAILED_LOGS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "MCFailedLogs.py")
AI_ANALYSIS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "MCAIanalysis.py")
ANALYSIS_HOST = "ifarm2401"

TIME_FMT = "%Y-%m-%d %H:%M"
MAX_MODE_LEN = 255
MAX_LIST = 200
MAX_HOURS = 24 * 90
LOG_TAIL = 4000
REQUEUE_MSG = "requeued after librarian restart"
PURGE_EVERY = 600
PURGE_BATCH = 50
RESULT_DIR = "REQUESTEDMC_LOGS"  # the only remote directory cleanup will delete from
TARBALL_RE = re.compile(r"^[A-Za-z0-9_.()+-]+\.tar\.gz$")
SSH_TARGET_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*@[A-Za-z0-9][A-Za-z0-9.-]*$")
USERNAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*$")


def log(*a):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), *a, flush=True)


def db_connect():
    cnx = MySQLdb.connect(host=dbhost, user=dbuser, db=dbname, connect_timeout=20)
    cnx.autocommit(True)
    return cnx, cnx.cursor(MySQLdb.cursors.DictCursor)


def host_params():
    return ",".join(["%s"] * len(HOSTNAMES)), list(HOSTNAMES)


###################################################### REQUEST -> ARGV #####################################################

class BadRequest(ValueError):
    pass


def as_int(v):
    if isinstance(v, bool):
        raise ValueError(v)
    return v if isinstance(v, int) else int(str(v).strip())


def as_project(v):
    n = as_int(v)
    if n <= 0:
        raise ValueError(v)
    return n


def as_mode(v):
    # modes are ProgramFailed strings (paths, '=', ...); safe because they only ever reach argv, never a shell
    s = str(v).strip()
    if not 0 < len(s) <= MAX_MODE_LEN or any(ord(c) < 32 or ord(c) == 127 for c in s):
        raise ValueError(v)
    return s


def json_list(raw, name, conv):
    if raw is None or str(raw).strip() in ("", "null", "[]"):
        return []
    try:
        vals = json.loads(raw)
    except ValueError:
        raise BadRequest("%s is not valid JSON: %r" % (name, raw))
    if not isinstance(vals, list):
        vals = [vals]
    if len(vals) > MAX_LIST:
        raise BadRequest("%s has more than %d entries" % (name, MAX_LIST))
    out = []
    for v in vals:
        try:
            out.append(conv(v))
        except (TypeError, ValueError):
            raise BadRequest("bad %s entry %r" % (name, v))
    return out


def build_argv(req, tag, result_json, send_to):
    # --opt=value so a value starting with '-' can never be read as an option
    argv = [sys.executable, FAILED_LOGS, "--tag=" + tag, "--result-json=" + result_json]
    start, end, hours = req["WindowStart"], req["WindowEnd"], req["Hours"]
    if start and end and start >= end:
        raise BadRequest("WindowStart must be before WindowEnd")
    if start:
        argv.append("--since=" + start.strftime(TIME_FMT))
    elif hours is not None:
        if not 0 < float(hours) <= MAX_HOURS:
            raise BadRequest("Hours must be in (0, %d]" % MAX_HOURS)
        argv.append("--hours=%g" % float(hours))
    if end:
        argv.append("--until=" + end.strftime(TIME_FMT))
    modes = json_list(req["Modes"], "Modes", as_mode)
    argv += ["--mode=" + m for m in modes] + (["--exact-mode"] if modes else [])
    argv += ["--project=%d" % p for p in json_list(req["Projects"], "Projects", as_project)]
    argv += ["--exit-code=%d" % e for e in json_list(req["ExitCodes"], "ExitCodes", as_int)]
    if req["AnyHost"]:
        argv.append("--any-host")
    if req["GroupByMode"]:
        argv.append("--group-by-mode")
    if req["LimitN"] is not None:
        if int(req["LimitN"]) <= 0:
            raise BadRequest("LimitN must be positive")
        argv.append("--limit=%d" % int(req["LimitN"]))
    if send_to:
        argv.append("--send-to=" + send_to)
    return argv


######################################################### PROCESSES ########################################################

def is_failed_logs(pid):
    try:
        with open("/proc/%d/cmdline" % pid, "rb") as fh:
            return b"MCFailedLogs.py" in fh.read()
    except OSError:
        return False


def kill_group(pid, proc=None, grace=10):
    """SIGTERM the process group (MCFailedLogs runs in its own session), SIGKILL after `grace` seconds."""
    try:
        os.killpg(pid, signal.SIGTERM)
    except OSError:
        return
    deadline = time.time() + grace
    while time.time() < deadline:
        if proc is not None:
            if proc.poll() is not None:
                return
        elif not os.path.exists("/proc/%d" % pid):
            return
        time.sleep(0.2)
    try:
        os.killpg(pid, signal.SIGKILL)
    except OSError:
        pass
    if proc is not None:
        proc.wait()


def log_tail(path):
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - LOG_TAIL))
            return fh.read().decode("utf-8", "replace").strip()
    except OSError:
        return ""


def read_json(path):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def remove_result(result_path, workdir):
    """Delete a shipped (user@host:/.../REQUESTEDMC_LOGS/x.tar.gz) or local (under workdir) tarball; True if gone."""
    target, sep, path = result_path.partition(":")
    if not sep:
        path = os.path.realpath(result_path)
        if not path.startswith(os.path.realpath(workdir) + os.sep):
            log("cleanup: refusing local path outside %s: %s" % (workdir, result_path))
            return False
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        except OSError as e:
            log("cleanup: %s: %s" % (path, e))
            return False
        return True
    norm = os.path.normpath(path)
    if (not SSH_TARGET_RE.match(target) or norm != path or not path.startswith("/")
            or os.path.basename(os.path.dirname(path)) != RESULT_DIR or not TARBALL_RE.match(os.path.basename(path))):
        log("cleanup: refusing unexpected result path %r" % result_path)
        return False
    try:
        rc = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", target, "rm -f -- " + shlex.quote(path)],
                            stdin=subprocess.DEVNULL, capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        log("cleanup: ssh %s failed: %s" % (target, e))
        return False
    if rc.returncode != 0:
        log("cleanup: ssh %s rm %s exited %d: %s" % (target, path, rc.returncode, rc.stderr.decode("utf-8", "replace").strip()[:300]))
        return False
    return True


def shipped_tarball(result_path):
    """Remote path of a shipped user@host:/.../REQUESTEDMC_LOGS/x.tar.gz, or None if it is not one."""
    target, sep, path = (result_path or "").partition(":")
    if (not sep or not SSH_TARGET_RE.match(target) or not path.startswith("/") or os.path.normpath(path) != path
            or os.path.basename(os.path.dirname(path)) != RESULT_DIR or not TARBALL_RE.match(os.path.basename(path))):
        return None
    return path


######################################################### LIBRARIAN ########################################################

class Job(object):
    def __init__(self, rid, proc, reqdir, req):
        self.rid = rid
        self.proc = proc
        self.reqdir = reqdir
        self.requested_by = req["RequestedBy"]
        self.analysis = bool(req.get("AnalysisRequested"))
        self.logpath = os.path.join(reqdir, "MCFailedLogs.log")
        self.result_json = os.path.join(reqdir, "result.json")
        self.started = time.time()


class Librarian(object):
    def __init__(self, args):
        self.args = args
        self.jobs = {}
        self.analyses = {}  # rid -> (ssh Popen, log path)
        self.beat_id = None
        self.next_purge = 0

    def start_beat(self, cur):
        try:
            cur.execute("INSERT INTO MCLibrarian (Host, PID, StartTime, LastBeat, Status) VALUES (%s, %s, NOW(), NOW(), 'Running')",
                        (MY_HOST, os.getpid()))
            self.beat_id = cur.lastrowid
        except MySQLdb.Error as e:
            log("heartbeat disabled: %s" % e)

    def beat(self, cur):
        if self.beat_id is not None:
            cur.execute("UPDATE MCLibrarian SET LastBeat=NOW(), Busy=%s WHERE ID=%s", (len(self.jobs), self.beat_id))

    def finish(self, cur, rid, status, **cols):
        """Close a request; only rows still 'running' are touched, so a dashboard cancel is never overwritten."""
        sets = ["Status=%s", "Completed_Time=NOW()"] + ["%s=%%s" % k for k in cols]
        cur.execute("UPDATE LogRequests SET %s WHERE ID=%%s AND Status='running'" % ", ".join(sets),
                    [status] + list(cols.values()) + [rid])
        msg = (cols.get("Message") or "").splitlines()
        log("request %d: %s %s" % (rid, status, msg[0][:200] if msg else ""))

    def requeue(self, cur, rid, message):
        if (message or "").startswith(REQUEUE_MSG):
            self.finish(cur, rid, "failed", Message="interrupted twice by librarian restarts; not retrying")
            return
        cur.execute("UPDATE LogRequests SET Status='queued', ClaimedBy=NULL, PID=NULL, Start_Time=NULL, Message=%s "
                    "WHERE ID=%s AND Status='running'", (REQUEUE_MSG, rid))
        log("request %d: requeued" % rid)

    def recover(self, cur):
        cur.execute("SELECT ID, PID, Message FROM LogRequests WHERE Status='running' AND ClaimedBy=%s", (MY_HOST,))
        for r in cur.fetchall():
            if r["PID"] and is_failed_logs(int(r["PID"])):
                kill_group(int(r["PID"]))
            self.requeue(cur, r["ID"], r["Message"])

    def start(self, cur, req):
        rid = req["ID"]
        tag = "R%d" % rid
        reqdir = os.path.join(self.args.workdir, tag)
        try:
            argv = build_argv(req, tag, os.path.join(reqdir, "result.json"), self.args.send_to)
        except (BadRequest, TypeError, ValueError) as e:
            self.finish(cur, rid, "failed", Message="invalid request: %s" % e)
            return
        try:
            shutil.rmtree(reqdir, ignore_errors=True)
            os.makedirs(reqdir)
            with open(os.path.join(reqdir, "MCFailedLogs.log"), "w") as fh:
                fh.write(" ".join(argv) + "\n")
                fh.flush()
                proc = subprocess.Popen(argv, cwd=reqdir, stdin=subprocess.DEVNULL, stdout=fh, stderr=subprocess.STDOUT,
                                        start_new_session=True)
        except OSError as e:
            self.finish(cur, rid, "failed", Message="could not start MCFailedLogs.py: %s" % e)
            return
        self.jobs[rid] = Job(rid, proc, reqdir, req)
        cur.execute("UPDATE LogRequests SET PID=%s WHERE ID=%s", (proc.pid, rid))
        log("request %d (%s): pid %d: %s" % (rid, req["RequestedBy"], proc.pid, " ".join(argv[4:])))

    def claim(self, cur):
        free = self.args.max_parallel - len(self.jobs)
        if free <= 0:
            return
        ph, hosts = host_params()
        cur.execute("SELECT ID FROM LogRequests WHERE Status='queued' AND SubmitHost IN (%s) ORDER BY ID LIMIT %%s" % ph,
                    hosts + [free])
        for row in cur.fetchall():
            cur.execute("UPDATE LogRequests SET Status='running', ClaimedBy=%s, PID=NULL, Start_Time=NOW() "
                        "WHERE ID=%s AND Status='queued'", (MY_HOST, row["ID"]))
            if cur.rowcount != 1:
                continue  # cancelled or claimed between SELECT and UPDATE
            cur.execute("SELECT * FROM LogRequests WHERE ID=%s", (row["ID"],))
            self.start(cur, cur.fetchone())

    def complete(self, cur, job, rc):
        result = read_json(job.result_json)
        if rc == 0 and result is not None:
            n = int(result.get("attempts") or 0)
            copied = int(result.get("files_local") or 0) + int(result.get("files_dtn") or 0)
            missing = int(result.get("files_missing") or 0)
            if n == 0:
                msg, path = "no failed attempts matched", None
            else:
                msg = "%d attempts, %d files copied, %d missing" % (n, copied, missing)
                path = result.get("sent_to") or result.get("tarball")
            self.finish(cur, job.rid, "done", NAttempts=n, NFilesCopied=copied if n else 0, NFilesMissing=missing,
                        ResultPath=path, Message=msg)
            if job.analysis and n:
                self.start_analysis(cur, job.rid, path, job.requested_by)
            elif job.analysis:
                cur.execute("UPDATE LogRequests SET AnalysisRequested=0 WHERE ID=%s", (job.rid,))
            if not self.args.keep and (n == 0 or result.get("sent_to")):
                shutil.rmtree(job.reqdir, ignore_errors=True)
        else:
            self.finish(cur, job.rid, "failed", Message="MCFailedLogs.py exited %s (log: %s)\n%s"
                        % (rc, job.logpath, log_tail(job.logpath)))

    def analysis_failed(self, cur, rid, reason):
        """Stage -1 unless MCAIanalysis.py already recorded its own outcome."""
        log("request %d: AI analysis failed: %s" % (rid, reason))
        cur.execute("UPDATE LogRequests SET AnalysisRequested=-1, Message=CONCAT(IFNULL(Message, ''), %s) "
                    "WHERE ID=%s AND AnalysisRequested BETWEEN 1 AND 5", ("\nAI analysis failed: " + reason[:500], rid))

    def start_analysis(self, cur, rid, result_path, requested_by):
        """Fire-and-forget MCAIanalysis.py on ANALYSIS_HOST; reaped later by reap_analyses."""
        path = shipped_tarball(result_path)
        if path is None:
            self.analysis_failed(cur, rid, "%r is not a shipped tarball" % result_path)
            return
        if not USERNAME_RE.match(requested_by or ""):
            self.analysis_failed(cur, rid, "bad RequestedBy %r" % requested_by)
            return
        email = requested_by + "@jlab.org"
        # non-interactive ssh does not read ~/.bash_profile, so fall back to the PAT file
        remote = ('DELPHI_PAT="${DELPHI_PAT:-$(cat ~/.config/delphi/pat 2>/dev/null)}" python3 %s %s %s --request-id=%d'
                  % (shlex.quote(AI_ANALYSIS), shlex.quote(path), shlex.quote(email), rid))
        logpath = os.path.join(self.args.workdir, "R%d_analysis.log" % rid)
        try:
            with open(logpath, "w") as fh:
                proc = subprocess.Popen(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
                                         runner_name + "@" + ANALYSIS_HOST, remote],
                                        stdin=subprocess.DEVNULL, stdout=fh, stderr=subprocess.STDOUT, start_new_session=True)
        except OSError as e:
            self.analysis_failed(cur, rid, "could not start ssh: %s" % e)
            return
        self.analyses[rid] = (proc, logpath)
        cur.execute("UPDATE LogRequests SET AnalysisRequested=2 WHERE ID=%s AND AnalysisRequested=1", (rid,))
        log("request %d: AI analysis of %s started on %s for %s (pid %d)" % (rid, path, ANALYSIS_HOST, email, proc.pid))

    def reap_analyses(self, cur):
        for rid, (proc, logpath) in list(self.analyses.items()):
            rc = proc.poll()
            if rc is None:
                continue
            del self.analyses[rid]
            if rc == 0:
                log("request %d: AI analysis emailed" % rid)
                try:
                    os.remove(logpath)
                except OSError:
                    pass
            else:
                tail = log_tail(logpath).splitlines()
                self.analysis_failed(cur, rid, "exited %d on %s (log: %s:%s) %s"
                                     % (rc, ANALYSIS_HOST, MY_HOST, logpath, tail[-1][:300] if tail else ""))

    def check_jobs(self, cur):
        if not self.jobs:
            return
        ids = list(self.jobs)
        cur.execute("SELECT ID, Status FROM LogRequests WHERE ID IN (%s)" % ",".join(["%s"] * len(ids)), ids)
        status = dict((r["ID"], r["Status"]) for r in cur.fetchall())
        for rid in ids:
            job = self.jobs[rid]
            rc = job.proc.poll()
            if rc is None and status.get(rid) != "running":
                kill_group(job.proc.pid, job.proc)
                cur.execute("UPDATE LogRequests SET Completed_Time=NOW(), Message='cancelled while running' "
                            "WHERE ID=%s AND Status='cancelled'", (rid,))
                log("request %d: %s while running; killed" % (rid, status.get(rid, "deleted")))
            elif rc is None and time.time() - job.started > self.args.max_runtime:
                kill_group(job.proc.pid, job.proc)
                self.finish(cur, rid, "failed", Message="killed after %ds (log: %s)\n%s"
                            % (self.args.max_runtime, job.logpath, log_tail(job.logpath)))
            elif rc is None:
                continue
            else:
                self.complete(cur, job, rc)
            del self.jobs[rid]

    def purge(self, cur):
        if time.time() < self.next_purge:
            return
        self.next_purge = time.time() + PURGE_EVERY
        cur.execute("SELECT ID, ResultPath, Downloaded FROM LogRequests "
                    "WHERE Status='done' AND ResultPath IS NOT NULL AND Purged IS NULL AND ClaimedBy=%s "
                    "AND (Downloaded < NOW() - INTERVAL %s HOUR OR Completed_Time < NOW() - INTERVAL %s DAY) "
                    "ORDER BY ID LIMIT %s",
                    (MY_HOST, self.args.purge_after, self.args.expire_days, PURGE_BATCH))
        for r in cur.fetchall():
            if remove_result(r["ResultPath"], self.args.workdir):
                cur.execute("UPDATE LogRequests SET Purged=NOW() WHERE ID=%s", (r["ID"],))
                log("request %d: removed %s (%s)" % (r["ID"], r["ResultPath"], "downloaded" if r["Downloaded"] else "expired"))

    def tick(self, claim):
        cnx, cur = db_connect()
        try:
            self.reap_analyses(cur)
            self.check_jobs(cur)
            if claim:
                self.claim(cur)
            self.beat(cur)
            try:
                self.purge(cur)
            except MySQLdb.Error as e:
                log("cleanup skipped: %s" % e)
        finally:
            cnx.close()

    def shutdown(self):
        if self.jobs:
            log("shutting down: stopping %d running requests" % len(self.jobs))
        for job in self.jobs.values():
            kill_group(job.proc.pid, job.proc)
        try:
            cnx, cur = db_connect()
            try:
                ids = list(self.jobs)
                if ids:
                    cur.execute("SELECT ID, Message FROM LogRequests WHERE ID IN (%s)" % ",".join(["%s"] * len(ids)), ids)
                    for r in cur.fetchall():
                        self.requeue(cur, r["ID"], r["Message"])
                if self.beat_id is not None:
                    cur.execute("UPDATE MCLibrarian SET LastBeat=NOW(), EndTime=NOW(), Busy=0, Status='Stopped' WHERE ID=%s",
                                (self.beat_id,))
            finally:
                cnx.close()
        except MySQLdb.Error as e:
            log("could not requeue/record shutdown (the next librarian will requeue): %s" % e)
        self.jobs.clear()


########################################################### MAIN ###########################################################

def acquire_lock():
    fh = open("/tmp/MCLogLibrarian_%s.lock" % runner_name, "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return None
    return fh


def on_signal(signum, frame):
    raise SystemExit(128 + signum)


def main():
    ap = argparse.ArgumentParser(description="Run MCFailedLogs.py for queued LogRequests rows targeting this host.")
    ap.add_argument("--once", action="store_true", help="claim what is queued now, wait for it to finish, exit")
    ap.add_argument("--poll", type=float, default=5, help="seconds between polls when idle (default 5)")
    ap.add_argument("--busy-poll", type=float, default=5, help="seconds between polls while requests run (default 5)")
    ap.add_argument("--max-parallel", type=int, default=2, help="requests run at once (default 2)")
    ap.add_argument("--max-runtime", type=int, default=3 * 3600, help="kill a request after this many seconds (default 10800)")
    ap.add_argument("--workdir", default=os.path.expanduser("~/MCLogLibrarian"), help="per-request work dirs (default ~/MCLogLibrarian)")
    ap.add_argument("--send-to", help="override MCFailedLogs.py's scp destination")
    ap.add_argument("--keep", action="store_true", help="keep local folders/tarballs after a successful send")
    ap.add_argument("--purge-after", type=int, default=7 * 24, help="delete a tarball this many hours after its download (default 168)")
    ap.add_argument("--expire-days", type=int, default=30, help="delete a never-downloaded tarball this many days after completion (default 30)")
    args = ap.parse_args()

    # silent: under cron this is the normal case whenever a librarian is already running
    lock = acquire_lock()
    if lock is None:
        return
    if not os.path.isfile(FAILED_LOGS):
        sys.exit("MCFailedLogs.py not found next to this script: %s" % FAILED_LOGS)
    os.makedirs(args.workdir, exist_ok=True)
    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)

    lib = Librarian(args)
    cnx, cur = db_connect()
    try:
        lib.recover(cur)
        lib.start_beat(cur)
    finally:
        cnx.close()
    log("librarian up on %s (hosts %s)" % (MY_HOST, ", ".join(HOSTNAMES)))

    first = True
    try:
        while True:
            try:
                lib.tick(claim=first or not args.once)
            except MySQLdb.Error as e:
                log("database error: %s" % e)
            except Exception:
                traceback.print_exc()
            first = False
            if args.once and not lib.jobs:
                break
            time.sleep(args.busy_poll if lib.jobs else args.poll)
    finally:
        lib.shutdown()


if __name__ == "__main__":
    main()
