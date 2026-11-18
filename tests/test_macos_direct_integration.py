"""Opt-in LAN HTTP(S) regression; never takes over the user's proxy or agent."""
import json
import os
from pathlib import Path
import plistlib
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import uuid

CORE = os.environ.get('DOMINO_TEST_CORE')
URL = os.environ.get('DOMINO_TEST_LAN_URL')
APP = os.environ.get('DOMINO_TEST_LAN_APP')


@unittest.skipUnless(sys.platform == 'darwin' and CORE and URL,
                     'set DOMINO_TEST_CORE and DOMINO_TEST_LAN_URL on a Mac with LAN HTTP(S) access')
class MacDirectIntegrationTests(unittest.TestCase):
    def test_launchagent_can_reach_same_target_as_native_and_child(self):
        from urllib.parse import urlsplit
        parsed = urlsplit(URL)
        self.assertIn(parsed.scheme, ['http', 'https'])
        self.assertFalse(parsed.username or parsed.password or parsed.query or parsed.fragment)
        core = str(Path(CORE).resolve())
        self.assertTrue(Path(core).is_file())
        with tempfile.TemporaryDirectory(prefix='domino-lan-regression-') as directory:
            root = Path(directory)
            with socket.socket() as listener:
                listener.bind(('127.0.0.1', 0))
                port = listener.getsockname()[1]
            config = root / 'config.json'
            config.write_text(json.dumps({'mixed-port':port,'bind-address':'127.0.0.1',
                                         'mode':'direct','dns':{'enable':False},'tun':{'enable':False}}))
            arguments = [core,'-d',directory,'-f',str(config)]
            association = {}
            if APP:
                import domino_macos_app as native
                app = Path(APP).resolve()
                self.assertTrue((app / native.EXECUTABLE).is_file())
                info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
                arguments.insert(0, str(app / native.EXECUTABLE))
                association = {'AssociatedBundleIdentifiers': [info['CFBundleIdentifier']]}
            def request(proxy=None):
                return subprocess.run(['curl','--silent','--show-error','--output','/dev/null',
                    '--write-out','%{http_code}','--max-time','8','--noproxy','' if proxy else '*',
                    '--proxy',proxy or '', '--url',URL],capture_output=True,text=True,timeout=10)
            def wait_ready():
                for _ in range(60):
                    try:
                        with socket.create_connection(('127.0.0.1',port),.1): return
                    except OSError: time.sleep(.1)
                self.fail('Disposable proxy did not start')
            native = request()
            self.assertEqual(native.returncode,0,'Native HTTP(S) prerequisite failed')
            with (root / 'child.log').open('w') as log:
                process = subprocess.Popen(arguments,cwd=directory,stdout=log,stderr=log,start_new_session=True)
                try:
                    wait_ready()
                    child = request(f'http://127.0.0.1:{port}')
                finally:
                    process.terminate()
                    try: process.wait(timeout=5)
                    except subprocess.TimeoutExpired: process.kill(); process.wait()
            self.assertEqual(child.returncode,0,'Child process HTTP(S) prerequisite failed')
            label = 'local.domino.test.' + uuid.uuid4().hex
            domain = f'gui/{os.getuid()}'
            plist = root / 'test.plist'
            plist.write_bytes(plistlib.dumps({**association,'Label':label,'ProgramArguments':arguments,
                'RunAtLoad':True,'WorkingDirectory':directory,
                'StandardOutPath':str(root / 'agent.log'),'StandardErrorPath':str(root / 'agent.log')}))
            subprocess.run(['launchctl','bootstrap',domain,str(plist)],check=True,capture_output=True)
            try:
                wait_ready()
                agent = request(f'http://127.0.0.1:{port}')
            finally:
                subprocess.run(['launchctl','bootout',domain+'/'+label],check=True,capture_output=True)
            self.assertEqual(agent.returncode,0,
                f'LaunchAgent HTTP(S) failed (curl exit {agent.returncode}); check local network authorization, responsible code identity and nehelper logs')
            self.assertEqual(agent.stdout,native.stdout)
