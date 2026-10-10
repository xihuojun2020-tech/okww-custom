"""Messenger result contracts without loading or operating a Windows messenger."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


SOURCE = Path(__file__).resolve().parents[1] / 'custom_ok/ok/notification/windows_messenger.py'


def messenger_method(name):
    tree = ast.parse(SOURCE.read_text(encoding='utf-8-sig'))
    node = next(node for node in ast.walk(tree)
                if isinstance(node, ast.FunctionDef) and node.name == name)
    namespace = {'time': SimpleNamespace(sleep=Mock()), 'logger': Mock()}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(SOURCE), 'exec'), namespace)
    return namespace[name]


class TestMessengerReview(unittest.TestCase):
    def test_both_send_routes_propagate_content_result(self):
        method = messenger_method('_send')
        for fast_header in (False, True):
            for completed in (False, True):
                with self.subTest(fast_header=fast_header, completed=completed):
                    points = (None, (100, 80), (200, 10)) if fast_header else ((1, 2), (100, 80))
                    sender = SimpleNamespace(
                        _find_hwnd=Mock(return_value=10), _wait_until_background=Mock(return_value=True),
                        _layout_regions=Mock(return_value=('search', 'contact', 'send')),
                        _wait_text=Mock(side_effect=points), _header_region=Mock(return_value='header'),
                        _click=Mock(return_value=20), _send_content=Mock(return_value=completed))
                    self.assertIs(method(sender, 'test contact', 'title', 'body', []), completed)
                    sender._send_content.assert_called_once()

    def test_content_returns_success_after_completing(self):
        method = messenger_method('_send_content')
        sender = SimpleNamespace(_should_stop=Mock(return_value=False), _click=Mock(return_value=20),
                                 _clear_unsent_text=Mock(), _type_text=Mock())
        self.assertIs(method(sender, 10, (100, 80), (20, 35), '', 'body', []), True)
        sender._type_text.assert_called_once_with(20, 'body')

    def test_cancelled_content_preserves_clipboard_cleanup(self):
        method = messenger_method('_send_content')
        for cancel_before_start in (False, True):
            with self.subTest(cancel_before_start=cancel_before_start):
                sender = SimpleNamespace(
                    _should_stop=Mock(side_effect=(True,) if cancel_before_start else (False, True)),
                    _click=Mock(return_value=20), _clear_unsent_text=Mock(),
                    _get_clipboard_text=Mock(return_value='original'), _restore_clipboard_text=Mock())
                self.assertIs(method(sender, 10, (100, 80), (20, 35), '', '', [object()]), False)
                if cancel_before_start:
                    sender._click.assert_not_called()
                    sender._restore_clipboard_text.assert_not_called()
                else:
                    sender._restore_clipboard_text.assert_called_once_with('original')


if __name__ == '__main__':
    unittest.main()
