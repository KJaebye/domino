"""Explicit locale for modules that assert Chinese UI, restored between modules.

Default-language and bilingual tests deliberately do not use this fixture.
"""
import os
from unittest.mock import patch


def chinese_ui():
    environment = patch.dict(os.environ, DOMINO_LANG='zh')
    # Some legacy cases call patch.stopall() during per-test cleanup. A module
    # fixture must outlive those patches, so enter it as a context manager.
    def restore():
        environment.__exit__(None, None, None)
    return environment.__enter__, restore
