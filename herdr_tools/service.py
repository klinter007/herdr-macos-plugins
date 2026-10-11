"""Small, session-owned workers. No shared PID killing and no unbounded logs."""
import fcntl
import os
from pathlib import Path
import subprocess
import sys
import signal

from .common import api, state_dir, write_json


def enabled():
    plugins = api("plugin.list", {"plugin_id": os.environ["HERDR_PLUGIN_ID"]})["plugins"]
    return any(p["enabled"] for p in plugins)


def worker_lock():
    stream = (state_dir(True) / "worker.lock").open("a")
    try:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        stream.close()
        return None
    return stream


def cleanup_on_signal():
    def stop(signum, frame):
        raise SystemExit(0)
    for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        signal.signal(sig, stop)


def start(module):
    # Check the same lock the worker holds; concurrent starts are also harmless.
    lock = worker_lock()
    if lock is None:
        return
    lock.close()
    subprocess.Popen([sys.executable, "-m", "herdr_tools.cli", module, "watch"],
                     cwd=Path(__file__).resolve().parent.parent,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True)




def status(value):
    write_json(state_dir(True) / "status.json", value)
