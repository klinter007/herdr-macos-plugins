import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from herdr_tools.common import UserError
from herdr_tools.paths import resolve, extract
from herdr_tools.metrics import workspace_path, FolderSizes
from herdr_tools.files import open_item


class Paths(unittest.TestCase):
    def setUp(self):
        clipboard = patch('herdr_tools.files.copied_selection', return_value='')
        app = patch('herdr_tools.files.default_app_name', return_value='QuickTime Player')
        app.start()
        self.addCleanup(app.stop)
        viewer = patch('herdr_tools.files.program_path', return_value='/installed/viewer')
        viewer.start()
        self.addCleanup(viewer.stop)
        self.clipboard = clipboard.start()
        self.addCleanup(clipboard.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'outputs' / 'my videos').mkdir(parents=True)
        self.file = self.root / 'outputs' / 'my videos' / '日本語 clip.mp4'
        self.file.write_bytes(b'fixture')
        (self.root / 'src').mkdir()
        (self.root / 'src' / 'a.py').write_text('hello')

    def test_absolute_relative_folder_and_unicode(self):
        for raw in (str(self.file), 'outputs/my videos/日本語 clip.mp4', '`outputs/my videos/日本語 clip.mp4`'):
            self.assertEqual(resolve(raw, self.root).value, str(self.file))
        self.assertEqual(resolve('outputs/', self.root).value, str(self.root / 'outputs'))

    def test_selection_broken_across_three_lines(self):
        raw = 'outputs/my videos/日\n本語 cli\np.mp4'
        self.assertEqual(resolve(raw, self.root).value, str(self.file))

    def test_wrap_preserves_filename_spaces(self):
        self.assertEqual(resolve('outputs/my \nvideos/日本語 clip.mp4', self.root).value, str(self.file))

    def test_line_column_and_hash(self):
        for raw in ('src/a.py:42:3', 'src/a.py#L42C3'):
            item = resolve(raw, self.root)
            self.assertEqual((item.line, item.column), (42, 3))

    def test_literal_colon_filename_wins(self):
        (self.root / 'src' / 'a.py:42').touch()
        item = resolve('src/a.py:42', self.root)
        self.assertTrue(item.value.endswith('a.py:42'))
        self.assertIsNone(item.line)

    def test_file_url_percent_encoding(self):
        self.assertEqual(resolve(self.file.as_uri(), self.root).value, str(self.file))

    def test_osc8_destination_over_wrapped_label(self):
        text = '\x1b]8;;' + self.file.as_uri() + '\x1b\\visible\nlabel\x1b]8;;\x1b\\'
        self.assertEqual(resolve(text, self.root).value, str(self.file))

    def test_markdown_destination(self):
        self.assertEqual(resolve('[video](outputs/my videos/日本語 clip.mp4)', self.root).value, str(self.file))

    def test_cwd_then_project_fallback(self):
        self.assertEqual(resolve('src/a.py', self.root / 'outputs', self.root).value, str(self.root / 'src/a.py'))

    def test_no_join_of_unrelated_output(self):
        self.assertEqual(extract('outputs/my\nvideos/日本語 clip.mp4', self.root), [])

    def test_url_and_ambiguous_hard_break(self):
        self.assertTrue(resolve('https://example.org/a?q=2', self.root).web)
        with self.assertRaises(UserError):
            resolve('https://example.org/\na', self.root)

    def test_reject_remote_or_executable_schemes(self):
        for text in ('file://remote/tmp/a', 'javascript:alert(1)', 'data:text/plain,a', 'https://', 'a\x00b'):
            with self.assertRaises((UserError, ValueError)):
                resolve(text, self.root)

    def test_shell_metacharacters_remain_data(self):
        target = self.root / '$(touch BAD); movie.mp4'
        target.touch()
        item = resolve(str(target), self.root)
        with patch('herdr_tools.files.run') as run:
            open_item(item, 'open', {})
        run.assert_called_once_with(['/usr/bin/open', str(target)])
        self.assertFalse((self.root / 'BAD').exists())

    def test_editor_launch_keeps_manifest_directory(self):
        item = resolve(str(self.file), self.root)
        with patch('herdr_tools.files.program_path', return_value='/reviewed/tode'), patch('herdr_tools.files.api') as api:
            open_item(item, 'tab', {'focused_pane_cwd': str(self.root), 'workspace_id': 'w1'})
        method, params = api.call_args.args
        self.assertEqual(method, 'plugin.pane.open')
        self.assertNotIn('cwd', params)  # A project/run.py must never replace our wrapper.
        self.assertEqual(params['env']['TOOLS_VIEWER_CWD'], str(self.root))

    def candidates(self, text, selected=None, copied=''):
        from herdr_tools.files import destinations
        self.clipboard.return_value = copied
        ctx = {'focused_pane_cwd': str(self.root), 'focused_pane_id': 'w1:p1',
               'selected_text': selected}
        with patch('herdr_tools.files.api', return_value={'read': {'text': text}}):
            return destinations(ctx)

    def test_selected_wrapped_path(self):
        self.assertEqual(self.candidates('', 'src/a.\npy')[0].value, str(self.root/'src/a.py'))

    def test_copied_visible_path_after_selection_cleared(self):
        target = str(self.root/'src/a.py')
        self.assertEqual([x.value for x in self.candidates(target+' src/', copied=target)], [target])

    def test_copied_wrapped_path(self):
        self.assertEqual(self.candidates('src/a.\npy src/', copied='src/a.\npy')[0].value,
                         str(self.root/'src/a.py'))

    def test_clipboard_outside_viewport_is_ignored(self):
        self.assertEqual(self.candidates('src/a.py', copied=str(self.file))[0].value,
                         str(self.root/'src/a.py'))

    def test_copied_filename_fragment(self):
        self.assertEqual(self.candidates('src/a.py src/', copied='a.py')[0].value,
                         str(self.root/'src/a.py'))

    def test_multiple_matching_fragments_preserved_for_choice(self):
        (self.root/'outputs/a.py').touch()
        items = self.candidates('src/a.py outputs/a.py src/', selected='a.py')
        self.assertEqual(len(items), 2)

    def test_screenshot_style_selection_extracts_both_files_only(self):
        (self.root/'outputs/blockout.mp4').touch()
        (self.root/'outputs/story.txt').touch()
        text = 'Watch the MP4 (outputs/blockout.mp4) · Read the short\nscript (outputs/story.txt)'
        items = self.candidates(text+'\nsrc/a.py', copied=text)
        self.assertEqual([Path(x.value).name for x in items], ['blockout.mp4', 'story.txt'])

    def test_parenthesized_wrapped_path_in_prose(self):
        items = self.candidates('', selected='Read the code (src/a.\npy).')
        self.assertEqual([x.value for x in items], [str(self.root/'src/a.py')])

    def test_single_file_opens_popup_without_launching_app(self):
        from herdr_tools.files import quick_open
        ctx = {'focused_pane_cwd': str(self.root), 'selected_text': 'src/a.py'}
        with patch('herdr_tools.files.popup') as popup, patch('herdr_tools.files.run') as run:
            quick_open(ctx)
        run.assert_not_called()
        data = json.loads(popup.call_args.args[1]['TOOLS_DESTINATIONS'])
        self.assertEqual(data[0]['value'], str(self.root/'src/a.py'))

    def test_single_folder_opens_finder_directly(self):
        from herdr_tools.files import quick_open
        ctx = {'focused_pane_cwd': str(self.root), 'selected_text': 'src/'}
        with patch('herdr_tools.files.popup') as popup, patch('herdr_tools.files.run') as run:
            quick_open(ctx)
        popup.assert_not_called()
        run.assert_called_once_with(['/usr/bin/open', '-a', 'Finder', str(self.root/'src')])

    def test_multiple_files_choose_target_then_where(self):
        from herdr_tools.files import show_destinations
        items = [resolve(str(self.file), self.root), resolve('src/a.py', self.root)]
        with patch('herdr_tools.files.choose', side_effect=[0, 0]) as choose, \
                patch('herdr_tools.files.run') as run:
            show_destinations(items, {})
        self.assertEqual(choose.call_count, 2)
        self.assertEqual('Open in QuickTime Player (default)', choose.call_args_list[1].args[1][0])
        run.assert_called_once_with(['/usr/bin/open', str(self.file)])

    def test_single_file_skips_target_choice_and_can_reveal(self):
        from herdr_tools.files import show_destinations
        item = resolve('src/a.py', self.root)
        with patch('herdr_tools.files.choose', return_value=2) as choose, \
                patch('herdr_tools.files.run') as run:
            show_destinations([item], {})
        choose.assert_called_once()
        self.assertTrue(choose.call_args.args[0].startswith('Open where?'))
        run.assert_called_once_with(['/usr/bin/open', '-R', item.value])

    def test_choosing_folder_skips_where_menu(self):
        from herdr_tools.files import show_destinations
        items = [resolve('src/', self.root), resolve('src/a.py', self.root)]
        with patch('herdr_tools.files.choose', return_value=0) as choose, \
                patch('herdr_tools.files.run') as run:
            show_destinations(items, {})
        choose.assert_called_once()
        run.assert_called_once_with(['/usr/bin/open', '-a', 'Finder', str(self.root/'src')])

    def test_cancel_does_not_open_anything(self):
        from herdr_tools.files import show_destinations
        with patch('herdr_tools.files.choose', return_value=None), patch('herdr_tools.files.run') as run:
            show_destinations([resolve('src/a.py', self.root)], {})
        run.assert_not_called()

    def test_stale_prose_clipboard_does_not_hide_files(self):
        items = self.candidates('Please open src/a.py now.', copied='open')
        self.assertEqual([x.value for x in items], [str(self.root/'src/a.py')])

    def test_unmatched_pathlike_clipboard_does_not_hide_files(self):
        items = self.candidates('Missing old.md; now use src/a.py.', copied='old.md')
        self.assertEqual([x.value for x in items], [str(self.root/'src/a.py')])

    def test_scan_rejects_prose_folders_and_root_shorthand(self):
        items = self.candidates('Run the src . / ~ src/a.py.')
        self.assertEqual([x.value for x in items], [str(self.root/'src/a.py')])
        self.assertEqual(self.candidates('done .'), [])
        self.assertEqual(self.candidates('Run src. Done: outputs: cd ../ see ~/ and ./'), [])

    def test_broken_url_is_not_silently_truncated_by_fallback(self):
        for raw in ['https://example.org/\na', '`https://example.org/\na`']:
            with self.assertRaises(UserError):
                self.candidates('', selected=raw)

    def test_literal_filename_with_final_punctuation_is_preserved(self):
        target = self.root/'src/odd.py!'
        target.touch()
        self.assertEqual(self.candidates('src/odd.py!')[0].value, str(target))

    def test_app_package_gets_menu_not_automatic_launch(self):
        from herdr_tools.files import quick_open
        from subprocess import CompletedProcess
        (self.root/'Example.app').mkdir()
        ctx = {'focused_pane_cwd': str(self.root), 'selected_text': 'Example.app'}
        with patch('herdr_tools.files.subprocess.run', return_value=CompletedProcess([], 0, 'package\n')), \
                patch('herdr_tools.files.popup') as popup, patch('herdr_tools.files.run') as run:
            quick_open(ctx)
        popup.assert_called_once()
        run.assert_not_called()




class Metrics(unittest.TestCase):
    def test_scan_is_reaped_without_a_focused_project(self):
        from unittest.mock import Mock
        sizes = FolderSizes()
        child = Mock()
        child.poll.return_value = None
        child.communicate.return_value = (b'', None)
        sizes.child, sizes.path, sizes.started = child, '/project', 0
        with patch('herdr_tools.metrics.time.monotonic', return_value=31):
            self.assertEqual(sizes.get(None), 'unavailable')
        child.kill.assert_called_once()
        self.assertIsNone(sizes.child)

    def test_disk_uses_project_volume(self):
        ws={'workspace_id':'w1','active_tab_id':'t1','worktree':{'checkout_path':'/Volumes/Media/project'}}
        self.assertEqual(workspace_path(ws,[]),'/Volumes/Media/project')

    def test_non_git_workspace_uses_own_pane(self):
        panes=[{'workspace_id':'w2','cwd':'/wrong'}, {'workspace_id':'w1','tab_id':'t1','cwd':'/right'}]
        self.assertEqual(workspace_path({'workspace_id':'w1','active_tab_id':'t1'},panes),'/right')

    def test_folder_scan_is_cached_and_does_not_follow_symlinks(self):
        import time
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / 'data').write_bytes(b'x' * 8192)
            (folder / 'outside').symlink_to(Path.home(), target_is_directory=True)
            sizes = FolderSizes()
            try:
                self.assertEqual(sizes.get(str(folder)), 'scanning…')
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline and sizes.child:
                    time.sleep(.03)
                    value = sizes.get(str(folder))
                self.assertEqual(value, '0 MiB')
                with patch('herdr_tools.metrics.subprocess.Popen') as spawn:
                    self.assertEqual(sizes.get(str(folder)), value)
                    spawn.assert_not_called()
            finally:
                sizes.close()




class Awake(unittest.TestCase):
    def test_api_timeouts_do_not_release_awake_after_three_failures(self):
        from herdr_tools import awake
        from unittest.mock import Mock
        child = Mock()
        child.poll.return_value = None
        with patch.object(awake.service, 'cleanup_on_signal'), \
                patch.object(awake.service, 'worker_lock'), \
                patch.object(awake.service, 'enabled', side_effect=[True, TimeoutError(), TimeoutError(), TimeoutError(), False]) as enabled, \
                patch.object(awake.service, 'status') as status, \
                patch.object(awake, 'mode', return_value='on'), \
                patch.object(awake.subprocess, 'Popen', return_value=child), \
                patch.object(awake.time, 'sleep'):
            awake.watch()
        self.assertEqual(enabled.call_count, 5)
        self.assertTrue(all(c.args[0]['active'] for c in status.call_args_list[:-1]))
        self.assertFalse(status.call_args.args[0]['active'])
        child.terminate.assert_called_once()

    def test_repeated_refusal_releases_awake(self):
        from herdr_tools import awake
        from unittest.mock import Mock
        child = Mock()
        child.poll.return_value = None
        with patch.object(awake.service, 'cleanup_on_signal'), \
                patch.object(awake.service, 'worker_lock'), \
                patch.object(awake.service, 'enabled', side_effect=[True, ConnectionRefusedError(), ConnectionRefusedError(), ConnectionRefusedError()]), \
                patch.object(awake.service, 'status') as status, \
                patch.object(awake, 'mode', return_value='on'), \
                patch.object(awake.subprocess, 'Popen', return_value=child), \
                patch.object(awake.time, 'sleep') as sleep:
            awake.watch()
        self.assertEqual(sleep.call_count, 3)
        child.terminate.assert_called_once()
        self.assertEqual(status.call_args.args[0]['mode'], 'on')
        self.assertIn('error', status.call_args.args[0])

    def test_indicator_distinguishes_running_off_transition_and_stale(self):
        from scripts.status import coffee_status
        with patch('scripts.status.time.time', return_value=100):
            live = {'mode': 'on', 'active': True, 'checked_at': 99}
            self.assertEqual(coffee_status(live, {'mode': 'on'}), '☕')
            self.assertEqual(coffee_status(live, {'mode': 'off'}), '⏳')
            self.assertEqual(coffee_status({**live, 'checked_at': 50}, {'mode': 'on'}), '❔')
            self.assertEqual(coffee_status({**live, 'error': 'lost connection'}, {'mode': 'on'}), '❔')
            self.assertEqual(coffee_status({}, {'mode': 'on'}), '❔')
            self.assertEqual(coffee_status({}, {}), '🌙')
            self.assertEqual(coffee_status({'mode': 'off', 'active': False, 'checked_at': 99},
                                           {'mode': 'off'}), '🌙')
            self.assertEqual(coffee_status({'mode': 'off', 'active': False, 'checked_at': 1},
                                           {'mode': 'off'}), '🌙')

    def test_popup_uses_active_pane_and_preserves_source_context(self):
        from herdr_tools.common import popup
        ctx = {'focused_pane_id': 'w1:p1', 'selected_text': 'example'}
        with patch.dict(os.environ, {'HERDR_PLUGIN_ID': 'gili.awake',
                                     'HERDR_PLUGIN_CONTEXT_JSON': json.dumps(ctx)}), \
                patch('herdr_tools.common.api') as api:
            popup('picker')
        method, params = api.call_args.args
        self.assertEqual(method, 'plugin.pane.open')
        self.assertNotIn('target_pane_id', params)
        self.assertEqual(json.loads(params['env']['TOOLS_SOURCE_CONTEXT']), ctx)

    def test_saved_modes_restore_on_startup_and_remain_session_scoped(self):
        from herdr_tools import awake
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {
                'HERDR_PLUGIN_STATE_DIR': temp, 'HERDR_SOCKET_PATH': '/test/first.sock'}):
            with patch.object(awake.service, 'start') as start:
                for saved in ('on', 'auto', 'off'):
                    awake.set_mode(saved)
                    start.reset_mock()
                    awake.main('startup')
                    self.assertEqual(awake.mode(), saved)
                    self.assertEqual(start.call_count, int(saved != 'off'))
                awake.set_mode('on')
                with patch.dict(os.environ, {'HERDR_SOCKET_PATH': '/test/second.sock'}):
                    self.assertEqual(awake.mode(), 'off')
                self.assertEqual(awake.mode(), 'on')

    def test_popup_shows_saved_option_without_claiming_stale_status_is_live(self):
        from herdr_tools import awake
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {
                'HERDR_PLUGIN_STATE_DIR': temp, 'HERDR_SOCKET_PATH': '/test/first.sock'}):
            with patch.object(awake.service, 'start'):
                awake.set_mode('on')
            with patch.object(awake, 'choose', return_value=None) as choose:
                awake.main('picker')
            args, kwargs = choose.call_args
            self.assertIn('unconfirmed', args[0])
            self.assertIn('[saved]', args[1][0])
            self.assertEqual(len(args[1]), 2)
            self.assertEqual(kwargs['initial'], 0)
            self.assertEqual(awake.mode(), 'on')


if __name__ == '__main__':
    unittest.main()
