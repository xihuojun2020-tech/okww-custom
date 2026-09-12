import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
import cv2
import numpy as np

from src.task.AutoAbyssTask import AutoAbyssTask, CharacterScanRecord, detect_character_slots
from src.task.abyss_energy import confirmed_energy


class TestAbyssEnergyRecovery(unittest.TestCase):
    def test_candidates_never_truncate_or_overwrite(self):
        self.assertEqual(confirmed_energy(['0'], 1), 0)
        self.assertEqual(confirmed_energy(['10'], 2), 10)
        for values, count in ((['10'], 1), (['410'], 2), (['7', '4'], 1),
                              (['1', '0'], 2), (['11'], 2), (['07'], 2), (['7x'], 1), ([], 1)):
            with self.subTest(values=values):
                self.assertIsNone(confirmed_energy(values, count))

    def task(self):
        task = AutoAbyssTask.__new__(AutoAbyssTask)
        for name in ('log_info', 'log_warning', 'screenshot', 'ensure_in_front', 'sleep', 'scroll_relative'):
            setattr(task, name, Mock())
        task._revisit_energy_page = Mock()
        return task

    def records(self):
        return (CharacterScanRecord('a', 'A', 4, 90, .9, 1, 0),
                CharacterScanRecord('a', 'A', 0, 90, .9, 2, 0))

    def test_old_wrong_value_is_corrected_only_after_both_sides_agree(self):
        task = self.task()
        old, new = self.records()
        frame = np.zeros((4, 4, 3), np.uint8)
        task._character_pages = {1: (.3, (old,)), 2: (.4, (new,))}
        task._fresh_record_energy = Mock(return_value=(0, [0, 0], frame))
        records, current, _ = task._reconcile_energy_conflicts([old], [new], [new], 2, {1: frame, 2: frame})
        self.assertEqual((records[0].energy, current[0].energy), (0, 0))
        self.assertEqual([c.args[0] for c in task._revisit_energy_page.call_args_list], [1, 2])
        self.assertEqual(old.energy, 4)
        self.assertEqual(task._character_pages[1][1][0].energy, 0)

    def test_persistent_or_unknown_conflict_does_not_change_ledger(self):
        for result in ((4, [4, 4]), (None, [None, 0])):
            task = self.task()
            old, new = self.records()
            frame = np.zeros((4, 4, 3), np.uint8)
            task._character_pages = {1: (.3, (old,)), 2: (.4, (new,))}
            task._fresh_record_energy = Mock(side_effect=[(*result, frame), (0, [0, 0], frame)])
            with self.assertRaisesRegex(Exception, '体力读数矛盾'):
                task._reconcile_energy_conflicts([old], [new], [new], 2, {1: frame, 2: frame})
            self.assertEqual(task._character_pages[1][1][0].energy, 4)

    def test_later_conflict_does_not_partially_commit_earlier_correction(self):
        task = self.task()
        old, new = self.records()
        b_old = CharacterScanRecord('b', 'B', 7, 90, .9, 1, 1)
        b_new = CharacterScanRecord('b', 'B', 8, 90, .9, 2, 1)
        frame = np.zeros((4, 4, 3), np.uint8)
        task._character_pages = {1: (.3, (old, b_old)), 2: (.4, (new, b_new))}
        task._fresh_record_energy = Mock(side_effect=[(n, [n, n], frame) for n in (0, 0, 7, 8)])
        with self.assertRaisesRegex(Exception, '体力读数矛盾'):
            task._reconcile_energy_conflicts([old, b_old], [new, b_new], [new, b_new], 2, {1: frame, 2: frame})
        self.assertEqual(task._character_pages[1][1][0].energy, 4)

    def test_fresh_samples_require_same_identity_and_value(self):
        task = self.task()
        old, _ = self.records()
        frame = np.zeros((4, 4, 3), np.uint8)
        task._wait_stable_character_frame = Mock(return_value=frame)
        task._relocate_record = Mock(return_value=SimpleNamespace(slot=(0, 0)))
        task._read_slot_energy = Mock(side_effect=[0, 4])
        self.assertIsNone(task._fresh_record_energy(old, 1)[0])
        task._relocate_record.return_value = None
        self.assertIsNone(task._fresh_record_energy(old, 1)[0])
        self.assertEqual(task._read_slot_energy.call_count, 2)

    def test_revisit_stuck_scroll_is_bounded(self):
        task = self.task()
        task._character_pages = {1: (.3, ())}
        task._wait_stable_character_frame = Mock(return_value=np.zeros((4, 4, 3), np.uint8))
        task._page_matches = Mock(return_value=False)
        with patch('src.task.AutoAbyssTask.scroll_thumb_center', return_value=.4):
            with self.assertRaisesRegex(Exception, '无法重新定位'):
                AutoAbyssTask._revisit_energy_page(task, 1)
        self.assertEqual(task.scroll_relative.call_count, 2)

    def test_revisit_matching_position_with_wrong_identity_stops_without_scroll(self):
        task = self.task()
        task._character_pages = {1: (.3, ())}
        task._wait_stable_character_frame = Mock(return_value=np.zeros((4, 4, 3), np.uint8))
        task._page_matches = Mock(return_value=False)
        with patch('src.task.AutoAbyssTask.scroll_thumb_center', return_value=.3):
            with self.assertRaisesRegex(Exception, '无法重新定位'):
                AutoAbyssTask._revisit_energy_page(task, 1)
        task.scroll_relative.assert_not_called()

    def test_stop_propagates_without_changing_records(self):
        from ok import TaskDisabledException
        task = self.task()
        old, new = self.records()
        frame = np.zeros((4, 4, 3), np.uint8)
        task._character_pages = {1: (.3, (old,)), 2: (.4, (new,))}
        task._revisit_energy_page.side_effect = TaskDisabledException()
        with self.assertRaises(TaskDisabledException):
            task._reconcile_energy_conflicts([old], [new], [new], 2, {1: frame, 2: frame})
        self.assertEqual(task._character_pages[1][1][0].energy, 4)

    def test_real_september12_cards_at_three_resolutions(self):
        from onnxocr.onnx_paddleocr import ONNXPaddleOcr
        engine = ONNXPaddleOcr(use_openvino=True, use_npu=False, use_angle_cls=False)
        task = self.task()
        task.ocr = lambda *args, frame, **kw: [SimpleNamespace(name=text)
            for _, (text, _) in engine.ocr(frame)[0]]
        expected = ([10, 10, 10, 0, 0, 0, 5, 5, 7, 2, 2, 7, 0, 8],
                    [5, 7, 2, 2, 7, 0, 8, 10, 9, 7, 10, 10, 10, 10])
        for page in (1, 2):
            source = cv2.imread(f'tests/fixtures/abyss_energy_1112/page{page}.png')
            for width, height in ((1280, 720), (1920, 1080), (2560, 1440)):
                frame = cv2.resize(source, (width, height))
                with self.subTest(page=page, height=height):
                    values = [task._read_slot_energy(frame, slot) for slot in detect_character_slots(frame)]
                    self.assertEqual(values, expected[page - 1])


if __name__ == '__main__':
    unittest.main()
