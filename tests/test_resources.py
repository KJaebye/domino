import hashlib
import gzip
import io
from contextlib import redirect_stdout
import json
from pathlib import Path
import tempfile
import subprocess
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import domino_resources as resources
import domino_cli as cli
from domino_model import DomainError


class ResourceSourceTests(unittest.TestCase):
    def test_macos_intel_requires_explicit_v1_instead_of_generic_or_v3(self):
        tag = 'v1.19.33'
        names = ['mihomo-darwin-amd64-' + tag + '.gz',
                 'mihomo-darwin-amd64-v3-' + tag + '.gz',
                 'mihomo-darwin-amd64-v1-' + tag + '.gz']
        release = {'tag_name': tag, 'assets': [{'name': name, 'digest': 'sha256:' + 'a' * 64,
            'browser_download_url': 'https://github.com/MetaCubeX/mihomo/releases/download/' + tag + '/' + name}
            for name in names]}
        with patch.object(resources, 'resource_base', return_value=None):
            self.assertEqual(cli.release_asset(release, 'amd64', 'darwin')[1]['name'], names[-1])
            release['assets'].pop()
            with self.assertRaises(DomainError):
                cli.release_asset(release, 'amd64', 'darwin')

    def test_cached_macos_intel_init_uses_the_verified_v1_archive(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict('os.environ', HOME=directory):
            home = Path(directory)
            cache = home / 'cache'
            cache.mkdir()
            name = 'mihomo-darwin-amd64-v1-v1.19.33.gz'
            archive = cache / name
            archive.write_bytes(b'verified fixture archive')
            manifest = home / '.local/share/domino/manifest.json'
            manifest.parent.mkdir(parents=True)
            manifest.write_text(json.dumps({'version': 'v1.19.33', 'platform': 'darwin', 'arch': 'amd64',
                'sha256_gzip': hashlib.sha256(archive.read_bytes()).hexdigest()}))
            args = SimpleNamespace(command='init', mihomo_version='latest')
            self.assertEqual(cli.cached_init_release(args, 'amd64', 'darwin', cache)[1]['name'], name)
            archive.write_bytes(b'changed')
            self.assertIsNone(cli.cached_init_release(args, 'amd64', 'darwin', cache))

    def test_resource_mirror_stages_the_explicit_macos_intel_baseline(self):
        from scripts import build_resources
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            name = 'mihomo-darwin-amd64-v1-v1.19.33.gz'
            archive = root / name
            archive.write_bytes(b'public fixture archive')
            metadata = root / 'release.json'
            metadata.write_text(json.dumps({'tag_name': 'v1.19.33', 'assets': [{'name': name,
                'digest': 'sha256:' + hashlib.sha256(archive.read_bytes()).hexdigest()}]}))
            output = root / 'resources'
            arguments = ['build_resources.py', '--base-url', 'https://cdn.example.test/domino/',
                '--release-json', str(metadata), '--archive', str(archive), '--output', str(output)]
            with patch('sys.argv', arguments), redirect_stdout(io.StringIO()):
                build_resources.main()
            self.assertEqual((output / 'mihomo/v1.19.33' / name).read_bytes(), archive.read_bytes())
            self.assertEqual(json.loads((output / 'mihomo/latest.json').read_text())['assets'][0]['name'], name)

    def test_ci_prefetched_metadata_keeps_version_and_archive_hash_checks(self):
        from scripts import fetch_test_core as fetch
        tag='v1.19.33';name='mihomo-darwin-arm64-'+tag+'.gz'
        archive=gzip.compress(b'isolated-test-core')
        url='https://github.com/MetaCubeX/mihomo/releases/download/'+tag+'/'+name
        metadata={'tag_name':tag,'assets':[{'name':name,'digest':'sha256:'+hashlib.sha256(archive).hexdigest(),
                                          'browser_download_url':url}]}
        for case in ['valid','tampered','wrong-version']:
            with self.subTest(case=case),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);source=root/'release.json';source.write_text(json.dumps(metadata));target=root/'mihomo'
                arguments=['fetch_test_core.py','--release-json',str(source),'--output',str(target)]
                if case=='wrong-version':arguments+=['--version','v1.2.3']
                def download(address,path,*args,**kwargs):
                    self.assertEqual(address,url)
                    path.write_bytes(archive if case!='tampered' else gzip.compress(b'tampered'))
                with patch.object(fetch.sys,'argv',arguments), \
                        patch.object(fetch.platform,'machine',return_value='arm64'), \
                        patch.object(fetch.platform,'system',return_value='Darwin'), \
                        patch.object(fetch.cli,'download',side_effect=download) as request, \
                        patch.object(resources,'resource_base',return_value=None), redirect_stdout(io.StringIO()):
                    if case=='valid':
                        fetch.main()
                        self.assertEqual(target.read_bytes(),b'isolated-test-core')
                        request.assert_called_once()
                    else:
                        with self.assertRaisesRegex(RuntimeError,'mismatch'):fetch.main()
                        self.assertFalse(target.exists())
                        if case=='wrong-version':request.assert_not_called()

    def test_http2_failure_retries_once_with_http11_without_exposing_credentials(self):
        for code in [16,92,95]:
            with self.subTest(code=code),tempfile.TemporaryDirectory() as directory:
                failure=subprocess.CalledProcessError(code,['curl'],output='',stderr='PRIVATE')
                with patch.object(cli.subprocess,'run',side_effect=[failure,subprocess.CompletedProcess([],0,stdout='200')]) as run:
                    cli.download('https://example.test/sub?token=PRIVATE',Path(directory)/'out')
                self.assertEqual(run.call_count,2)
                self.assertIn('--http1.1',run.call_args.args[0])
                self.assertNotIn('PRIVATE',' '.join(run.call_args.args[0]))
                self.assertEqual(run.call_args.kwargs['input'],run.call_args_list[0].kwargs['input'])

    def test_http11_failure_stays_bounded_and_auth_failures_are_not_retried(self):
        for code,http,retries in [(16,'',2),(22,'403',1)]:
            with self.subTest(code=code),tempfile.TemporaryDirectory() as directory:
                failure=subprocess.CalledProcessError(code,['curl'],output=http,stderr='PRIVATE')
                with patch.object(cli.subprocess,'run',side_effect=failure) as run,self.assertRaises(DomainError) as caught:
                    cli.download('https://example.test/sub?token=PRIVATE',Path(directory)/'out')
                self.assertEqual(run.call_count,retries)
                self.assertNotIn('PRIVATE',str(caught.exception))

    def test_custom_source_replaces_release_metadata_and_rejects_other_origins(self):
        with patch.dict('os.environ',{'DOMINO_RESOURCE_BASE':'https://cdn.example.test/domino'}):
            self.assertEqual(resources.release_url('latest',cli.RELEASE_API),'https://cdn.example.test/domino/mihomo/latest.json')
            self.assertEqual(resources.release_url('v1.2.3',cli.RELEASE_API),'https://cdn.example.test/domino/mihomo/v1.2.3.json')
            self.assertTrue(resources.asset_allowed('https://cdn.example.test/domino/mihomo/v1.2.3/core.gz','v1.2.3'))
            self.assertFalse(resources.asset_allowed('https://github.com/MetaCubeX/mihomo/releases/download/v1.2.3/core.gz','v1.2.3'))
        for url in ['http://cdn.example.test/','https://user:secret@cdn.example.test/','https://cdn.example.test/?token=private']:
            with patch.dict('os.environ',{'DOMINO_RESOURCE_BASE':url}),self.assertRaises(DomainError): resources.resource_base()

    def test_geo_dependencies_follow_rules_instead_of_node_names_or_domains(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            profile = {'proxies': [{'name': 'GEOIP'}], 'rules': ['DOMAIN,geoip,DIRECT', 'DOMAIN-SUFFIX,geosite.example,DIRECT']}
            self.assertEqual(resources.geo_requirements(profile, data), set())
            profile['rules'].append('AND,((NETWORK,TCP),(GEOIP,CN)),DIRECT')
            profile['sub-rules'] = {'nested': ['SRC-IP-ASN,123,DIRECT']}
            (data / 'rules.yaml').write_text('payload:\n  - GEOSITE,cn,DIRECT\n')
            profile['rule-providers'] = {'fixture': {'path': 'rules.yaml'}}
            self.assertEqual(resources.geo_requirements(profile, data), {'Country.mmdb', 'ASN.mmdb', 'geosite.dat'})

    def test_geo_closure_uses_only_configured_origin_and_checks_hashes(self):
        with tempfile.TemporaryDirectory() as work,patch.dict('os.environ',{'DOMINO_RESOURCE_BASE':'https://cdn.example.test/'}):
            content=b'fixture-mmdb'
            calls=[]
            def download(label,url,path,proxy):
                calls.append(url)
                path.write_bytes(json.dumps({'schema_version':1,'files':{'Country.mmdb':{'sha256':hashlib.sha256(content).hexdigest()}}}).encode() if url.endswith('index.json') else content)
            data=Path(work)
            profile={'rules':['GEOIP,CN,DIRECT']}
            resources.prepare_geo(profile,data,download)
            self.assertEqual((data/'Country.mmdb').read_bytes(),content)
            self.assertTrue(all(url.startswith('https://cdn.example.test/') for url in calls))
            self.assertEqual((data/'Country.mmdb').stat().st_mode & 0o077,0)
            self.assertNotIn('github.com',json.dumps(profile))
            (data/'Country.mmdb').unlink()
            def corrupt(label,url,path,proxy):
                download(label,url,path,proxy)
                if not url.endswith('index.json'): path.write_bytes(b'corrupt')
            with self.assertRaises(DomainError) as caught: resources.prepare_geo(profile,data,corrupt)
            self.assertEqual(caught.exception.code,'RESOURCE_DIGEST_MISMATCH')
            self.assertFalse((data/'Country.mmdb').exists())
