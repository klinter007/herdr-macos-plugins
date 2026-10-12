"""Jev's supervisor and agent must share the source project directory."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('node'), 'Node.js is required for Jev')
class JevDirectory(unittest.TestCase):
    def node(self, directory):
        code = f"""import {{enterProjectDirectory}} from {json.dumps((ROOT/'scripts/jev-session.mjs').as_uri())};
        try {{
          const cwd = enterProjectDirectory({json.dumps(directory)});
          console.log(JSON.stringify({{cwd, actual: process.cwd(), pwd: process.env.PWD}}));
        }} catch (error) {{ console.error(error.message); process.exitCode = 1; }}"""
        return subprocess.run(['node', '--input-type=module', '-e', code],
                              cwd=ROOT/'plugins/jev', capture_output=True, text=True, timeout=5,
                              env={**os.environ, 'PWD': str(ROOT/'plugins/jev')})

    def test_supervisor_changes_directory_and_pwd_including_spaces(self):
        with tempfile.TemporaryDirectory(prefix='jev cwd ') as tmp:
            target = str(Path(tmp).resolve())
            result = self.node(target)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), {'cwd': target, 'actual': target, 'pwd': target})

    def test_missing_relative_and_nonexistent_directory_never_fall_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            for value in (None, '', 'relative/project', str(Path(tmp)/'missing')):
                self.assertNotEqual(self.node(value).returncode, 0)

    def test_file_cannot_be_used_as_project_directory(self):
        self.assertNotEqual(self.node(str(ROOT/'README.md')).returncode, 0)

    def test_launch_passes_original_pane_directory_not_plugin_directory(self):
        from herdr_tools.jev import launch
        with tempfile.TemporaryDirectory() as tmp, \
                patch('herdr_tools.jev.installed_package', return_value=Path('/installed/gateway')), \
                patch('herdr_tools.jev.state_dir', return_value=Path(tmp)), \
                patch('herdr_tools.jev.api') as api:
            launch('claude', {'workspace_id': 'w1', 'focused_pane_cwd': '/project/working folder',
                              'workspace_cwd': '/project'})
        method, params = api.call_args.args
        self.assertEqual(method, 'plugin.pane.open')
        self.assertEqual(params['workspace_id'], 'w1')
        self.assertEqual(params['env']['TOOLS_JEV_CWD'], '/project/working folder')
        self.assertNotIn('cwd', params)  # run.py must still bootstrap from its plugin root.

    def test_launch_from_older_wrapper_uses_actual_agent_directory(self):
        from herdr_tools.jev import launch_directory
        with tempfile.TemporaryDirectory(prefix='old Jev project ') as tmp:
            processes = [
                {'argv': ['node', str(ROOT/'scripts/jev-session.mjs')],
                 'cwd': str(ROOT/'plugins/jev')},
                {'argv': ['/bin/claude'], 'cwd': tmp},
                {'argv': ['mcp-helper'], 'cwd': str(ROOT)},
            ]
            ctx = {'focused_pane_id': 'w1:p2', 'focused_pane_cwd': str(ROOT/'plugins/jev')}
            with patch('herdr_tools.jev.api', return_value={
                    'process_info': {'foreground_processes': processes}}):
                for argv in (['/bin/claude'], ['codex'], ['codex-aarch64-apple-darwin'],
                             ['node', '/lib/node_modules/@openai/codex/bin/codex.js'],
                             ['node', '/lib/node_modules/@anthropic-ai/claude-code/cli.js']):
                    processes[1]['argv'] = argv
                    self.assertEqual(launch_directory(ctx), tmp)

    def test_older_wrapper_without_unambiguous_agent_fails_instead_of_inheriting_plugin_root(self):
        from herdr_tools.common import UserError
        from herdr_tools.jev import launch_directory
        processes = [{'argv': ['node', str(ROOT/'scripts/jev-session.mjs')]}]
        ctx = {'focused_pane_id': 'w1:p2', 'focused_pane_cwd': str(ROOT/'plugins/jev')}
        with patch('herdr_tools.jev.api', return_value={
                'process_info': {'foreground_processes': processes}}):
            with self.assertRaises(UserError):
                launch_directory(ctx)
            processes += [{'argv': ['claude'], 'cwd': str(ROOT)},
                          {'argv': ['codex'], 'cwd': str(ROOT/'tests')}]
            with self.assertRaises(UserError):
                launch_directory(ctx)

    def test_ordinary_shell_in_plugin_root_is_not_redirected(self):
        from herdr_tools.jev import launch_directory
        ctx = {'focused_pane_id': 'w1:p2', 'focused_pane_cwd': str(ROOT/'plugins/jev')}
        with patch('herdr_tools.jev.api', return_value={
                'process_info': {'foreground_processes': [{'argv': ['zsh']}]}}):
            self.assertEqual(launch_directory(ctx), ctx['focused_pane_cwd'])


if __name__ == '__main__':
    unittest.main()
