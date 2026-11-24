"""Offline HTTPS simulation. Self-address traffic does not prove LAN permission."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import plistlib
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid

CORE = os.environ.get('DOMINO_TEST_CORE')


@unittest.skipUnless(sys.platform == 'darwin' and CORE,
                     'set DOMINO_TEST_CORE on macOS to run the offline HTTPS simulation')
class MacDirectSimulationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='domino-direct-simulation-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.core = str(Path(CORE).resolve())
        self.assertTrue(Path(self.core).is_file())

    @contextmanager
    def proxy(self, agent):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0))
            port = listener.getsockname()[1]
        config = self.root / 'config.json'
        config.write_text(json.dumps({'mixed-port':port,'bind-address':'127.0.0.1','mode':'rule',
            'rules':['IP-CIDR,127.0.0.0/8,DIRECT,no-resolve','MATCH,REJECT'],
            'dns':{'enable':False},'tun':{'enable':False}}))
        args = [self.core,'-d',str(self.root),'-f',str(config)]
        if agent:
            label = 'local.domino.simulation.' + uuid.uuid4().hex
            domain = f'gui/{os.getuid()}'
            plist = self.root / 'agent.plist'
            plist.write_bytes(plistlib.dumps({'Label':label,'ProgramArguments':args,'RunAtLoad':True,
                'StandardOutPath':str(self.root/'agent.log'),'StandardErrorPath':str(self.root/'agent.log')}))
            subprocess.run(['launchctl','bootstrap',domain,str(plist)],capture_output=True,check=True)
        else:
            process = subprocess.Popen(args,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
        try:
            for _ in range(60):
                try:
                    with socket.create_connection(('127.0.0.1',port),.1): break
                except OSError: time.sleep(.1)
            else: self.fail('Disposable core did not start')
            yield f'http://127.0.0.1:{port}'
        finally:
            if agent:
                subprocess.run(['launchctl','bootout',domain+'/'+label],capture_output=True,check=True)
            else:
                process.terminate()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired: process.kill(); process.wait()

    def curl(self, url, proxy='', ca=None):
        args = ['curl','--silent','--show-error','--connect-timeout','2','--max-time','5',
                '--noproxy','' if proxy else '*','--proxy',proxy,'--write-out','\n%{http_code} %{http_connect}']
        if ca: args += ['--cacert',str(ca)]
        return subprocess.run(args+['--url',url],capture_output=True,text=True,timeout=7)

    def test_direct_rule_completes_verified_https_in_child_and_launchagent(self):
        cert, key = self.root/'cert.pem', self.root/'key.pem'
        subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(key),
            '-out',str(cert),'-days','1','-subj','/CN=domino-test','-addext','subjectAltName=IP:127.0.0.1'],
            check=True,capture_output=True)
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args): pass
            def do_GET(self):
                self.send_response(200);self.end_headers();self.wfile.write(b'domino-https-ok')
        server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert,key)
        server.socket = ctx.wrap_socket(server.socket,server_side=True)
        thread = threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        try:
            url = f'https://127.0.0.1:{server.server_port}/'
            native = self.curl(url,ca=cert)
            self.assertEqual((native.returncode,native.stdout),(0,'domino-https-ok\n200 000'))
            for agent in [False,True]:
                with self.subTest(launchagent=agent),self.proxy(agent) as proxy:
                    response = self.curl(url,proxy,cert)
                    self.assertEqual((response.returncode,response.stdout),(0,'domino-https-ok\n200 200'))
        finally:
            server.shutdown();server.server_close();thread.join(timeout=5)

    def test_accepted_connect_does_not_hide_failed_direct_tcp(self):
        # A bound, non-listening socket keeps the destination port reserved and refuses TCP.
        with socket.socket() as closed:
            closed.bind(('127.0.0.1',0))
            url = f'https://127.0.0.1:{closed.getsockname()[1]}/'
            for agent in [False,True]:
                with self.subTest(launchagent=agent),self.proxy(agent) as proxy:
                    result = self.curl(url,proxy)
                    self.assertNotEqual(result.returncode,0)
                    self.assertEqual(result.stdout,'\n000 200')
