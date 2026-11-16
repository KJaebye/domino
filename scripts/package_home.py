"""Synthetic HOME fixtures shared by package lifecycle smoke tests."""
import argparse
import hashlib
import json
import os
from pathlib import Path


def snapshot(home):
    return {p.relative_to(home).as_posix(): ('link', os.readlink(p)) if p.is_symlink() else
            ('file', hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mode & 0o777) if p.is_file()
            else ('directory', '') for p in home.rglob('*')}


def seed(home):
    # Never import Domino or inspect the developer's actual configuration.
    for name, content in {
        '.config/domino/retention-test.txt': 'synthetic configuration\n',
        '.local/share/domino/data/retention-test.txt': 'synthetic runtime\n',
        '.config/systemd/user/domino-mihomo.service': '# synthetic service; never started\n',
        'Library/LaunchAgents/local.domino.mihomo.plist': '<!-- synthetic; never loaded -->\n',
        '.zshrc': '# synthetic shell configuration\n',
        '.local/bin/domino': '#!/bin/sh\n# synthetic old launcher; never executed\n',
    }.items():
        path = home / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    (home / '.local/bin/domino').chmod(0o755)
    (home / '.local/bin/domino-install').symlink_to('domino')


def unchanged(home, baseline, stage):
    current = snapshot(home)
    changed = sorted(name for name in set(current) | set(baseline)
                     if current.get(name) != baseline.get(name))
    assert not changed, stage + ' changed HOME: ' + ', '.join(changed)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['seed', 'check'])
    parser.add_argument('home', type=Path)
    parser.add_argument('record', type=Path, help='Snapshot stored outside the synthetic HOME')
    args = parser.parse_args()
    if args.action == 'seed':
        seed(args.home)
        args.record.write_text(json.dumps(snapshot(args.home)))
    else:
        baseline = {name: tuple(value) for name, value in json.loads(args.record.read_text()).items()}
        unchanged(args.home, baseline, 'Package lifecycle')
