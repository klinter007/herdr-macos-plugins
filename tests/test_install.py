"""Exercise installer transactions without changing a Herdr server or real config."""
import json
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch


@unittest.skipIf(sys.version_info < (3, 11), 'Installer requires Python 3.11')
class Install(unittest.TestCase):
    def setUp(self):
        from scripts import install
        self.install = install
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / 'config.toml'
        self.plugins = {}
        self.calls = []
        self.fail_enable = None
        for target, value in [('ROOT', self.root), ('FEATURES', {'files': (), 'metrics': ()})]:
            mock = patch.object(install, target, value)
            mock.start()
            self.addCleanup(mock.stop)
        mock = patch.object(install, 'cli', side_effect=self.cli)
        mock.start()
        self.addCleanup(mock.stop)

    def cli(self, *args):
        self.calls.append(args)
        if args[:2] == ('plugin', 'list'):
            return json.dumps({'result': {'plugins': list(self.plugins.values())}})
        if args[:2] == ('plugin', 'link'):
            plugin_id = 'gili.' + Path(args[2]).name
            self.plugins[plugin_id] = {'plugin_id': plugin_id, 'plugin_root': args[2], 'enabled': False}
        if args[:2] == ('plugin', 'enable'):
            if args[2] == self.fail_enable:
                self.fail_enable = None
                raise RuntimeError('Simulated enable failure')
            self.plugins[args[2]]['enabled'] = True
        if args[:2] == ('plugin', 'disable'):
            self.plugins[args[2]]['enabled'] = False
        if args[:2] == ('plugin', 'unlink'):
            del self.plugins[args[2]]
        return 'ok'

    def test_config_validated_before_plugin_changes(self):
        self.install.apply_changes(self.config, 'onboarding = false\n')
        check = self.calls.index(('config', 'check'))
        link = next(i for i, c in enumerate(self.calls) if c[:2] == ('plugin', 'link'))
        self.assertLess(check, link)
        self.assertTrue(all(p['enabled'] for p in self.plugins.values()))

    def test_failed_install_restores_config_and_registrations(self):
        self.config.write_text('onboarding = true\n')
        self.plugins['gili.files'] = {'plugin_id': 'gili.files',
                                     'plugin_root': str(self.root / 'plugins/files'), 'enabled': False}
        self.fail_enable = 'gili.metrics'
        with self.assertRaisesRegex(RuntimeError, 'Simulated'):
            self.install.apply_changes(self.config, 'onboarding = false\n')
        self.assertEqual(self.config.read_text(), 'onboarding = true\n')
        self.assertEqual(list(self.plugins), ['gili.files'])
        self.assertFalse(self.plugins['gili.files']['enabled'])

    def test_uninstall_is_repeatable_with_missing_plugins(self):
        self.config.write_text('onboarding = false\n')
        for _ in range(2):
            self.install.apply_changes(self.config, 'onboarding = false\n', uninstall=True)
        self.assertEqual(self.plugins, {})
        self.assertFalse(any(c[:2] == ('plugin', 'unlink') for c in self.calls))

    def test_symlink_and_original_mode_are_preserved(self):
        target = self.root / 'dotfiles.toml'
        target.write_text('onboarding = true\n')
        target.chmod(0o640)
        self.config.symlink_to(target)
        self.install.apply_changes(self.config, 'onboarding = false\n')
        self.assertTrue(self.config.is_symlink())
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o640)
        self.assertEqual(target.with_name('dotfiles.toml.herdr-tools.bak').read_text(), 'onboarding = true\n')
        self.install.apply_changes(self.config, 'onboarding = false\n')
        self.assertEqual(target.with_name('dotfiles.toml.herdr-tools.bak').read_text(), 'onboarding = true\n')

    def test_interrupt_rolls_back_new_config(self):
        with patch.object(self.install, 'cli', side_effect=[json.dumps({'result': {'plugins': []}}),
                          KeyboardInterrupt(), json.dumps({'result': {'plugins': []}}), 'ok']):
            with self.assertRaises(KeyboardInterrupt):
                self.install.apply_changes(self.config, 'onboarding = false\n')
        self.assertFalse(self.config.exists())

    def test_other_source_is_not_overwritten(self):
        self.plugins['gili.files'] = {'plugin_id': 'gili.files', 'plugin_root': '/another/source', 'enabled': True}
        with self.assertRaisesRegex(RuntimeError, 'another source'):
            self.install.apply_changes(self.config, 'onboarding = false\n')
        self.assertFalse(self.config.exists())


if __name__ == '__main__':
    unittest.main()
