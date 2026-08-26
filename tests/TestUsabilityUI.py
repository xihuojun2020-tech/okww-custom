import unittest

from src.gui.AccountFilterBar import AccountFilter


class TestUsabilityUI(unittest.TestCase):
    def test_filter_model_keeps_text_and_sequence(self):
        current = AccountFilter("A3", "序列2", True)
        self.assertEqual(current.text, "A3")
        self.assertEqual(current.sequence_id, "序列2")
        self.assertTrue(current.incomplete_only)


if __name__ == "__main__":
    unittest.main()
