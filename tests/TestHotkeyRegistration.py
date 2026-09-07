import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from custom_ok.ok.gui.start.StartCard import StartCard


class TestHotkeyRegistration(unittest.TestCase):
    def test_failed_registration_retries_after_backoff_and_records_error(self):
        card = SimpleNamespace(basic_options={'Start/Stop': 'F9'}, current_hotkey=None,
                               _desired_hotkey='UNINIT', _retry_after=0, _hotkey_stop=threading.Event(),
                               hotkey_changed=Mock(), hotkey_status_changed=Mock(), handler=Mock(), tr=lambda x:x)
        card.rebind_hotkey = lambda key: StartCard.rebind_hotkey(card, key)
        card.check_hotkey = lambda: StartCard.check_hotkey(card)
        api = Mock()
        api.user32.RegisterHotKey.side_effect = [False, True, True]
        api.user32.PeekMessageW.return_value = False
        api.kernel32.GetLastError.return_value = 1409
        with patch('custom_ok.ok.gui.start.StartCard.windll', api), \
                patch('custom_ok.ok.gui.start.StartCard.time.monotonic', return_value=10) as now:
            card.check_hotkey()
            self.assertIsNone(card.current_hotkey)
            self.assertIn('1409', card.hotkey_status_changed.emit.call_args.args[0])
            now.return_value = 12
            card.check_hotkey()
            self.assertEqual(api.user32.RegisterHotKey.call_count, 1)
            now.return_value = 15
            card.check_hotkey()
            self.assertEqual(card.current_hotkey, 'F9')
            card.basic_options['Start/Stop'] = 'F10'
            card.check_hotkey()
            self.assertEqual(card.current_hotkey, 'F10')
            card.basic_options['Start/Stop'] = 'None'
            card.check_hotkey()
            self.assertEqual(card.current_hotkey, 'None')
            card._hotkey_stop.set()
            count = card.handler.post.call_count
            card.check_hotkey()
            self.assertEqual(card.handler.post.call_count, count)
            self.assertEqual(api.user32.RegisterHotKey.call_count, 3)


if __name__ == '__main__':
    unittest.main()
