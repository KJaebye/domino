"""Disposable core resolves target hosts without a DNS listener or external network."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.request

import domino_cli as cli

CORE = Path(os.environ['DOMINO_TEST_CORE']) if os.environ.get('DOMINO_TEST_CORE') else None


@unittest.skipUnless(CORE and CORE.is_file(), 'set DOMINO_TEST_CORE to a disposable Mihomo binary')
class SystemHostsIntegrationTests(unittest.TestCase):
    def test_generated_profile_resolves_system_hosts_and_serves_http_after_fresh_starts(self):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                body = b'domino-system-hosts-ok\n'
                self.send_response(200)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        host = os.environ.get('DOMINO_TEST_SYSTEM_HOST', 'localhost')
        addresses = socket.getaddrinfo(host, 80, type=socket.SOCK_STREAM)
        import ipaddress
        if not addresses or any(not ipaddress.ip_address(item[4][0]).is_loopback for item in addresses):
            self.skipTest('System hosts fixture must resolve only to loopback')
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            cases = ([(False, 0)] if host != 'localhost' else []) + [(True, 0), (True, 1)]
            for enabled, attempt in cases:
                with self.subTest(system_hosts_enabled=enabled, fresh_start=attempt), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    with socket.socket() as proxy, socket.socket() as controller:
                        proxy.bind(('127.0.0.1', 0))
                        controller.bind(('127.0.0.1', 0))
                        config = cli.sanitize_profile({'mode': 'rule', 'rules': ['MATCH,DIRECT']}, {},
                            proxy.getsockname()[1], controller.getsockname()[1])
                    if not enabled:
                        config['dns'] = {'enable': False}
                    path = root / 'config.json'
                    path.write_text(json.dumps(config))
                    path.chmod(0o600)
                    with (root / 'core.log').open('w') as log:
                        process = subprocess.Popen([str(CORE), '-d', str(root), '-f', str(path)], stdout=log, stderr=log)
                        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                        def api(route):
                            request = urllib.request.Request('http://' + config['external-controller'] + route,
                                headers={'Authorization': 'Bearer ' + config['secret']})
                            with opener.open(request, timeout=2) as response:
                                return json.load(response)
                        try:
                            for _ in range(100):
                                if process.poll() is not None:
                                    self.fail('Disposable core exited during startup')
                                try:
                                    api('/version')
                                    # The controller may answer before the mixed listener binds.
                                    with socket.create_connection(('127.0.0.1', config['mixed-port']), timeout=.2):
                                        pass
                                    break
                                except OSError:
                                    time.sleep(.05)
                            else:
                                self.fail('Disposable core controller did not start')
                            # The DNS query API queries upstream DNS without the outbound
                            # resolver's hosts fallback. Exercise the actual DIRECT dial.
                            result = subprocess.run(['curl', '--silent', '--show-error', '--fail', '--max-time', '5',
                                '--noproxy', '', '--proxy', 'http://127.0.0.1:' + str(config['mixed-port']),
                                'http://' + host + ':' + str(server.server_port) + '/'], capture_output=True, text=True, timeout=8)
                            if enabled:
                                self.assertEqual(result.returncode, 0, result.stderr)
                                self.assertEqual(result.stdout, 'domino-system-hosts-ok\n')
                            else:
                                self.assertNotEqual(result.returncode, 0)
                        finally:
                            process.terminate()
                            try:
                                process.wait(timeout=5)
                            except subprocess.TimeoutExpired:
                                process.kill()
                                process.wait()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
