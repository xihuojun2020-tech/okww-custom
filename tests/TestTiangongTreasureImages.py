"""Real OCR of the user's sanitized screenshots; never sends input."""
from config import config
from ok.test.TaskTestCase import TaskTestCase
from src.task.TiangongTreasureTask import TiangongTreasureTask
from src.task.tiangong_treasure import hardest

config['debug'] = True


class TestTiangongTreasureImages(TaskTestCase):
    task_class = TiangongTreasureTask
    config = config

    def test_page_score_and_locked_stage(self):
        self.set_image('tests/fixtures/tiangong_treasure/page.png')
        frame = self.task.require_game_frame()
        self.assertTrue(self.task._page(frame))
        self.assertTrue(self.task._selected(frame, 0))
        self.assertEqual(self.task._state(frame, 0), dict(status='pending', score=30415))
        self.assertEqual(self.task._state(frame, 1), dict(status='pending', score=0))
        self.assertEqual(self.task._state(frame, 3)['status'], 'locked')
        self.assertFalse(hardest(self.task.ocr(*self.task.LEVEL, frame=frame)))

    def test_formation_and_zero_score_result_are_disjoint(self):
        self.set_image('tests/fixtures/tiangong_treasure/formation.png')
        frame = self.task.require_game_frame()
        self.assertTrue(self.task._formation(frame))
        self.assertFalse(self.task._page(frame))
        self.assertFalse(self.task._result(frame))
        self.set_image('tests/fixtures/tiangong_treasure/result.png')
        frame = self.task.require_game_frame()
        self.assertTrue(self.task._result(frame))
        self.assertFalse(self.task._formation(frame))
        self.assertFalse(self.task._page(frame))

    def test_real_highest_level_and_expanded_menu(self):
        self.set_image('tests/fixtures/tiangong_treasure/hard.png')
        frame = self.task.require_game_frame()
        self.assertTrue(hardest(self.task.ocr(*self.task.LEVEL, frame=frame)))
        self.set_image('tests/fixtures/tiangong_treasure/menu.png')
        frame = self.task.require_game_frame()
        self.assertTrue(any('困难' in b.name for b in self.task.ocr(.66, .51, .96, .74, frame=frame)))
        self.assertFalse(self.task._result(frame))

    def test_selected_zero_and_previously_completed_stage(self):
        self.set_image('tests/fixtures/tiangong_treasure/selected_zero.png')
        frame = self.task.require_game_frame()
        self.assertEqual(self.task._state(frame, 0), dict(status='completed', score=90952))
        self.assertEqual(self.task._state(frame, 1), dict(status='pending', score=0))
