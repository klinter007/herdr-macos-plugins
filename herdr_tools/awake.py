import fcntl
import subprocess
import time
import os

from . import service
from .common import api, choose, notify, popup, read_json, state_dir, write_json


def set_mode(mode):
    path = state_dir(True)
    with (path / "mode.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if mode == 'toggle':
            previous = read_json(path / 'mode.json', {'mode': 'off'})['mode']
            active = read_json(path / 'status.json', {}).get('active', False)
            mode = 'off' if previous == 'on' or (previous == 'auto' and active) else 'on'
        write_json(path / "mode.json", {"mode": mode})
    service.start("awake")


def mode():
    return read_json(state_dir(True) / "mode.json", {"mode": "off"})["mode"]


def watch():
    service.cleanup_on_signal()
    lock = service.worker_lock()
    if lock is None:
        return
    child = None
    failing_since = None
    refusals = 0
    desired = 'off'
    try:
        while True:
            try:
                if not service.enabled():
                    break
                desired = mode()
                awake = desired == "on"
                if desired == "auto":
                    awake = any(a.get("agent_status") == "working"
                                for a in api("agent.list")["agents"])
                if awake and (child is None or child.poll() is not None):
                    old = child
                    # macOS releases the assertion when this supervisor exits,
                    # including SIGKILL. API latency cannot create a renewal gap.
                    child = subprocess.Popen(["/usr/bin/caffeinate", "-di", "-w", str(os.getpid())],
                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    if old and old.poll() is None:
                        old.terminate()
                        old.wait(timeout=3)
                if not awake and child:
                    if child.poll() is None:
                        child.terminate()
                    child.wait(timeout=3)
                    child = None
                actual = child is not None and child.poll() is None
                label = "ON" if actual else ("AUTO · idle" if desired == "auto" else "OFF")
                service.status({"mode": desired, "active": actual,
                                "label": "Awake " + label,
                                "pid": child.pid if actual else None, "checked_at": time.time()})
                failing_since = None
                refusals = 0
            except FileNotFoundError:
                break
            except ConnectionRefusedError:
                # macOS can also refuse a connection when the backlog is full.
                refusals += 1
                if refusals >= 3:
                    break
                time.sleep(1)
                continue
            except Exception as error:
                refusals = 0
                if failing_since is None:
                    failing_since = time.monotonic()
                actual = child is not None and child.poll() is None
                service.status({"mode": desired, "active": actual, "label": "Awake ?",
                                "pid": child.pid if actual else None,
                                "error": str(error), "checked_at": time.time()})
                # Keep an existing assertion through short stalls. Bound a
                # server that accepts connections but never recovers to 15 min.
                if time.monotonic() - failing_since >= 900:
                    break
            time.sleep(3)
    finally:
        if child and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=3)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=3)
        service.status({"mode": desired, "active": False, "checked_at": time.time(),
                        **({"error": "Awake worker stopped"} if desired != 'off' else {})})
        lock.close()


def main(command):
    if command == "watch":
        watch()
    elif command == "startup":
        if mode() != "off":
            service.start("awake")
    elif command == "menu":
        popup("picker")
    elif command == "picker":
        saved = mode()
        modes = ["on", "off"]
        labels = ["☕ On — keep system and display awake", "🌙 Off — allow normal sleep"]
        labels = [label + ("  [saved]" if value == saved else "")
                  for value, label in zip(modes, labels)]
        status = read_json(state_dir(True) / "status.json", {})
        fresh = time.time() - status.get("checked_at", 0) < 20
        actual = ("On" if status.get("active") else "Off") if fresh else "unconfirmed"
        choice = choose(f"Stay Awake: {actual} · saved: {saved.upper()}", labels,
                        initial=modes.index(saved) if saved in modes else 0, mouse=True,
                        subtitle="Click / Enter to save · restored at startup · Esc close")
        if choice is not None:
            set_mode(modes[choice])
            notify(f"Stay Awake: {modes[choice].upper()} saved; restored next startup.")
    elif command in ("on", "off", "auto", "toggle"):
        set_mode(command)
        if command != 'toggle':
            notify(f"Stay Awake: {command.upper()}")
