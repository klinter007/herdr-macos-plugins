# Herdr macOS plugins

Three small plugins for [Herdr](https://herdr.dev): open files from terminal output,
keep your Mac awake, and see CPU/disk/project-folder usage in one status bar.
Uses standard Herdr—no custom build. MIT licensed.

## Files and Links

Select a path, filename, or passage containing paths, then press **Control+Option+O**.

- **One file:** an “Open where?” menu, naming the app macOS would normally use.
- **Several files:** choose one, then choose where to open it.
- **Folder:** opens directly in Finder.

Menus accept mouse clicks, arrow keys and Enter; Esc closes them. Reveal in Finder
and Copy Path are also available. File links go through the same menu. macOS file
packages, including `.app` bundles, get the file menu rather than the folder shortcut.

MP4, JPEG, HTML, Markdown and other files use the default application configured
on **your** Mac, exactly as `/usr/bin/open` does. No extension-to-app list is
hardcoded. The menu queries Launch Services for the actual app name. Opening a
movie requests the default player; whether playback begins automatically is up
to that application.

Relative paths use the source pane's directory, then its project directory. Spaces,
Unicode, `file://` URLs, Markdown paths and line/column suffixes are supported.
Select all fragments of a path broken across lines. A passage such as
`Watch (output/movie.mp4) · Read (output/story.txt)` offers both files. A filename
fragment narrows the list to matching complete paths visible in the pane.

Herdr 0.9.3 clears mouse selections before dispatching plugin shortcuts. As a
workaround, the plugin reads the clipboard **only when invoked** and uses
path-shaped copied text only if it appears in the visible pane. Herdr's default
`copy_on_select = true` makes this automatic; otherwise copy first. An older copied
path can still be considered while visible. There is no clipboard watcher.
With no usable selection, the menu lists paths detected on the visible screen.
Plain single clicks on arbitrary text and native right-click menus are not provided.
Unselected scanning skips bare extensionless names and dotfiles such as Makefile
and .env to avoid treating ordinary words as files; explicitly select those paths.

“Open in Herdr Tab” is optional and shown only when a compatible Tode (files) or
terminal-browser (web links) command is available. Neither is bundled or installed.
The optional editor integration uses a local code-server backend and project-local
runtime state; ordinary default-app opening has no such dependency. See
[verification and limitations](VERIFICATION.md) before using that integration.

## Stay Awake

**Ctrl+B**, release, then **Shift+A** opens a clickable On/Off menu. On runs
`caffeinate -di -w <worker-pid>`, preventing idle system and display sleep while
its worker lives. It does not override closing the lid or OS-enforced sleep.
The saved choice is restored when the Herdr server starts.

**☕** running · **🌙** off · **⏳** changing · **❔** unconfirmed/error.
The status reflects the observed worker state. Confirmed server loss or disabling
the plugin releases the assertion. Temporary API failures are tolerated for up
to 15 minutes; continued failure then releases it. The native status bar is an
indicator, not a clickable control.

## System Monitor

One compact status area: **⚙ CPU · 💾 free space · 📁 folder size · ☕/🌙 awake**.
CPU is sampled once per Herdr session; disk space follows the active project's
volume. Folder size is allocated disk space, including hidden/dependency folders,
without following symlinks or crossing volumes. A low-priority scan is limited to
30 seconds, with a five-minute cache. Unavailable/stale readings are indicated.

**Ctrl+B**, release, then **Shift+M** opens details. A narrow terminal may hide
status-bar content. Metrics workers stop when disabled or their server is lost.

## Install

Requires **macOS**, **Herdr 0.9.3+**, and **Python 3.11+ for the installer**.
Plugin runtime code is also tested on macOS's Python 3.9. The installer configures
the default Herdr session and `~/.config/herdr/config.toml`.

```sh
git clone https://github.com/klinter007/herdr-macos-plugins.git
cd herdr-macos-plugins
python3 scripts/install.py
```

Keep this checkout: Herdr links directly to its plugin source. The installer
registers only these three plugins, adds removable key/status blocks, and starts
metrics. Awake remains unchanged (Off on a fresh installation). Existing custom
status bars and conflicting keybindings require a manual merge; the installer
refuses to overwrite them. Existing registrations from another checkout are also
preserved rather than silently replaced.

Configuration symlinks and file permissions are preserved. One initial
`config.toml.herdr-tools.bak` recovery copy is kept (not overwritten on reinstall) beside the resolved config.
Failed operations attempt to restore the previous config and plugin registrations;
any incomplete rollback is reported. User settings are retained on uninstall.

Use **Herdr Menu → reload config** in each open client after adding shortcuts;
a server reload alone does not refresh client keybindings.

### Terminal keyboard setup

The shortcut is lowercase **o**, with **no Shift**. macOS calls Alt **Option**.

**iTerm2:** if the shortcut reaches the agent or does nothing, add a profile key
mapping in Settings → Profiles → Keys → Key Mappings:

| Field | Value |
| --- | --- |
| Shortcut | Control+Option+o |
| Action | Send Hex Code |
| Value | `0x1b 0x0f` |

The last pair is **zero + f**. This mapping changes only that chord.
[Official iTerm documentation](https://iterm2.com/documentation-preferences-profiles-keys.html).

**Apple Terminal:** Apple provides **Settings → Profiles → Keyboard → Use Option
as Meta key**. This affects Option combinations broadly, including special-character
entry. The setting is documented, but the physical shortcut has **not** been tested
in Terminal.app. [Apple documentation](https://support.apple.com/guide/terminal/trmlkbrd/mac).

Fallback in either terminal: **Ctrl+B**, release, then **Shift+O** opens the same
file menu. This uses Herdr's normal prefix and needs no Option mapping.

### Remove

```sh
python3 scripts/install.py --uninstall
```

This unlinks the three plugins and removes their managed config blocks. Repeating
uninstall is supported. Saved plugin settings, the config recovery copy, and any
optional editor runtime remain; remove them separately only if no longer needed.
Runtime state belongs to Herdr, under its plugin state directory. Plugin IDs remain
`gili.files`, `gili.awake`, and `gili.metrics` for compatibility with existing installs.

## Develop

The core plugins use only Python's standard library and built-in macOS tools.

```sh
python3 -m unittest discover -s tests -q
```

Tests mock external app launches and installer mutations. Please report the Herdr,
macOS, Python and terminal versions with bugs. Contributions should preserve
relative/wrapped paths, ordinary macOS app associations, bounded background work,
and explicit error reporting. Never include clipboard contents, credentials,
private file paths, runtime bundles, or personal logs in an issue or commit.
