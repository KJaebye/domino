"""Real disposable cores verify adjacent re-deployment after the source is removed."""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.request

import domino_cli as cli

CORE=Path(os.environ['DOMINO_TEST_CORE']) if os.environ.get('DOMINO_TEST_CORE') else None


@unittest.skipUnless(CORE and CORE.is_file(),'set DOMINO_TEST_CORE to a disposable Mihomo binary')
class IndependentBundleTests(unittest.TestCase):
    def test_each_adjacent_copy_runs_after_its_source_is_removed(self):
        with tempfile.TemporaryDirectory(prefix='domino-independent-') as directory:
            root=Path(directory)
            source=root/'source'
            source.mkdir()
            (source/'nodes.json').write_text(json.dumps({'proxies':[{'name':'fixture-node','type':'socks5','server':'example.invalid','port':1080}]}))
            original={'mode':'rule','secret':'SOURCE-SECRET','proxy-providers':{'fixture':{'type':'file','path':'nodes.json'}},
                'proxy-groups':[{'name':'出口','type':'select','proxies':['DIRECT'],'use':['fixture']}],'rules':['MATCH,出口']}
            def copy(config,origin,target):
                data=target/'data'
                data.mkdir(parents=True)
                with socket.socket() as a,socket.socket() as b:
                    a.bind(('127.0.0.1',0)); b.bind(('127.0.0.1',0))
                    profile=cli.sanitize_profile(config,{},a.getsockname()[1],b.getsockname()[1])
                cli.provider_resources(profile,origin,data,None)
                (data/'config.json').write_text(json.dumps(profile))
                shutil.copy2(CORE,target/'mihomo')
                (target/'mihomo').chmod(0o755)
                return profile
            processes=[]
            handles=[]
            def start(target,config):
                log=(target/'core.log').open('w')
                handles.append(log)
                process=subprocess.Popen([str(target/'mihomo'),'-d',str(target/'data'),'-f',str(target/'data/config.json')],stdout=log,stderr=log)
                processes.append(process)
                opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
                for _ in range(100):
                    try:
                        request=urllib.request.Request('http://'+config['external-controller']+'/proxies',headers={'Authorization':'Bearer '+config['secret']})
                        with opener.open(request,timeout=.2) as response: proxies=json.load(response)['proxies']
                        self.assertIn('fixture-node',proxies['出口']['all'])
                        return process
                    except OSError: time.sleep(.05)
                self.fail('Disposable core failed to start')
            class Handler(BaseHTTPRequestHandler):
                def log_message(self,*args): pass
                def do_GET(self):
                    self.send_response(200); self.end_headers(); self.wfile.write(b'adjacent-copy-ok')
            server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
            threading.Thread(target=server.serve_forever,daemon=True).start()
            def probe(config):
                for _ in range(50):
                    response=subprocess.run(['curl','--silent','--show-error','--fail','--noproxy','','--max-time','3',
                        '--proxy',f"http://127.0.0.1:{config['mixed-port']}",f'http://127.0.0.1:{server.server_port}/'],capture_output=True,timeout=5)
                    if response.returncode==0: break
                    time.sleep(.1)
                self.assertEqual(response.returncode,0,response.stderr.decode(errors='replace'))
                self.assertEqual(response.stdout,b'adjacent-copy-ok')
            try:
                first=root/'first'
                one=copy(original,source,first)
                shutil.rmtree(source)
                running=start(first,one)
                probe(one)
                second=root/'second'
                two=copy(one,first/'data',second)
                self.assertNotEqual(one['secret'],two['secret'])
                running.terminate(); running.wait(timeout=5)
                shutil.rmtree(first)
                start(second,two)
                probe(two)
                self.assertNotIn(str(first),(second/'data/config.json').read_text())
                self.assertFalse(two['tun']['enable'])
            finally:
                for process in processes:
                    if process.poll() is None:
                        process.terminate()
                        try: process.wait(timeout=5)
                        except subprocess.TimeoutExpired: process.kill(); process.wait()
                for handle in handles: handle.close()
                server.shutdown(); server.server_close()
