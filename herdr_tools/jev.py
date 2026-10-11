"""Herdr controls for the installed Jev gateway; no second decision service."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import urllib.request
import uuid

from .common import UserError, api, choose, popup, read_json, source_context, state_dir
from .files import roots

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PORTS = {'codex': 8790, 'claude': 8789}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def gateway_request(port, path, method='GET'):
    if type(port) is not int or not 1024 <= port <= 65535:
        raise UserError('Invalid local gateway port.')
    request = urllib.request.Request(f'http://127.0.0.1:{port}{path}', method=method)
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect)
        with opener.open(request, timeout=3) as response:
            return json.loads(response.read(2 * 1024 * 1024))
    except (OSError, ValueError):
        raise UserError('The local Jev gateway did not respond. No request was retried.') from None


def installed_package():
    launcher = shutil.which('jev-codex')
    if not launcher:
        raise UserError('The existing jev-gateway installation is not on PATH.')
    root = Path(launcher).resolve().parents[1]
    doc = read_json(root / 'package.json', {})
    if doc.get('name') != 'jev-gateway' or not (root / 'dist/app.js').is_file():
        raise UserError('Could not verify the installed Jev gateway package.')
    return root


def gateway_for_pane(ctx):
    pane_id = ctx.get('focused_pane_id')
    if not pane_id:
        return None
    pane = api('pane.get', {'pane_id': pane_id})['pane']
    for path in state_dir(True).glob('gateway-*.json'):
        record = read_json(path, {})
        if record.get('pane_id') != pane_id or record.get('terminal_id') != pane.get('terminal_id'):
            continue
        health = gateway_request(record['port'], '/health')
        if health.get('pid') != record.get('pid'):
            raise UserError('This pane’s previous gateway is no longer running.')
        return {**record, 'shared': False}
    processes = api('pane.process_info', {'pane_id': pane_id})['process_info']['foreground_processes']
    # Identify official launchers without reading environment variables or secrets.
    for kind, default_port in DEFAULT_PORTS.items():
        if any(any(Path(arg).name in (f'jev-{kind}', f'jev-{kind}.mjs')
                       for arg in proc.get('argv', [])) for proc in processes):
            port = default_port
            if kind == 'codex':
                for proc in processes:
                    for arg in proc.get('argv', []):
                        match = re.fullmatch(r'model_providers\.jev-gateway\.base_url="http://127\.0\.0\.1:(\d+)/v1"', arg)
                        if match:
                            port = int(match[1])
            health = gateway_request(port, '/health')
            return {'port': port, 'agent': kind, 'pid': health.get('pid'), 'shared': True,
                    'pane_id': pane_id}
    return None


def gateway_status(gateway):
    # Only inspect routing metadata. Do not fetch event history from shared chats.
    data = gateway_request(gateway['port'], '/dashboard/events?since=999999999')
    router = data.get('router', {})
    if router.get('client') != gateway['agent'] or type(router.get('routing')) is not bool:
        raise UserError('The endpoint is not the expected agent gateway.')
    return router


def set_routing(gateway, enabled):
    if gateway_request(gateway['port'], '/health').get('pid') != gateway['pid']:
        raise UserError('Gateway changed; reopen the menu before switching it.')
    gateway_status(gateway)
    result = gateway_request(gateway['port'], '/dashboard/routing?enabled=' + str(enabled).lower(), 'POST')
    if result.get('routing') is not enabled:
        raise UserError('The gateway did not confirm the requested routing state.')


def launch(kind, ctx):
    if kind not in DEFAULT_PORTS:
        raise UserError('Choose Codex or Claude.')
    package = installed_package()
    cwd, _ = roots(ctx)
    record = state_dir(True) / f'gateway-{uuid.uuid4().hex}.json'
    return api('plugin.pane.open', {
        'plugin_id': 'gili.jev', 'entrypoint': 'session', 'placement': 'tab',
        'workspace_id': ctx.get('workspace_id'), 'focus': True,
        'env': {'TOOLS_JEV_AGENT': kind, 'TOOLS_JEV_PACKAGE': str(package),
                'TOOLS_JEV_CWD': cwd, 'TOOLS_JEV_RECORD': str(record)},
    })


def picker():
    ctx = source_context()
    while True:
        gateway = gateway_for_pane(ctx)
        labels, actions = [], []
        if gateway:
            status = gateway_status(gateway)
            on = status['routing']
            scope = 'SHARED gateway' if gateway['shared'] else 'this agent session'
            title = f'{gateway["agent"].title()} · Jev {"On" if on else "Off"} · {scope}'
            labels += [f'Turn Jev {"Off" if on else "On"}' + (' — ALL sessions on this gateway' if gateway['shared'] else ' — this session only'),
                       'Open routing dashboard']
            actions += ['toggle', 'dashboard']
        else:
            # Offer a new session only when this pane has none to switch.
            title = 'This pane: no Jev gateway detected'
            labels += ['New Claude + Jev tab…', 'New Codex + Jev tab…']
            actions += ['claude', 'codex']
        labels.append('Close')
        actions.append('close')
        selected = choose(title, labels, mouse=True,
                          subtitle='Click / Enter · Esc close' if gateway else
                          'A running agent can\'t switch to Jev · new tabs start Off · Esc close')
        if selected is None or actions[selected] == 'close':
            return
        action = actions[selected]
        if action == 'toggle':
            if gateway['shared'] and choose('This affects every session on the shared gateway',
                                            ['Cancel', f'Turn shared {gateway["agent"]} routing {"Off" if on else "On"}'], mouse=True) != 1:
                continue
            set_routing(gateway, not on)
        elif action == 'dashboard':
            subprocess.run(['/usr/bin/open', f'http://127.0.0.1:{gateway["port"]}/dashboard'], check=True, timeout=10)
            return
        else:
            launch(action, ctx)
            return


def main(command):
    if command == 'menu':
        popup('picker')
    elif command == 'picker':
        picker()
    elif command == 'session':
        node = shutil.which('node')
        if not node:
            raise UserError('Node.js is required by the installed Jev gateway.')
        os.execv(node, [node, str(ROOT / 'scripts/jev-session.mjs')])
    else:
        raise UserError('Open the Jev menu to control the selected session.')
