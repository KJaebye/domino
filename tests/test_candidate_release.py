import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from unittest.mock import patch

from scripts import candidate_release as candidate
from scripts import build_distribution as distribution
from scripts import release_channels as release
from tests.test_distribution import DistributionFixture


class CandidateReleaseTests(DistributionFixture):
    def setUp(self):
        super().setUp()
        self.source = self.root / 'source'
        (self.source / 'src').mkdir(parents=True)
        (self.source / 'scripts').mkdir()
        (self.source / 'src/domino_cli.py').write_text("VERSION = '0.16.0'\nBUILD_CHANNEL = 'release'\n")
        (self.source / 'scripts/build_release.py').write_text('# synthetic builder\n')
        subprocess.run(['git', 'init', '-q', str(self.source)], check=True)
        subprocess.run(['git', '-C', str(self.source), 'add', 'src', 'scripts'], check=True)
        subprocess.run(['git', '-C', str(self.source), '-c', 'user.name=Fixture', '-c',
                        'user.email=fixture@example.invalid', 'commit', '-qm', 'fixture'], check=True)
        self.sha = subprocess.check_output(['git', '-C', str(self.source), 'rev-parse', 'HEAD'], text=True).strip()
        self.manifest.update(published=False, source_files={
            'src/domino_cli.py': candidate.digest(self.source / 'src/domino_cli.py')},
            build_script_sha256=candidate.digest(self.source / 'scripts/build_release.py'))
        wheel = self.release / 'domino_proxy-0.16.0-py3-none-any.whl'
        wheel.write_bytes(b'synthetic wheel; twine and execution are mocked only in import tests')
        self.manifest['files'].append({'name': wheel.name, 'sha256': candidate.digest(wheel), 'bytes': wheel.stat().st_size})
        self.write_manifest()
        self.bundle = self.root / 'candidate'
        self.output = self.bundle / 'output'
        (self.output / 'dist').mkdir(parents=True)
        shutil.copytree(self.release, self.output / 'dist/release')
        (self.output / 'dist/pypi').mkdir()
        (self.output / 'dist/pypi/domino_proxy-0.16.0.tar.gz').write_bytes(b'synthetic source distribution')
        distribution.build(self.output / 'dist/release', self.output / 'dist/distribution')
        self.checks = {'schema': 1, 'profile': 'full', 'mode': 'release-candidate', 'published': False,
                       'ok': True, 'not_tested': ['macOS native installation'],
                       'checks': [{'name': name, 'ok': True} for name in [
                           'release-preflight', 'repository', 'install-test-package', 'full-regression', 'build-release',
                           'verify-artifacts', 'verify-pip', 'build-sdist', 'verify-pypi-metadata', 'prepare-unsigned-apt']]}
        self.report = {'schema': 1, 'project': 'domino', 'repository': 'KJaebye/domino',
                       'ok': True, 'publication_allowed': False, 'source_sha': self.sha,
                       'infra_sha': 'a' * 40, 'image_id': 'sha256:' + 'b' * 64,
                       'run_id': '20261123T000000Z-' + self.sha[:12] + '-123456',
                       'version': '0.16.0', 'build_channel': 'release', 'profile': 'full',
                       'mode': 'release-candidate'}
        self.seal()

    def seal(self):
        (self.output / 'checks.json').write_text(json.dumps(self.checks))
        self.report.update(checks=self.checks,
            files={p.relative_to(self.output).as_posix(): candidate.digest(p)
                   for p in self.output.rglob('*') if p.is_file()})
        (self.bundle / 'result.json').write_text(json.dumps(self.report))

    def plan(self, existing=False):
        work = self.root / 'publish-work'
        work.mkdir()
        release.write_json(work / 'plan.json', {'schema': 1, 'version': '0.16.0',
            'repository': 'KJaebye/domino', 'source_sha': self.sha, 'existing_release': existing,
            'tap_repository': 'KJaebye/homebrew-tap', 'apt_repository': 'KJaebye/domino-apt',
            'apt_url': 'https://example.invalid/apt/'})
        return work

    def test_stable_candidate_review_is_not_publication_authorization(self):
        result = candidate.review(self.bundle, self.source)
        self.assertTrue(result['candidate_verified'])
        self.assertTrue(result['eligible_for_release_preparation'])
        self.assertFalse(result['publication_allowed'])
        self.assertEqual(result['source_sha'], self.sha)

    def test_development_candidate_stays_ineligible_even_with_successful_full_ci(self):
        (self.source / 'src/domino_cli.py').write_text("VERSION = '0.16.0'\nBUILD_CHANNEL = 'development'\n")
        subprocess.run(['git', '-C', str(self.source), '-c', 'user.name=Fixture', '-c',
                        'user.email=fixture@example.invalid', 'commit', '-qam', 'development'], check=True)
        self.report.update(source_sha=subprocess.check_output(['git', '-C', str(self.source), 'rev-parse', 'HEAD'], text=True).strip(),
                           mode='development', build_channel='development')
        self.report['run_id'] = '20261123T000000Z-' + self.report['source_sha'][:12] + '-123456'
        self.checks['mode'] = 'development'
        manifest = json.loads((self.output / 'dist/release/release.json').read_text())
        manifest['source_files']['src/domino_cli.py'] = candidate.digest(self.source / 'src/domino_cli.py')
        (self.output / 'dist/release/release.json').write_text(json.dumps(manifest))
        # Recompute the two bound manifests as a real development build would.
        sums = self.output / 'dist/release/SHA256SUMS'
        lines = [line for line in sums.read_text().splitlines() if not line.endswith('  release.json')]
        sums.write_text('\n'.join(lines) + '\n' + candidate.digest(sums.parent / 'release.json') + '  release.json\n')
        distro = self.output / 'dist/distribution/distribution.json'
        meta = json.loads(distro.read_text())
        meta['release_manifest_sha256'] = candidate.digest(sums.parent / 'release.json')
        distro.write_text(json.dumps(meta))
        self.seal()
        result = candidate.review(self.bundle, self.source)
        self.assertFalse(result['eligible_for_release_preparation'])
        self.assertIn('Development', result['blockers'][0])

    def test_extra_output_modified_bytes_and_symlink_are_rejected(self):
        target = self.output / 'dist/pypi/domino_proxy-0.16.0.tar.gz'
        target.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'inventory|checksum'):
            candidate.verify_inventory(self.bundle)
        self.seal()
        (self.output / 'unlisted').write_bytes(b'extra')
        with self.assertRaisesRegex(ValueError, 'inventory'):
            candidate.verify_inventory(self.bundle)
        (self.output / 'unlisted').unlink()
        (self.output / 'escape').symlink_to(self.source, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlinks'):
            candidate.verify_inventory(self.bundle)

    def test_unsafe_report_inventory_paths_are_rejected(self):
        for path in ('../outside', '/etc/passwd', 'dist/../escape', 'dist\\escape'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                candidate.safe_relative(path)

    def test_controller_container_disagreement_and_dirty_source_are_rejected(self):
        self.report['checks'] = {**self.checks, 'profile': 'smoke'}
        (self.bundle / 'result.json').write_text(json.dumps(self.report))
        with self.assertRaisesRegex(ValueError, 'reports differ'):
            candidate.review(self.bundle, self.source)
        self.seal()
        (self.source / 'src/domino_cli.py').write_text('changed')
        with self.assertRaisesRegex(ValueError, 'modifications'):
            candidate.review(self.bundle, self.source)

    def test_preparation_imports_original_bytes_without_building_wheel_or_sdist(self):
        work = self.plan()
        original = subprocess.run
        commands = []
        def run(args, **kwargs):
            commands.append(args)
            if args[:4] == [sys.executable, '-m', 'twine', 'check']:
                return subprocess.CompletedProcess(args, 0)
            return original(args, **kwargs)
        with patch.object(release.verify_artifacts, 'verify', return_value={'ok': True}), \
                patch.object(distribution, 'deb_bytes', side_effect=AssertionError('Do not recompress original CI packages')), \
                patch.object(release.subprocess, 'run', side_effect=run):
            plan = release.prepare(work, self.source, candidate=self.bundle)
        for name in ('domino-runtime-0.16.0.tar.gz', 'domino_proxy-0.16.0-py3-none-any.whl'):
            self.assertEqual((work / 'release' / name).read_bytes(), (self.output / 'dist/release' / name).read_bytes())
        self.assertEqual(plan['ci_candidate']['run_id'], self.report['run_id'])
        self.assertFalse(any('scripts/build_release.py' in str(args) or '--sdist' in args for args in commands))
        self.assertEqual(candidate.digest(work / 'channels/distribution/domino-proxy_0.16.0-1_all.deb'),
                         candidate.digest(self.output / 'dist/distribution/domino-proxy_0.16.0-1_all.deb'))

    def published_assets(self, work, change_sdist=False):
        assets = {p.name: p.read_bytes() for p in (self.output / 'dist/release').iterdir()}
        sdist = 'domino_proxy-0.16.0.tar.gz'
        assets[sdist] = (self.output / 'dist/pypi' / sdist).read_bytes() + (b'other build' if change_sdist else b'')
        names = ['domino_proxy-0.16.0-py3-none-any.whl', sdist]
        assets['PYPI-SHA256SUMS'] = ''.join(hashlib.sha256(assets[name]).hexdigest() + '  ' + name + '\n' for name in names).encode()
        plan = release.plan_at(work)
        plan['assets'] = [{'name': name, 'digest': 'sha256:' + hashlib.sha256(content).hexdigest()}
                          for name, content in assets.items()]
        release.write_json(work / 'plan.json', plan)
        return assets

    def test_channel_recovery_uses_matching_official_originals_without_rebuilding(self):
        work = self.plan(existing=True)
        assets = self.published_assets(work)
        original = subprocess.run
        def run(args, **kwargs):
            if args[:4] == [sys.executable, '-m', 'twine', 'check']:
                return subprocess.CompletedProcess(args, 0)
            return original(args, **kwargs)
        with patch.object(release, 'fetch', side_effect=lambda url: assets[url.rsplit('/', 1)[1]]), \
             patch.object(release.verify_artifacts, 'verify', return_value={'ok': True}), \
             patch.object(distribution, 'deb_bytes', side_effect=AssertionError('Do not recompress original CI packages')), \
             patch.object(release.subprocess, 'run', side_effect=run):
            result = release.prepare(work, self.source, candidate=self.bundle)
        self.assertTrue(result['existing_release'])
        self.assertEqual(result['ci_candidate']['run_id'], self.report['run_id'])
        self.assertEqual((work / 'release/domino_proxy-0.16.0.tar.gz').read_bytes(), assets['domino_proxy-0.16.0.tar.gz'])

    def test_different_published_bytes_cannot_be_replaced_by_a_same_version_candidate(self):
        work = self.plan(existing=True)
        assets = self.published_assets(work, change_sdist=True)
        original = subprocess.run
        def run(args, **kwargs):
            if args[:4] == [sys.executable, '-m', 'twine', 'check']:
                return subprocess.CompletedProcess(args, 0)
            return original(args, **kwargs)
        with patch.object(release, 'fetch', side_effect=lambda url: assets[url.rsplit('/', 1)[1]]), \
             patch.object(release.verify_artifacts, 'verify', return_value={'ok': True}), \
             patch.object(release.subprocess, 'run', side_effect=run):
            with self.assertRaisesRegex(ValueError, 'Published source distribution differs'):
                release.prepare(work, self.source, candidate=self.bundle)

    def test_preflight_blocks_already_published_github_version_before_other_requests(self):
        with patch.object(candidate, 'source_metadata', return_value=('0.16.0', 'release')), \
             patch.object(release, 'api', return_value={'id': 1}), patch.object(release, 'fetch') as fetch:
            with self.assertRaisesRegex(ValueError, 'already has a GitHub'):
                candidate.preflight()
            fetch.assert_not_called()

    def test_preflight_blocks_pypi_or_apt_version_without_rebuilding(self):
        for responses in ([b'{"urls": []}'], [None, b'{"version":"1.0.0"}']):
            with self.subTest(responses=responses), \
                 patch.object(candidate, 'source_metadata', return_value=('0.16.0', 'release')), \
                 patch.object(release, 'api', return_value=None), \
                 patch.object(release, 'fetch', side_effect=responses):
                with self.assertRaisesRegex(ValueError, 'already'):
                    candidate.preflight()
