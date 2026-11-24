import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts import candidate_release, release_channels as release


class FileCredentialTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.root.chmod(0o700)

    def secret(self, name, value):
        path = self.root / name
        path.write_text(value)
        path.chmod(0o600)
        return path

    def test_txt_values_are_read_without_stripping_password_spaces(self):
        self.secret(release.APT_PASSPHRASE_FILE, ' passphrase with spaces \n')
        self.assertEqual(release.credential_text(self.root, release.APT_PASSPHRASE_FILE), ' passphrase with spaces ')
        self.secret(release.PYPI_TOKEN_FILE, 'PyPI upload token:\npypi-disposable-test-token\n')
        self.assertEqual(release.credential_text(self.root, release.PYPI_TOKEN_FILE), 'pypi-disposable-test-token')

    def test_unsafe_file_is_rejected_before_its_value_is_read(self):
        path = self.secret(release.PYPI_TOKEN_FILE, 'pypi-private-value')
        path.chmod(0o644)
        with patch.object(Path, 'read_text', side_effect=AssertionError('must not read')):
            with self.assertRaisesRegex(ValueError, '0600'):
                release.credential_text(self.root, release.PYPI_TOKEN_FILE)

    def test_credential_symlink_is_rejected(self):
        target = self.secret('other.txt', 'pypi-private-value')
        (self.root / release.PYPI_TOKEN_FILE).symlink_to(target)
        with self.assertRaisesRegex(ValueError, 'regular files'):
            release.credential_text(self.root, release.PYPI_TOKEN_FILE)

    def test_ambiguous_token_error_contains_no_token_values(self):
        self.secret(release.PYPI_TOKEN_FILE, 'pypi-private-one\npypi-private-two\n')
        with self.assertRaises(ValueError) as error:
            release.credential_text(self.root, release.PYPI_TOKEN_FILE)
        self.assertNotIn('pypi-private', str(error.exception))

    def test_repository_credential_directory_is_rejected(self):
        with patch.object(release.prepare_channels, 'ROOT', self.root):
            with self.assertRaisesRegex(ValueError, 'outside the repository'):
                release.credential_directory(self.root)

    def test_doctor_uses_only_public_config_and_credential_metadata(self):
        fingerprint = '61ADCFADCDBE96102419F2797501FC6C688FCF00'
        grip = 'A' * 40
        self.secret('state.json', json.dumps({'apt_fingerprint': fingerprint}))
        self.secret(release.PYPI_TOKEN_FILE, 'pypi-disposable')
        self.secret(release.APT_PASSPHRASE_FILE, 'disposable passphrase')
        home = self.root / 'gnupg/private-keys-v1.d'
        home.mkdir(parents=True, mode=0o700)
        (home.parent).chmod(0o700)
        key = home / (grip + '.key')
        key.write_bytes(b'encrypted fixture')
        key.chmod(0o600)
        listing = f'fpr:::::::::{fingerprint}:\ngrp:::::::::{grip}:\n'
        original = Path.read_text
        def read(path, *args, **kwargs):
            if path.name in (release.PYPI_TOKEN_FILE, release.APT_PASSPHRASE_FILE):
                raise AssertionError('doctor must not read secret values')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'read_text', read), \
             patch.object(candidate_release.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, listing)), \
             patch.object(candidate_release.shutil, 'which', return_value='/gpg'):
            report = candidate_release.doctor(self.root)
        self.assertTrue(report['publication_credentials_ready'])
        self.assertFalse(report['production_secrets_read'])
        self.assertEqual(report['credential_storage'], 'text-files')

    def test_signing_failure_removes_temporary_keys_and_restores_environment(self):
        self.secret('state.json', json.dumps({'apt_fingerprint': 'A' * 40}))
        self.secret(release.APT_PASSPHRASE_FILE, 'disposable passphrase')
        (self.root / 'gnupg').mkdir(mode=0o700)
        before = dict(os.environ)
        with patch.object(release.subprocess, 'run'):
            with self.assertRaisesRegex(RuntimeError, 'signing failed'):
                with release.local_credentials(self.root, 'apt'):
                    temporary_home = Path(os.environ['GNUPGHOME'])
                    raise RuntimeError('signing failed')
        self.assertFalse(temporary_home.exists())
        self.assertEqual(dict(os.environ), before)
