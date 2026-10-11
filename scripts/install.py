#!/usr/bin/env python3
"""Link local plugins and maintain one removable block in Herdr's config."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import sys
try:
    import tomllib
except ImportError:
    raise SystemExit("Installer requires Python 3.11 or newer; run it with that interpreter.")
import re
import shlex
import json
import stat

ROOT = Path(__file__).resolve().parents[1]
BEGIN = '# BEGIN gili-herdr-tools (managed by herdr-plugins/scripts/install.py)'
END = '# END gili-herdr-tools'
STATUS_BEGIN = '# BEGIN gili-herdr-status'
STATUS_END = '# END gili-herdr-status'
FEATURES = {'files': ('o', 'Files and Links'), 'awake': ('a', 'Stay Awake'),
            'metrics': ('m', 'System Monitor')}
ENV = {k: v for k, v in os.environ.items() if not k.startswith('HERDR_')}


def cli(*args):
    return subprocess.run(['herdr', '--session', 'default', *args], env=ENV,
                          text=True, check=True, capture_output=True, timeout=30).stdout


def replace(path, text):
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix='.tools-config-')
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(text)
            if path.exists():
                os.fchmod(stream.fileno(), stat.S_IMODE(path.stat().st_mode))
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


def plugin_snapshot():
    return {p['plugin_id']: p for p in json.loads(cli('plugin', 'list', '--json'))['result']['plugins']}


def apply_changes(config, new, uninstall=False):
    """Keep config and plugin registrations together, rolling back on failure."""
    config = config.resolve()
    existed = config.exists()
    original = config.read_text() if existed else ''
    before = plugin_snapshot()
    for feature in FEATURES:
        prior = before.get(f'gili.{feature}')
        expected = (ROOT / 'plugins' / feature).resolve()
        if prior and Path(prior['plugin_root']).resolve() != expected:
            raise RuntimeError(f"gili.{feature} is already linked from another source; left unchanged.")
    config.parent.mkdir(parents=True, exist_ok=True)
    backup = config.with_name(config.name + '.herdr-tools.bak')
    if existed and not backup.exists():
        # Retain the first recovery copy; repeated installs must not overwrite it.
        replace(backup, original)
    try:
        replace(config, new)
        cli('config', 'check')
        for feature in FEATURES:
            plugin_id = f'gili.{feature}'
            if uninstall:
                if plugin_id in before:
                    cli('plugin', 'disable', plugin_id)
                    cli('plugin', 'unlink', plugin_id)
            else:
                if plugin_id not in before:
                    cli('plugin', 'link', str(ROOT / 'plugins' / feature), '--disabled')
                cli('plugin', 'enable', plugin_id)
        cli('server', 'reload-config')
        if not uninstall:
            cli('plugin', 'action', 'invoke', 'start', '--plugin', 'gili.metrics')
    except BaseException as error:
        failures = []
        try:
            if existed:
                replace(config, original)
            else:
                config.unlink(missing_ok=True)
        except Exception as rollback_error:
            failures.append(str(rollback_error))
        try:
            current = plugin_snapshot()  # Inspect state even if a mutation timed out.
            for feature in FEATURES:
                plugin_id = f'gili.{feature}'
                prior, now = before.get(plugin_id), current.get(plugin_id)
                if prior:
                    if not now:
                        cli('plugin', 'link', prior['plugin_root'], '--disabled')
                    cli('plugin', 'enable' if prior['enabled'] else 'disable', plugin_id)
                elif now:
                    cli('plugin', 'disable', plugin_id)
                    cli('plugin', 'unlink', plugin_id)
            cli('server', 'reload-config')
        except Exception as rollback_error:
            failures.append(str(rollback_error))
        if failures:
            raise RuntimeError(f"{error}; rollback incomplete: {'; '.join(failures)}") from error
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--uninstall', action='store_true')
    args = parser.parse_args()
    if not shutil.which('herdr'):
        parser.error('Herdr must be installed and on PATH.')
    config = (Path.home() / '.config/herdr/config.toml').resolve()
    original = config.read_text() if config.exists() else ''
    base = original
    for begin, finish in [(BEGIN, END), (STATUS_BEGIN, STATUS_END)]:
        if begin in base:
            start = base.index(begin)
            end = base.index(finish, start) + len(finish)
            base = base[:start] + base[end:].lstrip('\n')
    parsed = tomllib.loads(base)
    if args.uninstall:
        new = base.rstrip() + '\n'
    else:
        if 'tab_bar_right' in parsed.get('ui', {}):
            parser.error('Existing tab-bar status needs a manual merge; it was left unchanged.')
        bindings = parsed.get('keys', {}).get('command', [])
        direct_key = 'ctrl+alt+o'
        configured = parsed.get('keys', {})
        if any(b.get('key') == direct_key for b in bindings) or any(
                value == direct_key or isinstance(value, list) and direct_key in value
                for name, value in configured.items() if name != 'command'):
            parser.error(f'{direct_key} is already assigned; configuration was left unchanged.')
        for key, _ in FEATURES.values():
            if any(b.get('key') == f'prefix+shift+{key}' for b in bindings):
                parser.error(f'prefix+shift+{key} is already assigned; configuration was left unchanged.')
        status_command = shlex.join([sys.executable, str(ROOT / 'scripts/status.py')])
        status = STATUS_BEGIN + '\ntab_bar_right = [{ type = "command", command = ' + json.dumps(status_command) + ', interval_seconds = 3, timeout_seconds = 2 }]\n' + STATUS_END + '\n'
        header = re.search(r'^\[ui\]\s*$', base, re.MULTILINE)
        if header:
            base = base[:header.end()] + '\n' + status + base[header.end():].lstrip('\n')
        else:
            base = base.rstrip() + '\n\n[ui]\n' + status
        block = [BEGIN]
        for feature, (key, title) in FEATURES.items():
            block += ['', '[[keys.command]]', f'key = "prefix+shift+{key}"',
                      'type = "plugin_action"', f'command = "gili.{feature}.menu"',
                      f'description = "{title}"']
        block += ['', '[[keys.command]]', f'key = "{direct_key}"',
                  'type = "plugin_action"', 'command = "gili.files.quick-open"',
                  'description = "Choose where to open selected or visible files"']
        block += [END, '']
        new = base.rstrip() + '\n\n' + '\n'.join(block)
        tomllib.loads(new)
    apply_changes(config, new, args.uninstall)
    print('Unlinked; saved plugin settings and runtime files retained.' if args.uninstall else
          'Installed. Metrics started; Stay Awake is unchanged (initially Off).')
    print('In each open Herdr client, choose Menu → reload config to refresh its local shortcuts.')


if __name__ == '__main__':
    main()
