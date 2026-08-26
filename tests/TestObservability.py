import unittest

from src.observability import CorrelationContext, redact_message, safe_call


class TestObservability(unittest.TestCase):
    def test_redaction_removes_credentials(self):
        text = redact_message("phone=13800000000 token=abcdefghijklmnopqrstuvwxyz0123456789")
        self.assertNotIn("13800000000", text)
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz0123456789", text)

    def test_safe_call_reports_failure(self):
        result = safe_call("账号刷新", lambda: 1 / 0)
        self.assertEqual(result.state, "failed")
        self.assertTrue(result.user_message)

    def test_correlation_context_is_scoped(self):
        with CorrelationContext.new("测试", profile_id="a1", revision="r1") as context:
            self.assertEqual(context.operation, "测试")
            self.assertEqual(context.profile_id, "a1")


if __name__ == "__main__":
    unittest.main()
