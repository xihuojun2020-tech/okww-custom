import unittest
from types import SimpleNamespace

from src.task.DailyTask import (
    DailyActivityDetectionError,
    DailyActivityIncomplete,
    DailyTask,
)


class TestDailyActivityFlow(unittest.TestCase):
    def test_daily_points_ocr_miss_is_unknown_instead_of_zero(self):
        class FakeTask:
            def __init__(self):
                self.frames = 0
                self.info = {}

            def ocr(self, *_args, **_kwargs):
                return []

            def next_frame(self):
                self.frames += 1

            def log_info(self, *_args, **_kwargs):
                pass

            def info_set(self, key, value):
                self.info[key] = value

        task = FakeTask()

        self.assertIsNone(DailyTask.get_total_daily_points(task))
        self.assertEqual(2, task.frames)
        self.assertIsNone(task.info['total daily points'])

    def test_daily_points_use_highest_valid_value_from_retries(self):
        responses = iter([
            [SimpleNamespace(name='70', confidence=0.9)],
            [SimpleNamespace(name='领取', confidence=0.9)],
            [SimpleNamespace(name='100', confidence=0.8)],
        ])

        class FakeTask:
            def ocr(self, *_args, **_kwargs):
                return next(responses)

            def next_frame(self):
                pass

            def log_info(self, *_args, **_kwargs):
                pass

            def info_set(self, key, value):
                self.info = (key, value)

        task = FakeTask()

        self.assertEqual(100, DailyTask.get_total_daily_points(task))
        self.assertEqual(('total daily points', 100), task.info)

    def test_unknown_activity_disables_backup_for_stamina_policy(self):
        policy = DailyTask._stamina_policy_activity_ready

        self.assertTrue(policy(None))
        self.assertTrue(policy(True))
        self.assertFalse(policy(False))

    def test_unknown_activity_claims_before_recheck(self):
        task = self._finish_task(True)

        self.assertEqual((180, True), DailyTask._claim_and_recheck_daily_activity(task))
        self.assertLess(task.events.index('claim'), task.events.index('verify'))

    @staticmethod
    def _finish_task(verified_ready):
        class FakeTask:
            def __init__(self):
                self.events = []

            def _publish_daily_stage(self, *_args):
                self.events.append('publish')

            def log_info(self, *_args, **_kwargs):
                self.events.append('log')

            def claim_daily(self):
                self.events.append('claim')

            def open_daily(self):
                self.events.append('verify')
                return 180, verified_ready

            def _notify_incomplete_daily_activity(self, _message):
                self.events.append('notify')

        return FakeTask()

    def test_claim_happens_before_retrying_unknown_activity(self):
        task = self._finish_task(True)

        self.assertTrue(DailyTask._finish_daily_rewards(task, None))
        self.assertLess(task.events.index('claim'), task.events.index('verify'))

    def test_confirmed_incomplete_claims_before_raising(self):
        task = self._finish_task(False)

        with self.assertRaises(DailyActivityIncomplete):
            DailyTask._finish_daily_rewards(task, False)

        self.assertLess(task.events.index('claim'), task.events.index('notify'))

    def test_unknown_after_claim_raises_detection_error(self):
        task = self._finish_task(None)

        with self.assertRaises(DailyActivityDetectionError):
            DailyTask._finish_daily_rewards(task, None)

        self.assertLess(task.events.index('claim'), task.events.index('notify'))

    def test_claim_daily_prefers_ocr_button_and_retries_only_once(self):
        first = SimpleNamespace(name='领取', confidence=0.8)
        retry = SimpleNamespace(name='领取', confidence=0.9)

        class FakeTask:
            def __init__(self):
                self.buttons = iter((first, retry))
                self.clicks = []

            def info_set(self, *_args):
                pass

            def openF2Book(self, *_args):
                pass

            def find_one(self, *_args, **_kwargs):
                return True

            def box_of_screen(self, *_args):
                return object()

            def _find_daily_claim_button(self):
                return next(self.buttons)

            def log_info(self, *_args):
                pass

            def click(self, target, *args, **kwargs):
                self.clicks.append(target)

            def next_frame(self):
                pass

            def ensure_main(self, **_kwargs):
                pass

        task = FakeTask()

        DailyTask.claim_daily(task)

        self.assertEqual([first, retry], task.clicks)

    def test_claim_daily_keeps_coordinate_fallback(self):
        class FakeTask:
            def __init__(self):
                self.clicks = []

            def info_set(self, *_args):
                pass

            def openF2Book(self, *_args):
                pass

            def find_one(self, *_args, **_kwargs):
                return True

            def box_of_screen(self, *_args):
                return object()

            def _find_daily_claim_button(self):
                return None

            def log_info(self, *_args):
                pass

            def click(self, *args, **kwargs):
                self.clicks.append((args, kwargs))

            def ensure_main(self, **_kwargs):
                pass

        task = FakeTask()

        DailyTask.claim_daily(task)

        self.assertEqual((0.930, 0.882), task.clicks[0][0])


if __name__ == '__main__':
    unittest.main()
