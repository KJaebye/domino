"""Bilingual UI checks in isolated homes; never change real preferences or services."""
import ast
import json
import os
from pathlib import Path
import string
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import domino_cli as cli
import domino_i18n as i18n
import domino_tui as ui
from domino_translations import ENGLISH
from tests.remote_transport import local_action_argv


class LanguageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='domino-language-tests-')
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.environment = {k: v for k, v in os.environ.items()
                            if not k.startswith(('DOMINO_', '_DOMINO')) and k not in ('PYTHONPATH', 'PYTHONHOME')}
        self.environment.update(HOME=str(self.home), NO_COLOR='1', TERM='dumb')

    def run_cli(self, *arguments, env=None, expected=0):
        result = subprocess.run([sys.executable, str(Path(cli.__file__)), *arguments],
                                env={**self.environment, **(env or {})}, cwd=self.home,
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, expected, result.stderr)
        return result

    def test_default_language_is_english_without_writing_preferences(self):
        self.assertIn('Interface language: English', self.run_cli('language').stdout)
        self.assertFalse((self.home / '.config/domino/preferences.json').exists())
        self.assertIn('Profiles', self.run_cli('list').stdout)

    def test_preference_persists_across_processes_and_temporary_override_does_not_change_it(self):
        self.assertIn('Interface language: English', self.run_cli('language', 'en').stdout)
        preference = self.home / '.config/domino/preferences.json'
        self.assertEqual(preference.stat().st_mode & 0o777, 0o600)
        original = preference.read_bytes()
        self.assertIn('List all Domino-managed proxy profiles', self.run_cli('--help').stdout)
        self.assertIn('配置', self.run_cli('--lang', 'zh', 'list').stdout)
        self.assertEqual(preference.read_bytes(), original)
        self.assertIn('Profiles', self.run_cli('list').stdout)
        self.run_cli('language', 'zh')
        self.assertIn('配置', self.run_cli('list').stdout)

    def test_flag_overrides_environment_which_overrides_saved_preference(self):
        self.run_cli('language', 'en')
        self.assertIn('配置', self.run_cli('list', env={'DOMINO_LANG': 'zh'}).stdout)
        self.assertIn('Profiles', self.run_cli('list', '--lang', 'en', env={'DOMINO_LANG': 'zh'}).stdout)
        self.assertFalse((self.home / '.config/domino/subscriptions/index.json').exists())

    def test_chinese_profile_names_and_structured_data_are_not_translated(self):
        root = self.home / '.config/domino/subscriptions'
        root.mkdir(parents=True)
        registry = root / 'index.json'
        registry.write_text(json.dumps({'schema': 1, 'items': [
            {'id': 'a' * 32, 'name': '当前配置', 'kind': 'snapshot', 'node_count': 1}]}))
        data = self.home / '.local/share/domino/data'
        data.mkdir(parents=True)
        profile = data / 'config.json'
        profile.write_text(json.dumps({'mixed-port': 17897, 'proxies': [{'name': '节点选择'}],
                                       'rules': ['DOMAIN-SUFFIX,example.test,直连']}))
        (data / 'subscription.json').write_text(json.dumps({'id': 'a' * 32}))
        original = registry.read_bytes(), profile.read_bytes()
        english = self.run_cli('--lang', 'en', 'list').stdout
        self.assertIn('Current profile', english)
        self.assertIn('当前配置', english)
        zh = json.loads(self.run_cli('--lang', 'zh', 'list', '--json').stdout)
        en = json.loads(self.run_cli('--lang', 'en', 'list', '--json').stdout)
        self.assertEqual(zh, en)
        self.assertEqual((registry.read_bytes(), profile.read_bytes()), original)

    def test_english_help_and_errors_are_localized(self):
        for arguments in [('--help',), ('list', '--help'), ('test', '--help'), ('language', '--help')]:
            text = self.run_cli('--lang', 'en', *arguments).stdout
            self.assertFalse(any('\u4e00' <= c <= '\u9fff' for c in text), text)
        result = self.run_cli('--lang', 'en', 'add', 'name', '--url', 'http://example.test/private', expected=1)
        self.assertIn('HTTPS', result.stderr)
        self.assertNotIn('订阅', result.stderr)
        self.assertNotIn('http://example.test/private', result.stderr)

    def test_invalid_language_and_symlinked_preferences_do_not_write(self):
        self.run_cli('language', 'fr', expected=2)
        target = self.home / 'other.json'
        target.write_text('{"keep":true}')
        root = self.home / '.config/domino'
        root.mkdir(parents=True)
        (root / 'preferences.json').symlink_to(target)
        self.run_cli('language', 'en', expected=2)
        self.assertEqual(target.read_text(), '{"keep":true}')

    def test_workspace_switches_live_and_translates_command_descriptions(self):
        with patch.dict(os.environ, {**self.environment, 'DOMINO_LANG': 'zh'}):
            workspace = object.__new__(ui.Workspace)
            workspace.state = ui.State('localhost')
            workspace._refresh = Mock()
            workspace.app = Mock()
            workspace.dispatch('/language en')
            workspace.help()
            self.assertEqual(i18n.get_language(), 'en')
            self.assertIn('Interface language: English', str(workspace.state.events))
            self.assertIn('Switch between Chinese and English', str(workspace.state.events))
            workspace.dispatch('/language zh')
            self.assertEqual(i18n.get_language(), 'zh')
            self.assertIn('界面语言', str(workspace.state.events))
            self.assertEqual(json.loads((self.home / '.config/domino/preferences.json').read_text())['language'], 'zh')

    def test_remote_payload_uses_client_language_without_changing_target_preference(self):
        preference = self.home / '.config/domino/preferences.json'
        preference.parent.mkdir(parents=True)
        preference.write_text('{"language":"zh"}')
        with patch.dict(os.environ, {'DOMINO_LANG': 'en'}):
            ssh = cli.SSH(cli.build_parser().parse_args(['fixture.test', 'list']))
            ssh.socket = '/tmp/not-used'
            argv = local_action_argv(ssh, 'configs')
        result = subprocess.run(argv, env=self.environment, cwd=self.home,
                                capture_output=True, text=True, timeout=25)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Profiles', result.stdout)
        self.assertNotIn('配置', result.stdout)
        self.assertEqual(preference.read_text(), '{"language":"zh"}')

    def test_catalog_has_all_explicit_messages_and_matching_format_fields(self):
        formatter = string.Formatter()
        def fields(value):
            return sorted((field, spec, conversion) for _, field, spec, conversion in formatter.parse(value)
                          if field is not None)
        for path in Path(cli.__file__).parent.glob('*.py'):
            if path.name in ('domino_i18n.py', 'domino_translations.py'):
                continue
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == '_t' \
                        and node.args and isinstance(node.args[0], ast.Constant):
                    key = node.args[0].value
                    self.assertIn(key, ENGLISH, (path.name, key))
                    if len(node.args) > 1:
                        self.assertEqual(fields(key), fields(ENGLISH[key]), key)
        for value in ENGLISH.values():
            self.assertFalse(any('\u4e00' <= c <= '\u9fff' for c in value), value)


if __name__ == '__main__':
    unittest.main()
