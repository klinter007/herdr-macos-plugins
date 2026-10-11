# Verification

This initial release targets standard Herdr 0.9.3 on macOS.

- 50 unit tests cover local/relative/Unicode/wrapped paths, multi-file selections,
  copied text and false-positive scans, URL boundaries, file/folder menus, package
  handling, Awake states/failures, folder scanning, installer rollback and repeatable
  uninstall, and config symlink/mode preservation.
- Runtime tests also pass on macOS Python 3.9; the six installer tests require
  Python 3.11 and are skipped on 3.9. The installer checks that requirement.
- Real standard-Herdr popup rendering and isolated-session CPU/disk sampling were
  exercised during development. A curses PTY check exercised file choice followed
  by the destination menu. The OS app launch in that check was mocked.
- Real caffeinate assertions were created/released in an isolated test session.
  Killing its supervisor also released its assertion. API failure behavior is
  covered by regression tests.
- Launch Services resolved temporary MP4, JPEG, HTML and Markdown fixtures to the
  current Mac's configured applications. This queries associations without
  launching those applications. `/usr/bin/open` argument handling is unit tested;
  playback and editing in every possible default app are not claimed tested.
- iTerm's targeted `1b 0f` mapping reaches the action. Apple Terminal's documented
  Option-as-Meta setting was inspected, but physical key delivery there remains
  unverified because automated native Terminal access was unavailable.

## Optional viewer

Tode / terminal-browser / code-server are separate third-party software, not
included in this repository. The optional adapter was previously checked with
Tode 0.4.2, terminal-browser 0.13.4, and code-server 4.132.0. It uses isolated runtime
paths. The editor backend binds to localhost without authentication and disables
telemetry and workspace trust: use only for trusted local projects. This integration
is optional; default-app opening and Finder require none of these tools. The last
editor tab normally shuts down its dedicated backend. The release does not claim
those versions work in every terminal or that editing/media playback was visually
verified end to end.

## Review and scope

A separate Claude advisor reviewed the working source before publication. The
release excludes experimental Jev/layout integrations, private Herdr patches,
personal configuration/history, runtime binaries, credentials, and local logs.
The `gili.*` plugin IDs are retained to avoid changing existing state paths.
