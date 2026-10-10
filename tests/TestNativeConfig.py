"""Bulk native task overrides honor validation, persistence and UI events."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.runtime.native_config import Config


class TestNativeConfig(unittest.TestCase):
    def test_bulk_override_validates_all_values_before_write_and_reloads_saved_values(self):
        with tempfile.TemporaryDirectory() as directory:
            defaults = {'mode': 'daily', 'count': 1}
            config = Config('task', defaults, folder=Path(directory),
                            validator=lambda key, value: (key != 'count' or value > 0, 'count must be positive'))
            events = []
            config.on_change = lambda key, value: events.append((key, value))
            before = config.config_file.read_bytes()
            with self.assertRaisesRegex(ValueError, 'positive'):
                config.update({'mode': 'weekly', 'count': 0})
            self.assertEqual(config, defaults)
            self.assertEqual(config.config_file.read_bytes(), before)
            self.assertEqual(events, [])
            config.update({'mode': 'weekly'}, count=3)
            self.assertEqual(Config('task', defaults, folder=Path(directory)), {'mode': 'weekly', 'count': 3})
            self.assertEqual(events, [('mode', 'weekly'), ('count', 3)])
            with patch.object(config, 'save_file', side_effect=OSError('disk failure')):
                with self.assertRaisesRegex(OSError, 'disk failure'):
                    config.update(count=4)
            self.assertEqual(events, [('mode', 'weekly'), ('count', 3)])


if __name__ == '__main__':
    unittest.main()
