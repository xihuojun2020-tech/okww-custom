import unittest

from src.account_identity import (
    AccountIdentityError,
    masked_phone,
    resolve_profile_identity,
    resolve_profile_short_names,
    short_profile_name,
)


class TestAccountIdentity(unittest.TestCase):
    def setUp(self):
        self.profiles = {
            "【A1-small-15300000001】": {"account_aliases": ["U-A1"]},
            "【A10-large-15300000010】": {"account_aliases": ["U-A10"]},
        }

    def test_short_names_are_bounded_and_exact(self):
        self.assertEqual("A1", short_profile_name("【A1-small-15300000001】"))
        self.assertEqual("A10", short_profile_name("【A10-large-15300000010】"))
        self.assertIsNone(short_profile_name("prefix-A1"))
        self.assertEqual(
            ["【A1-small-15300000001】", "【A10-large-15300000010】"],
            resolve_profile_short_names(("A1", "A10"), self.profiles),
        )

    def test_alias_and_masked_phone_resolve_without_leaking_phone_in_error(self):
        self.assertEqual("【A1-small-15300000001】", resolve_profile_identity("u-a1", self.profiles))
        self.assertEqual("【A1-small-15300000001】", resolve_profile_identity("153****0001", self.profiles))
        self.assertEqual("153****0001", masked_phone("15300000001"))

    def test_duplicate_identity_is_rejected_with_redacted_message(self):
        profiles = {"A1": {"account_aliases": ["shared"]}, "A3": {"account_aliases": ["shared"]}}
        with self.assertRaises(AccountIdentityError) as raised:
            resolve_profile_identity("shared", profiles)
        self.assertNotIn("15300000001", str(raised.exception))

    def test_missing_or_empty_sequence_is_rejected(self):
        self.assertIsNone(resolve_profile_identity("missing", self.profiles))
        with self.assertRaises(AccountIdentityError):
            resolve_profile_short_names((), self.profiles)


if __name__ == "__main__":
    unittest.main()
