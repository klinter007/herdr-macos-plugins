#!/usr/bin/env python3
"""Fast, read-only tab-bar output. Never scans folders or makes network calls."""
import hashlib
import json
import os
from pathlib import Path
import time


def read(feature, filename='status.json'):
    root = Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state')))
    socket = os.environ.get('HERDR_SOCKET_PATH', '')
    session = hashlib.sha256(socket.encode()).hexdigest()[:16]
    path = root / 'herdr/plugins' / f'gili.{feature}' / session / filename
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def coffee_status(awake, saved):
    desired = saved.get('mode', 'off')
    if not awake and desired == 'off':
        return '🌙'
    if desired == 'off' and awake.get('mode') == 'off' and awake.get('active') is False:
        return '🌙'
    if awake.get('error') or time.time() - awake.get('checked_at', 0) >= 20:
        return '❔'
    if awake.get('mode') != desired:
        return '⏳'
    active = awake.get('active', False)
    # Preserve the truth for older sessions with Auto saved, even though the
    # simplified menu no longer offers it.
    if desired == 'auto':
        return '☕' if active else '🌙'
    if active != (desired == 'on'):
        return '⏳'
    return '☕' if active else '🌙'


def main():
    metrics, awake = read('metrics'), read('awake')
    cpu, disk, folder = '—', '—', '—'
    current = metrics.get('current')
    if current and time.time() - metrics.get('checked_at', 0) < 20:
        cpu = current['cpu'].replace('unavailable', '?')
        # Never label the previous project's folder size as the current project.
        if current['workspace_id'] == os.environ.get('HERDR_ACTIVE_WORKSPACE_ID'):
            disk = current['disk'].replace(' GiB free', 'G').replace('unavailable', '?')
            folder = current.get('size', '…').replace(' GiB', 'G').replace(' MiB', 'M').replace('scanning…', '…').replace('unavailable', '?')
        else:
            disk, folder = '…', '…'
    coffee = coffee_status(awake, read('awake', 'mode.json'))
    print(f'⚙  {cpu} 💾 {disk} 📁 {folder} {coffee}')


if __name__ == '__main__':
    main()
