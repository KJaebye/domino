from contextlib import redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest

from scripts import check_repository as check


class RepositoryChecksTests(unittest.TestCase):
    def fixture(self, root):
        for name in check.REQUIRED:
            path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('')
        (root/'domino_cli.py').write_text("VERSION='0.1.0'\nCLI_MODULES=('domino_cli.py',)\n")
        (root/'pyproject.toml').write_text('[project]\nversion = "0.1.0"\n')

    def test_secret_findings_are_redacted_and_ignored_build_files_are_not_scanned(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);self.fixture(root)
            token='ghp_'+'X'*40
            (root/'leak.txt').write_text(token)
            (root/'dist').mkdir();(root/'dist/generated.txt').write_text(token)
            report=check.inspect(root)
            self.assertFalse(report['ok'])
            self.assertEqual(report['errors'],[{'path':'leak.txt','line':1,'rule':'github-token'}])
            self.assertNotIn(token,str(report))

    def test_missing_modules_and_broken_documentation_links_block_release_check(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);self.fixture(root)
            (root/'domino_cli.py').write_text("VERSION='0.1.0'\nCLI_MODULES=('missing.py',)\n")
            (root/'README.md').write_text('[guide](docs/no-such-file.md)')
            report=check.inspect(root)
            self.assertEqual({v['rule'] for v in report['errors']},{'module-not-in-public-candidates','broken-local-link'})

    def test_old_python_syntax_and_unpinned_actions_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);self.fixture(root)
            (root/'new.py').write_text('match value:\n case 1: pass\n')
            (root/'.github/workflows/verify.yml').write_text('steps:\n - uses: actions/checkout@main\n')
            report=check.inspect(root)
            self.assertEqual({v['rule'] for v in report['errors']},{'python39-syntax','action-not-pinned'})
