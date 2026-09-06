import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from ok.util.config import Config
from src.char.Chixia import Chixia
from src.char.CustomCharLoader import clear_custom_char_cache, is_custom_char_enabled, save_custom_char_code
from src.char.Mortefi import Mortefi
from src.Labels import Labels
from src.gui.CharacterCodeTab import CharacterCodeTab


class TestCharacterCodeTab(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.old_config_folder = Config.config_folder
        self.temp_dir = tempfile.TemporaryDirectory()
        Config.config_folder = self.temp_dir.name
        clear_custom_char_cache()

    def tearDown(self):
        clear_custom_char_cache()
        Config.config_folder = self.old_config_folder
        self.temp_dir.cleanup()

    def test_builtin_mode_persists_when_switching_between_custom_saved_chars(self):
        save_custom_char_code(Mortefi, self._custom_code(Mortefi), use_custom=True)
        save_custom_char_code(Chixia, self._custom_code(Chixia), use_custom=True)

        tab = CharacterCodeTab()
        try:
            tab.char_list.setCurrentRow(self._row_for_char(tab, Chixia))
            self.assertTrue(tab.custom_radio.isChecked())

            tab.builtin_radio.setChecked(True)
            self.assertFalse(is_custom_char_enabled(Chixia))

            tab.char_list.setCurrentRow(self._row_for_char(tab, Mortefi))
            self.assertTrue(tab.custom_radio.isChecked())

            tab.char_list.setCurrentRow(self._row_for_char(tab, Chixia))
            self.assertTrue(tab.builtin_radio.isChecked())
            self.assertFalse(tab.custom_radio.isChecked())
        finally:
            tab.deleteLater()

    def _row_for_char(self, tab, char_cls):
        for row in range(tab.char_list.count()):
            item = tab.char_list.item(row)
            if item.data(Qt.UserRole) == char_cls.__name__:
                return row
        raise AssertionError(f"{char_cls.__name__} not found in character list")

    def test_builtin_direct_base_v1_v2_builtin_preserves_state_and_other_char(self):
        from src.char.CustomCharLoader import remove_custom_char_code
        task = SimpleNamespace()
        current = Mortefi(task, 0, char_name=Labels.char_mortefi)
        other = Chixia(task, 1, char_name=Labels.char_chixia)
        fields = ('is_current_char', 'has_intro', 'has_sub_dps_intro', 'last_switch_time',
                  'last_switch_in_time', 'last_res', 'last_echo', 'last_liberation', 'last_buff_time',
                  'last_full_con_switch_time', 'last_perform', 'last_outro_time')
        for index, field in enumerate(fields):
            setattr(current, field, True if index < 3 else index + 10)
        expected = {field: getattr(current, field) for field in fields}
        task.chars = [current, other]
        tab = CharacterCodeTab()
        tab.executor = SimpleNamespace(onetime_tasks=[task], trigger_tasks=[], current_task=None)
        tab.current_char_cls = Mortefi
        try:
            for version in (1, 2, None):
                if version:
                    save_custom_char_code(Mortefi, 'from src.char.BaseChar import BaseChar\n'
                                          f'class Mortefi(BaseChar):\n    marker = {version}\n')
                else:
                    remove_custom_char_code(Mortefi)
                self.assertEqual(tab._reload_live_char_code(), 1)
                self.assertIsNot(task.chars[0], current)
                current = task.chars[0]
                self.assertEqual(getattr(current, 'marker', None), version)
                self.assertEqual({field: getattr(current, field) for field in fields}, expected)
                self.assertIs(task.chars[1], other)
            self.assertIs(type(current), Mortefi)
        finally:
            tab.deleteLater()

    def test_running_paused_or_in_action_defers_replacement_with_visible_result(self):
        task = SimpleNamespace()
        char = Mortefi(task, 0, char_name=Labels.char_mortefi)
        task.chars = [char]
        tab = CharacterCodeTab()
        tab.current_char_cls = Mortefi
        try:
            for flags in ({'current_task': task}, {'paused': True}, {'_in_action': True}):
                task._in_action = flags.get('_in_action', False)
                tab.executor = SimpleNamespace(onetime_tasks=[task], trigger_tasks=[], **flags)
                with patch('src.gui.CharacterCodeTab.load_custom_char_class') as load, \
                        patch('src.gui.CharacterCodeTab.show_info_bar') as message:
                    self.assertEqual(tab._reload_live_char_code(), 0)
                    load.assert_not_called()
                    self.assertIs(task.chars[0], char)
                    tab._show_reload_result('saved')
                    self.assertIn('next team rebuild', message.call_args.args[1])
        finally:
            tab.deleteLater()

    def _custom_code(self, char_cls):
        class_name = char_cls.__name__
        return f"""
from src.char.{class_name} import {class_name} as Builtin{class_name}


class {class_name}(Builtin{class_name}):
    custom_marker = True
"""


if __name__ == "__main__":
    unittest.main()
