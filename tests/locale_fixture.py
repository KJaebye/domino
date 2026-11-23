"""Explicit locale for modules that assert Chinese UI, restored between modules.

Default-language and bilingual tests deliberately do not use this fixture.
"""
import os
from unittest.mock import patch


def chinese_ui():
    environment = patch.dict(os.environ, DOMINO_LANG='zh')
    return environment.start, environment.stop
