import unittest
from unittest.mock import Mock

import cv2
import numpy as np

from config import config
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
            if key_for(row, column) in keys:
                cv2.circle(frame, center, round(39 * scale), (70, 190, 240), max(3, round(12 * scale)))
    return frame


class TestPianoTeaching(unittest.TestCase):
    def test_task_is_registered_in_test_features(self):
        self.assertIn(["src.task.PianoTeachingTask", "PianoTeachingTask"], config["onetime_tasks"])
        self.assertEqual(PianoTeachingTask.navigation_section, "tests")

    def test_layout_and_reference_mapping(self):
        self.assertEqual(key_for(1, 1), "S")
        self.assertEqual(len(KEY_ORDER), 21)
        with self.assertRaises(ValueError):
            key_for(3, 0)

    def test_detector_finds_single_and_multiple_highlights(self):
        detector = PianoDetector()
        self.assertEqual(detector.analyze(piano_frame()).status, "no_highlight")
        self.assertEqual(detector.analyze(piano_frame({"S"})).on_keys, ("S",))
        result = detector.analyze(piano_frame({"Q", "S", "M"}))
        self.assertEqual(result.status, "candidate")
        self.assertEqual(result.on_keys, ("Q", "S", "M"))

    def test_detector_rejects_wrong_scene_and_aspect_ratio(self):
        detector = PianoDetector()
        self.assertEqual(detector.analyze(np.zeros((720, 1280, 3), np.uint8)).status, "invalid_roi")
        self.assertEqual(detector.analyze(piano_frame(width=1200)).status, "invalid_roi")

    def test_state_machine_confirms_chords_and_does_not_repeat_held_keys(self):
        detector = PianoDetector()
        tracker = PianoStateMachine()
        events = []
        for keys in ({"S"}, {"S"}, {"S", "D"}, {"S", "D"}, {"S", "D"}):
            event = tracker.step(detector.analyze(piano_frame(keys)))
            if event:
                events.append(event.keys)
        self.assertEqual(events, [("S",), ("D",)])

        tracker.step(detector.analyze(piano_frame({"D"})))
        tracker.step(detector.analyze(piano_frame({"D"})))
        self.assertIsNone(tracker.step(detector.analyze(piano_frame({"S", "D"}))))
        self.assertEqual(tracker.step(detector.analyze(piano_frame({"S", "D"}))).keys, ("S",))

    def test_long_capture_gap_does_not_count_as_consecutive_frames(self):
        detector = PianoDetector()
        tracker = PianoStateMachine()
        result = detector.analyze(piano_frame({"S"}))
        self.assertIsNone(tracker.step(result, 1.0))
        self.assertIsNone(tracker.step(result, 1.5))
        self.assertEqual(tracker.step(result, 1.55).keys, ("S",))

    def test_task_presses_chord_together_and_releases_in_reverse(self):
        task = PianoTeachingTask.__new__(PianoTeachingTask)
        task._pressed_keys = []
        calls = []
        task.send_key_down = lambda key: calls.append(("down", key))
        task.send_key_up = lambda key: calls.append(("up", key))
        task.sleep = lambda seconds: calls.append(("sleep", seconds))
        task._press_event(ChordEvent(("S", "D")), 0.03)
        self.assertEqual(calls, [("down", "s"), ("down", "d"), ("sleep", 0.03),
                                 ("up", "d"), ("up", "s")])
        self.assertEqual(task._pressed_keys, [])

    def test_task_releases_every_attempted_key_after_failure(self):
        task = PianoTeachingTask.__new__(PianoTeachingTask)
        task._pressed_keys = []
        task.send_key_down = Mock(side_effect=[None, RuntimeError("down failed")])
        task.send_key_up = Mock()
        task.sleep = Mock()
        with self.assertRaisesRegex(RuntimeError, "down failed"):
            task._press_event(ChordEvent(("S", "D")), 0.03)
        self.assertEqual([call.args[0] for call in task.send_key_up.call_args_list], ["d", "s"])
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


if __name__ == "__main__":
    unittest.main()
