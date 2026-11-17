import gzip
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import domino_cli
import domino_install
from scripts import build_distribution as distro
from scripts import build_release


def ar_members(data):
    if not data.startswith(b'!<arch>\n'):
        raise AssertionError('Not a Debian ar archive')
    result, offset = {}, 8
    while offset < len(data):
        header = data[offset:offset + 60]
        assert len(header) == 60 and header[-2:] == b'`\n'
        name = header[:16].decode().strip().rstrip('/')
        size = int(header[48:58])
        offset += 60
        result[name] = data[offset:offset + size]
        assert len(result[name]) == size
        offset += size + size % 2
    assert offset == len(data)
    return result


def tar_members(data):
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        return {member.name: (archive.extractfile(member).read(), member.mode)
                for member in archive if member.isfile()}


class DistributionFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.release = self.root / 'release'
        self.release.mkdir()
        self.output = self.root / 'distribution'
        files = {'cli/domino_install.py': b'# package entry points\n',
                 'cli/completion.zsh': b'#compdef domino\n',
                 'cli/completion.bash': b'# bash completion\n',
                 'cli/domino_cli.py': b'# synthetic CLI\n',
                 'cli/_vendor/yaml/__init__.py': b'# synthetic dependency\n',
                 'NOTICE': b'Third party notices\n', 'README.md': b'Example documentation\n'}
        self.runtime = self.release / 'domino-runtime-0.16.0.tar.gz'
        self.runtime.write_bytes(distro.tar_bytes({'domino-0.16.0/' + name: (data, 0o644)
                                                  for name, data in files.items()}, 0))
        self.formula = self.release / 'domino.rb.in'
        self.formula.write_text(build_release.formula_text(self.runtime.name, '0.16.0',
                                                          distro.digest(self.runtime.read_bytes()), 'https://example.invalid'))
        self.manifest = {'version': '0.16.0', 'built_at': '2026-11-16T00:00:00+00:00', 'files': [
            {'name': path.name, 'sha256': distro.digest(path.read_bytes()), 'bytes': path.stat().st_size}
            for path in [self.runtime, self.formula]]}
        self.write_manifest()

    def write_manifest(self):
        path = self.release / 'release.json'
        path.write_text(json.dumps(self.manifest))
        sums = {item['name']: item['sha256'] for item in self.manifest['files']}
        sums['release.json'] = distro.digest(path.read_bytes())
        (self.release / 'SHA256SUMS').write_text(''.join(checksum + '  ' + name + '\n' for name, checksum in sums.items()))


class DistributionTests(DistributionFixture):
    def test_previous_pool_survives_updates_without_replacing_published_packages(self):
        first = distro.build(self.release, self.output)
        previous = self.output / 'apt'
        pool = previous / 'pool/main/d/domino-proxy'
        old = pool / 'domino-proxy_0.15.0-1_all.deb'
        old.write_bytes((self.output / first['deb']).read_bytes())
        second = self.root / 'second'
        distro.build(self.release, second, previous_repo=previous)
        self.assertEqual((second / 'apt/pool/main/d/domino-proxy' / old.name).read_bytes(), old.read_bytes())
        self.assertNotIn('0.15.0', (second / 'apt/dists/stable/main/binary-amd64/Packages').read_text())
        (pool / first['deb']).write_bytes(b'!<arch>\nchanged')
        with self.assertRaisesRegex(ValueError, 'cannot be replaced'):
            distro.build(self.release, self.root / 'third', previous_repo=previous)
        self.assertFalse((self.root / 'third').exists())

    def test_previous_pool_rejects_missing_paths_and_symlink_members(self):
        with self.assertRaisesRegex(ValueError, 'lacks a pool'):
            distro.build(self.release, self.output, previous_repo=self.root / 'missing')
        previous = self.root / 'previous'
        (previous / 'pool').mkdir(parents=True)
        (previous / 'pool/linked').symlink_to(self.release, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            distro.build(self.release, self.output, previous_repo=previous)
        self.assertFalse(self.output.exists())

    def test_stable_one_major_release_builds_versioned_debian_package(self):
        _, files = distro.load_runtime(self.release)
        self.runtime = self.release / 'domino-runtime-1.0.0.tar.gz'
        self.runtime.write_bytes(distro.tar_bytes({'domino-1.0.0/' + name: (data, 0o644)
                                                  for name, data in files.items()}, 0))
        self.formula.write_text(build_release.formula_text(self.runtime.name, '1.0.0',
            distro.digest(self.runtime.read_bytes()), 'https://example.invalid'))
        self.manifest.update(version='1.0.0', files=[
            {'name': path.name, 'sha256': distro.digest(path.read_bytes()), 'bytes': path.stat().st_size}
            for path in [self.runtime, self.formula]])
        self.write_manifest()
        report = distro.build(self.release, self.output)
        self.assertEqual(report['version'], '1.0.0')
        control = tar_members(ar_members((self.output / report['deb']).read_bytes())['control.tar.gz'])
        self.assertIn('Version: 1.0.0-1\n', control['control'][0].decode())

    def test_deb_and_repository_are_consistent_and_install_cli_only(self):
        report = distro.build(self.release, self.output)
        deb = self.output / report['deb']
        members = ar_members(deb.read_bytes())
        self.assertEqual(set(members), {'debian-binary', 'control.tar.gz', 'data.tar.gz'})
        self.assertEqual(members['debian-binary'], b'2.0\n')
        controls = tar_members(members['control.tar.gz'])
        self.assertEqual(set(controls), {'control', 'md5sums'})  # No maintainer install/remove hooks.
        control = controls['control'][0].decode()
        self.assertIn('Architecture: all\n', control)
        self.assertIn('Depends: python3 (>= 3.9), curl, openssh-client\n', control)
        data = tar_members(members['data.tar.gz'])
        self.assertEqual(data['usr/bin/domino'][1], 0o755)
        self.assertIn(b'package_cli', data['usr/bin/domino'][0])
        self.assertIn('usr/lib/domino/cli/_vendor/yaml/__init__.py', data)
        self.assertIn('usr/share/zsh/vendor-completions/_domino', data)
        self.assertIn('usr/share/bash-completion/completions/domino', data)
        self.assertFalse(any('/home/' in name or name.startswith(('etc/', 'lib/systemd/')) for name in data))
        for line in controls['md5sums'][0].decode().splitlines():
            checksum, name = line.split('  ')
            self.assertEqual(hashlib.md5(data[name][0]).hexdigest(), checksum)
        suite = self.output / 'apt/dists/stable'
        for arch in ['amd64', 'arm64']:
            index = suite / f'main/binary-{arch}/Packages'
            text = index.read_text()
            filename = next(line[10:] for line in text.splitlines() if line.startswith('Filename: '))
            self.assertEqual((self.output / 'apt' / filename).read_bytes(), deb.read_bytes())
            self.assertIn('SHA256: ' + distro.digest(deb.read_bytes()), text)
            self.assertEqual(gzip.decompress(index.with_suffix('.gz').read_bytes()), index.read_bytes())
        release = (suite / 'Release').read_text()
        for index in suite.rglob('Packages*'):
            self.assertIn(distro.digest(index.read_bytes()) + f' {index.stat().st_size:16} {index.relative_to(suite)}', release)
        self.assertFalse(report['apt_signed'])
        self.assertFalse((suite / 'InRelease').exists())
        # An independent system parser validates the portable writer on Ubuntu CI.
        if shutil.which('dpkg-deb'):
            self.assertEqual(subprocess.check_output(['dpkg-deb', '--field', str(deb), 'Package'], text=True).strip(), distro.PACKAGE)
            subprocess.run(['dpkg-deb', '--extract', str(deb), str(self.root / 'extracted')], check=True)

    def test_deb_records_directories_before_children_for_dpkg_install_and_removal(self):
        report = distro.build(self.release, self.output)
        data = ar_members((self.output / report['deb']).read_bytes())['data.tar.gz']
        with tarfile.open(fileobj=io.BytesIO(data)) as archive:
            seen = set()
            for member in archive:
                for parent in Path(member.name).parents:
                    if parent != Path('.'):
                        self.assertIn(parent.as_posix(), seen, member.name)
                if member.isdir():
                    self.assertEqual(member.mode, 0o755)
                    seen.add(member.name)
            self.assertIn('usr/lib/domino/cli/_vendor/yaml', seen)

    def test_root_queries_do_not_leave_untracked_python_bytecode(self):
        # Execute the real generated launcher against a writable synthetic module,
        # equivalent to root reading the installed /usr/lib/domino/cli tree.
        module = self.root / 'modules'
        module.mkdir()
        (module / 'domino_install.py').write_text('def package_cli(): return 0\n')
        launcher = self.root / 'domino'
        launcher.write_bytes(distro.wrapper('package_cli').replace(
            b'"/usr/lib/domino/cli", "/usr/lib/domino/cli/_vendor"', repr(str(module)).encode()))
        import sys
        subprocess.run([sys.executable, str(launcher)], check=True)
        self.assertFalse((module / '__pycache__').exists())

    def test_deb_rebuild_is_deterministic_and_outputs_are_immutable(self):
        first = distro.build(self.release, self.output)
        second_dir = self.root / 'second'
        second = distro.build(self.release, second_dir)
        self.assertEqual(first['files'], second['files'])
        with self.assertRaises(FileExistsError):
            distro.build(self.release, self.output)

    def test_tampered_runtime_or_manifest_is_rejected_before_outputs(self):
        self.runtime.write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            distro.build(self.release, self.output)
        self.assertFalse(self.output.exists())
        self.write_manifest()
        (self.release / 'release.json').write_text('{}')
        with self.assertRaises((KeyError, ValueError)):
            distro.build(self.release, self.output)
        self.assertFalse(self.output.exists())

    def test_unsafe_runtime_is_rejected(self):
        self.runtime.write_bytes(distro.tar_bytes({'domino-0.16.0/../../escape': (b'bad', 0o644)}, 0))
        self.manifest['files'][0].update(sha256=distro.digest(self.runtime.read_bytes()), bytes=self.runtime.stat().st_size)
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, 'Unsafe'):
            distro.build(self.release, self.output)
        self.assertFalse((self.root / 'escape').exists())

    def test_failed_signing_does_not_publish_partial_output(self):
        with patch.object(distro, 'sign_repository', side_effect=RuntimeError('signing failed')):
            with self.assertRaisesRegex(RuntimeError, 'signing failed'):
                distro.build(self.release, self.output, sign_key='A' * 40)
        self.assertFalse(self.output.exists())
        self.assertFalse(list(self.root.glob('.domino-distribution-*')))

    def test_formula_does_not_start_services_or_modify_user_environment(self):
        formula = self.formula.read_text()
        self.assertNotIn('post_install', formula)
        self.assertNotIn('system bin/"domino-install"', formula)
        self.assertIn('from domino_install import #{entry}', formula)
        self.assertIn('def caveats', formula)

    def test_local_initialization_sets_cli_owner_without_inheriting_bundle_owner(self):
        args = domino_cli.build_parser().parse_args(['init', '--batch', '--bundle', 'synthetic.tar.gz'])
        def unpack(path, destination):
            (destination / 'manifest.json').write_text('{"package_managed_cli":true}')
        for managed in [True, False]:
            def backend_run(command, **kwargs):
                manifest = json.loads((Path(command[-1]) / 'manifest.json').read_text())
                self.assertEqual(manifest['package_managed_cli'], managed)
            with patch.object(domino_cli, 'PACKAGE_MANAGED', managed), \
                    patch.object(domino_cli.Path, 'home', return_value=self.root), \
                    patch.object(domino_cli, 'cache_dir', return_value=self.root), \
                    patch.object(domino_cli, 'local_target', return_value='arm64'), \
                    patch.object(domino_cli, 'unpack_bundle', side_effect=unpack), \
                    patch.object(domino_cli, 'copy_cli'), \
                    patch.object(domino_cli, 'run', side_effect=backend_run), \
                    patch('builtins.print'):
                domino_cli.initialize(args)

    def test_package_entries_keep_ownership_through_nested_cli_and_restore_context(self):
        for entry, installing in [(domino_install.package_cli, False), (domino_install.package_install, True)]:
            def invoked(args, **kwargs):
                self.assertTrue(domino_cli.PACKAGE_MANAGED)
                self.assertEqual(kwargs, {'installing': installing})
                raise RuntimeError('synthetic initialization failure')
            with patch.object(domino_install, 'cli_main', side_effect=invoked):
                with self.assertRaises(RuntimeError):
                    entry(['--batch'])
            self.assertFalse(domino_cli.PACKAGE_MANAGED)


if __name__ == '__main__':
    unittest.main()
