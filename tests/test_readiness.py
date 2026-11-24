"""Product-facing completion and health states must describe observed facts."""
from contextlib import redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest
import install_domino as control

from tests.locale_fixture import chinese_ui

setUpModule, tearDownModule = chinese_ui()


class InstallationSummaryTests(unittest.TestCase):
    def test_pending_install_has_one_next_step_and_does_not_claim_connectivity(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory); app = home / 'app'
            (app / 'cli').mkdir(parents=True)
            (app / 'cli/completion.zsh').touch()
            output = io.StringIO()
            with redirect_stdout(output):
                control.installation_summary(app, home, system='darwin', shell_env=True,
                    pending=True, health=None, backup=Path('backup-123'))
            text = output.getvalue()
            self.assertEqual(text.count('下一步'), 1)
            self.assertIn('domino add "名称"', text)
            self.assertIn('新开的 Zsh 终端自动加载', text)
            self.assertIn('未检测', text)
            self.assertNotIn('已检测通过', text)
            self.assertIn('策略已关闭', text)

    def test_configured_linux_install_and_opt_out_are_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory); app = home / 'app'
            (app / 'cli').mkdir(parents=True)
            (app / 'cli/completion.bash').touch()
            for enabled in (False, True):
                output = io.StringIO()
                with redirect_stdout(output):
                    control.installation_summary(app, home, system='linux', shell_env=enabled,
                        pending=False, health={'healthy': True}, backup=Path('backup-123'))
                text = output.getvalue()
                self.assertIn('开机自启', text)
                self.assertIn('已检测通过', text)
                self.assertIn('domino status', text)
                self.assertIn('新开的 Bash 终端自动加载' if enabled else '本次未设置终端接入', text)
                self.assertFalse((home / '.bashrc').exists())


class StatusMeaningTests(unittest.TestCase):
    def test_unchecked_connectivity_is_not_a_failed_check(self):
        state = {'installed': True, 'active': True, 'enabled': True, 'healthy': False,
                 'controller_reachable': True, 'exit_checked': False, 'proxy_port': 17897}
        text = control.status_text(state)
        self.assertIn('出网尚未检测', text)
        self.assertIn('domino status 执行出网检查', text)
        self.assertNotIn('连通检查未通过', text)
        state.update(exit_checked=True, exit_checked_at='2026-11-20T06:00:00+00:00')
        text = control.status_text(state)
        self.assertIn('连通检查未通过', text)
        self.assertNotIn('2026-11-20', text)
        self.assertNotIn('未检测；按目标地址', text)
        detailed=control.status_text(state,verbose=True)
        self.assertIn('2026-11-20',detailed)
        self.assertIn('未检测；按目标地址',detailed)


class BuildIdentityTests(unittest.TestCase):
    def test_same_version_changes_identity_when_source_changes_and_does_not_run_git(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entry = root / 'domino_cli.py'
            entry.write_text("VERSION='1.3.0'\nBUILD_CHANNEL='development'\nCLI_MODULES=('domino_cli.py','domino_model.py')\n")
            model = root / 'domino_model.py';model.write_text('value=1\n')
            with patch.object(control.subprocess,'run',side_effect=AssertionError('metadata must be local and read-only')):
                first = control.cli_build_info(root)
                model.write_text('value=2\n')
                second = control.cli_build_info(root)
            self.assertTrue(first['complete'])
            self.assertEqual(first['version'],second['version'])
            self.assertNotEqual(first['build_id'],second['build_id'])
            model.unlink()
            self.assertFalse(control.cli_build_info(root)['complete'])

    def test_manifest_cannot_read_arbitrary_files_or_follow_resource_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entry = root/'domino_cli.py'
            entry.write_text("VERSION='1.3.0'\nCLI_MODULES=('../other',)\n")
            self.assertFalse(control.cli_build_info(root)['complete'])
            entry.write_text("VERSION='1.3.0'\nCLI_MODULES=('domino_cli.py','domino_model.py')\n")
            (root/'domino_model.py').symlink_to(entry)
            self.assertFalse(control.cli_build_info(root)['complete'])
