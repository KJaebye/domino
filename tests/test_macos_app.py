"""Exercise the real supervisor, including signal forwarding and child reaping."""
import json
import os
from pathlib import Path
import plistlib
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import domino_macos_app as native
import domino_macos_app_build as build
import install_domino as common


class NativeLauncherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which('cc')
        if not compiler:
            raise unittest.SkipTest('C compiler unavailable')
        cls.directory = tempfile.TemporaryDirectory(prefix='domino-launcher-tests-')
        cls.addClassCleanup(cls.directory.cleanup)
        cls.root = Path(cls.directory.name)
        source = cls.root / 'launcher.c'
        source.write_text(build.LAUNCHER_SOURCE)
        cls.binary = cls.root / 'launcher'
        subprocess.run([compiler, '-Wall', '-Wextra', '-Werror', str(source), '-o', str(cls.binary)],
                       capture_output=True, check=True, timeout=30)

    def test_arguments_are_passed_without_a_shell_and_exit_status_is_preserved(self):
        argument = 'literal space; $(not-a-command)'
        result = subprocess.run([str(self.binary), sys.executable, '-c',
                                 'import sys,json;print(json.dumps(sys.argv[1:]));sys.exit(17)', argument],
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 17)
        self.assertEqual(json.loads(result.stdout), [argument])
        result = subprocess.run([str(self.binary), 'relative-path'], capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 64)

    def test_termination_reaches_child_and_parent_reaps_it(self):
        ready = self.root / 'child.pid'
        ready.unlink(missing_ok=True)
        code = 'import os,time,pathlib;pathlib.Path(__import__("sys").argv[1]).write_text(str(os.getpid()));time.sleep(30)'
        process = subprocess.Popen([str(self.binary), sys.executable, '-c', code, str(ready)])
        child = None
        try:
            for _ in range(100):
                if ready.exists() and ready.read_text():
                    child = int(ready.read_text())
                    break
                time.sleep(.02)
            self.assertIsNotNone(child, 'child did not become ready')
            self.assertIsNone(process.poll(), 'parent must remain alive to own the app identity')
            process.terminate()
            self.assertEqual(process.wait(timeout=5), 128 + signal.SIGTERM)
            with self.assertRaises(ProcessLookupError):
                os.kill(child, 0)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            if child:
                try: os.kill(child, signal.SIGKILL)
                except ProcessLookupError: pass


class AppPreparationTests(unittest.TestCase):
    def test_missing_developer_tools_fail_before_yielding_an_app(self):
        ctx = SimpleNamespace(InstallError=common.InstallError)
        with patch.object(native.subprocess, 'run', return_value=SimpleNamespace(returncode=1)) as run:
            with self.assertRaises(common.InstallError):
                with native.prepared(ctx):
                    self.fail('must not yield an unbuilt app')
        self.assertEqual(run.call_count, 1)

    @unittest.skipUnless(sys.platform == 'darwin', 'Mach-O and codesign require macOS')
    def test_prepared_app_has_a_signed_uuid_but_does_not_contain_or_modify_a_core(self):
        ctx = SimpleNamespace(InstallError=common.InstallError)
        with native.prepared(ctx) as app:
            info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
            self.assertEqual(info['CFBundleIdentifier'], native.BUNDLE_ID)
            self.assertTrue(info['NSLocalNetworkUsageDescription'])
            self.assertEqual(info['CFBundleIconFile'], 'Domino.icns')
            self.assertEqual((app / 'Contents/Resources/Domino.icns').read_bytes()[:4], b'icns')
            self.assertEqual(list((app / 'Contents/MacOS').iterdir()), [app / native.EXECUTABLE])
            load = subprocess.check_output(['otool', '-l', str(app / native.EXECUTABLE)], text=True)
            self.assertIn('LC_UUID', load)
            subprocess.run(['codesign', '--verify', '--strict', str(app)], check=True, capture_output=True)
        self.assertFalse(app.exists())

    @unittest.skipUnless(sys.platform == 'darwin', 'Mach-O UUIDs require macOS')
    def test_distinct_app_identities_have_distinct_launcher_uuids(self):
        ctx = SimpleNamespace(InstallError=common.InstallError)
        def uuid():
            with native.prepared(ctx) as app:
                return subprocess.check_output(['dwarfdump', '--uuid', str(app / native.EXECUTABLE)], text=True).split()[1]
        original = uuid()
        with patch.object(build, 'BUNDLE_ID', 'io.github.kjaebye.domino.launcher-test'):
            other = uuid()
        self.assertNotEqual(original, other)
        self.assertEqual(original, uuid(), 'rebuilding the same app identity must keep its UUID stable')
