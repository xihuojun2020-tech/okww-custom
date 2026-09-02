import unittest

from src.task.BaseWWTask import BaseWWTask


class TestStaminaAccounting(unittest.TestCase):

    def test_projected_stamina_uses_backup_without_negative_current(self):
        current, backup, total = BaseWWTask.project_stamina_after_use(0, 106, 60)

        self.assertEqual((0, 46, 46), (current, backup, total))

    def test_projected_stamina_spends_current_before_backup(self):
        current, backup, total = BaseWWTask.project_stamina_after_use(30, 100, 60)

        self.assertEqual((0, 70, 70), (current, backup, total))


if __name__ == '__main__':
    unittest.main()
