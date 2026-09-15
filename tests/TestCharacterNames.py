import gettext
import unittest

from src.char.CharFactory import char_dict
from src.char.BaseChar import BaseChar
from src.char.character_names import character_display_name, CHARACTER_DISPLAY_NAMES


class TestCharacterNames(unittest.TestCase):
    def test_all_registered_characters_have_chinese_names(self):
        for locale in ('zh_CN', 'zh_TW'):
            tr = gettext.translation('ok', 'i18n', [locale]).gettext
            for cls in {info['cls'] for info in char_dict.values()} - {BaseChar}:
                with self.subTest(locale=locale, character=cls.__name__):
                    key = character_display_name(cls)
                    self.assertNotEqual(tr(key), key)

    def test_aliases_and_display_overrides(self):
        for name, official in CHARACTER_DISPLAY_NAMES.items():
            cls = type(name, (), {})
            self.assertEqual(character_display_name(cls), official)
            self.assertEqual(character_display_name(cls()), official)
            self.assertEqual(character_display_name(name), official)
        cls = type('Linnai', (), {'DISPLAY_NAME': 'explicit'})
        self.assertEqual(character_display_name(cls), 'explicit')
        instance = cls()
        instance.display_name = 'dynamic form'
        self.assertEqual(character_display_name(instance), 'dynamic form')


if __name__ == '__main__':
    unittest.main()
