"""Headless task exceptions for the Wuthering Waves native runtime."""

from contextlib import contextmanager

from gameframe.api import Cancelled


class TaskDisabledException(Exception):
    """An explicit stop while production task code is running."""


class CannotFindException(Exception):
    pass


class FinishedException(Exception):
    pass


class WaitFailedException(Exception):
    pass


class CaptureException(Exception):
    pass


class HotkeyConfigException(Exception):
    def __init__(self, key):
        self.key = key
        super().__init__(f"{key} is invalid, please check the hotkey config!")


@contextmanager
def translate_cancelled():
    """Keep a core stop out of production ``except Exception`` recovery loops."""
    try:
        yield
    except Cancelled as error:
        raise TaskDisabledException(str(error)) from error
