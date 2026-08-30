import io
import logging
import unittest

from src.observability import (
    RedactingFilter,
    _reset_sensitive_values_for_tests,
    register_sensitive_values,
)


class TestLoggingRedaction(unittest.TestCase):
    def tearDown(self):
        _reset_sensitive_values_for_tests()

    def _render(self, message, *args, exc_info=None):
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger = logging.getLogger(f"redaction-test-{id(stream)}")
        logger.handlers = [handler]
        logger.filters = [RedactingFilter()]
        logger.propagate = False
        logger.setLevel(logging.DEBUG)
        logger.error(message, *args, exc_info=exc_info)
        return stream.getvalue()

    def test_filter_redacts_message_arguments_and_registered_values(self):
        register_sensitive_values(["TEST-FEATURE-A3"])
        rendered = self._render(
            "phone=%s masked=%s login=%s feature=%s",
            "19910000003", "199****0003", "UTEST0003A", "TEST-FEATURE-A3",
        )
        for secret in (
            "19910000003", "199****0003", "UTEST0003A", "TEST-FEATURE-A3",
        ):
            self.assertNotIn(secret, rendered)

    def test_filter_redacts_traceback(self):
        try:
            raise RuntimeError("login UTEST0004A phone 19910000004")
        except RuntimeError:
            import sys
            rendered = self._render("failed", exc_info=sys.exc_info())
        self.assertNotIn("UTEST0004A", rendered)
        self.assertNotIn("19910000004", rendered)
        self.assertIn("RuntimeError", rendered)


if __name__ == "__main__":
    unittest.main()
