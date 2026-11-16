#!/usr/bin/env python3
"""Optional isolated OpenSSH transport check; no system sshd/service is changed."""
import getpass
import json
import os
from pathlib import Path
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import tarfile
import hashlib
import platform

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT / "src"))
import domino_cli as cli
from domino_agent import decode_response,uploaded_bundle


def main():
    daemon=shutil.which('sshd') or ('/usr/sbin/sshd' if Path('/usr/sbin/sshd').is_file() else None)
    if not daemon: print(json.dumps({'ok':False,'skipped':'sshd unavailable'})); return 3
    with tempfile.TemporaryDirectory(prefix='domino-ssh-test-') as work:
        work=Path(work)
        for name in ['host','client']:
            subprocess.run(['ssh-keygen','-q','-t','ed25519','-N','','-f',str(work/name)],check=True,capture_output=True)
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0)); port=listener.getsockname()[1]
        config=work/'sshd_config'
        config.write_text(f'Port {port}\nListenAddress 127.0.0.1\nHostKey {work}/host\n'
            f'AuthorizedKeysFile {work}/client.pub\nPidFile {work}/sshd.pid\n'
            'PasswordAuthentication no\nKbdInteractiveAuthentication no\nUsePAM no\nStrictModes no\n'
            f'AllowUsers {getpass.getuser()}\nLogLevel ERROR\n')
        server=subprocess.Popen([daemon,'-D','-e','-f',str(config)],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        try:
            for _ in range(50):
                if server.poll() is not None:
                    print(json.dumps({'ok':False,'skipped':'user-owned sshd could not start','exit_code':server.returncode}))
                    return 3
                try:
                    with socket.create_connection(('127.0.0.1',port),timeout=.1): break
                except OSError: time.sleep(.1)
            known=work/'known_hosts'
            known.write_text(f'[127.0.0.1]:{port} '+(work/'host.pub').read_text())
            args=cli.build_parser().parse_args([getpass.getuser()+'@127.0.0.1','status','--ssh-port',str(port),'--identity',str(work/'client'),'--batch'])
            args.machine_mode=True
            ssh=cli.SSH(args)
            ssh.options+=['-F','/dev/null','-o','UserKnownHostsFile='+str(known),'-o','StrictHostKeyChecking=yes']
            home=work/'home'
            home.mkdir()
            original_command=ssh.command_argv
            ssh.command_argv=lambda command,tty=False:original_command('env HOME='+shlex.quote(str(home))+' sh -c '+shlex.quote(command),tty)
            with ssh:
                request={'schema_version':1,'operation':'configs.add','arguments':{'name':'SSH fixture','url':'https://example.test/private'},
                    'operation_id':'a'*32,'transport_token':'b'*32,'target':ssh.target,'request_id':'ssh-fixture'}
                results=[]
                for identifier in ['a'*32,'c'*32]:
                    request['operation_id']=identifier
                    argv=ssh.action_argv('agent')
                    response=subprocess.run(argv,input=json.dumps(request),capture_output=True,text=True,timeout=30)
                    result=decode_response(response.stdout,request['transport_token'])
                    if response.returncode or not result['ok']: raise RuntimeError('SSH protocol check failed')
                    results.append(result)
                if results[0]['operation_id']!=results[1]['operation_id'] or not results[1]['replayed']:
                    raise RuntimeError('SSH replay contract failed')
                listing=subprocess.run(ssh.action_argv('cli','list','--json'),capture_output=True,text=True,timeout=30)
                if listing.returncode or not any(item['name']=='SSH fixture' for item in json.loads(listing.stdout)['configs']):
                    raise RuntimeError('SSH flat CLI list failed')
                uncached=subprocess.run(ssh.action_argv('delay','--config','SSH fixture'),capture_output=True,text=True,timeout=30)
                if uncached.returncode!=1 or '尚未下载' not in uncached.stderr or 'ModuleNotFoundError' in uncached.stderr:
                    raise RuntimeError('SSH config delay payload failed')
                fixture=work/'fixture'
                (fixture/'data').mkdir(parents=True)
                (fixture/'mihomo').write_text('#!/bin/sh\nexit 0\n')
                (fixture/'manifest.json').write_text(json.dumps({'platform':platform.system().lower(),'arch':cli.normalize_arch(platform.machine()),'proxy_port':17897,'api_port':19091}))
                (fixture/'selections.json').write_text('{}')
                (fixture/'data/config.json').write_text('{"mixed-port":17897,"external-controller":"127.0.0.1:19091"}')
                archive=work/'bundle.tar.gz'
                with tarfile.open(archive,'w:gz') as bundle:
                    for path in fixture.iterdir(): bundle.add(path,arcname=path.name)
                archive.chmod(0o600)
                parameters={'bundle':str(archive),'bundle_sha256':hashlib.sha256(archive.read_bytes()).hexdigest()}
                with uploaded_bundle(ssh,parameters) as destination:
                    request.update(operation='deployment.apply',operation_id='d'*32,arguments=dict(parameters,bundle=destination),dry_run=True)
                    request.pop('request_id')
                    response=subprocess.run(ssh.action_argv('agent'),input=json.dumps(request),capture_output=True,text=True,timeout=30)
                    result=decode_response(response.stdout,request['transport_token'])
                    if response.returncode or not result['ok'] or not result['data']['dry_run']: raise RuntimeError('SSH upload preview failed')
                if list(home.glob('.domino-deploy.*')): raise RuntimeError('Staging cleanup failed')
            report={'ok':True,'transport':'OpenSSH loopback','operations':['configs.add','request replay','flat CLI list','config delay uncached validation','deployment.apply upload and dry-run'],'system_service_changed':False}
            (ROOT/'dist').mkdir(exist_ok=True)
            (ROOT/'dist/ssh-verification.json').write_text(json.dumps(report,indent=2)+'\n')
            print(json.dumps(report))
            return 0
        finally:
            server.terminate()
            try: server.communicate(timeout=3)
            except subprocess.TimeoutExpired: server.kill(); server.communicate()


if __name__=='__main__': raise SystemExit(main())
