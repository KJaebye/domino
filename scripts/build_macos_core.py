#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 KJaebye
"""Build a local Mihomo core with a Mach-O UUID; never install or sign a core."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True, help='Trusted upstream source checkout or extracted release')
    parser.add_argument('--version', required=True, help='Source release tag, e.g. v1.19.34')
    parser.add_argument('--go', default='go', help='Go toolchain with Mach-O UUID support')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != 'darwin': parser.error('Build and validate this core on macOS')
    if not re.fullmatch(r'v\d+\.\d+\.\d+', args.version): parser.error('Stable source release tag required')
    source = args.source.resolve()
    if not re.search(r'^module github.com/metacubex/mihomo\s*$', (source / 'go.mod').read_text(), re.M):
        parser.error('Expected a Mihomo source tree')
    output = args.output.absolute()
    if output.exists() or output.is_symlink(): parser.error('Output already exists; choose a new path')
    output.parent.mkdir(parents=True, exist_ok=True)
    version = args.version + '-domino-uuid'
    build_time = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    flags = ('-s -w -B gobuildid -X github.com/metacubex/mihomo/constant.Version=' + version
             + ' -X github.com/metacubex/mihomo/constant.BuildTime=' + build_time)
    with tempfile.TemporaryDirectory(prefix='.domino-core-', dir=output.parent) as directory:
        binary = Path(directory) / 'mihomo'
        subprocess.run([args.go, 'build', '-tags', 'with_gvisor', '-trimpath', '-ldflags', flags,
                        '-o', str(binary), '.'], cwd=source, env={**os.environ, 'CGO_ENABLED':'0'}, check=True)
        load = subprocess.check_output(['otool', '-l', str(binary)], text=True)
        uuids = re.findall(r'\buuid ([0-9A-Fa-f-]{36})', load)
        if not uuids or any(int(value.replace('-', ''), 16) == 0 for value in uuids):
            raise RuntimeError('Built core has no valid LC_UUID; use a toolchain with Mach-O UUID support')
        subprocess.run(['codesign', '--verify', '--strict', str(binary)], check=True)
        # A hard link publishes the checked artifact atomically and refuses overwrite.
        os.link(binary, output)
    print(json.dumps({'output':str(output), 'version':version, 'mach_o_uuids':uuids,
                      'sha256':hashlib.sha256(output.read_bytes()).hexdigest(), 'installed':False}))


if __name__ == '__main__': main()
