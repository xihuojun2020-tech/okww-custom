import unittest

from src.runtime.game_runtime_errors import FrameUnavailable, GameProcessLost
from src.task.BaseWWTask import BaseWWTask


class _Window:
    def __init__(self, exists):
        self.exists = exists


class _DeviceManager:
    def __init__(self, exists):
        self.hwnd_window = _Window(exists)


class _Executor:
    frame = None

    def __init__(self, exists, connected):
        self.device_manager = _DeviceManager(exists)
        self._connected = connected

    def connected(self):
        return self._connected


class TestGameRuntimeErrors(unittest.TestCase):
    def test_missing_window_is_not_reported_as_missing_asset(self):
        task = BaseWWTask.__new__(BaseWWTask)
        task._executor = _Executor(False, False)

        with self.assertRaises(GameProcessLost):
            task.require_game_frame()

    def test_connected_window_without_frame_has_specific_error(self):
        task = BaseWWTask.__new__(BaseWWTask)
        task._executor = _Executor(True, True)

        with self.assertRaises(FrameUnavailable):
            task.require_game_frame()


if __name__ == '__main__':
    unittest.main()
