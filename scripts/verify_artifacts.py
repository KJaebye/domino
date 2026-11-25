#!/usr/bin/env python3
"""Check current release bytes and smoke both packages outside the checkout."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import zipfile

ROOT=Path(__file__).resolve().parents[1]


def verify(release):
    manifest=json.loads((release/'release.json').read_text());version=manifest['version'];distribution=manifest.get('distribution','domino').replace('-','_')
    for line in (release/'SHA256SUMS').read_text().splitlines():
        digest,name=line.split('  ');assert hashlib.sha256((release/name).read_bytes()).hexdigest()==digest,name
    for name,digest in manifest['source_files'].items():assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest,name
    for item in manifest['files']:
        path=release/item['name'];assert path.stat().st_size==item['bytes'] and hashlib.sha256(path.read_bytes()).hexdigest()==item['sha256']
    with tempfile.TemporaryDirectory(prefix='domino-artifacts-') as directory:
        work=Path(directory);wheel=work/'wheel';runtime=work/'runtime';home=work/'home';home.mkdir()
        with zipfile.ZipFile(release/f'{distribution}-{version}-py3-none-any.whl') as archive:
            metadata=archive.read(f'{distribution}-{version}.dist-info/METADATA').decode();assert f'Version: {version}\n' in metadata;assert f'Name: {manifest.get("distribution","domino")}\n' in metadata
            assert 'Project-URL: Repository, https://github.com/KJaebye/domino' in metadata
            archive.extractall(wheel)
        with tarfile.open(release/f'domino-runtime-{version}.tar.gz') as archive:
            for member in archive:
                path=Path(member.name)
                assert not path.is_absolute() and '..' not in path.parts and (member.isfile() or member.isdir())
            archive.extractall(runtime)
        for location,docs in [(wheel,wheel/f'{distribution}-{version}.data/data/share/doc/domino'),
                              (runtime/f'domino-{version}/cli',runtime/f'domino-{version}')]:
            for name in manifest['source_files']:
                if name.startswith('src/'):assert (location/name[4:]).read_bytes()==(ROOT/name).read_bytes(),name
            for name in ['README.md','NOTICE','docs/USAGE.md','assets/domino-logo.gif','licenses/mihomo-GPL-3.0.txt']:
                assert (docs/name).read_bytes()==(ROOT/name).read_bytes(),name
            if (ROOT/'LICENSE').is_file():assert (docs/'LICENSE').read_bytes()==(ROOT/'LICENSE').read_bytes()
            env={**os.environ,'HOME':str(home),'TERM':'dumb','NO_COLOR':'1'}
            if (location/'_vendor').is_dir():
                result = subprocess.run(
                    [sys.executable, '-I', '-S', '-c',
                     'import sys;sys.path.insert(0,sys.argv[1]);import prompt_toolkit,yaml,wcwidth;'
                     'from prompt_toolkit.input import DummyInput;assert prompt_toolkit.__version__',
                     str(location/'_vendor')], env=env, cwd=work, capture_output=True, text=True, timeout=15)
                assert result.returncode == 0, result.stderr

            for name in list(env):
                if name.startswith('DOMINO_') or name.startswith('_DOMINO'):env.pop(name)
            bootstrap='import sys,runpy;from pathlib import Path;p=Path(sys.argv.pop(1));sys.path[:0]=[str(p),str(p/"_vendor")];sys.argv[0]="domino";runpy.run_module("domino_cli",run_name="__main__")'
            def run(args):
                result=subprocess.run([sys.executable,'-I','-c',bootstrap,str(location),*args],env=env,cwd=work,
                                      capture_output=True,text=True,timeout=15)
                assert result.returncode==0,'packaged CLI query failed: '+str(args)
                return result.stdout
            assert run(['--version']).strip()==version
            assert 'Domino' in run([]);assert 'usage:' in run(['-h'])
            assert json.loads(run(['shell','status','--json']))['policy_only']
            assert json.loads(run(['--output','json','capabilities']))['data']['application_version']==version
            assert not list(home.iterdir()),'read-only smoke modified HOME'
            assert json.loads(run(['list','--json']))['configs']==[]
            assert {p.relative_to(home).as_posix() for p in home.rglob('*')}=={
                '.local','.local/share','.local/share/domino.lock'},'list modified configuration beyond its coordination lock'
            # Each package starts with a fresh HOME; the lock is an expected coordination file.
            import shutil
            shutil.rmtree(home/'.local')
    return {'version':version,'ok':True,'checksums_match':True,'source_artifact_match':True,'wheel_runtime_smoke':True,
            'docs_and_logo_in_both_packages':True,'configuration_unchanged':True,'list_creates_only_coordination_lock':True,
            'other_queries_leave_home_empty':True,'source_checkout_on_import_path':False,
            'native_install_changed':False}


def main():
    report=verify(ROOT/'dist/release')
    (ROOT/'dist/artifact-verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))


if __name__=='__main__':main()
