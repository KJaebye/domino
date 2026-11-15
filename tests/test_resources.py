import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import domino_resources as resources
import domino_cli as cli
from domino_model import DomainError


class ResourceSourceTests(unittest.TestCase):
    def test_custom_source_replaces_release_metadata_and_rejects_other_origins(self):
        with patch.dict('os.environ',{'DOMINO_RESOURCE_BASE':'https://cdn.example.test/domino'}):
            self.assertEqual(resources.release_url('latest',cli.RELEASE_API),'https://cdn.example.test/domino/mihomo/latest.json')
            self.assertEqual(resources.release_url('v1.2.3',cli.RELEASE_API),'https://cdn.example.test/domino/mihomo/v1.2.3.json')
            self.assertTrue(resources.asset_allowed('https://cdn.example.test/domino/mihomo/v1.2.3/core.gz','v1.2.3'))
            self.assertFalse(resources.asset_allowed('https://github.com/MetaCubeX/mihomo/releases/download/v1.2.3/core.gz','v1.2.3'))
        for url in ['http://cdn.example.test/','https://user:secret@cdn.example.test/','https://cdn.example.test/?token=private']:
            with patch.dict('os.environ',{'DOMINO_RESOURCE_BASE':url}),self.assertRaises(DomainError): resources.resource_base()

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
