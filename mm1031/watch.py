"""Realtime watcher: keep the registry in sync with the filesystem.

The engine's ingest is scan-based; without a watcher, files saved a
second ago are invisible until someone runs a manual scan. This loop
closes that gap: every interval it incrementally scans every
registered node (unchanged files are skipped by size+mtime, so a
round over thousands of files is cheap), and when a round registered
something new it refreshes previews and re-runs conversation batch
inference, so new files arrive in the app with thumbnails, excerpts
and a conversation to hang off.

Run:  python3 -m mm1031.watch --db leanfile.db [--interval 30] [--once]
Logs go to stdout with timestamps; launchd redirects them to a file.
A failed round is logged and the loop carries on.
"""
import argparse
import subprocess
import sys
import time
from datetime import datetime

from .core import Registry
from .nodes import list_nodes, scan_node


def log(msg):
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("[%s] %s" % (stamp, msg), flush=True)


def one_round(db_path, cache_dir, state=None, background_previews=True):
    """Scan all nodes once. Returns the number of newly registered files."""
    reg = Registry(db_path)
    total = 0
    try:
        for node in list_nodes(reg):
            try:
                stats = scan_node(reg, node["name"])
            except Exception as exc:  # one bad node must not stop the rest
                log("scan failed for node %s: %r" % (node["name"], exc))
                continue
            total += stats["registered"]
            if stats["registered"] or stats["errors"]:
                log("scan %s: %s" % (node["name"], stats))
    finally:
        reg.db.close()
    if total > 0:
        # Inference is fast, pure SQL: run it inline so new files get
        # their conversation within this round. Previews are the slow
        # part (Quick Look over the whole library takes minutes), so
        # in loop mode they run as a background subprocess: the scan
        # cadence must never wait on thumbnail generation. A second
        # launch is skipped while one is still running.
        from .preview import build_previews, infer_conversation_batches

        log("inference: %s" % infer_conversation_batches(db_path))
        if background_previews:
            proc = (state or {}).get("previews_proc")
            if proc is not None and proc.poll() is None:
                log("previews still running (pid %d); not relaunching"
                    % proc.pid)
            else:
                proc = subprocess.Popen(
                    [sys.executable, "-m", "mm1031.cli", "--db", db_path,
                     "build-previews", "--cache", cache_dir],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                if state is not None:
                    state["previews_proc"] = proc
                log("previews launched in background (pid %d)" % proc.pid)
        else:
            log("previews: %s" % build_previews(db_path, cache_dir))
        log("round done: %d new file(s) registered" % total)
    return total


def main(argv=None):
    ap = argparse.ArgumentParser(prog="mm1031-watch")
    ap.add_argument("--db", default="mm1031.db")
    ap.add_argument("--cache", default="preview-cache",
                    help="preview cache dir (same convention as the CLI)")
    ap.add_argument("--interval", type=float, default=30,
                    help="seconds between rounds (default 30)")
    ap.add_argument("--once", action="store_true",
                    help="run a single round and exit")
    args = ap.parse_args(argv)
    log("watcher started: db=%s interval=%ss once=%s"
        % (args.db, args.interval, args.once))
    state = {}
    while True:
        try:
            one_round(args.db, args.cache, state=state,
                      background_previews=not args.once)
        except Exception as exc:  # never let one round kill the watcher
            log("round failed: %r" % (exc,))
        if args.once:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
