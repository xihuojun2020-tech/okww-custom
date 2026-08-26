import inspect
import unittest

from src.task.DailyTask import FORGERY_DOMAIN_OPTIONS, FORGERY_DOMAIN_NAMES


class TestForgeryDomainLabels(unittest.TestCase):
    def test_first_four_domains_have_requested_names(self):
        self.assertEqual(
            [label for _value, label in FORGERY_DOMAIN_OPTIONS[:4]],
            [
                "陨翼云渊-武器及技能材料：迅刀",
                "静灭云渊-武器及技能材料：音感仪",
                "裂斩云渊-武器及技能材料：长刃",
                "碎蚀云渊-武器及技能材料：臂铠",
            ],
        )
        self.assertEqual([value for value, _label in FORGERY_DOMAIN_OPTIONS[:4]], [1, 2, 3, 4])

    def test_dropdown_keeps_all_legacy_integer_positions(self):
        self.assertEqual(len(FORGERY_DOMAIN_OPTIONS), 20)
        self.assertEqual([value for value, _label in FORGERY_DOMAIN_OPTIONS], list(range(1, 21)))
        source = inspect.getsource(__import__(
            "src.task.DailyTask", fromlist=["DailyTask"]).DailyTask.__init__)
        self.assertIn("'type': 'integer_drop_down'", source)


if __name__ == "__main__":
    unittest.main()
