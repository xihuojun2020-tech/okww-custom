import json
import tempfile
import unittest
import threading
import time
from pathlib import Path
from unittest.mock import patch

import numpy as np

from src.account_switch_evidence import AccountSwitchEvidenceSession, cleanup_account_switch_evidence
from src.task.MultiAccountDailyTask import MultiAccountDailyTask
from src.task.TestAccountSwitchTask import SINGLE_MODE, TestAccountSwitchTask


class TestAccountSwitchEvidence(unittest.TestCase):
    def test_success_discards_frames_without_creating_event(self):
        with tempfile.TemporaryDirectory() as root:
            session = AccountSwitchEvidenceSession("A3", root=root, clock=lambda: 100.0)
            session.record_stage("login_screen")
            session.record_frame(np.zeros((8, 8, 3), dtype=np.uint8), stage="login_screen")
            session.record_click("postmessage", (2, 3), target_box=(1, 2, 4, 5))
            session.succeed()
            self.assertEqual(list(Path(root).iterdir()), [])

    def test_failure_writes_structured_event_and_annotated_frame(self):
        with tempfile.TemporaryDirectory() as root:
            session = AccountSwitchEvidenceSession("A3", root=root, clock=lambda: 100.0)
            session.record_stage("select")
            session.record_identity("A1")
            session.record_frame(np.zeros((12, 16, 3), dtype=np.uint8), stage="select")
            session.record_click("screen", (7, 8), target_box=(2, 3, 4, 5),
                                 screen_point=(107, 208), window_point=(7, 8), attempt=2)
            event_dir = Path(session.fail("selection failed"))
            event = json.loads((event_dir / "event.json").read_text(encoding="utf-8"))
            self.assertEqual(event["target_account"], "A3")
            self.assertEqual(event["last_account"], "A1")
            self.assertEqual(event["events"][0]["stage"], "select")
            self.assertEqual(event["clicks"][0]["screen_point"], [107, 208])
            self.assertTrue(list(event_dir.glob("*.jpg")))

    def test_each_frame_only_marks_its_own_click(self):
        with tempfile.TemporaryDirectory() as root:
            session = AccountSwitchEvidenceSession("A3", root=root, clock=lambda: 100.0)
            frame = np.zeros((80, 100, 3), dtype=np.uint8)
            session.record_frame(frame, stage="ordinary")
            session.record_click("screen", (10, 10), target_box=(5, 5, 10, 10),
                                 window_point=(10, 10), frame=frame)
            session.record_click("postmessage", (80, 70), target_box=(75, 65, 10, 10),
                                 window_point=(80, 70), frame=frame)
            ordinary = session._annotate(session.frames[0][1], session.frames[0][2])
            first = session._annotate(session.frames[1][1], session.frames[1][2])
            second = session._annotate(session.frames[2][1], session.frames[2][2])
            self.assertEqual(int(ordinary[10, 10, 2]), 0)
            self.assertEqual(int(ordinary[70, 80, 2]), 0)
            self.assertGreater(int(first[10, 10, 2]), int(first[70, 80, 2]))
            self.assertGreater(int(second[70, 80, 2]), int(second[10, 10, 2]))

    def test_framework_blur_configuration_is_applied(self):
        with tempfile.TemporaryDirectory() as root:
            session = AccountSwitchEvidenceSession("A3", root=root)
            with patch("ok.util.blur.apply_blur_areas") as blur:
                blur.side_effect = lambda image, *_args: image
                session._annotate(np.zeros((8, 8, 3), dtype=np.uint8))
            self.assertTrue(blur.called)

    def test_stopped_failure_starts_bounded_writer_without_waiting(self):
        with tempfile.TemporaryDirectory() as root:
            session = AccountSwitchEvidenceSession("A3", root=root)
            started = threading.Event()
            release = threading.Event()

            def writer(*_args):
                started.set()
                release.wait(2)

            session._write_failure_event = writer
            begin = time.monotonic()
            session.fail("stopped", stage="stopped", stopped=True)
            elapsed = time.monotonic() - begin
            self.assertLess(elapsed, 0.5)
            self.assertTrue(started.wait(0.5))
            release.set()

    def test_cleanup_removes_old_event_as_a_whole(self):
        with tempfile.TemporaryDirectory() as root:
            old = Path(root) / "old"
            old.mkdir()
            (old / "event.json").write_text("{}", encoding="utf-8")
            with patch("src.account_switch_evidence.time.time", return_value=1000.0):
                import os
                os.utime(old, (0, 0))
                cleanup_account_switch_evidence(root=root, now=1000.0, max_age_seconds=10)
            self.assertFalse(old.exists())

    def test_regular_sampling_keeps_latest_thirty_with_two_second_throttle(self):
        current = [0.0]

        def clock():
            return current[0]

        session = AccountSwitchEvidenceSession("A3", clock=clock)
        frame = np.zeros((2, 2, 3), dtype=np.uint8)
        for index in range(100):
            current[0] = float(index * 2)
            session.record_frame(frame, stage=str(index))
        self.assertEqual(len(session.frames), 30)
        self.assertEqual(session.frames[0][2]["stage"], "70")

    def test_public_entry_point_is_available(self):
        self.assertTrue(callable(getattr(MultiAccountDailyTask, "switch_to_account", None)))

    def test_formal_and_continuous_wrappers_delegate_to_one_entry(self):
        calls = []

        class FakeTask:
            integrity_service = None
            _select_and_login_specific = MultiAccountDailyTask._select_and_login_specific
            _select_and_login_sequence = MultiAccountDailyTask._select_and_login_sequence

            def _next_target_account(self):
                return "A1"

            def switch_to_account(self, target):
                calls.append(target)
                return target

            def log_info(self, *_args, **_kwargs):
                pass

            def _switch_to_login(self):
                pass

            def sleep(self, _seconds):
                pass

        task = FakeTask()
        self.assertEqual(MultiAccountDailyTask._select_and_login_account(task), "A1")
        self.assertEqual(MultiAccountDailyTask._select_and_login_specific(task, "A3"), "A3")
        self.assertEqual(MultiAccountDailyTask._select_and_login_sequence(task, ["A1", "A4"]), ["A1", "A4"])
        self.assertEqual(calls, ["A1", "A3", "A1", "A4"])

    def test_test_task_single_mode_reaches_public_entry_through_instance(self):
        calls = []

        class Executor:
            def get_task_by_class(self, _klass):
                return None

        class MultiTask:
            _select_and_login_specific = MultiAccountDailyTask._select_and_login_specific

            def do_find_account_drop_down(self):
                return object()

            def switch_to_account(self, target):
                calls.append(target)
                return target

        task = object.__new__(TestAccountSwitchTask)
        task._executor = Executor()
        task.config = {
            '测试模式': SINGLE_MODE,
            '目标账号': 'A3',
            '连续账号顺序': 'A1,A3,A4',
            '测试轮数': '1',
        }
        task._get_multi_account_task = lambda: MultiTask()
        task.log_info = lambda *_args, **_kwargs: None
        task.info_set = lambda *_args, **_kwargs: None
        task.sleep = lambda *_args, **_kwargs: None
        task.screenshot = lambda *_args, **_kwargs: None
        task.is_main = lambda **_kwargs: False
        task.log_error = lambda *_args, **_kwargs: None
        with patch("src.task.TestAccountSwitchTask.require_account_runtime_for_task") as gate, \
                patch("src.task.TestAccountSwitchTask.WWOneTimeTask.run"):
            task.run()
        gate.assert_called_once_with(task)
        self.assertEqual(calls, ['A3'])


if __name__ == "__main__":
    unittest.main()
