"""Run Specter as an independent supervised OS process on the Vultr VM.

This does not provide host-compromise resistance: both services use one machine.
"""
from __future__ import annotations
import signal
import threading
from .specter import SpecterJournal, watch


def main():
    stop = threading.Event()
    def shutdown(signum, frame):
        stop.set()
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    watch(stop, SpecterJournal(), interval=1.0)

if __name__ == '__main__':
    main()
