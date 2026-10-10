"""Headless logging for native Wuthering Waves tasks."""

import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path


_LOGGER = logging.getLogger('ok')
_SINK = logging.getLogger()
_FORMAT = logging.Formatter('%(asctime)s %(levelname)s %(threadName)s %(message)s')


class Logger:
    def __init__(self, name):
        self.name = name.split('.')[-1]

    @staticmethod
    def get_logger(name):
        return Logger(name)

    def debug(self, message):
        _LOGGER.debug('%s:%s', self.name, message)

    def info(self, message):
        _LOGGER.info('%s:%s', self.name, message)

    def warning(self, message):
        _LOGGER.warning('%s:%s', self.name, message)

    def error(self, message, exception=None):
        exc_info = ((type(exception), exception, exception.__traceback__)
                    if exception is not None else None)
        _LOGGER.error('%s:%s', self.name, message, exc_info=exc_info)

    def critical(self, message):
        _LOGGER.critical('%s:%s', self.name, message)


def configure_logging(data_dir, *, debug=False):
    """Write native task logs inside the caller's explicit data directory."""
    log_dir = Path(data_dir) / 'logs'
    log_dir.mkdir(parents=True, exist_ok=True)
    for handler in tuple(_SINK.handlers):
        if getattr(handler, '_native_handler', False):
            _SINK.removeHandler(handler)
            handler.close()
    file_handler = TimedRotatingFileHandler(
        log_dir / 'ok-native.log', when='midnight', backupCount=7, encoding='utf-8')
    file_handler._native_handler = True
    file_handler.setFormatter(_FORMAT)
    file_handler.setLevel(logging.DEBUG if debug else logging.INFO)
    _SINK.addHandler(file_handler)
    _SINK.setLevel(logging.DEBUG if debug else logging.INFO)
    return file_handler
