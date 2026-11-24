#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 KJaebye
"""Back up and migrate an existing macOS runtime to the responsible app launcher."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Back up and update the owned LaunchAgent; preserve the core and proxy settings')
    args = parser.parse_args()
    if sys.platform != 'darwin':
        parser.error('This repair is macOS only')
    if not args.apply:
        parser.error('Use --apply to migrate the current user runtime with a rollback backup')
    import install_domino as ctx
    import domino_macos
    try:
        with ctx.deployment_lock():
            domino_macos.setup_network_app(ctx)
    except ctx.InstallError as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()
