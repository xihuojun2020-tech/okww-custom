"""Character contract regressions without importing game/device/config modules."""
import ast
from pathlib import Path
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]


def character_method(file, name):
    tree = ast.parse((ROOT / 'src/char' / file).read_text(encoding='utf-8-sig'))
    node = next(node for node in ast.walk(tree)
                if isinstance(node, ast.FunctionDef) and node.name == name)
    namespace = {'time': time}
    exec(compile(ast.Module(body=[node], type_ignores=[]), file, 'exec'), namespace)
    return namespace[name]


class TestCharacterReview(unittest.TestCase):
    def test_ciaccona_uses_current_teammate_form(self):
        class Cartethyia:
            def __init__(self, form):
                self.is_cartethyia = form

        method = character_method('Ciaccona.py', 'need_fast_perform')
        with patch.dict(sys.modules, {'src.char.Cartethyia': SimpleNamespace(Cartethyia=Cartethyia)}):
            for teammate, expected in ((Cartethyia(True), True), (Cartethyia(False), False), (None, False)):
                with self.subTest(expected=expected, teammate=teammate):
                    task = SimpleNamespace(has_char=Mock(return_value=teammate))
                    self.assertEqual(method(SimpleNamespace(task=task)), expected)
                    task.has_char.assert_called_once_with(Cartethyia)

    def test_shorekeeper_forte_follows_resonance_success_flag(self):
        method = character_method('ShoreKeeper.py', 'do_perform')
        for clicked in (False, True):
            with self.subTest(clicked=clicked):
                char = SimpleNamespace(has_intro=False, click_echo=Mock(), click_liberation=Mock(),
                                       click_resonance=Mock(return_value=(clicked, .5, False)),
                                       heavy_click_forte=Mock(), is_mouse_forte_full=Mock(),
                                       switch_next_char=Mock())
                method(char)
                if clicked:
                    char.heavy_click_forte.assert_not_called()
                else:
                    char.heavy_click_forte.assert_called_once_with(char.is_mouse_forte_full)
                char.switch_next_char.assert_called_once_with()

    def test_cantarella_switches_early_only_after_successful_resonance(self):
        method = character_method('Cantarella.py', 'do_perform')
        for clicked in (False, True):
            with self.subTest(clicked=clicked), patch.object(time, 'time', side_effect=(0, 1)):
                task = SimpleNamespace(mouse_up=Mock(), mouse_down=Mock(), next_frame=Mock())
                char = SimpleNamespace(has_intro=False, task=task, last_heavy=0,
                                       click_liberation=Mock(), is_mouse_forte_full=Mock(return_value=False),
                                       is_forte_full=Mock(side_effect=(True, False)),
                                       time_elapsed_accounting_for_freeze=Mock(return_value=0),
                                       resonance_available=Mock(return_value=True),
                                       click_resonance=Mock(return_value=(clicked, 0, False)),
                                       need_fast_perform=Mock(return_value=False), sleep=Mock(),
                                       click_echo=Mock(), switch_next_char=Mock())
                method(char)
                char.click_resonance.assert_called_once_with(send_click=False)
                if clicked:
                    char.click_echo.assert_not_called()
                else:
                    char.click_echo.assert_called_once_with()
                char.switch_next_char.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
