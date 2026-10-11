import curses
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import uuid


class UserError(Exception):
    pass


def api(method, params=None):
    """One bounded request, never retry an uncertain mutation."""
    address = os.environ.get("HERDR_SOCKET_PATH")
    if not address:
        raise UserError("Run this action inside Herdr.")
    request_id = str(uuid.uuid4())
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(8)
        sock.connect(address)
        sock.sendall((json.dumps({"id": request_id, "method": method,
                                 "params": params or {}}) + "\n").encode())
        with sock.makefile("rb") as stream:
            line = stream.readline(8 * 1024 * 1024)
    reply = json.loads(line)
    if reply.get("id") != request_id:
        raise UserError("Herdr returned a mismatched response.")
    if "error" in reply:
        raise UserError(reply["error"]["message"])
    return reply["result"]


def context():
    return json.loads(os.environ.get("HERDR_PLUGIN_CONTEXT_JSON", "{}"))


def state_dir(session=False):
    value = os.environ.get("HERDR_PLUGIN_STATE_DIR")
    if not value:
        raise UserError("Plugin state directory is missing; invoke through Herdr.")
    path = Path(value)
    if session:
        key = hashlib.sha256(os.environ["HERDR_SOCKET_PATH"].encode()).hexdigest()[:16]
        path /= key
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def write_json(path, value):
    path = Path(path)
    fd, temp = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError:
        return default


def run(argv, **kwargs):
    return subprocess.run(argv, check=True, timeout=15, **kwargs)


def popup(entrypoint, env=None):
    ctx = context()
    return api("plugin.pane.open", {
        "plugin_id": os.environ["HERDR_PLUGIN_ID"], "entrypoint": entrypoint,
        "placement": "popup", "focus": True,
        "env": {"TOOLS_SOURCE_CONTEXT": json.dumps(ctx), **(env or {})},
    })


def source_context():
    return json.loads(os.environ.get("TOOLS_SOURCE_CONTEXT", "null")) or context()


def notify(message):
    api("notification.show", {"title": "Herdr tools", "body": message, "sound": "none"})


def choose(title, labels, *, initial=0, subtitle=None, mouse=False):
    if not labels:
        raise UserError("No items available.")

    def screen(win):
        curses.set_escdelay(25)
        curses.curs_set(0)
        selected = max(0, min(initial, len(labels) - 1))
        win.keypad(True)
        if mouse:
            curses.mousemask(curses.BUTTON1_CLICKED | curses.BUTTON1_RELEASED)
        while True:
            win.erase()
            height, width = win.getmaxyx()
            def put(y, text, style=0):
                if y < height - 1 and width > 2:
                    win.addnstr(y, 1, text.replace("\n", " "), width - 2, style)
            put(1, title, curses.A_BOLD)
            put(2, subtitle or "↑↓ choose   Enter open   Esc close", curses.A_DIM)
            visible = max(1, height - 5)
            start = max(0, selected - visible + 1)
            for i in range(start, min(len(labels), start + visible)):
                put(i - start + 4, str(labels[i]), curses.A_REVERSE if i == selected else 0)
            win.refresh()
            key = win.getch()
            if key in (27, ord("q")):
                return None
            if key in (curses.KEY_UP, ord("k")):
                selected = max(0, selected - 1)
            elif key in (curses.KEY_DOWN, ord("j")):
                selected = min(len(labels) - 1, selected + 1)
            elif key in (10, 13, curses.KEY_ENTER):
                return selected
            elif mouse and key == curses.KEY_MOUSE:
                try:
                    _, x, y, _, buttons = curses.getmouse()
                except curses.error:
                    continue
                index = start + y - 4
                if (1 <= x < width - 1 and 4 <= y < min(height - 1, 4 + visible)
                        and 0 <= index < len(labels)
                        and buttons & (curses.BUTTON1_CLICKED | curses.BUTTON1_RELEASED)):
                    return index
    return curses.wrapper(screen)
