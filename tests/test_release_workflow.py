import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from unittest.mock import patch

from scripts import prepare_channels
from scripts import release_channels as release
from tests.test_distribution import DistributionFixture


class ReleaseWorkflowTests(DistributionFixture):
    def setUp(self):
        super().setUp()
        self.work = self.root / 'work'
        self.work.mkdir()
        self.requested = '0.16.0'
        self.packages = {'domino_proxy-0.16.0-py3-none-any.whl': b'fixture wheel',
                         'domino_proxy-0.16.0.tar.gz': b'fixture sdist'}
        for name, data in self.packages.items():
            (self.release / name).write_bytes(data)
        self.package_sums = {name: hashlib.sha256(data).hexdigest() for name, data in self.packages.items()}
        (self.release / 'PYPI-SHA256SUMS').write_text(''.join(digest + '  ' + name + '\n'
            for name, digest in self.package_sums.items()))
        shutil.copytree(self.release, self.work / 'release')
        prepare_channels.prepare(self.work / 'release', self.work / 'channels',
                                 apt_repo='KJaebye/domino', apt_url='https://kjaebye.github.io/domino/apt/')
        self.plan = {'schema': 1, 'version': self.requested, 'source_sha': 'a' * 40,
                     'repository': 'KJaebye/domino', 'tap_repository': 'KJaebye/homebrew-tap',
                     'apt_repository': 'KJaebye/domino-apt',
                     'apt_url': 'https://kjaebye.github.io/domino/apt/', 'existing_release': True,
                     'pypi_files': self.package_sums,
                     'files': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                               for p in (self.work / 'release').iterdir()}}
        release.write_json(self.work / 'plan.json', self.plan)
        self.environment = patch.dict(os.environ, {}, clear=False)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        for name in ['GITHUB_OUTPUT', 'GITHUB_STEP_SUMMARY', 'APT_GPG_PRIVATE_KEY',
                     'APT_GPG_PASSPHRASE', 'APT_GPG_FINGERPRINT', 'RELEASE_TAP_SSH_KEY']:
            os.environ.pop(name, None)

    def pypi_response(self, missing=(), conflict=None):
        return json.dumps({'urls': [{'filename': name, 'digests': {'sha256': '0' * 64 if name == conflict else digest}}
                                    for name, digest in self.package_sums.items() if name not in missing]}).encode()

    def test_pypi_resume_skips_matching_files_and_uploads_only_the_missing_file(self):
        first = next(iter(self.packages))
        with patch.object(release, 'fetch', return_value=self.pypi_response(missing=[first])):
            self.assertEqual(release.stage_pypi(self.work), [first])
        self.assertEqual({p.name for p in (self.work / 'pypi-upload').iterdir()}, {first})
        self.assertEqual((self.work / 'pypi-upload' / first).read_bytes(), self.packages[first])

    def test_pypi_already_published_needs_no_credentials_or_upload(self):
        output = self.root / 'outputs'
        os.environ['GITHUB_OUTPUT'] = str(output)
        with patch.object(release, 'fetch', return_value=self.pypi_response()):
            self.assertEqual(release.stage_pypi(self.work), [])
            release.verify_pypi(self.work)
        self.assertEqual(output.read_text(), 'needed=false\n')
        self.assertFalse(list((self.work / 'pypi-upload').iterdir()))

    def test_pypi_content_conflict_fails_before_upload_staging(self):
        with patch.object(release, 'fetch', return_value=self.pypi_response(conflict=next(iter(self.packages)))):
            with self.assertRaisesRegex(ValueError, 'conflicts'):
                release.stage_pypi(self.work)
        self.assertFalse((self.work / 'pypi-upload').exists())

    def test_local_pypi_uses_twine_only_for_missing_files_without_a_plaintext_config(self):
        missing = next(iter(self.packages))
        with patch.object(release, 'fetch', return_value=self.pypi_response(missing=[missing])), \
                patch.object(release.subprocess, 'run') as command, patch.object(release, 'verify_pypi') as verify, \
                patch.object(release, 'keychain_password', return_value='disposable-test-token'):
            release.publish_pypi_local(self.work)
        args = command.call_args.args[0]
        self.assertEqual(args[:4], [release.sys.executable, '-m', 'twine', 'upload'])
        self.assertEqual(args[args.index('--config-file') + 1], os.devnull)
        self.assertEqual(args[-1], str(self.work / 'pypi-upload' / missing))
        self.assertNotIn('--skip-existing', args)
        self.assertNotIn('disposable-test-token', str(args))
        self.assertEqual(command.call_args.kwargs['env']['TWINE_PASSWORD'], 'disposable-test-token')
        verify.assert_called_once_with(self.work, install=True)

    def test_local_pypi_already_published_never_calls_twine(self):
        with patch.object(release, 'fetch', return_value=self.pypi_response()), \
                patch.object(release.subprocess, 'run') as command, patch.object(release, 'verify_pypi'):
            release.publish_pypi_local(self.work)
        command.assert_not_called()

    def test_local_apt_credentials_use_keychain_and_restore_the_environment(self):
        directory = self.root / 'local-credentials'
        directory.mkdir(mode=0o700)
        (directory / 'gnupg').mkdir(mode=0o700)
        release.write_json(directory / 'state.json', {'keychain_service': 'test-service',
            'keychain_username': 'test-user', 'apt_fingerprint': 'A' * 40})
        before = dict(os.environ)
        with patch.object(release, 'keychain_password', return_value='disposable passphrase') as keychain, \
                patch.object(release.subprocess, 'run'):
            with release.local_credentials(directory, 'apt'):
                self.assertEqual(Path(os.environ['GNUPGHOME']).resolve(), (directory / 'gnupg').resolve())
                self.assertEqual(os.environ['APT_GPG_PASSPHRASE'], 'disposable passphrase')
                self.assertNotIn('APT_GPG_PRIVATE_KEY', os.environ)
            keychain.assert_called_once_with('test-service', 'test-user')
        self.assertEqual(dict(os.environ), before)

    def test_local_credentials_reject_a_directory_readable_by_other_users(self):
        directory = self.root / 'unsafe-credentials'
        directory.mkdir(mode=0o755)
        directory.chmod(0o755)
        with self.assertRaisesRegex(ValueError, '0700'):
            with release.local_credentials(directory, 'brew'):
                self.fail('insecure directory accepted')

    def test_apt_publisher_refuses_private_paths_before_starting_git(self):
        source = self.work / 'pages/apt'
        source.mkdir(parents=True)
        release.write_json(source / 'channel.json', {'files': {'private.key': '0' * 64}})
        with patch.object(release.subprocess, 'run') as command:
            with self.assertRaisesRegex(ValueError, 'Only public APT'):
                release.publish_apt_git(self.work)
        command.assert_not_called()

    def test_git_api_publication_is_atomic_preserves_the_base_tree_and_deduplicates_blobs(self):
        data = b'Public apt index\n'
        digest = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        replies = [{'object': {'sha': 'old-commit'}}, {'tree': {'sha': 'old-tree'}},
                   {'tree': [{'path': 'existing-file', 'sha': 'old-blob', 'type': 'blob'}]},
                   {'sha': digest}, {'sha': 'new-tree'}, {'sha': 'new-commit'}, {}]
        with patch.object(release, 'api', side_effect=replies) as requests:
            result = release.publish_git_files('KJaebye/domino-apt', {'index-a': data, 'index-b': data}, 'Publish test')
        self.assertEqual(result, 'new-commit')
        calls = requests.call_args_list
        self.assertEqual(len([call for call in calls if call.args[0].endswith('/git/blobs')]), 1)
        self.assertEqual(calls[-3].kwargs['data']['base_tree'], 'old-tree')
        self.assertEqual(calls[-2].kwargs['data']['parents'], ['old-commit'])
        self.assertEqual(calls[-1].kwargs['method'], 'PATCH')
        self.assertEqual(calls[-1].kwargs['data'], {'sha': 'new-commit', 'force': False})

    def test_modified_prepared_formula_is_rejected(self):
        (self.work / 'channels/tap/Formula/domino.rb').write_text('tampered')
        with self.assertRaisesRegex(ValueError, 'channel materials changed'):
            release.validate_inputs(self.work)

    def test_https_downgrade_is_rejected_before_reading_public_key_or_metadata(self):
        with patch.object(release, 'urlopen') as request:
            response = request.return_value.__enter__.return_value
            response.url = 'http://example.invalid/apt/domino.sources'
            with self.assertRaisesRegex(RuntimeError, 'outside HTTPS'):
                release.fetch('https://example.invalid/apt/domino.sources')
            response.read.assert_not_called()

    def test_github_resume_reuses_matching_draft_assets_without_clobbering(self):
        items = [{'name': name, 'digest': 'sha256:' + digest} for name, digest in self.plan['files'].items()]
        with patch.object(release, 'api', side_effect=[{'draft': True, 'assets': items[:1]}, {'assets': items}]), \
                patch.object(release.subprocess, 'run') as command:
            release.publish_github(self.work)
        calls = [call.args[0] for call in command.call_args_list]
        self.assertEqual([args[2] for args in calls], ['upload', 'edit'])
        self.assertNotIn('--clobber', str(calls))
        self.assertNotIn(str(self.work / 'release' / items[0]['name']), calls[0])

    def test_github_release_conflict_never_writes_remote_files(self):
        name = next(iter(self.plan['files']))
        with patch.object(release, 'api', return_value={'draft': False, 'assets': [{'name': name, 'digest': 'sha256:' + '0' * 64}]}), \
                patch.object(release.subprocess, 'run') as command:
            with self.assertRaisesRegex(ValueError, 'conflicts'):
                release.publish_github(self.work)
        command.assert_not_called()

    def test_existing_github_release_is_verified_without_publishing(self):
        assets = [{'name': name, 'digest': 'sha256:' + digest} for name, digest in self.plan['files'].items()]
        with patch.object(release, 'api', return_value={'draft': False, 'assets': assets}), \
                patch.object(release.subprocess, 'run') as command:
            release.publish_github(self.work)
        command.assert_not_called()

    def test_tag_resolution_pins_annotated_tag_and_rejects_version_injection(self):
        target = self.root / 'resolve'
        replies = [{'object': {'type': 'tag', 'sha': 'b' * 40}},
                   {'object': {'type': 'commit', 'sha': 'a' * 40}}, None]
        with patch.object(release, 'api', side_effect=replies):
            plan = release.resolve(target, 'KJaebye/domino', '1.2.3')
        self.assertEqual(plan['source_sha'], 'a' * 40)
        self.assertFalse(plan['existing_release'])
        with patch.object(release, 'api') as remote:
            for value in ['1.2.3\ninjection', '$(false)', 'v1.2.3', '../1.2.3']:
                with self.assertRaises(ValueError):
                    release.resolve(target, 'KJaebye/domino', value)
        remote.assert_not_called()

    def test_partial_failure_is_recorded_without_claiming_complete(self):
        results = {'prepare': 'success', 'github': 'success', 'pypi': 'success', 'brew': 'success', 'apt': 'failure'}
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            release.summary(self.work, results, 'all', False)
        state = json.loads((self.work / 'release-status.json').read_text())
        self.assertEqual(state['channels'], {'pypi': 'verified', 'brew': 'verified', 'apt': 'failed'})
        self.assertFalse(state['complete'])

    def test_dry_run_and_single_channel_resume_have_distinct_results(self):
        result = release.summary(self.work, {'prepare': 'success'}, 'all', True)
        self.assertFalse(result['complete'])
        self.assertEqual(set(result['channels'].values()), {'checked'})
        result = release.summary(self.work, {'prepare': 'success', 'apt': 'success'}, 'apt', False)
        self.assertEqual(result['channels'], {'apt': 'verified'})
        self.assertFalse(result['complete'])
        self.assertTrue(result['request_complete'])

    def test_prepare_failure_still_produces_a_failure_report(self):
        empty = self.root / 'empty'
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            release.summary(empty, {'prepare': 'failure', 'apt': 'skipped'}, 'all', False)
        state = json.loads((empty / 'release-status.json').read_text())
        self.assertEqual(set(state['channels'].values()), {'blocked'})
        self.assertFalse(state['complete'])

    def test_homebrew_downgrade_never_commits_or_pushes(self):
        def git_clone(command, **kwargs):
            self.assertEqual(command[:2], ['git', 'clone'])
            destination = Path(command[-1])
            (destination / 'Formula').mkdir(parents=True)
            (destination / 'Formula/domino.rb').write_text('class Domino < Formula\n  version "1.0.0"\nend\n')
        os.environ['GH_TOKEN'] = 'test-credential'
        with patch.object(release.subprocess, 'run', side_effect=git_clone) as commands:
            with self.assertRaisesRegex(ValueError, 'downgrade'):
                release.publish_brew(self.work)
        self.assertEqual(commands.call_count, 1)

    def test_tap_deploy_key_is_scoped_to_temporary_files_and_pinned_host_keys(self):
        os.environ['RELEASE_TAP_SSH_KEY'] = 'disposable synthetic key\n'
        with patch.object(release, 'api', return_value={'ssh_keys': ['ssh-ed25519 QUJD']}):
            with release.tap_credentials() as (env, ssh):
                self.assertTrue(ssh)
                self.assertNotIn('RELEASE_TAP_SSH_KEY', env)
                self.assertNotIn('GH_TOKEN', env)
                args = release.shlex.split(env['GIT_SSH_COMMAND'])
                key = Path(args[args.index('-i') + 1])
                self.assertEqual(key.stat().st_mode & 0o777, 0o600)
                self.assertIn('StrictHostKeyChecking=yes', env['GIT_SSH_COMMAND'])
        self.assertFalse(key.exists())

    def test_tap_key_from_a_trimmed_secret_can_be_loaded_by_openssh(self):
        if not shutil.which('ssh-keygen'):
            self.skipTest('OpenSSH tooling unavailable')
        original = self.root / 'disposable-ssh-key'
        subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(original)],
                       check=True, capture_output=True)
        os.environ['RELEASE_TAP_SSH_KEY'] = original.read_text().strip().replace('\n', '\r\n')
        with patch.object(release, 'api', return_value={'ssh_keys': ['ssh-ed25519 QUJD']}):
            with release.tap_credentials() as (env, ssh):
                args = release.shlex.split(env['GIT_SSH_COMMAND'])
                private = Path(args[args.index('-i') + 1])
                loaded = subprocess.run(['ssh-keygen', '-y', '-f', str(private)], check=True, capture_output=True)
                self.assertTrue(loaded.stdout.startswith(b'ssh-ed25519 '))
        self.assertFalse(private.exists())

    def test_apt_downgrade_or_unrecognized_source_is_rejected(self):
        old = {'schema': 1, 'repository': 'KJaebye/domino', 'version': '1.0.0'}
        with patch.object(release, 'fetch', return_value=json.dumps(old).encode()):
            with self.assertRaisesRegex(ValueError, 'downgrade'):
                release.apt_state(self.plan)
        with patch.object(release, 'fetch', side_effect=[None, b'signed source']):
            with self.assertRaisesRegex(ValueError, 'no channel state'):
                release.apt_state(self.plan)

    def test_signed_apt_roundtrip_preserves_old_pool_and_pins_both_key_forms(self):
        if not shutil.which('gpg') or not shutil.which('gpgv'):
            self.skipTest('GPG tooling unavailable')
        home = self.root / 'keys'
        home.mkdir(mode=0o700)
        password = 'disposable test passphrase'
        with patch.dict(os.environ, GNUPGHOME=str(home)):
            subprocess.run(['gpg', '--batch', '--pinentry-mode', 'loopback', '--passphrase-fd', '0',
                            '--quick-generate-key', 'Domino workflow test <test@example.invalid>', 'ed25519', 'sign', '1d'],
                           input=(password + '\n').encode(), check=True, capture_output=True)
            self.addCleanup(subprocess.run, ['gpgconf', '--homedir', str(home), '--kill', 'gpg-agent'], capture_output=True)
            listing = subprocess.check_output(['gpg', '--with-colons', '--list-secret-keys'], text=True, stderr=subprocess.DEVNULL)
            fingerprint = next(line.split(':')[9] for line in listing.splitlines() if line.startswith('fpr:'))
            private = subprocess.run(['gpg', '--batch', '--pinentry-mode', 'loopback', '--passphrase-fd', '0',
                                      '--armor', '--export-secret-keys', fingerprint], input=password + '\n',
                                     check=True, capture_output=True, text=True).stdout
        old_package = b'!<arch>\nprevious-package'
        old_name = 'pool/main/d/domino-proxy/domino-proxy_0.15.0-1_all.deb'
        previous = {'schema': 1, 'repository': self.plan['repository'], 'version': '0.15.0',
                    'signing_fingerprint': fingerprint, 'files': {old_name: hashlib.sha256(old_package).hexdigest()}}
        os.environ.update(APT_GPG_PRIVATE_KEY=private, APT_GPG_PASSPHRASE=password, APT_GPG_FINGERPRINT=fingerprint)
        def old_site(url, **kwargs):
            return old_package if url.endswith(old_name) else json.dumps(previous).encode()
        with patch.object(release, 'fetch', side_effect=old_site):
            release.prepare_apt(self.work)
        site = self.work / 'pages/apt'
        self.assertEqual((site / old_name).read_bytes(), old_package)
        self.assertFalse(any(b'PRIVATE KEY BLOCK' in path.read_bytes() for path in site.rglob('*') if path.is_file()))
        os.environ.pop('APT_GPG_PRIVATE_KEY')
        def live_site(url, **kwargs):
            return (site / url.removeprefix(self.plan['apt_url'])).read_bytes()
        with patch.object(release, 'fetch', side_effect=live_site):
            release.verify_apt(self.work)
            with patch.object(release, 'signing_home') as signer:
                release.prepare_apt(self.work)
                signer.assert_not_called()
        # Even if an attacker rewrites the unsigned state, a different embedded
        # key cannot be trusted by the actual apt invocation.
        source = site / 'domino.sources'
        source.write_text(source.read_text().replace('Signed-By:', 'Trusted: yes\nSigned-By:'))
        state = json.loads((site / 'channel.json').read_text())
        state['files']['domino.sources'] = hashlib.sha256(source.read_bytes()).hexdigest()
        release.write_json(site / 'channel.json', state)
        with patch.object(release, 'fetch', side_effect=live_site):
            with self.assertRaisesRegex(ValueError, 'source fields differ'):
                release.verify_apt(self.work)

    def test_actions_are_optional_read_only_checks_without_publishing_credentials(self):
        import yaml
        root = Path(__file__).resolve().parents[1]
        path = root / '.github/workflows/release.yml'
        workflow = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
        self.assertEqual(workflow['concurrency']['cancel-in-progress'], 'false')
        self.assertEqual(set(workflow['on']), {'workflow_dispatch'})
        self.assertEqual(set(workflow['jobs']), {'tooling', 'installation'})
        self.assertFalse((root / '.github/workflows/publish-pypi.yml').exists())
        self.assertEqual(workflow['permissions'], {'contents': 'read'})
        self.assertNotIn('secrets.', path.read_text())
        self.assertNotIn('id-token:', path.read_text())
        self.assertNotIn('pypa/gh-action-pypi-publish@', path.read_text())
