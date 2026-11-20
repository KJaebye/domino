"""Product-facing completion and health states must describe observed facts."""
from contextlib import redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest
import install_domino as control


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
