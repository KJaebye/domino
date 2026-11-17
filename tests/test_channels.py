import hashlib
import os
import shutil
import subprocess
from unittest.mock import patch

from scripts import prepare_channels as channels
from tests.test_distribution import DistributionFixture


class ChannelTests(DistributionFixture):
    def test_preview_pins_public_release_and_cannot_be_used_as_an_unsigned_source(self):
        report = channels.prepare(self.release, self.output)
        formula = (self.output / 'tap/Formula/domino.rb').read_text()
        self.assertIn('https://github.com/KJaebye/domino/releases/download/v0.16.0/' + self.runtime.name, formula)
        self.assertIn(hashlib.sha256(self.runtime.read_bytes()).hexdigest(), formula)
        self.assertFalse(report['apt_signed'])
        self.assertIsNone(report['signing_fingerprint'])
        self.assertFalse((self.output / 'apt-site/domino.sources').exists())
        self.assertIn('unsigned preview', (self.output / 'apt-site/README.md').read_text())
        for name, digest in report['files'].items():
            self.assertEqual(hashlib.sha256((self.output / name).read_bytes()).hexdigest(), digest)
        with self.assertRaises(FileExistsError):
            channels.prepare(self.release, self.output)

    def test_invalid_repository_or_signing_key_is_rejected_before_output(self):
        for kwargs in [dict(release_repo='../private'), dict(tap_repo='owner/wrong'),
                       dict(apt_repo='owner/repo\ninjection'), dict(sign_key='--list-secret-keys')]:
            with self.assertRaises(ValueError):
                channels.prepare(self.release, self.output, **kwargs)
            self.assertFalse(self.output.exists())

    def test_failed_channel_signing_leaves_no_partial_output(self):
        with patch.object(channels, 'fingerprint', return_value='A' * 40), \
                patch.object(channels.build_distribution, 'sign_repository', side_effect=RuntimeError('failed')):
            with self.assertRaisesRegex(RuntimeError, 'failed'):
                channels.prepare(self.release, self.output, sign_key='A' * 40)
        self.assertFalse(self.output.exists())
        self.assertFalse(list(self.root.glob('.domino-channels-*')))

    def test_signed_site_has_verifiable_metadata_and_embedded_public_key(self):
        if not shutil.which('gpg'):
            self.skipTest('gpg not available')
        home = self.root / 'gnupg'
        home.mkdir(mode=0o700)
        with patch.dict(os.environ, GNUPGHOME=str(home)):
            subprocess.run(['gpg', '--batch', '--pinentry-mode', 'loopback', '--passphrase', '',
                            '--quick-generate-key', 'Domino test <test@example.invalid>', 'ed25519', 'sign', '1d'],
                           check=True, capture_output=True)
            self.addCleanup(subprocess.run, ['gpgconf', '--homedir', str(home), '--kill', 'gpg-agent'], capture_output=True)
            listing = subprocess.check_output(['gpg', '--batch', '--with-colons', '--list-secret-keys'], text=True, stderr=subprocess.DEVNULL)
            key = next(line.split(':')[9] for line in listing.splitlines() if line.startswith('fpr:'))
            report = channels.prepare(self.release, self.output, sign_key=key)
        site = self.output / 'apt-site'
        sources = (site / 'domino.sources').read_text()
        self.assertTrue(report['apt_signed'])
        self.assertEqual(report['signing_fingerprint'], key)
        self.assertIn('URIs: https://kjaebye.github.io/domino-apt/\n', sources)
        self.assertIn('\nSigned-By:\n -----BEGIN PGP PUBLIC KEY BLOCK-----\n .\n', sources)
        self.assertNotIn('PRIVATE KEY', sources)
        verifier = self.root / 'verifier'
        verifier.mkdir(mode=0o700)
        subprocess.run(['gpg', '--homedir', str(verifier), '--no-default-keyring', '--keyring',
                        str(site / 'domino-archive-keyring.gpg'), '--verify',
                        str(site / 'dists/stable/InRelease')], check=True, capture_output=True)
        subprocess.run(['gpg', '--homedir', str(verifier), '--no-default-keyring', '--keyring',
                        str(site / 'domino-archive-keyring.gpg'), '--verify',
                        str(site / 'dists/stable/Release.gpg'), str(site / 'dists/stable/Release')],
                       check=True, capture_output=True)
