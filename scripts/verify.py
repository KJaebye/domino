#!/usr/bin/env python3
"""Portable regression runner with a machine-readable platform report."""
import json
from pathlib import Path
import platform
import sys
import unittest

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
suite=unittest.defaultTestLoader.discover(str(root/'tests'))
result=unittest.TextTestRunner(verbosity=1).run(suite)
report={'schema_version':1,'platform':platform.system(),'arch':platform.machine(),'python':platform.python_version(),
        'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),
        'skipped':[{'test':str(test),'reason':reason} for test,reason in result.skipped],'ok':result.wasSuccessful()}
output=root/'dist/verification.json'
output.parent.mkdir(exist_ok=True)
output.write_text(json.dumps(report,indent=2)+'\n')
raise SystemExit(0 if report['ok'] else 1)
