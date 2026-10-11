import json
import os
from pathlib import Path
import shutil
import fcntl
import signal
import subprocess

from .common import UserError, api, choose, popup, run, source_context
from .paths import Destination, extract, resolve


RUNTIME = Path(__file__).resolve().parent.parent / "runtime"


def program_path(program):
    bundled = RUNTIME / ("tode" if program == "tode" else "terminal-browser") / "bin" / program
    return str(bundled) if bundled.is_file() else shutil.which(program)


def viewer_environment():
    return {"DO_NOT_TRACK": "1", "TERMINAL_BROWSER_NO_TELEMETRY": "1",
            "TODE_INSTALL_ROOT": str(RUNTIME / "tode"),
            "XDG_STATE_HOME": str(RUNTIME / "state"), "XDG_DATA_HOME": str(RUNTIME / "data"),
            "XDG_CONFIG_HOME": str(RUNTIME / "config"), "XDG_BIN_HOME": str(RUNTIME / "bin"),
            "XDG_CACHE_HOME": str(RUNTIME / "cache")}


def roots(ctx):
    project = (ctx.get("worktree") or {}).get("checkout_path") or ctx.get("workspace_cwd")
    cwd = ctx.get("focused_pane_cwd") or project
    if not cwd:
        raise UserError("No source directory available.")
    return cwd, project


def selected(ctx):
    raw = ctx.get("clicked_url") or ctx.get("selected_text")
    return resolve(raw, *roots(ctx)) if raw else None


def open_item(item, action, ctx):
    if action == "copy":
        run(["/usr/bin/pbcopy"], input=item.value.encode())
    elif action == "reveal":
        if item.web:
            raise UserError("Web links do not have a Finder location.")
        run(["/usr/bin/open", "-R", item.value])
    elif action == "open":
        run(["/usr/bin/open", item.value])
    elif action == "tab":
        program = "terminal-browser" if item.web else "tode"
        if not program_path(program):
            raise UserError(f"{program} is not installed. Install the reviewed browser/editor integration first.")
        cwd, _ = roots(ctx)
        # No shell command injection: Herdr directly launches the manifest's argv.
        api("plugin.pane.open", {
            "plugin_id": "gili.files", "entrypoint": "viewer", "placement": "tab",
            "workspace_id": ctx.get("workspace_id"), "focus": True,
            "env": {"TOOLS_DESTINATION": json.dumps(item.__dict__),
                    "TOOLS_VIEWER_CWD": cwd,
                    **viewer_environment()},
        })


def viewer():
    item = Destination(**json.loads(os.environ["TOOLS_DESTINATION"]))
    os.chdir(os.environ["TOOLS_VIEWER_CWD"])
    if item.web:
        argv = ["terminal-browser", "open", item.value]
    else:
        argv = ["tode", "--new-window"]
        if item.line:
            argv += ["--goto", f"{item.value}:{item.line}:{item.column or 1}"]
        else:
            argv += [item.value]
    executable = program_path(argv[0])
    if not executable:
        raise UserError(f"{argv[0]} is unavailable.")
    # One lease per editor tab. Shut down our dedicated editor backend after its
    # final tab closes; a new tab waits until any in-progress shutdown finishes.
    lease = None
    if not item.web:
        RUNTIME.mkdir(exist_ok=True)
        lease = (RUNTIME / "editor.lock").open("a")
        fcntl.flock(lease, fcntl.LOCK_SH)
    child = subprocess.Popen([executable, *argv[1:]])
    def stop(signum, frame):
        if child.poll() is None:
            child.terminate()
    for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        signal.signal(sig, stop)
    try:
        child.wait()
    finally:
        if child.poll() is None:
            child.terminate()
        if lease:
            fcntl.flock(lease, fcntl.LOCK_UN)
            try:
                fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                pass
            else:
                subprocess.run([executable, "--shutdown"], timeout=20, check=False,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            finally:
                lease.close()


def default_app_name(item):
    """Ask Launch Services, including per-file associations; never choose by suffix."""
    script = '''ObjC.import("AppKit"); function run(argv) {
        var url = argv[1] === "web" ? $.NSURL.URLWithString(argv[0]) : $.NSURL.fileURLWithPath(argv[0]);
        var app = $.NSWorkspace.sharedWorkspace.URLForApplicationToOpenURL(url);
        return app ? ObjC.unwrap($.NSFileManager.defaultManager.displayNameAtPath(app.path)) : "";
    }'''
    try:
        result = subprocess.run(['/usr/bin/osascript', '-l', 'JavaScript', '-e', script,
                                 item.value, 'web' if item.web else 'file'],
                                capture_output=True, text=True, timeout=3, check=True)
        return result.stdout.strip().removesuffix('.app')
    except (OSError, subprocess.SubprocessError):
        return ''


def plain_folder(item):
    # macOS packages look like directories to pathlib but must get the file menu.
    if item.web or not Path(item.value).is_dir():
        return False
    script = '''ObjC.import("AppKit"); function run(argv) {
        return $.NSWorkspace.sharedWorkspace.isFilePackageAtPath(argv[0]) ? "package" : "folder";
    }'''
    try:
        result = subprocess.run(['/usr/bin/osascript', '-l', 'JavaScript', '-e', script, item.value],
                                capture_output=True, text=True, timeout=3, check=True)
        return result.stdout.strip() == 'folder'
    except (OSError, subprocess.SubprocessError):
        return False  # Uncertain packages get a menu, never an automatic launch.


def show_destinations(items, ctx):
    if len(items) > 1:
        index = choose("Choose a file or folder", [item.value for item in items], mouse=True)
        if index is None:
            return
        item = items[index]
    else:
        item = items[0]
    if plain_folder(item):
        run(["/usr/bin/open", "-a", "Finder", item.value])
        return
    app = default_app_name(item)
    label = f"Open in {app} (default)" if app else "Open in default app"
    options = [(label, "open")]
    if program_path("terminal-browser" if item.web else "tode"):
        options.append(("Open in Herdr Tab", "tab"))
    if not item.web:
        options.append(("Reveal in Finder", "reveal"))
    options.append(("Copy Link" if item.web else "Copy Path", "copy"))
    index = choose("Open where? — " + (item.value if item.web else Path(item.value).name),
                   [label for label, _ in options], mouse=True)
    if index is not None:
        open_item(item, options[index][1], ctx)


def picker():
    ctx = source_context()
    prepared = os.environ.get("TOOLS_DESTINATIONS")
    items = [Destination(**item) for item in json.loads(prepared)] if prepared else destinations(ctx)
    if not items:
        raise UserError("No existing files or links found in the selection or visible pane.")
    show_destinations(items, ctx)


def copied_selection():
    """Herdr 0.9.3 clears mouse selections before dispatching direct bindings."""
    try:
        result = subprocess.run(['/usr/bin/pbpaste'], capture_output=True,
                                timeout=2, check=True)
        if len(result.stdout) > 8192:
            return ''
        text = result.stdout.decode('utf-8').strip()
        if len(text) < 2 or any(ord(c) < 32 and c not in '\r\n\t' for c in text):
            return ''
        return text
    except (OSError, UnicodeError, subprocess.SubprocessError):
        return ''


def destinations(ctx):
    visible = None
    from_clipboard = False
    if not (ctx.get('selected_text') or ctx.get('clicked_url')):
        pane = ctx.get('focused_pane_id')
        if not pane:
            raise UserError('No source pane available.')
        visible = api('pane.read', {'pane_id': pane, 'source': 'visible'})['read']['text']
        copied = copied_selection()
        # Only use copied text actually present in this viewport. This also
        # tolerates terminal wrapping; resolve still verifies the real file.
        joined = lambda text: ''.join(line.strip() for line in text.splitlines())
        if copied and any(c in copied for c in '/.:') and joined(copied) in joined(visible):
            ctx = {**ctx, 'selected_text': copied}
            from_clipboard = True
    raw = ctx.get('clicked_url') or ctx.get('selected_text')
    if raw:
        try:
            return [resolve(raw, *roots(ctx))]
        except (UserError, ValueError, OSError):
            if raw.strip().strip('`"<>').lower().startswith(('https://', 'http://')) and any(c in raw for c in '\r\n'):
                raise UserError('This URL contains a real newline. Select its unwrapped hyperlink destination.')
            items = extract(raw, *roots(ctx))
            if items:
                return list({item.value: item for item in items}.values())
    if visible is None:
        pane = ctx.get('focused_pane_id')
        if not pane:
            raise UserError('No source pane available.')
        visible = api('pane.read', {'pane_id': pane, 'source': 'visible'})['read']['text']
    items = list({item.value: item for item in extract(visible, *roots(ctx))}.values())
    if raw:
        fragment = raw.strip().strip('`"<>')
        matched = [item for item in items if fragment in item.value]
        if matched or not from_clipboard:
            items = matched
    return items


def quick_open(ctx):
    items = destinations(ctx)
    if not items:
        raise UserError("No existing files or links found. Select the path, including its wrapped lines, and try again.")
    if len(items) == 1 and plain_folder(items[0]):
        run(["/usr/bin/open", "-a", "Finder", items[0].value])
        return
    # Resolve in the original pane before opening the popup. Never scan the popup.
    popup("picker", {"TOOLS_SOURCE_CONTEXT": json.dumps(ctx),
                     "TOOLS_DESTINATIONS": json.dumps([item.__dict__ for item in items])})


def main(command):
    if command == "viewer":
        viewer()
    elif command == "picker":
        picker()
    elif command == "menu":
        quick_open(source_context())
    elif command == "quick-open":
        quick_open(source_context())
    else:
        ctx = source_context()
        item = selected(ctx)
        if item:
            open_item(item, command, ctx)
        else:
            popup("picker")
