#!/usr/bin/env python3
##########################################################################################################################
#
# MCAIanalysis.py -- untar a failed-log tarball, have a Delphi-hosted model diagnose it, email the report
#
#   MCAIanalysis.py /path/to/failed_logs_X.tar.gz someone@jlab.org [--model M] [--workdir /tmp/mcwrap]
#
#   * extracts into --workdir (default /tmp/mcwrap, created 0700); refuses members that would land outside it
#   * the model cannot read this host's disk, so the text of the logs is sent along with the prompt:
#     manifest.tsv first (untruncated), then the attempts' logs round-robin across failure modes so every mode is
#     represented before the budget runs out (each head+tail truncated to --per-file chars, everything to --max-chars)
#   * report: <workdir>/AIanalysis_<untarred dir>.txt, emailed from <this account>@jlab.org through localhost SMTP
#   * needs DELPHI_PAT in the environment
#   * progress goes to stderr with timestamps; the reply is streamed and a heartbeat reports elapsed time/chars
#   * self-healing (--attempts): context overflow -> fewer logs, empty answer -> more reply tokens, network -> back off
#   * --request-id N: stage is written to LogRequests.AnalysisRequested for the dashboard
#     (3 reading logs, 4 model analyzing, 5 emailing, 6 emailed, -1 failed + reason appended to Message)
#
##########################################################################################################################
import argparse
import csv
import http.client
import json
import os
import pwd
import re
import smtplib
import socket
import sys
import tarfile
import threading
import time
import urllib.error
import urllib.request
from collections import OrderedDict
from email.message import EmailMessage

DELPHI_URL = "https://api.delphi.jlab.org/v1/chat/completions"
DEFAULT_MODEL = "jlab/qwen3.8-27b" #"azure_ai/claude-sonnet-5-5"
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
PROMPT = ("Analyze the failed MCwrapper job logs from {folder}. Its manifest.tsv, listing every failed attempt and its "
          "failure mode, comes first; read it before the logs. In event there are a large number of logs, which may cause max_tokens to be exceeded, subsample each failure mode ensuring each failure mode is represented. For each failure mode diagnose the "
          "underlying problem and supply possible corrective actions, then write a report which summarizes all of your "
          "findings. Ignore any warnings unrelated to the underlying problems. This summary should be terse and to the point; avoid uneccessary repetition, just show the excerpts and codes etc that are directly pertinent to the diagnosis. make sure the suggested fixes are clear and visible"
          "Include a haiku based off the summary at the end of the email")

HEARTBEAT = 15
REQUEST_ID = None


class Retry(Exception):
    """A Delphi failure worth another attempt; kind is 'context', 'transient' or 'empty'."""
    def __init__(self, kind, msg):
        Exception.__init__(self, msg)
        self.kind = kind


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, file=sys.stderr, flush=True)


def set_stage(stage, reason=None):
    if REQUEST_ID is None:
        return
    try:
        import MySQLdb
        cnx = MySQLdb.connect(host="hallddb.jlab.org", user="mcuser", db="gluex_mc", connect_timeout=20)
        cnx.autocommit(True)
        cur = cnx.cursor()
        if reason is None:
            cur.execute("UPDATE LogRequests SET AnalysisRequested=%s WHERE ID=%s", (stage, REQUEST_ID))
        else:
            cur.execute("UPDATE LogRequests SET AnalysisRequested=%s, Message=CONCAT(IFNULL(Message, ''), %s) WHERE ID=%s",
                        (stage, "\nAI analysis failed: " + reason[:500], REQUEST_ID))
        cnx.close()
    except Exception as e:
        log("could not record stage %s for request %s: %s" % (stage, REQUEST_ID, e))


def die(msg):
    log("ERROR: " + msg)
    set_stage(-1, msg)
    sys.exit(1)


def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return "%.1f %s" % (n, unit) if unit != "B" else "%d B" % n
        n /= 1024.0


def tar_stem(path):
    name = os.path.basename(path)
    for ext in (".tar.gz", ".tgz", ".tar.bz2", ".tar.xz", ".tar"):
        if name.endswith(ext):
            return name[:-len(ext)]
    return name


def safe_extract(tar_path, workdir):
    """Extract tar_path under workdir and return the directory holding its contents."""
    t0 = time.time()
    with tarfile.open(tar_path) as tf:
        members = tf.getmembers()
        log("tarball holds %d members (%s uncompressed)" % (len(members), human(sum(m.size for m in members))))
        tops = {m.name.lstrip("./").split("/", 1)[0] for m in members if m.name.lstrip("./")}
        # a single top-level directory is the "untarred directory"; otherwise give the contents one named after the tarball
        if len(tops) == 1 and any(m.isdir() and m.name.strip("./") == next(iter(tops)) for m in members):
            dest_root, folder = workdir, os.path.join(workdir, next(iter(tops)))
        else:
            folder = os.path.join(workdir, tar_stem(tar_path))
            dest_root = folder
            os.makedirs(folder, exist_ok=True)
        if hasattr(tarfile, "data_filter"):
            tf.extractall(dest_root, filter="data")
        else:
            root = os.path.realpath(dest_root)
            for m in members:
                target = os.path.realpath(os.path.join(root, m.name))
                if not (m.isfile() or m.isdir()) or os.path.commonpath([root, target]) != root:
                    die("refusing unsafe tar member %r" % m.name)
            tf.extractall(dest_root)
    log("extracted to %s in %.1fs" % (folder, time.time() - t0))
    return folder


def read_text(path, per_file):
    with open(path, "rb") as fh:
        data = fh.read()
    if b"\0" in data[:8192]:
        return None
    text = data.decode("utf-8", "replace")
    if len(text) > per_file:
        half = per_file // 2
        text = text[:half] + "\n... [%d chars omitted] ...\n" % (len(text) - per_file) + text[-half:]
    return text


def collect_logs(folder, per_file, max_chars):
    paths = []
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames.sort()
        paths.extend(os.path.join(dirpath, fn) for fn in sorted(filenames))
    manifest = os.path.join(folder, "manifest.tsv")
    mode_of = {}
    if manifest in paths:
        paths.remove(manifest)
        with open(manifest, newline="") as fh:
            rows = list(csv.DictReader(fh, delimiter="\t"))
        by_mode = OrderedDict()
        for r in rows:
            by_mode.setdefault(r.get("mode") or "?", []).append(r.get("file") or "")
        nmodes = len(by_mode)
        # most prevalent mode first; attempts whose logs were not copied would waste a mode's turn
        present = set(paths)
        by_mode = OrderedDict((m, [f for f in files if any(os.path.join(folder, f + e) in present for e in (".out", ".err"))])
                              for m, files in sorted(by_mode.items(), key=lambda kv: -len(kv[1])))
        ordered, rnd = [], 0
        while any(rnd < len(files) for files in by_mode.values()):
            for mode, files in by_mode.items():
                if rnd < len(files):
                    for ext in (".out", ".err"):
                        p = os.path.join(folder, files[rnd] + ext)
                        if p in paths and p not in mode_of:
                            ordered.append(p)
                            mode_of[p] = mode
            rnd += 1
        paths = [manifest] + ordered + [p for p in paths if p not in mode_of]
        log("manifest: %d attempts in %d modes; logs interleaved across modes, most prevalent first" % (len(rows), nmodes))
    else:
        log("no manifest.tsv in %s" % folder)
    parts, total, skipped = [], 0, []
    for path in paths:
        rel = os.path.relpath(path, folder)
        text = read_text(path, max_chars if path == manifest else per_file)
        if text is None:
            skipped.append(rel + " (binary)")
            continue
        label = "%s (mode %s)" % (rel, mode_of[path]) if path in mode_of else rel
        block = "===== %s =====\n%s\n" % (label, text)
        if total + len(block) > max_chars:
            skipped.append(rel + " (size budget)")
            continue
        parts.append(block)
        total += len(block)
    log("including %d files (%d chars, ~%dk tokens); skipped %d" % (len(parts), total, total // 2000, len(skipped)))
    for s in skipped[:10]:
        log("  skipped " + s)
    if len(skipped) > 10:
        log("  ... and %d more" % (len(skipped) - 10))
    if skipped:
        parts.append("===== not included =====\n" + "\n".join(skipped) + "\n")
    return "".join(parts)


def heartbeat(stop, t0, state):
    while not stop.wait(HEARTBEAT):
        if state["chars"] or state["reasoning"]:
            log("  ... %ds elapsed, %d chars of reply, %d chars of model reasoning received"
                % (time.time() - t0, state["chars"], state["reasoning"]))
        else:
            log("  ... %ds elapsed, waiting for the model to start replying" % (time.time() - t0))


def ask_delphi(pat, model, prompt, logs, max_tokens):
    body = json.dumps({
        "model": model,
        "max_tokens": max_tokens,
        "stream": True,
        "stream_options": {"include_usage": True},
        "messages": [{"role": "user", "content": prompt + "\n\nThe log files follow.\n\n" + logs}],
    }).encode()
    req = urllib.request.Request(DELPHI_URL, data=body, method="POST",
                                 headers={"Authorization": "Bearer " + pat, "Content-Type": "application/json"})
    log("sending %s request to %s (model %s, max %d reply tokens)" % (human(len(body)), DELPHI_URL, model, max_tokens))
    t0 = time.time()
    state = {"chars": 0, "reasoning": 0}
    stop = threading.Event()
    threading.Thread(target=heartbeat, args=(stop, t0, state), daemon=True).start()
    chunks, finish, usage = [], None, None
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            if "text/event-stream" not in resp.headers.get("Content-Type", ""):
                reply = json.load(resp)
                choice = (reply.get("choices") or [{}])[0]
                msg = choice.get("message") or {}
                chunks.append(msg.get("content") or "")
                state["reasoning"] = len(msg.get("reasoning_content") or msg.get("reasoning") or "")
                finish, usage = choice.get("finish_reason"), reply.get("usage")
            else:
                for raw in resp:
                    line = raw.decode("utf-8", "replace").strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    obj = json.loads(data)
                    if obj.get("error"):
                        raise Retry("transient", "Delphi stream error: %s" % json.dumps(obj["error"])[:1000])
                    usage = obj.get("usage") or usage
                    choices = obj.get("choices") or [{}]
                    delta = choices[0].get("delta") or {}
                    finish = choices[0].get("finish_reason") or finish
                    # thinking models stream their reasoning separately; it counts against max_tokens but is not the answer
                    state["reasoning"] += len(delta.get("reasoning_content") or delta.get("reasoning") or "")
                    piece = delta.get("content") or ""
                    if piece and not state["chars"]:
                        log("model started answering after %.1fs" % (time.time() - t0))
                    chunks.append(piece)
                    state["chars"] += len(piece)
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", "replace")[:1000]
        msg = "Delphi returned HTTP %d: %s" % (e.code, text)
        if "ContextWindowExceeded" in text or "maximum context length" in text:
            raise Retry("context", msg)
        if e.code == 429 or e.code >= 500:
            raise Retry("transient", msg)
        die(msg)
    except (urllib.error.URLError, socket.timeout, ConnectionError, http.client.HTTPException) as e:
        raise Retry("transient", "could not reach Delphi after %.0fs: %s" % (time.time() - t0, getattr(e, "reason", e)))
    finally:
        stop.set()
    reply = "".join(chunks)
    tokens = " (%s prompt + %s reply tokens)" % (usage.get("prompt_tokens"), usage.get("completion_tokens")) if usage else ""
    log("reply complete: %d chars, %d chars of reasoning, finish_reason=%s in %.1fs%s"
        % (len(reply), state["reasoning"], finish, time.time() - t0, tokens))
    if not reply.strip():
        raise Retry("empty" if finish == "length" else "transient",
                    "the model returned an empty answer (finish_reason=%s, %d chars of reasoning%s)"
                    % (finish, state["reasoning"], tokens))
    if finish == "length":
        log("WARNING: the answer was cut off at --max-tokens")
        reply += "\n\n[report truncated: the model hit its reply token limit]"
    return reply


def send_report(to_addr, report_path, name):
    sender = pwd.getpwuid(os.getuid())[0] + "@jlab.org"
    with open(report_path) as fh:
        report = fh.read()
    msg = EmailMessage()
    msg["Subject"] = "MCwrapper AI log analysis: " + name
    msg["From"] = sender
    msg["To"] = to_addr
    msg.set_content(report)
    msg.add_attachment(report.encode(), maintype="text", subtype="plain", filename=os.path.basename(report_path))
    log("emailing %s from %s via localhost SMTP" % (to_addr, sender))
    try:
        s = smtplib.SMTP("localhost", timeout=60)
        s.send_message(msg)
        s.quit()
    except (OSError, smtplib.SMTPException) as e:
        die("email failed (%s); the report is still at %s" % (e, report_path))


def main():
    ap = argparse.ArgumentParser(description="AI analysis of an MCwrapper failed-log tarball, emailed as a report.")
    ap.add_argument("tarball", help="path to the .tar(.gz) of logs")
    ap.add_argument("email", help="address to send the report to")
    ap.add_argument("--model", default=DEFAULT_MODEL, help="Delphi model id (default %s)" % DEFAULT_MODEL)
    ap.add_argument("--workdir", default="/tmp/mcwrap", help="extraction/report directory (default /tmp/mcwrap)")
    ap.add_argument("--per-file", type=int, default=10000, help="max chars sent per log file (default 10000)")
    ap.add_argument("--context-tokens", type=int, default=163840, help="model context window (default 163840, jlab/qwen3.8-27b)")
    ap.add_argument("--max-chars", type=int, help="max chars of logs sent in total (default: what fits in "
                    "--context-tokens minus --max-tokens at 2 chars/token, less 10%%)")
    ap.add_argument("--max-tokens", type=int, default=60000, help="max tokens in the model's reply, reasoning included (default 60000)")
    ap.add_argument("--request-id", type=int, help="LogRequests.ID whose AnalysisRequested stage to update")
    ap.add_argument("--attempts", type=int, default=5, help="Delphi attempts before giving up (default 5); a context "
                    "overflow resends 60%% of the logs, an answer lost to reasoning gets 1.5x --max-tokens, "
                    "network/5xx errors back off and resend")
    args = ap.parse_args()
    global REQUEST_ID
    REQUEST_ID = args.request_id
    if args.max_chars is None:
        # 280k chars of R26 logs exceeded 103.8k tokens, i.e. < 2.7 chars/token
        args.max_chars = int((args.context_tokens - args.max_tokens) * 2 * 0.9)
    if args.max_chars <= 0:
        die("--max-tokens %d leaves no room for logs in a %d-token context" % (args.max_tokens, args.context_tokens))

    pat = os.environ.get("DELPHI_PAT")
    if not pat:
        die("DELPHI_PAT is not set")
    if not EMAIL_RE.match(args.email):
        die("bad email address %r" % args.email)
    if not os.path.isfile(args.tarball) or not tarfile.is_tarfile(args.tarball):
        die("not a tar file: %s" % args.tarball)

    t0 = time.time()
    set_stage(3)
    log("[1/4] extracting %s (%s)" % (args.tarball, human(os.path.getsize(args.tarball))))
    os.makedirs(args.workdir, mode=0o700, exist_ok=True)
    folder = safe_extract(args.tarball, args.workdir)
    name = os.path.basename(folder)

    log("[2/4] reading the manifest and logs")
    prompt = PROMPT.format(folder=folder)
    max_chars, max_tokens = args.max_chars, args.max_tokens
    analysis = None
    for attempt in range(1, args.attempts + 1):
        logs = collect_logs(folder, args.per_file, max_chars)
        if not logs:
            die("no readable files in %s" % folder)
        log("[3/4] asking the model for an analysis, attempt %d of %d (this can take minutes)" % (attempt, args.attempts))
        set_stage(4)
        try:
            analysis = ask_delphi(pat, args.model, prompt, logs, max_tokens)
            break
        except Retry as e:
            if attempt == args.attempts:
                die("%s (gave up after %d attempts)" % (e, attempt))
            if e.kind == "context":
                max_chars = int(max_chars * 0.6)
                log("context overflow; retrying with %d chars of logs: %s" % (max_chars, str(e)[:200]))
            elif e.kind == "empty":
                max_tokens = min(int(max_tokens * 1.5), args.context_tokens // 2)
                max_chars = min(max_chars, int((args.context_tokens - max_tokens) * 2 * 0.9))
                log("reasoning used every reply token; retrying with %d reply tokens and %d chars of logs"
                    % (max_tokens, max_chars))
            else:
                wait = 30 * attempt
                log("%s; retrying in %ds" % (str(e)[:300], wait))
                time.sleep(wait)
    report_path = os.path.join(args.workdir, "AIanalysis_%s.txt" % name)
    with open(report_path, "w") as fh:
        fh.write(analysis + "\n")
    log("report written to " + report_path)

    log("[4/4] sending the report")
    set_stage(5)
    send_report(args.email, report_path, name)
    set_stage(6)
    log("done in %.0fs: emailed %s" % (time.time() - t0, args.email))


if __name__ == "__main__":
    main()
