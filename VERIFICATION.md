# Verification

What I tested, on standard Herdr 0.9.3 and macOS.

## Unit tests

55 tests: relative, absolute, Unicode and wrapped paths, several files in one sentence, clipboard text and false positives, URL edge cases, file and folder menus, `.app` packages, Awake states and failures, folder scans, the Jev menu and gateway checks, installer rollback, repeated uninstall, config symlinks and permissions.

They also pass on the macOS system Python 3.9. The 6 installer tests need Python 3.11 and are skipped there.

## Real runs

- The screenshots in the README come from a real Herdr session with Claude Code and dummy files in `/tmp/herdr-demo`.
- Popups, CPU and disk sampling ran in a real Herdr session. A curses check went from file choice to the "Open where?" menu, with the app launch mocked.
- `caffeinate` assertions were created and released in an isolated session. Killing the worker released the assertion too.
- Launch Services returned the configured app for MP4, JPEG, HTML and Markdown test files, without launching them. I didn't test playback or editing in every possible default app.
- A Claude + Jev tab started its own gateway with Jev Off, named the tab `Claude + Jev`, and the menu in that tab offered only that session's switch.
- iTerm2's `1b 0f` mapping reaches the shortcut. The Terminal.app Option-as-Meta setting is documented by Apple, but I couldn't test the key press there.

## Optional viewer

Tode, terminal-browser and code-server are third-party and not in this repo. I checked the adapter with Tode 0.4.2, terminal-browser 0.13.4 and code-server 4.132.0. The editor backend listens on localhost without auth and turns off telemetry and workspace trust, so use it only for projects you trust. The default app and Finder don't need any of it.

## Scope

Not included: layout templates, private Herdr patches, personal config or history, runtime binaries, keys and logs. The `gili.*` plugin IDs stay so existing installs keep their state.
