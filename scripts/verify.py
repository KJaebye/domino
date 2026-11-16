#!/usr/bin/env python3
"""Portable regression runner with a machine-readable platform report."""
import json
import argparse
import os
from pathlib import Path
import platform
import sys
import unittest

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--require-core',action='store_true',help='Fail if the disposable Mihomo integration test cannot run')
args=parser.parse_args()
if args.require_core and not (os.environ.get('DOMINO_TEST_CORE') and Path(os.environ['DOMINO_TEST_CORE']).is_file()):
    parser.error('--require-core needs DOMINO_TEST_CORE pointing to a disposable binary')
suite=unittest.defaultTestLoader.discover(str(root/'tests'))
result=unittest.TextTestRunner(verbosity=1).run(suite)
report={'schema_version':1,'platform':platform.system(),'arch':platform.machine(),'python':platform.python_version(),
        'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'core_required':args.require_core,
        'skipped':[{'test':str(test),'reason':reason} for test,reason in result.skipped],'ok':result.wasSuccessful()}
output=root/'dist/verification.json'
output.parent.mkdir(exist_ok=True)
output.write_text(json.dumps(report,indent=2)+'\n')
raise SystemExit(0 if report['ok'] else 1)
