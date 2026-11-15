import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import install_domino as backend
from domino_logs import read_logs


class PrivateLogTests(unittest.TestCase):
    def test_bounded_logs_redact_known_credentials_urls_and_control_characters(self):
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory)
            app=home/'app'
            (app/'data').mkdir(parents=True)
            (app/'data/config.json').write_text(json.dumps({'secret':'PRIVATE-CONTROLLER','proxy-providers':{'A':{'url':'https://example.test/private?token=PRIVATE-TOKEN'}}}))
            path=home/'Library/Logs/domino/mihomo.log'
            path.parent.mkdir(parents=True)
            path.write_text('old line\nPRIVATE-CONTROLLER PRIVATE-TOKEN https://another.test/private-token\npassword=OLD-PRIVATE\nlast\x1b line\n')
            with patch.multiple(backend,HOME=home),patch.object(backend,'current_installation',return_value=(app,None)),patch('domino_logs.platform.system',return_value='Darwin'):
                result=read_logs(backend,3)
            text=json.dumps(result)
            for secret in ['PRIVATE-CONTROLLER','PRIVATE-TOKEN','private-token','OLD-PRIVATE','\\u001b','old line']:
                self.assertNotIn(secret,text)
            self.assertEqual(len(result['lines']),3)
            self.assertFalse(result['truncated'])
