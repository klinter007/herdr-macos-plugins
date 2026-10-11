import re
import os
from pathlib import Path
import shutil
import subprocess
import time

from . import service
from .common import api, choose, popup, state_dir, read_json


class FolderSizes:
    """One low-priority scan at a time, with a five-minute bounded cache."""
    def __init__(self):
        self.cache = {}
        self.child = None
        self.path = None
        self.started = 0

    def close(self):
        if self.child is not None:
            if self.child.poll() is None:
                self.child.terminate()
            try:
                self.child.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                self.child.kill()
                self.child.communicate()
            self.child = None

    def get(self, path):
        now = time.monotonic()
        if self.child is not None:
            expired = now - self.started > 30
            if self.child.poll() is not None or expired:
                if expired:
                    self.child.kill()
                output, _ = self.child.communicate()
                value = 'unavailable'
                if not expired and self.child.returncode == 0:
                    try:
                        kib = int(output.split()[0])
                        value = f'{kib / 1024**2:.1f} GiB' if kib >= 1024**2 else f'{kib / 1024:.0f} MiB'
                    except (ValueError, IndexError):
                        pass
                self.cache[self.path] = (now, value)
                if len(self.cache) > 64:
                    del self.cache[next(iter(self.cache))]
                self.child = None
        cached = self.cache.get(path)
        if path and (not cached or now - cached[0] > 300) and self.child is None:
            self.path, self.started = path, now
            self.child = subprocess.Popen(['/usr/bin/nice', '-n', '10', '/usr/bin/du', '-skx', path],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        return cached[1] if cached else ('scanning…' if path else 'unavailable')


def cpu_usage():
    # Sample two intervals; the first macOS top sample is a since-boot average.
    result = subprocess.run(["/usr/bin/top", "-l", "2", "-s", "1", "-n", "0"],
                            capture_output=True, text=True, timeout=5, check=True)
    samples = re.findall(r"CPU usage:.*?([\d.]+)% idle", result.stdout)
    return f"{100 - float(samples[-1]):.0f}%" if samples else "unavailable"


def workspace_path(ws, panes):
    worktree = ws.get("worktree") or {}
    if worktree.get("checkout_path"):
        return worktree["checkout_path"]
    members = [p for p in panes if p.get("workspace_id") == ws["workspace_id"] and p.get("cwd")]
    # A non-git workspace's active tab is the best available project context.
    members.sort(key=lambda p: (p.get("tab_id") != ws.get("active_tab_id"), not p.get("focused")))
    return members[0]["cwd"] if members else None


def collect():
    try:
        cpu = cpu_usage()
    except (OSError, subprocess.SubprocessError):
        cpu = "unavailable"
    panes = api("pane.list")["panes"]
    values = []
    for ws in api("workspace.list")["workspaces"]:
        path = workspace_path(ws, panes)
        try:
            disk = shutil.disk_usage(path) if path else None
            free = f"{disk.free / 1024**3:.0f} GiB free" if disk else "unavailable"
        except OSError:
            free = "unavailable"
        values.append({"workspace_id": ws["workspace_id"], "label": ws["label"],
                       "path": path, "cpu": cpu, "disk": free, "focused": ws.get("focused", False)})
    return values


def watch():
    service.cleanup_on_signal()
    lock = service.worker_lock()
    if lock is None:
        return
    stop = state_dir(True) / "stopped"
    failures = 0
    sizes = FolderSizes()
    try:
        while not stop.exists():
            try:
                if not service.enabled():
                    break
                values = collect()
                current = next((v for v in values if v['focused']), None)
                folder_size = sizes.get(current['path'] if current else None)
                if current:
                    current['size'] = folder_size
                service.status({"current": current, "checked_at": time.time()})
                failures = 0
            except Exception as error:
                failures += 1
                service.status({"error": str(error), "checked_at": time.time()})
                if failures >= 3:
                    break
            time.sleep(5)
    finally:
        sizes.close()
        service.status({"current": None, "checked_at": time.time()})
        lock.close()


def main(command):
    stop = state_dir(True) / "stopped"
    if command == "watch":
        watch()
    elif command == "stop":
        stop.touch()
    elif command in ("start", "startup"):
        if command == "start":
            stop.unlink(missing_ok=True)
        if not stop.exists():
            service.start("metrics")
    elif command == "menu":
        popup("picker")
    elif command == "picker":
        saved = read_json(state_dir(True) / 'status.json', {})
        current = saved.get('current')
        if current:
            choose('System Monitor — current project', [f'CPU {current["cpu"]}',
                f'Drive: {current["disk"]}', f'Folder: {current.get("size", "scanning…")}',
                current['path'] or 'No directory', 'Folder size: allocated space; refreshed about every 5 minutes'])
        else:
            choose('System Monitor', ['No recent sample — use Start System Monitor'])
