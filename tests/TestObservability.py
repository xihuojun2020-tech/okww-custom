import unittest

from src.observability import (
    CorrelationContext,
    _reset_sensitive_values_for_tests,
    redact_message,
    register_sensitive_values,
    safe_call,
)


class TestObservability(unittest.TestCase):
    def test_authorization_and_cookie_headers_do_not_leave_tail_credentials(self):
        text = redact_message('Authorization: Bearer SECRET_A\nCookie: first=SECRET_B; second=SECRET_C')
        for secret in ('SECRET_A', 'SECRET_B', 'SECRET_C'):
            self.assertNotIn(secret, text)

    def tearDown(self):
        _reset_sensitive_values_for_tests()

    def test_redaction_removes_credentials(self):
        text = redact_message(
            "phone=19910000002 masked=199****0002 "
            "alternate=UTEST0002A token=abcdefghijklmnopqrstuvwxyz0123456789")
        self.assertNotIn("19910000002", text)
        self.assertNotIn("199****0002", text)
        self.assertNotIn("UTEST0002A", text)
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz0123456789", text)

    def test_registered_identity_fields_are_redacted(self):
        register_sensitive_values(["TEST-FEATURE-A1", "测试昵称"])
        text = redact_message({"feature": "TEST-FEATURE-A1", "nickname": "测试昵称"})
        self.assertNotIn("TEST-FEATURE-A1", text)
        self.assertNotIn("测试昵称", text)

    def test_normal_repository_path_is_not_treated_as_a_token(self):
        path = "E:/AI work/ok-wuthering-waves-master"
        self.assertEqual(path, redact_message(path))

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
