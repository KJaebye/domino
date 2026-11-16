from contextlib import redirect_stdout
import gzip
import hashlib
import io
import json
import importlib.metadata
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import domino_cli as tool


class BootstrapTests(unittest.TestCase):
    def test_installer_prepares_environment_without_a_subscription_or_existing_client(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            cache=root/'cache'
            cache.mkdir()
            archive=cache/'mihomo-darwin-arm64-v1.2.3.gz'
            archive.write_bytes(gzip.compress(b'FIXTURE-CORE'))
            asset={'name':archive.name,'digest':'sha256:'+hashlib.sha256(archive.read_bytes()).hexdigest()}
            args=tool.build_parser().parse_args(['init'])
            args.base_install=True
            args.target_system='darwin'
            with patch.object(Path,'home',return_value=root), patch.object(tool,'cache_dir',return_value=cache), \
                    patch.object(tool,'discover_proxy',return_value=None), patch.object(tool,'source_config') as source, \
                    patch.object(tool,'release_asset',return_value=('v1.2.3',asset)), \
                    patch.object(tool,'download',side_effect=lambda url,path,proxy:path.write_text('{}')), \
                    patch.object(tool,'copy_cli'), patch.object(tool,'run'), redirect_stdout(io.StringIO()):
                package,manifest=tool.prepare(args,'arm64',root)
            source.assert_not_called()
            self.assertTrue(manifest['awaiting_subscription'])
            with tarfile.open(package) as bundle:
                config=json.load(bundle.extractfile('data/config.json'))
            self.assertEqual(config['proxies'],[])
            self.assertEqual(config['rules'],['MATCH,REJECT'])
            self.assertEqual(config['mixed-port'],17897)
            self.assertEqual(config['external-controller'],'127.0.0.1:19091')
            self.assertTrue(config['secret'])

    def test_installer_chooses_empty_setup_only_when_no_configuration_is_available(self):
        import domino_install
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            with patch.object(Path,'home',return_value=root), patch.object(tool,'sys') as runtime, patch.object(tool,'initialize') as install:
                runtime.stdin.isatty.return_value=True
                runtime.platform='linux'
                self.assertEqual(domino_install.main([]),0)
                self.assertTrue(install.call_args.args[0].base_install)
                self.assertEqual(domino_install.main(['--subscription','https://example.test/config']),0)
                self.assertFalse(install.call_args.args[0].base_install)
                path=root/'.local/share/domino/data/config.json'
                path.parent.mkdir(parents=True)
                path.write_text('{}')
                self.assertEqual(domino_install.main([]),0)
                self.assertFalse(install.call_args.args[0].base_install)

    def test_linux_noninteractive_installer_requires_explicit_batch(self):
        import domino_install
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(Path,'home',return_value=Path(directory)), \
                    patch.object(tool.sys.stdin,'isatty',return_value=False), \
                    patch.object(tool.sys,'platform','linux'), \
                    patch.object(tool,'initialize') as install, redirect_stdout(io.StringIO()):
                self.assertEqual(domino_install.main([]),1)
                install.assert_not_called()
                self.assertEqual(domino_install.main(['--batch']),0)
                self.assertTrue(install.call_args.args[0].batch)

    def test_reinstall_of_pending_environment_preserves_ports(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            data=root/'.local/share/domino/data'
            data.mkdir(parents=True)
            (data/'config.json').write_text('{"mixed-port":17898,"external-controller":"127.0.0.1:19092","proxies":[]}')
            (data.parent/'manifest.json').write_text('{"awaiting_subscription":true}')
            args=tool.build_parser().parse_args(['init','--batch'])
            args.installing=True
            args.port_overrides=set()
            def prepared_bundle(args, arch, work):
                (work / 'bundle').mkdir()
                (work / 'bundle/manifest.json').write_text('{"schema":1}')
            with patch.object(Path,'home',return_value=root), patch.object(tool,'local_target',return_value='arm64'), \
                    patch.object(tool,'cache_dir',return_value=root), patch.object(tool,'prepare',side_effect=prepared_bundle) as prepare, \
                    patch.object(tool,'run'), redirect_stdout(io.StringIO()):
                tool.initialize(args)
            prepared=prepare.call_args.args[0]
            self.assertTrue(prepared.base_install)
            self.assertEqual(prepared.proxy_port,17898)
            self.assertEqual(prepared.api_port,19092)

    def test_repeated_init_packages_verified_installed_release_without_network(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = root / '.local/share/domino'
            app.mkdir(parents=True)
            cache = root / 'cache'
            cache.mkdir()
            binary = b'EXISTING-MIHOMO'
            archive = cache / 'mihomo-darwin-arm64-v1.2.3.gz'
            archive.write_bytes(gzip.compress(binary))
            (app / 'manifest.json').write_text(json.dumps({'platform':'darwin','arch':'arm64',
                'version':'v1.2.3','sha256_gzip':hashlib.sha256(archive.read_bytes()).hexdigest()}))
            source = root / 'config.json'
            source.write_text(json.dumps({'proxies':[{'name':'node','type':'socks5','server':'node.example','port':1080}]}))
            args = tool.build_parser().parse_args(['init','--source',str(source),'--batch'])
            args.target_system = 'darwin'
            with patch.object(Path,'home',return_value=root), patch.object(tool,'cache_dir',return_value=cache), \
                    patch.object(tool,'discover_proxy',return_value=None), patch.object(tool,'download') as download, \
                    patch.object(tool,'copy_cli'), patch.object(tool,'run'), redirect_stdout(io.StringIO()):
                package,manifest = tool.prepare(args,'arm64',root)
            download.assert_not_called()
            self.assertEqual(manifest['version'],'v1.2.3')
            with tarfile.open(package) as bundle:
                self.assertEqual(bundle.extractfile('mihomo').read(),binary)

    def test_reinstall_keeps_the_active_subscription_association_in_the_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            app=root/'.local/share/domino'
            (app/'data').mkdir(parents=True)
            source=app/'data/config.json'
            source.write_text(json.dumps({'proxies':[{'name':'node','type':'socks5','server':'node.example','port':1080}]}))
            (source.parent/'subscription.json').write_text(json.dumps({'id':'a'*32}))
            cache=root/'cache'
            cache.mkdir()
            archive=cache/'mihomo-darwin-arm64-v1.2.3.gz'
            archive.write_bytes(gzip.compress(b'EXISTING-CORE'))
            (app/'manifest.json').write_text(json.dumps({'platform':'darwin','arch':'arm64','version':'v1.2.3',
                'sha256_gzip':hashlib.sha256(archive.read_bytes()).hexdigest()}))
            args=tool.build_parser().parse_args(['init'])
            args.installing=True
            args.target_system='darwin'
            with patch.object(Path,'home',return_value=root), patch.object(tool,'cache_dir',return_value=cache), \
                    patch.object(tool,'live_selections',return_value={}), patch.object(tool,'copy_cli'), \
                    patch.object(tool,'run'), patch.object(tool,'download') as download, redirect_stdout(io.StringIO()):
                package,_=tool.prepare(args,'arm64',root)
            download.assert_not_called()
            with tarfile.open(package) as bundle:
                self.assertEqual(json.load(bundle.extractfile('data/subscription.json')),{'id':'a'*32})
                self.assertTrue(json.load(bundle.extractfile('registration.json'))['preserve_current'])

    def test_init_cache_rejects_corruption_wrong_platform_and_explicit_version(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = root / '.local/share/domino'
            app.mkdir(parents=True)
            archive = root / 'mihomo-darwin-arm64-v1.2.3.gz'
            archive.write_bytes(b'archive')
            manifest = {'platform':'darwin','arch':'arm64','version':'v1.2.3',
                        'sha256_gzip':hashlib.sha256(archive.read_bytes()).hexdigest()}
            path = app / 'manifest.json'
            path.write_text(json.dumps(manifest))
            args = tool.build_parser().parse_args(['init'])
            with patch.object(Path,'home',return_value=root):
                self.assertIsNotNone(tool.cached_init_release(args,'arm64','darwin',root))
                for arch,system in [('amd64','darwin'),('arm64','linux')]:
                    self.assertIsNone(tool.cached_init_release(args,arch,system,root))
                args.mihomo_version = 'v1.2.3'
                self.assertIsNone(tool.cached_init_release(args,'arm64','darwin',root))
                args.mihomo_version = 'latest'
                args.command = 'export'
                self.assertIsNone(tool.cached_init_release(args,'arm64','darwin',root))
                args.command = 'init'
                archive.write_bytes(b'corrupt')
                self.assertIsNone(tool.cached_init_release(args,'arm64','darwin',root))
                path.write_text('invalid json')
                self.assertIsNone(tool.cached_init_release(args,'arm64','darwin',root))

    def test_download_failure_identifies_resource_without_leaking_address(self):
        with patch.object(tool,'download',side_effect=tool.ToolError('下载失败（HTTP 403）。')):
            with self.assertRaises(tool.ToolError) as caught:
                tool.download_resource('Mihomo 版本信息（GitHub API）','https://example.test/?token=PRIVATE',Path('/tmp/unused'))
        self.assertIn('GitHub API',str(caught.exception))
        self.assertIn('HTTP 403',str(caught.exception))
        self.assertNotIn('PRIVATE',str(caught.exception))

    def test_offline_ui_dependencies_survive_cli_refresh_without_pip(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for name in ['prompt_toolkit','wcwidth','yaml']:
                package=root/'cli/_vendor'/name
                package.mkdir(parents=True)
                (package/'__init__.py').write_text('# bundled '+name)
            licenses=root/'cli/_vendor/licenses'
            licenses.mkdir()
            (licenses/'prompt_toolkit-LICENSE').write_text('MIT fixture')
            (root/'cli/old_module.py').write_text('old')
            (root/'cli/domino_clients.py').write_text('removed external proxy adapter')
            with patch.object(tool.importlib.util,'find_spec',return_value=None), \
                    patch.object(tool.importlib.metadata,'distribution',side_effect=importlib.metadata.PackageNotFoundError):
                tool.copy_cli(root)
            self.assertIn('bundled prompt_toolkit',(root/'cli/_vendor/prompt_toolkit/__init__.py').read_text())
            self.assertIn('bundled yaml',(root/'cli/_vendor/yaml/__init__.py').read_text())
            self.assertTrue((root/'cli/_vendor/licenses/prompt_toolkit-LICENSE').exists())
            self.assertFalse((root/'cli/old_module.py').exists())
            self.assertFalse((root/'cli/domino_clients.py').exists())

    def test_subscription_uses_downloaded_configuration_without_assuming_a_running_client(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = tool.build_parser().parse_args(['init', '--subscription', 'https://example.test/config?token=PRIVATE', '--batch'])
            config = {'mixed-port': 7897, 'external-controller': '127.0.0.1:9090',
                      'proxies': [{'name': 'Japan', 'type': 'socks5', 'server': 'node.example', 'port': 1080}]}
            def download(url, path, proxy, *, user_agent=None):
                self.assertEqual(user_agent,tool.SUBSCRIPTION_USER_AGENT)
                path.write_text(json.dumps(config))
            with patch.object(tool, 'cache_dir', return_value=root), patch.object(tool, 'discover_proxy', return_value=None), \
                    patch.object(tool, 'download', side_effect=download), patch.object(tool, 'run') as run:
                with tool.source_input(args) as prepared:
                    source, raw, proxy = tool.source_config(prepared)
                    self.assertEqual(source.stat().st_mode & 0o777, 0o600)
                    self.assertIsNone(proxy)
                    self.assertEqual(tool.live_selections(prepared, raw, source), {})
                    self.assertEqual(raw['proxies'][0]['server'], 'node.example')
                self.assertFalse(source.exists())
                run.assert_not_called()

    def test_init_with_local_configuration_ignores_its_client_control_and_proxy_ports(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            path.write_text(json.dumps({'mixed-port': 7897, 'external-controller': '127.0.0.1:9090',
                                        'proxies': [{'name': 'Japan', 'server': 'node.example'}]}))
            args = tool.build_parser().parse_args(['init', '--source', str(path), '--batch'])
            with patch.object(tool, 'discover_proxy', return_value=None), patch.object(tool, 'run') as run:
                source, config, proxy = tool.source_config(args)
                self.assertIsNone(proxy)
                self.assertEqual(tool.live_selections(args, config, source), {})
                run.assert_not_called()

    def create_bundle(self, root):
        contents = root / 'contents'
        (contents / 'data').mkdir(parents=True)
        (contents / 'mihomo').write_bytes(b'SYNTHETIC-BINARY')
        (contents / 'manifest.json').write_text(json.dumps({'schema': 1, 'arch': 'arm64', 'shell_env': True, 'non_interactive': False}))
        (contents / 'data/config.json').write_text('{}')
        (contents / 'selections.json').write_text('{}')
        (contents / 'install_domino.py').write_text('raise RuntimeError("do not run an archive supplied installer")')
        archive = root / 'device.tar.gz'
        with tarfile.open(archive, 'w:gz') as package:
            for path in contents.iterdir():
                package.add(path, arcname=path.name)
        return archive

    def test_offline_initialization_never_downloads_or_opens_ssh_and_uses_current_installer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = self.create_bundle(root)
            def install(command, **options):
                self.assertEqual(command[:3], [tool.sys.executable, str(tool.REMOTE_SCRIPT), 'install'])
                bundle = Path(command[3])
                manifest = json.loads((bundle / 'manifest.json').read_text())
                self.assertTrue(manifest['non_interactive'])
                self.assertFalse(manifest['shell_env'])
                self.assertEqual((bundle / 'mihomo').stat().st_mode & 0o777, 0o755)
                self.assertEqual((bundle / 'data/config.json').stat().st_mode & 0o777, 0o600)
                self.assertEqual((bundle / 'cli/domino_cli.py').read_bytes(), Path(tool.__file__).read_bytes())
            with patch.object(tool, 'local_target', return_value='arm64'), patch.object(tool, 'cache_dir', return_value=root), \
                    patch.object(tool, 'download') as download, patch.object(tool, 'SSH') as ssh, \
                    patch.object(tool, 'run', side_effect=install), redirect_stdout(io.StringIO()):
                self.assertEqual(tool.main(['init', '--bundle', str(archive), '--batch', '--no-shell-env']), 0)
            download.assert_not_called()
            ssh.assert_not_called()

    def test_init_rejects_conflicting_inputs_before_installation(self):
        args = tool.build_parser().parse_args(['init', '--bundle', '/tmp/package', '--source', '/tmp/config', '--batch'])
        with patch.object(tool, 'local_target') as local, patch.object(tool, 'run') as run, self.assertRaises(tool.ToolError):
            tool.initialize(args)
        local.assert_not_called()
        run.assert_not_called()

    def test_offline_bundle_rejects_traversal_links_and_special_files(self):
        cases = [('escape', '../outside', tarfile.REGTYPE), ('absolute', '/tmp/outside', tarfile.REGTYPE),
                 ('symlink', 'link', tarfile.SYMTYPE), ('hardlink', 'link', tarfile.LNKTYPE),
                 ('device', 'device', tarfile.CHRTYPE)]
        for label, name, kind in cases:
            with self.subTest(kind=label), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                archive = root / 'bad.tar.gz'
                with tarfile.open(archive, 'w:gz') as package:
                    entry = tarfile.TarInfo(name)
                    entry.type = kind
                    entry.linkname = '../outside'
                    package.addfile(entry)
                target = root / 'unpack'
                target.mkdir()
                with self.assertRaises(tool.ToolError):
                    tool.unpack_bundle(archive, target)
                self.assertFalse((root / 'outside').exists())


if __name__ == '__main__':
    unittest.main()
