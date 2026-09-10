import unittest
from unittest.mock import Mock, PropertyMock, patch

import cv2
import numpy as np

from config import config
from ok import TaskDisabledException
from src.task.PianoTeachingTask import PianoTeachingTask
from src.task.piano import (
    ChordEvent, KEY_ORDER, PianoDetector, PianoStateMachine,
    X_CENTERS, Y_CENTERS, key_for,
)


def piano_frame(keys=(), width=1280, height=720):
    frame = np.full((height, width, 3), 70, dtype=np.uint8)
    scale = height / 1440
    for row, y_ratio in enumerate(Y_CENTERS):
        for column, x_ratio in enumerate(X_CENTERS):
            center = round(x_ratio * width), round(y_ratio * height)
            cv2.circle(frame, center, max(3, round(9 * scale)), (190, 190, 190), -1)
            key = key_for(row, column)
            if key in keys:
                color = keys[key] if isinstance(keys, dict) else (70, 190, 240)
                cv2.circle(frame, center, round(39 * scale), color, max(3, round(12 * scale)))
    return frame


class TestPianoTeaching(unittest.TestCase):
    def test_task_is_registered_in_activities(self):
        self.assertIn(["src.task.PianoTeachingTask", "PianoTeachingTask"], config["onetime_tasks"])
        self.assertEqual(PianoTeachingTask.navigation_section, "activities")

    def test_layout_and_reference_mapping(self):
        self.assertEqual(key_for(1, 1), "S")
        self.assertEqual(len(KEY_ORDER), 21)
        with self.assertRaises(ValueError):
            key_for(3, 0)

    def test_detector_finds_single_and_rejects_competing_highlights(self):
        detector = PianoDetector()
        self.assertEqual(detector.analyze(piano_frame()).status, "no_highlight")
        self.assertEqual(detector.analyze(piano_frame({"S"})).on_keys, ("S",))
        result = detector.analyze(piano_frame({"Q", "S", "M"}))
        self.assertEqual(result.status, "ambiguous")
        self.assertEqual(result.on_keys, ("Q", "S", "M"))

    def test_detector_accepts_a_clearly_dominant_single_highlight(self):
        detector = PianoDetector()
        result = detector.analyze(piano_frame({"S": (70, 190, 240), "Y": (70, 145, 180)}))
        self.assertEqual(result.status, "candidate")
        self.assertEqual(result.on_keys, ("S",))
        self.assertIn("over Y", result.reason)

    def test_detector_rejects_wrong_scene_and_aspect_ratio(self):
        detector = PianoDetector()
        self.assertEqual(detector.analyze(np.zeros((720, 1280, 3), np.uint8)).status, "invalid_roi")
        self.assertEqual(detector.analyze(piano_frame(width=1200)).status, "invalid_roi")

    def test_state_machine_confirms_single_keys_and_does_not_repeat_held_keys(self):
        detector = PianoDetector()
        tracker = PianoStateMachine()
        events = []
        for keys in ({"S"}, {"S"}, {"D"}, {"D"}, {"D"}):
            event = tracker.step(detector.analyze(piano_frame(keys)))
            if event:
                events.append(event.keys)
        self.assertEqual(events, [("S",), ("D",)])

    def test_transition_reset_allows_a_new_segment_to_repeat_the_same_key(self):
        detector = PianoDetector()
        tracker = PianoStateMachine()
        note = detector.analyze(piano_frame({"S"}))
        self.assertIsNone(tracker.step(note))
        self.assertEqual(tracker.step(note).keys, ("S",))
        tracker.reset()
        self.assertIsNone(tracker.step(note))
        self.assertEqual(tracker.step(note).keys, ("S",))

    def test_multiple_highlights_never_produce_an_event(self):
        detector = PianoDetector()
        tracker = PianoStateMachine()
        result = detector.analyze(piano_frame({"S", "D"}))
        for _ in range(4):
            self.assertIsNone(tracker.step(result))

    def test_long_capture_gap_does_not_count_as_consecutive_frames(self):
        detector = PianoDetector()
        tracker = PianoStateMachine()
        result = detector.analyze(piano_frame({"S"}))
        self.assertIsNone(tracker.step(result, 1.0))
        self.assertIsNone(tracker.step(result, 1.5))
        self.assertEqual(tracker.step(result, 1.55).keys, ("S",))

    def test_task_presses_and_releases_one_key(self):
        task = PianoTeachingTask.__new__(PianoTeachingTask)
        task._pressed_keys = []
        calls = []
        task.send_key_down = lambda key: calls.append(("down", key))
        task.send_key_up = lambda key: calls.append(("up", key))
        task.sleep = lambda seconds: calls.append(("sleep", seconds))
        task._press_event(ChordEvent(("S",)), 0.03)
        self.assertEqual(calls, [("down", "s"), ("sleep", 0.03), ("up", "s")])
        self.assertEqual(task._pressed_keys, [])

    def test_task_releases_every_attempted_key_after_failure(self):
        task = PianoTeachingTask.__new__(PianoTeachingTask)
        task._pressed_keys = []
        task.send_key_down = Mock(side_effect=RuntimeError("down failed"))
        task.send_key_up = Mock()
        task.sleep = Mock()
        with self.assertRaisesRegex(RuntimeError, "down failed"):
            task._press_event(ChordEvent(("S",)), 0.03)
        self.assertEqual([call.args[0] for call in task.send_key_up.call_args_list], ["s"])
        self.assertEqual(task._pressed_keys, [])

    def test_one_release_failure_does_not_skip_other_keys(self):
        task = PianoTeachingTask.__new__(PianoTeachingTask)
        task._pressed_keys = ["s", "d"]
        task.send_key_up = Mock(side_effect=[RuntimeError("d stuck"), None])
        task.log_warning = Mock()
        task._release_pressed()
        self.assertEqual([call.args[0] for call in task.send_key_up.call_args_list], ["d", "s"])
        self.assertEqual(task._pressed_keys, ["d"])

    def test_diagnostic_capture_contains_only_the_piano_area(self):
        frame = np.zeros((720, 1280, 3), np.uint8)
        crop = PianoTeachingTask._diagnostic_crop(frame)
        self.assertEqual(crop.shape, (230, 640, 3))

    def test_detection_summary_contains_calibration_evidence(self):
        result = PianoDetector().analyze(piano_frame({"S"}))
        summary = PianoTeachingTask._detection_summary(result)
        self.assertIn("status=candidate", summary)
        self.assertIn("valid_dots=21/21", summary)
        self.assertIn("on=S", summary)
        self.assertIn("top=S:", summary)

    def test_story_frame_waits_until_user_stops_instead_of_reporting_not_found(self):
        task = PianoTeachingTask.__new__(PianoTeachingTask)
        task.config = {"Sample Interval": 0.03, "Key Hold Time": 0.03, "Post Key Delay": 0.15}
        task._pressed_keys = []
        task.info_set = Mock()
        task.log_info = Mock()
        task.sleep = Mock()
        task.next_frame = Mock(side_effect=[np.zeros((720, 1280, 3), np.uint8), TaskDisabledException()])
        task.screenshot = Mock()
        task.send_key_up = Mock()
        with patch.object(PianoTeachingTask, "game_lang", new_callable=PropertyMock,
                          return_value="zh_CN"), \
                patch("src.task.PianoTeachingTask.WWOneTimeTask.run"), \
                self.assertRaises(TaskDisabledException):
            task.run()
        task.info_set.assert_any_call("弹琴状态", "剧情或转场中，等待弹琴界面")
        task.screenshot.assert_not_called()


if __name__ == "__main__":
    unittest.main()
