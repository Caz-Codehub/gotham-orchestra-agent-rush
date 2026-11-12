"""Run the restricted Specter audit sidecar using pre-provisioned OS resources.

This command never creates OS users/groups, sockets' parent directory,
permissions, or privileged services. An administrator must configure distinct
OS identities before enabling GOTHAM_REQUIRE_INDEPENDENT_SPECTER on workers.
"""
from __future__ import annotations

import argparse
import os
import signal
import stat
import threading
from pathlib import Path

from .specter_transport import SpecterRecordServer, SpecterVerifyServer


def main(argv=None):
    ap = argparse.ArgumentParser(description="Gotham Specter record-only + Batman reader service")
    ap.add_argument("--journal", required=True)
    ap.add_argument("--record-socket", required=True)
    ap.add_argument("--verify-socket", required=True)
    ap.add_argument("--worker-uid", required=True, type=int)
    ap.add_argument("--batman-api-uid", required=True, type=int)
    args = ap.parse_args(argv)

    if os.geteuid() == 0:
        ap.error("Specter must not run as root")
    if args.worker_uid == args.batman_api_uid:
        ap.error("worker and Batman API must have distinct UIDs")
    if args.worker_uid == os.geteuid() or args.batman_api_uid == os.geteuid():
        ap.error("auditor, worker and Batman API must use three distinct UIDs")
    if args.worker_uid < 0 or args.batman_api_uid < 0:
        ap.error("invalid peer UID")
    if os.environ.get("GOTHAM_SPECTER_RECORD_SOCKET") or os.environ.get("GOTHAM_SPECTER_VERIFY_SOCKET"):
        ap.error("service must hold local journal, never connect back through an audit client")
    if os.environ.get("GOTHAM_AUDIT_KEY"):
        ap.error("auditor must use its private keyfile, not an inherited environment secret")
    journal = Path(args.journal)
    record = Path(args.record_socket)
    verify = Path(args.verify_socket)
    if record == verify or record.parent == journal.parent or verify.parent == journal.parent:
        ap.error("record, verify and journal storage must be separated")
    if not all(p.parent.is_dir() for p in (record, verify, journal)):
        ap.error("all socket and journal directories must be provisioned by the administrator")
    for p in (record.parent, verify.parent, journal.parent):
        if p.is_symlink():
            ap.error("Specter IPC and journal directories cannot be symbolic links")
        mode = stat.S_IMODE(p.stat().st_mode)
        if p.stat().st_uid != os.geteuid():
            ap.error("each private Specter directory must be owned by the auditor service UID")
        if mode & 0o007:
            ap.error("Specter socket and journal directories must deny access to other users")
        if p == journal.parent and mode & 0o077:
            ap.error("Specter journal directory must be private to auditor UID (mode 0700)")
        if p != journal.parent and mode & 0o027:
            ap.error("Specter socket directories may grant group-only connect but not group writes")
    if journal.is_symlink() or journal.with_suffix(".key").is_symlink():
        ap.error("Specter journal and key must not be symbolic links")
    for private_file in (journal, journal.with_suffix(".key")):
        if private_file.exists():
            if private_file.stat().st_uid != os.geteuid():
                ap.error("Specter journal and key must be owned by auditor UID")
            if stat.S_IMODE(private_file.stat().st_mode) & 0o077:
                ap.error("Specter journal and key must not be group/world readable")

    stop = threading.Event()
    rec = None
    ver = None
    threads = []
    try:
        # The directories control socket-group ownership via setgid. This
        # service will not change user/group ownership of files.
        rec = SpecterRecordServer(record, journal, allowed_uids={args.worker_uid}, mode=0o660)
        ver = SpecterVerifyServer(verify, journal, allowed_uids={args.batman_api_uid}, mode=0o660)
        threads = [
            threading.Thread(target=rec.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True),
            threading.Thread(target=ver.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True),
        ]
        for thread in threads:
            thread.start()
        signal.signal(signal.SIGTERM, lambda *_: stop.set())
        signal.signal(signal.SIGINT, lambda *_: stop.set())
        print("Specter IPC ready: segregated recorder and Batman verifier", flush=True)
        stop.wait()
    finally:
        if ver:
            if len(threads) == 2 and threads[1].is_alive():
                ver.shutdown()
            ver.server_close()
        if rec:
            if threads and threads[0].is_alive():
                rec.shutdown()
            rec.server_close()
        for thread in threads:
            thread.join(timeout=3)


if __name__ == "__main__":
    main()
