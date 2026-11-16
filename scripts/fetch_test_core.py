#!/usr/bin/env python3
"""Fetch a hash-verified disposable core for CI; never install a service."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import platform
import sys
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1] / "src"))
import domino_cli as cli
from domino_resources import release_url


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--version',default='v1.19.33')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='domino-test-core-') as work:
        work=Path(work)
        metadata=work/'release.json'
        cli.download(release_url(args.version,cli.RELEASE_API),metadata)
        tag,asset=cli.release_asset(json.loads(metadata.read_text()),cli.normalize_arch(platform.machine()),platform.system().lower())
        archive=work/'core.gz'
        cli.download(asset['browser_download_url'],archive)
        if hashlib.sha256(archive.read_bytes()).hexdigest()!=asset['digest'].split(':')[1]:
            raise RuntimeError('Core digest mismatch')
        args.output.parent.mkdir(parents=True,exist_ok=True)
        cli.private_write(args.output,gzip.decompress(archive.read_bytes()))
        args.output.chmod(0o755)
        print(json.dumps({'version':tag,'platform':platform.system(),'arch':platform.machine(),'installed_service':False}))


if __name__=='__main__': main()
