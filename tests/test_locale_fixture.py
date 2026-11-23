import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tests.locale_fixture import chinese_ui


class LocaleFixtureTests(unittest.TestCase):
    def test_case_patch_cleanup_preserves_module_locale_then_restores_original(self):
        with patch.dict(os.environ, DOMINO_LANG='en'):
            enter, restore = chinese_ui()
            enter()
            try:
                fixture = SimpleNamespace(value='original')
                patch.object(fixture, 'value', 'changed').start()
                patch.stopall()
                self.assertEqual(fixture.value, 'original')
                self.assertEqual(os.environ['DOMINO_LANG'], 'zh')
            finally:
                restore()
            self.assertEqual(os.environ['DOMINO_LANG'], 'en')
