"""Offline contracts for native combat configuration and error boundaries."""

import json
import logging
import tempfile
import unittest
from pathlib import Path

from gameframe.api import Cancelled
from src.runtime.native_config import Config
from src.runtime.native_errors import TaskDisabledException, translate_cancelled
from src.runtime.native_logging import Logger, configure_logging


class TestNativeConfig(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.previous_folder = Config.config_folder
        self.addCleanup(setattr, Config, 'config_folder', self.previous_folder)
        Config.config_folder = Path(self.temp.name) / 'configs'

    def test_requires_explicit_absolute_directory(self):
        Config.config_folder = None
        with self.assertRaisesRegex(RuntimeError, 'bound before task import'):
            Config('combat', {'enabled': True})
        with self.assertRaisesRegex(ValueError, 'absolute path'):
            Config('combat', {'enabled': True}, folder='configs')

    def test_create_repair_and_persist_mutation(self):
        path = Config.config_folder / 'combat.json'
        config = Config('combat', {'_enabled': False, 'size': 0})
        self.assertEqual(json.loads(path.read_text(encoding='utf-8')),
                         {'_enabled': False, 'size': 0})
        path.write_text('{"_enabled": true, "size": "bad", "obsolete": 1}',
                        encoding='utf-8')
        config = Config('combat', {'_enabled': False, 'size': 0})
        self.assertEqual(dict(config), {'_enabled': True, 'size': 0})
        config['size'] = 12
        self.assertEqual(json.loads(path.read_text(encoding='utf-8')),
                         {'_enabled': True, 'size': 12})

    def test_invalid_json_remains_available_for_diagnosis(self):
        path = Config.config_folder / 'combat.json'
        path.parent.mkdir(parents=True)
        path.write_text('{broken', encoding='utf-8')
        with self.assertRaises(json.JSONDecodeError):
            Config('combat', {'size': 0})
        self.assertEqual(path.read_text(encoding='utf-8'), '{broken')


class TestNativeErrorsAndLogging(unittest.TestCase):
    def test_cancelled_becomes_production_stop(self):
        with self.assertRaises(TaskDisabledException) as caught:
            with translate_cancelled():
                raise Cancelled('user stopped')
        self.assertIsInstance(caught.exception.__cause__, Cancelled)

    def test_logging_writes_inside_explicit_data_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            handler = configure_logging(directory)
            try:
                Logger.get_logger('src.char.BaseChar').warning('combat waiting')
                logging.getLogger('src.vision.ocr').error('OCR diagnostic failed')
                handler.flush()
                log = (Path(directory) / 'logs' / 'ok-native.log').read_text(encoding='utf-8')
                self.assertIn('BaseChar:combat waiting', log)
                self.assertIn('OCR diagnostic failed', log)
            finally:
                logging.getLogger().removeHandler(handler)
                handler.close()


if __name__ == '__main__':
    unittest.main()
