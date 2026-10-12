"""Check Herdr's observed Jev cwd in a disposable headless session.

Requires Herdr, Node, and the configured installed Jev gateway. Uses harmless
stand-in agents and makes no model requests. Never registers or unlinks plugins.
"""
import json
import os
from pathlib import Path
import shlex
import socket
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from herdr_tools.common import api
from herdr_tools.jev import installed_package


def wait_for(check, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(.1)
    raise AssertionError('Timed out waiting for cwd check')


def main():
    package = installed_package()
    server_env = {k: v for k, v in os.environ.items() if not k.startswith('HERDR_')}
    original_socket = os.environ.get('HERDR_SOCKET_PATH')
    ROOT.joinpath('.work').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='jc-', dir=ROOT/'.work') as temp:
        temp = Path(temp).resolve()
        for kind in ('CONFIG', 'STATE', 'CACHE', 'DATA'):
            server_env[f'XDG_{kind}_HOME'] = str(temp/kind.lower())
        config = temp/'config.toml'
        config.write_text('')
        server_env['HERDR_CONFIG_PATH'] = str(config)
        with (temp/'server.log').open('w') as log:
            server = subprocess.Popen(['herdr', 'server'],
                                      env=server_env, stdout=log, stderr=log)
        records = []
        try:
            def find_socket():
                if server.poll() is not None:
                    raise AssertionError((temp/'server.log').read_text())
                sessions = json.loads(subprocess.check_output(
                    ['herdr', 'session', 'list', '--json'], env=server_env))['sessions']
                return next((s['socket_path'] for s in sessions
                             if s['default'] and s['running']), None)
            test_socket = wait_for(find_socket)
            assert temp in Path(test_socket).resolve().parents, 'Refusing a socket outside the test directory'
            os.environ['HERDR_SOCKET_PATH'] = test_socket
            server_env['HERDR_SOCKET_PATH'] = test_socket
            runner = temp/'runner.mjs'
            runner.write_text("""import {spawn} from 'node:child_process';
import {writeFileSync} from 'node:fs';
import {runSession} from WRAPPER;
process.exitCode = await runSession({spawnAgent: (_client, _args, options) => {
  writeFileSync(process.env.CWD_RESULT + '.parent', JSON.stringify({
    cwd: process.cwd(), pwd: process.env.PWD, childCwd: options.cwd,
    childPwd: options.env.PWD
  }));
  return spawn(process.execPath, ['-e', `
    require('node:fs').writeFileSync(process.env.CWD_RESULT, JSON.stringify({
      cwd: process.cwd(), pwd: process.env.PWD
    }));
    const timer = setInterval(() => {
      if (require('node:fs').existsSync(process.env.CWD_RESULT + '.stop')) process.exit(0);
    }, 100);
    setTimeout(() => process.exit(1), 30000);
  `], options);
}});
""".replace('WRAPPER', json.dumps((ROOT/'scripts/jev-session.mjs').as_uri())))
            for kind in ('claude', 'codex'):
                project = temp/f'{kind} project with spaces'
                project.mkdir()
                result = temp/f'{kind}-result.json'
                record = temp/f'{kind}-gateway.json'
                pane = api('workspace.create', {'cwd': str(ROOT/'plugins/jev'),
                           'label': 'Jev cwd test', 'focus': False})['root_pane']['pane_id']
                env = {'TOOLS_JEV_PACKAGE': str(package), 'TOOLS_JEV_AGENT': kind,
                       'TOOLS_JEV_CWD': str(project), 'TOOLS_JEV_RECORD': str(record),
                       'CWD_RESULT': str(result)}
                command = 'exec env ' + ' '.join(shlex.quote(f'{k}={v}') for k, v in env.items())
                command += ' node ' + shlex.quote(str(runner))
                subprocess.run(['herdr', 'pane', 'run', pane, command],
                               env=server_env, check=True, capture_output=True, timeout=10)
                wait_for(result.exists)
                records.append(json.loads(record.read_text()))
                expected = str(project)
                assert json.loads(result.read_text()) == {'cwd': expected, 'pwd': expected}
                assert json.loads(Path(str(result)+'.parent').read_text()) == {
                    'cwd': expected, 'pwd': expected, 'childCwd': expected, 'childPwd': expected}
                assert records[-1]['cwd'] == expected
                def observed():
                    state = api('pane.get', {'pane_id': pane})['pane']
                    return state['cwd'] == expected and state['foreground_cwd'] == expected
                wait_for(observed)
                print(f'PASS {kind}: supervisor, child, PWD and Herdr cwd agree', flush=True)
                # The exec'd stand-in exits normally; Herdr closes its terminal.
                Path(str(result)+'.stop').touch()
                wait_for(lambda: not record.exists())
        finally:
            # Only terminate the process we started, never a discovered session.
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=10)
            if original_socket is None:
                os.environ.pop('HERDR_SOCKET_PATH', None)
            else:
                os.environ['HERDR_SOCKET_PATH'] = original_socket
            for record in records:
                with socket.socket() as sock:
                    sock.settimeout(1)
                    assert sock.connect_ex(('127.0.0.1', record['port'])) != 0, 'Gateway still running'
        print('PASS disposable session removed and gateway ports closed')


if __name__ == '__main__':
    main()
