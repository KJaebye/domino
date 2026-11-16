"""Source delivery integration tests; never install, contact services, or use real HOME."""
import ast
from tests.source_assertions import executable_tree
import base64
import bz2
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import copy
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import shlex
import shutil
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import domino_cli as tool
import domino_sources as sources


class SourceDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.home = Path(self.stack.enter_context(tempfile.TemporaryDirectory())).resolve()
        self.stack.enter_context(patch.object(Path, 'home', return_value=self.home))
        self.stack.enter_context(patch.dict(os.environ, {'HOME': str(self.home)}))
        self.stdout = self.stack.enter_context(redirect_stdout(io.StringIO()))
        self.stderr = self.stack.enter_context(redirect_stderr(io.StringIO()))
        self.stack.enter_context(patch.object(tool.sys.stdin, 'isatty', return_value=True))
        self.install = self.stack.enter_context(patch.object(tool, 'initialize'))
        self.run = self.stack.enter_context(patch.object(tool, 'run', return_value=SimpleNamespace(stdout='{}')))
        self.download = self.stack.enter_context(patch.object(
            tool, 'download_resource', side_effect=AssertionError('Unexpected resource download')))
        self.live = self.stack.enter_context(patch.object(tool, 'live_selections', return_value={}))
        self.stack.enter_context(patch.object(tool, 'discover_proxy', return_value=None))
        self.stack.enter_context(patch.object(tool, 'discover_sources', return_value=[]))
        self.stack.enter_context(patch.object(tool, 'copy_cli'))
        self.cache = self.home / 'cache'
        self.cache.mkdir()
        archive = self.cache / 'mihomo-darwin-arm64-v1.2.3.gz'
        self.binary = b'TEST-ONLY-NOT-EXECUTABLE'
        archive.write_bytes(gzip.compress(self.binary))
        asset = {'name': archive.name, 'digest': 'sha256:' + hashlib.sha256(archive.read_bytes()).hexdigest()}
        self.stack.enter_context(patch.object(tool, 'cache_dir', return_value=self.cache))
        self.stack.enter_context(patch.object(tool, 'cached_init_release', return_value=('v1.2.3', asset)))
        self.raw = {
            'mode': 'rule', 'mixed-port': 7897, 'external-controller': '127.0.0.1:9090',
            'secret': 'SOURCE-CONTROLLER-PRIVATE', 'tun': {'enable': True},
            'proxies': [self.node('original'), self.node('second')],
            'proxy-groups': [{'name': 'Choice', 'type': 'select', 'proxies': ['original', 'second']}],
            'rules': ['MATCH,Choice'],
        }
        self.source = self.write('external/config.json', self.raw)

    @staticmethod
    def node(name):
        return {'name': name, 'type': 'ss', 'server': 'node.example.test', 'port': 443,
                'cipher': 'aes-128-gcm', 'password': 'NODE-PRIVATE-CREDENTIAL'}

    def write(self, relative, value):
        path = self.home / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))
        return path

    def args(self, *options):
        args = tool.build_parser().parse_args(['export', '--arch', 'arm64', '--output', 'unused.tar.gz', *options])
        args.target_system = 'darwin'
        return args

    def prepare(self, args, name='work', *, within_catch=False):
        # Do not inspect or select an installed application binary on the host.
        if not args.core:
            args.core = str(self.home / 'nonexistent-test-core')
        work = self.home / name
        work.mkdir()
        package, manifest = tool.prepare(args, 'arm64', work)
        with tarfile.open(package) as archive:
            members = {member.name: archive.extractfile(member).read()
                       for member in archive.getmembers() if member.isfile()}
        self.assertEqual(members['mihomo'], self.binary)
        self.assertEqual(package.stat().st_mode & 0o777, 0o600)
        self.assertFalse(manifest['requires_source_online'])
        if not within_catch:
            self.install.assert_not_called()
        return work / 'bundle', members, manifest

    def test_explicit_file_delivery_keeps_pre_sanitize_source_and_private_envelope(self):
        self.live.return_value = {'Choice': 'second'}
        core = self.home / 'fixture-core'
        core.write_bytes(b'NOT-EXECUTABLE')
        args = self.args('--source', str(self.source), '--core', str(core))
        bundle, members, _ = self.prepare(args)
        original, metadata = sources.read_source(bundle / 'data/source')
        runtime = json.loads(members['data/config.json'])
        self.assertEqual(original, self.raw)
        self.assertEqual(metadata['capture_kind'], 'file')
        self.assertEqual(metadata['original_path'], str(self.source))
        self.assertEqual(json.loads(members['registration.json']), {'version': 1, 'kind': 'snapshot'})
        self.assertEqual(json.loads(members['selections.json']), {'Choice': 'second'})
        self.assertEqual(runtime['proxy-groups'][0]['proxies'], ['second', 'original'])
        self.assertFalse(runtime['tun']['enable'])
        self.assertEqual(runtime['external-controller'], '127.0.0.1:19091')
        self.assertNotEqual(runtime['secret'], self.raw['secret'])
        self.assertEqual((bundle / 'registration.json').stat().st_mode & 0o777, 0o600)
        for path in (bundle / 'data/source').rglob('*'):
            self.assertEqual(path.stat().st_mode & 0o777, 0o700 if path.is_dir() else 0o600)
        self.run.assert_called_once()
        self.assertEqual(self.run.call_args.args[0], [str(core), '-t', '-d', str(bundle / 'data'),
                                                    '-f', str(bundle / 'data/config.json')])
        self.download.assert_not_called()
        self.assertNotIn('NODE-PRIVATE-CREDENTIAL', self.stdout.getvalue() + self.stderr.getvalue())

    def test_current_runtime_reexport_keeps_original_source_but_delivers_effective_changes(self):
        current = self.write('.local/share/domino/data/config.json', self.raw)
        sources.create_source(self.raw, self.source, current.parent / 'source')
        source_bytes = {p.relative_to(current.parent / 'source'): p.read_bytes()
                        for p in (current.parent / 'source').rglob('*') if p.is_file()}
        effective = copy.deepcopy(self.raw)
        effective['proxies'].append(self.node('added-after-import'))
        effective['rules'].insert(0, 'DOMAIN,edited.example.test,DIRECT')
        current.write_text(json.dumps(effective))
        foreign_id = 'a' * 32
        private_url = 'https://subscription.example.test/config?token=FOREIGN-URL-SECRET'
        self.write('.local/share/domino/data/subscription.json', {'id': foreign_id})
        registry = self.write('.config/domino/subscriptions/index.json',
                              {'schema': 1, 'items': [{'id': foreign_id, 'name': 'Foreign online',
                                                       'kind': 'subscription', 'url': private_url}]})
        registry_before = registry.read_bytes()
        self.live.return_value = {'Choice': 'second'}
        bundle, members, _ = self.prepare(self.args('--source', str(current)))
        runtime = json.loads(members['data/config.json'])
        self.assertEqual(runtime['rules'], effective['rules'])
        self.assertEqual(runtime['proxies'], effective['proxies'])
        self.assertEqual(runtime['proxy-groups'][0]['proxies'], ['second', 'original'])
        self.assertEqual(json.loads(members['selections.json']), {'Choice': 'second'})
        self.live.assert_called_once()
        self.assertEqual(self.live.call_args.args[1], effective)
        self.assertEqual(self.live.call_args.args[2], current)
        for relative, payload in source_bytes.items():
            self.assertEqual(members['data/source/' + relative.as_posix()], payload)
        self.assertEqual(sources.read_source(bundle / 'data/source')[0], self.raw)
        self.assertEqual(json.loads(members['registration.json']), {'version': 1, 'kind': 'snapshot'})
        self.assertNotIn('data/subscription.json', members)
        self.assertFalse(any('/subscriptions/' in name for name in members))
        for payload in members.values():
            for secret in (private_url, foreign_id):
                self.assertNotIn(secret.encode(), payload)
        self.assertEqual(registry.read_bytes(), registry_before)
        self.assertEqual(json.loads((current.parent / 'subscription.json').read_text()), {'id': foreign_id})
        self.assertEqual({p.relative_to(current.parent / 'source'): p.read_bytes()
                          for p in (current.parent / 'source').rglob('*') if p.is_file()}, source_bytes)
        self.download.assert_not_called()
        self.run.assert_not_called()

    def test_online_temporary_source_survives_context_with_url_only_in_private_registration(self):
        url = 'https://subscription.example.test/config?token=EXPLICIT-URL-PRIVATE'
        downloaded = []
        def download(label, requested, destination, proxy, **kwargs):
            self.assertEqual(requested, url)
            destination.write_text(json.dumps(self.raw))
            downloaded.append(destination)
        self.download.side_effect = download
        args = tool.build_parser().parse_args(['init', '--subscription', url, '--name', 'Fixture online'])
        args.target_system = 'darwin'
        bundle, members, _ = self.prepare(args)
        self.assertEqual(len(downloaded), 1)
        self.assertFalse(downloaded[0].exists())
        original, metadata = sources.read_source(bundle / 'data/source')
        self.assertEqual(original, self.raw)
        self.assertEqual(metadata['capture_kind'], 'subscription')
        self.assertNotIn('original_path', metadata)
        self.assertEqual(json.loads(members['registration.json']),
                         {'version': 1, 'kind': 'subscription', 'url': url, 'name': 'Fixture online'})
        public = json.dumps(sources.public_info(bundle / 'data'))
        for value in (url, str(downloaded[0]), 'EXPLICIT-URL-PRIVATE', 'SOURCE-CONTROLLER-PRIVATE',
                      'NODE-PRIVATE-CREDENTIAL'):
            self.assertNotIn(value, public)
            self.assertNotIn(value, json.dumps(metadata))
        for name, payload in members.items():
            if name != 'registration.json':
                self.assertNotIn(url.encode(), payload)
                self.assertNotIn(str(downloaded[0]).encode(), payload)
        self.assertEqual((bundle / 'registration.json').stat().st_mode & 0o777, 0o600)
        self.run.assert_not_called()

    def test_export_resource_directory_option_is_carried_into_portable_bundle(self):
        resource_dir = self.home / 'shared'
        resource_dir.mkdir()
        (resource_dir / 'certificate.pem').write_text('fixture certificate')
        raw = copy.deepcopy(self.raw)
        raw['proxies'][0]['certificate'] = 'certificate.pem'
        self.source.write_text(json.dumps(raw))
        bundle, _, _ = self.prepare(self.args('--source', str(self.source), '--resource-dir', str(resource_dir)))
        shutil.rmtree(resource_dir)
        profile = tool.load_yaml(bundle / 'data/config.json')
        self.assertEqual((bundle / 'data' / profile['proxies'][0]['certificate']).read_text(), 'fixture certificate')
        self.download.assert_not_called()

    def test_provider_and_certificate_resources_are_shared_without_repeated_downloads(self):
        raw = copy.deepcopy(self.raw)
        cert = self.source.parent / 'client.pem'
        cert.write_text('TEST-ONLY-CERTIFICATE')
        raw['proxies'][0]['certificate'] = str(cert)
        inline = dict(self.node('inline-node'), certificate='client.pem')
        file_node = dict(self.node('file-node'), **{'private-key': str(cert)})
        self.write('external/file-provider.json', {'proxies': [file_node]})
        remote_url = 'https://provider.example.test/nodes?token=PROVIDER-PRIVATE'
        raw['proxy-providers'] = {
            'online': {'type': 'http', 'url': remote_url, 'interval': 3600},
            'local': {'type': 'file', 'path': 'file-provider.json'},
            'inline': {'type': 'inline', 'payload': [inline]},
        }
        self.source.write_text(json.dumps(raw))
        def download(label, requested, destination, proxy, **kwargs):
            self.assertEqual(requested, remote_url)
            destination.write_text(json.dumps({'proxies': [self.node('downloaded-node')]}))
        self.download.side_effect = download
        bundle, members, _ = self.prepare(self.args('--source', str(self.source)))
        self.download.assert_called_once()
        shutil.rmtree(self.source.parent)
        snapshot, metadata = sources.read_source(bundle / 'data/source')
        runtime = json.loads(members['data/config.json'])
        for root, config in ((bundle / 'data/source', snapshot), (bundle / 'data', runtime)):
            for name in ('online', 'local'):
                provider = config['proxy-providers'][name]
                path = Path(provider['path'])
                self.assertFalse(path.is_absolute())
                payload = tool.load_yaml(root / path)
                self.assertTrue(payload['proxies'])
                if name == 'local':
                    self.assertEqual((root / payload['proxies'][0]['private-key']).read_text(), 'TEST-ONLY-CERTIFICATE')
                self.assertEqual((root / path).stat().st_mode & 0o777, 0o600)
            self.assertEqual((root / config['proxies'][0]['certificate']).read_text(), 'TEST-ONLY-CERTIFICATE')
            inline_cert = config['proxy-providers']['inline']['payload'][0]['certificate']
            self.assertEqual((root / inline_cert).read_text(), 'TEST-ONLY-CERTIFICATE')
        self.assertEqual(snapshot['proxy-providers']['online']['path'], runtime['proxy-providers']['online']['path'])
        self.assertNotIn(str(self.source.parent), json.dumps(snapshot))
        self.assertEqual(metadata['capture_kind'], 'file')
        public = json.dumps(sources.public_info(bundle / 'data'))
        for private in (remote_url, 'PROVIDER-PRIVATE', 'NODE-PRIVATE-CREDENTIAL', str(self.source)):
            self.assertNotIn(private, public)
        self.run.assert_not_called()

    def test_catch_freezes_profile_identity_before_confirmation_changes_index(self):
        root = self.home / 'Library/Application Support/io.github.clash-verge-rev.clash-verge-rev'
        profile = self.write(str(root.relative_to(self.home) / 'profiles/approved.json'), self.raw)
        index = self.write(str(root.relative_to(self.home) / 'profiles.yaml'),
                           {'current': 'approved', 'items': [
                               {'uid': 'approved', 'name': 'Approved profile', 'file': profile.name, 'type': 'remote',
                                'url': 'https://index.example.test/config?token=INDEX-PRIVATE'}]})
        runtime_path = self.write(str(root.relative_to(self.home) / 'clash-verge.yaml'), self.raw)
        self.live.return_value = {'Choice': 'second'}
        prepared = []
        def confirm(_prompt):
            index.write_text(json.dumps({'current': 'replacement', 'items': [
                {'uid': 'replacement', 'name': 'Changed after approval', 'file': 'changed.json', 'type': 'remote'}]}))
            runtime_path.write_text('{}')
            return 'yes'
        def prepare_only(args):
            args.target_system = 'darwin'
            prepared.append(self.prepare(args, 'confirmed-work', within_catch=True))
        self.install.side_effect = prepare_only
        with patch('builtins.input', side_effect=confirm):
            args = tool.build_parser().parse_args(['catch', '--source', str(runtime_path)])
            self.assertEqual(tool.catch(args), 0)
        self.live.assert_called_once()
        self.install.assert_called_once()
        bundle, members, _ = prepared[0]
        snapshot, metadata = sources.read_source(bundle / 'data/source')
        self.assertEqual(snapshot, self.raw)
        self.assertEqual(metadata['capture_kind'], 'verge-runtime')
        self.assertEqual(metadata['profile_id'], 'approved')
        self.assertEqual(metadata['profile_name'], 'Approved profile')
        self.assertEqual(metadata['association'], 'index')
        self.assertEqual(json.loads(members['selections.json']), {'Choice': 'second'})
        self.assertEqual(json.loads(members['registration.json']), {'version': 1, 'kind': 'snapshot'})
        self.assertNotIn('INDEX-PRIVATE', json.dumps(metadata))
        self.download.assert_not_called()
        self.run.assert_not_called()

    def test_pending_base_delivery_has_no_fictional_source_or_registration(self):
        args = self.args()
        args.base_install = True
        bundle, members, manifest = self.prepare(args)
        self.assertTrue(manifest['awaiting_subscription'])
        self.assertNotIn('registration.json', members)
        self.assertNotIn('data/subscription.json', members)
        self.assertFalse(any(name.startswith('data/source/') for name in members))
        self.assertFalse((bundle / 'data/source').exists())
        self.assertEqual(json.loads(members['data/config.json'])['proxies'], [])
        self.live.assert_not_called()
        self.download.assert_not_called()
        self.run.assert_not_called()

    def test_source_helper_is_declared_for_cli_wheel_and_embedded_remote_actions(self):
        try: import tomllib
        except ModuleNotFoundError: import tomli as tomllib
        project = Path(tool.__file__).resolve().parent
        self.assertIn('domino_sources.py', tool.CLI_MODULES)
        self.assertIn('domino_client_sources.py', tool.CLI_MODULES)
        packaging = tomllib.loads((project.parent / 'pyproject.toml').read_text())
        self.assertIn('domino_sources', packaging['tool']['setuptools']['py-modules'])
        self.assertIn('domino_client_sources', packaging['tool']['setuptools']['py-modules'])
        args = tool.build_parser().parse_args(['scan'])
        args.target, args.user, args.ssh_port, args.identity, args.batch = 'fixture.example.test', None, None, None, True
        ssh = tool.SSH(args)
        ssh.socket = str(self.home / 'never-opened-control-socket')
        for action in ('scan', 'configs', 'agent', 'catch-options'):
            with self.subTest(action=action):
                command = shlex.split(ssh.action_argv(action)[-1])
                self.assertEqual(command[:2], ['python3', '-c'])
                self.assertEqual(command[-1], action)
                wrapper = ast.parse(command[2])
                encoded = next(node for node in ast.walk(wrapper)
                               if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                               and node.func.attr == 'b85decode')
                payload = bz2.decompress(base64.b85decode(ast.literal_eval(encoded.args[0]))).decode()
                tree = ast.parse(payload)
                assignment = next(node for node in tree.body if isinstance(node, ast.Assign)
                                  and any(isinstance(target, ast.Name) and target.id == '__domino_sources'
                                          for target in node.targets))
                modules = ast.literal_eval(assignment.value)
                self.assertEqual(executable_tree(modules['domino_sources']),
                                 executable_tree((project / 'domino_sources.py').read_text()))
                compile(modules['domino_sources'], '<embedded-domino-sources>', 'exec')
                self.assertEqual(executable_tree(modules['domino_client_sources']),
                                 executable_tree((project / 'domino_client_sources.py').read_text()))
        self.run.assert_not_called()
        self.download.assert_not_called()


if __name__ == '__main__':
    unittest.main()
