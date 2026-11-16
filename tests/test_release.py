from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from scripts import build_release


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'repo'
        self.root.mkdir()
        for name in build_release.SOURCE_FILES:
            (self.root / name).parent.mkdir(parents=True,exist_ok=True)
            (self.root / name).write_text('current ' + name)
        (self.root / 'pyproject.toml').write_text('[project]\nname = "domino-proxy"\nversion = "' + build_release.cli.VERSION + '"\n')
        (self.root / 'src/domino_cli.py').write_text('VERSION = ' + repr(build_release.cli.VERSION) + '\n')
        self.output = Path(self.temp.name) / 'release'
        self.root_patch = patch.object(build_release, 'ROOT', self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.wheel = patch.object(build_release.subprocess, 'run', side_effect=self.make_wheel).start()
        self.copy_cli = patch.object(build_release.cli, 'copy_cli', side_effect=self.make_cli).start()
        self.addCleanup(patch.stopall)

    def make_wheel(self, command, **options):
        self.assertTrue(options['check'])
        self.assertEqual(command[:4], [build_release.sys.executable, '-m', 'pip', 'wheel'])
        for option in ['--no-build-isolation', '--no-deps', '--no-index']:
            self.assertIn(option, command)
        source = Path(command[command.index('--wheel-dir') - 1])
        self.assertNotEqual(source, self.root)
        self.assertEqual({p.relative_to(source).as_posix() for p in source.rglob('*') if p.is_file()}, set(build_release.SOURCE_FILES))
        for name in build_release.SOURCE_FILES:
            self.assertEqual((source / name).read_bytes(), (self.root / name).read_bytes())
        output = Path(command[command.index('--wheel-dir') + 1])
        (output / build_release.wheel_name(build_release.cli.VERSION)).write_bytes(b'fixture wheel')

    def make_cli(self, package):
        cli = package / 'cli'
        cli.mkdir()
        # Deliberately stale module copies must be replaced from staged sources.
        for name in build_release.cli.CLI_MODULES:
            (cli / name).write_bytes(b'stale module')
        for name in ['yaml', 'prompt_toolkit', 'wcwidth']:
            (cli / '_vendor' / name).mkdir(parents=True)

    def run_build(self, *args):
        with patch.object(build_release.sys, 'argv', ['build_release.py', *args]), redirect_stdout(io.StringIO()):
            build_release.main()

    def assert_no_temporary_outputs(self):
        self.assertEqual(list(self.output.parent.glob('.domino-build-*')), [])
        self.assertFalse(self.output.exists())

    def test_release_stages_current_sources_without_old_build_or_registry_modules(self):
        stale = {}
        for name in ['domino_clients.py', 'build/lib/domino_clients.py',
                     'domino.egg-info/SOURCES.txt', 'domino.egg-info/top_level.txt']:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('stale external runtime management')
            stale[path] = path.read_bytes()
        self.run_build('--output', str(self.output))
        self.wheel.assert_called_once()
        archive = self.output / f'domino-runtime-{build_release.cli.VERSION}.tar.gz'
        with tarfile.open(archive) as bundle:
            names = bundle.getnames()
            self.assertFalse(any('domino_clients' in name for name in names))
            for name in build_release.cli.CLI_MODULES:
                member = f'domino-{build_release.cli.VERSION}/cli/{name}'
                self.assertEqual(bundle.extractfile(member).read(), (self.root / 'src' / name).read_bytes())
            self.assertTrue(any(name.endswith('/CHANGELOG.md') for name in names))
            for name in build_release.DOCUMENT_FILES:
                self.assertEqual(bundle.extractfile(f'domino-{build_release.cli.VERSION}/{name}').read(),(self.root/name).read_bytes())
        manifest = json.loads((self.output / 'release.json').read_text())
        self.assertFalse(manifest['published'])
        self.assertEqual(manifest['version'], build_release.cli.VERSION)
        self.assertTrue(manifest['built_at'].endswith('+00:00'))
        self.assertEqual(manifest['source_files'], build_release.hashes(
            {name: (self.root / name).read_bytes() for name in build_release.SOURCE_FILES}))
        self.assertTrue((self.output / 'domino.rb.in').is_file())
        for path, content in stale.items():
            self.assertEqual(path.read_bytes(), content)
        for item in manifest['files']:
            path = self.output / item['name']
            self.assertEqual(item['bytes'], path.stat().st_size)
            self.assertEqual(item['sha256'], hashlib.sha256(path.read_bytes()).hexdigest())
        sums = (self.output / 'SHA256SUMS').read_text().splitlines()
        self.assertEqual(len(sums), len(manifest['files']) + 1)
        for line in sums:
            digest, name = line.split('  ')
            self.assertEqual(digest, hashlib.sha256((self.output / name).read_bytes()).hexdigest())
        self.assertEqual({p.name for p in self.output.iterdir()},
                         {v['name'] for v in manifest['files']} | {'release.json', 'SHA256SUMS'})

    def test_default_output_keeps_flat_release_and_root_wheel(self):
        self.run_build()
        output = self.root / 'dist/release'
        self.assertTrue((output / 'release.json').is_file())
        wheel = build_release.wheel_name(build_release.cli.VERSION)
        self.assertEqual((self.root / 'dist' / wheel).read_bytes(), (output / wheel).read_bytes())
        self.assertFalse((output / build_release.cli.VERSION).exists())
        self.assertFalse((self.root / 'dist/.domino-release.lock').exists())
        before = {path.name: path.read_bytes() for path in output.iterdir()}
        with self.assertRaises(FileExistsError):
            self.run_build()
        self.assertEqual(before, {path.name: path.read_bytes() for path in output.iterdir()})
        self.assertEqual(self.wheel.call_count, 1)

    def previous_flat_release(self):
        output = self.root / 'dist/release'
        output.mkdir(parents=True)
        contents = {'domino-0.12.0-py3-none-any.whl': b'previous wheel',
                    'domino-runtime-0.12.0.tar.gz': b'previous runtime',
                    'domino.rb.in': b'previous formula'}
        entries = [{'name': name, 'bytes': len(content), 'sha256': hashlib.sha256(content).hexdigest()}
                   for name, content in contents.items()]
        # Match the historical schema: only artifacts in the checksum file, no source hashes.
        contents['release.json'] = json.dumps({'schema_version': 1, 'version': '0.12.0',
                                             'published': False, 'files': entries}).encode()
        contents['SHA256SUMS'] = ''.join(item['sha256'] + '  ' + item['name'] + '\n'
                                        for item in entries).encode()
        for name, content in contents.items():
            (output / name).write_bytes(content)
        (output.parent / 'domino-0.11.1-py3-none-any.whl').write_bytes(b'older root wheel')
        (output.parent / 'installed-verification.json').write_bytes(b'old installed verification')
        return output, contents

    def test_flat_release_archives_previous_metadata_without_moving_old_packages(self):
        output, previous = self.previous_flat_release()
        self.run_build()
        for name, content in previous.items():
            self.assertEqual((output / 'history/0.12.0' / name).read_bytes(), content)
            if name.endswith(('.whl', '.tar.gz')):
                self.assertEqual((output / name).read_bytes(), content)
        manifest = json.loads((output / 'release.json').read_text())
        self.assertEqual(manifest['version'], build_release.cli.VERSION)
        self.assertEqual({item['name'] for item in manifest['files']},
                         {build_release.wheel_name(build_release.cli.VERSION),
                          f'domino-runtime-{build_release.cli.VERSION}.tar.gz', 'domino.rb.in'})
        self.assertEqual((output.parent / 'domino-0.11.1-py3-none-any.whl').read_bytes(), b'older root wheel')
        self.assertEqual((output.parent / 'installed-verification.json').read_bytes(), b'old installed verification')

    def test_next_patch_release_accepts_new_manifest_and_archives_public_formula(self):
        self.run_build('--base-url', 'https://example.test/releases')
        output = self.root / 'dist/release'
        old = {path.name: path.read_bytes() for path in output.iterdir()}
        major, minor, patch_version = build_release.cli.VERSION.split('.')
        version = f'{major}.{minor}.{int(patch_version) + 1}'
        (self.root / 'src/domino_cli.py').write_text('VERSION = ' + repr(version) + '\n')
        (self.root / 'pyproject.toml').write_text('[project]\nversion="' + version + '"\n')
        with patch.object(build_release.cli, 'VERSION', version):
            self.run_build()
        self.assertFalse((output / 'domino.rb').exists())
        self.assertTrue((output / 'domino.rb.in').is_file())
        self.assertEqual(json.loads((output / 'release.json').read_text())['version'], version)
        for name, content in old.items():
            self.assertEqual((output / 'history' / build_release.cli.VERSION / name).read_bytes(), content)

    def test_existing_root_wheel_blocks_default_build_without_changing_release(self):
        output, previous = self.previous_flat_release()
        wheel = output.parent / build_release.wheel_name(build_release.cli.VERSION)
        wheel.write_bytes(b'existing version')
        with self.assertRaises(FileExistsError):
            self.run_build()
        self.wheel.assert_not_called()
        self.assertEqual(wheel.read_bytes(), b'existing version')
        self.assertEqual((output / 'release.json').read_bytes(), previous['release.json'])

    def test_corrupt_previous_flat_release_fails_before_build(self):
        output, previous = self.previous_flat_release()
        (output / 'domino.rb.in').write_bytes(b'corrupted formula')
        with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
            self.run_build()
        self.wheel.assert_not_called()
        self.assertEqual((output / 'release.json').read_bytes(), previous['release.json'])
        self.assertFalse((output.parent / '.domino-release.lock').exists())

    def test_flat_publish_failure_restores_old_metadata_and_removes_new_packages(self):
        output, previous = self.previous_flat_release()
        real_replace = Path.replace
        def fail_once(path, target):
            if path.parent.name == 'artifacts' and path.name == 'release.json':
                raise OSError('manifest commit failed')
            return real_replace(path, target)
        with patch.object(Path, 'replace', fail_once), self.assertRaisesRegex(OSError, 'manifest commit failed'):
            self.run_build()
        for name, content in previous.items():
            self.assertEqual((output / name).read_bytes(), content)
        self.assertFalse((output / 'history/0.12.0').exists())
        self.assertFalse((output / f'domino-runtime-{build_release.cli.VERSION}.tar.gz').exists())
        self.assertFalse((output / build_release.wheel_name(build_release.cli.VERSION)).exists())
        self.assertFalse((output.parent / build_release.wheel_name(build_release.cli.VERSION)).exists())
        self.assertFalse((output.parent / '.domino-release.lock').exists())

    def test_changed_previous_release_during_build_is_not_overwritten(self):
        output, previous = self.previous_flat_release()
        def mutate(package):
            self.make_cli(package)
            (output / 'domino.rb.in').write_bytes(b'concurrent owner')
        with patch.object(build_release.cli, 'copy_cli', side_effect=mutate), self.assertRaises(ValueError):
            self.run_build()
        self.assertEqual((output / 'domino.rb.in').read_bytes(), b'concurrent owner')
        self.assertEqual((output / 'release.json').read_bytes(), previous['release.json'])
        self.assertFalse((output / 'history').exists())

    def test_flat_build_lock_is_not_removed_when_owned_by_another_build(self):
        lock = self.root / 'dist/.domino-release.lock'
        lock.mkdir(parents=True)
        with self.assertRaises(FileExistsError):
            self.run_build()
        self.wheel.assert_not_called()
        self.assertTrue(lock.is_dir())

    def test_version_preflight_rejects_missing_invalid_or_mismatched_versions(self):
        path = self.root / 'pyproject.toml'
        major = int(build_release.cli.VERSION.split('.')[0]) + 1
        for content in ['[project]\nname="domino"\n', f'[project]\nversion="{major}.0.0"\n',
                        '[project]\nversion="0.13"\n', '[project]\nversion="0.13.1.2"\n', '[other]\nversion="' + build_release.cli.VERSION + '"\n']:
            with self.subTest(content=content):
                path.write_text(content)
                with redirect_stdout(io.StringIO()), patch('sys.stderr', io.StringIO()), self.assertRaises(SystemExit):
                    self.run_build('--output', str(self.output))
                self.assertFalse(self.output.exists())
        self.wheel.assert_not_called()

    def test_big_and_small_update_versions_are_supported(self):
        for version in ['0.13.0', '0.13.1', '0.14.0', '0.14.2', '1.0.0', '1.0.1', '1.1.0', '2.0.0']:
            with self.subTest(version=version), patch.object(build_release.cli, 'VERSION', version):
                inputs = {'src/domino_cli.py': ('VERSION = ' + repr(version)).encode(),
                          'pyproject.toml': ('[project]\nversion="' + version + '"\n').encode()}
                self.assertEqual(build_release.source_version(inputs), version)

    def test_noncanonical_release_versions_are_rejected_even_when_declarations_match(self):
        for version in ['01.0.0', '1.00.0', '1.0.01', '1.0.0rc1', '1.0', '-1.0.0']:
            with self.subTest(version=version), patch.object(build_release.cli, 'VERSION', version):
                inputs = {'src/domino_cli.py': ('VERSION = ' + repr(version)).encode(),
                          'pyproject.toml': ('[project]\nversion="' + version + '"\n').encode()}
                with self.assertRaises(ValueError):
                    build_release.source_version(inputs)

    def test_checked_in_versions_match(self):
        root = Path(build_release.__file__).resolve().parents[1]
        inputs = {name: (root / name).read_bytes() for name in ('src/domino_cli.py', 'pyproject.toml')}
        self.assertEqual(build_release.source_version(inputs), build_release.cli.VERSION)

    def test_existing_outputs_including_dangling_links_are_never_overwritten(self):
        for kind in ['empty', 'nonempty', 'file', 'symlink']:
            with self.subTest(kind=kind):
                if kind in ('empty', 'nonempty'):
                    self.output.mkdir()
                    if kind == 'nonempty':
                        (self.output / 'keep').write_bytes(b'previous build')
                elif kind == 'file':
                    self.output.write_bytes(b'previous build')
                else:
                    self.output.symlink_to(self.output.parent / 'missing')
                with patch('sys.stderr', io.StringIO()), self.assertRaises(SystemExit):
                    self.run_build('--output', str(self.output))
                if self.output.is_symlink():
                    self.assertTrue(self.output.is_symlink())
                    self.output.unlink()
                elif self.output.is_file():
                    self.assertEqual(self.output.read_bytes(), b'previous build')
                    self.output.unlink()
                else:
                    if kind == 'nonempty':
                        self.assertEqual((self.output / 'keep').read_bytes(), b'previous build')
                        (self.output / 'keep').unlink()
                    self.output.rmdir()
        self.wheel.assert_not_called()

    def test_build_failures_clean_temporary_and_final_outputs(self):
        for step in ['wheel', 'dependencies', 'archive', 'manifest']:
            with self.subTest(step=step):
                if step == 'wheel':
                    hook = patch.object(build_release.subprocess, 'run', side_effect=RuntimeError('wheel failed'))
                elif step == 'dependencies':
                    def missing(package):
                        self.make_cli(package)
                        (package / 'cli/_vendor/yaml').rmdir()
                    hook = patch.object(build_release.cli, 'copy_cli', side_effect=missing)
                elif step == 'archive':
                    hook = patch.object(build_release.tarfile, 'open', side_effect=OSError('archive failed'))
                else:
                    hook = patch.object(build_release.json, 'dumps', side_effect=ValueError('manifest failed'))
                with hook, self.assertRaises((RuntimeError, OSError, ValueError)):
                    self.run_build('--output', str(self.output))
                self.assert_no_temporary_outputs()

    def test_runtime_rejects_dependencies_above_the_declared_python_minimum(self):
        with patch.object(build_release.importlib.metadata,'metadata',return_value={'Requires-Python':'>=3.10'}):
            with self.assertRaisesRegex(RuntimeError,'Python 3.9'):
                self.run_build('--output',str(self.output))
        self.wheel.assert_not_called()
        self.assert_no_temporary_outputs()

    def test_sources_changed_during_build_fail_without_delivering(self):
        def mutate(package):
            self.make_cli(package)
            (self.root / 'README.md').write_text('changed while building')
        with patch.object(build_release.cli, 'copy_cli', side_effect=mutate), self.assertRaisesRegex(RuntimeError, 'Sources changed'):
            self.run_build('--output', str(self.output))
        self.assert_no_temporary_outputs()

    def test_output_created_concurrently_is_not_overwritten(self):
        def create_output(package):
            self.make_cli(package)
            self.output.mkdir()
            (self.output / 'keep').write_bytes(b'concurrent owner')
        with patch.object(build_release.cli, 'copy_cli', side_effect=create_output), self.assertRaises(FileExistsError):
            self.run_build('--output', str(self.output))
        self.assertEqual((self.output / 'keep').read_bytes(), b'concurrent owner')
        self.assertEqual(list(self.output.parent.glob('.domino-build-*')), [])

    def test_failed_publication_cleans_reserved_output(self):
        real_rename = Path.rename
        def fail(path, destination):
            if Path(destination).parent == self.output:
                raise OSError('publication failed')
            return real_rename(path, destination)
        with patch.object(Path, 'rename', fail), self.assertRaises(OSError):
            self.run_build('--output', str(self.output))
        self.assert_no_temporary_outputs()

    def test_public_formula_is_opt_in_and_old_output_is_untouched(self):
        self.output.mkdir()
        (self.output / 'old.whl').write_bytes(b'old')
        new_output = self.output.parent / 'new-release'
        self.run_build('--output', str(new_output), '--base-url', 'https://example.test/releases')
        formula = (new_output / 'domino.rb').read_text()
        self.assertIn('https://example.test/releases/domino-runtime-' + build_release.cli.VERSION, formula)
        self.assertNotIn('old.whl', (new_output / 'release.json').read_text())
        self.assertEqual((self.output / 'old.whl').read_bytes(), b'old')
