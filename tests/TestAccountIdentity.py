import unittest

from src.account_identity import (
    AccountIdentityError,
    extract_account_identity,
    match_profile_identity,
    masked_phone,
    normalize_identity,
    resolve_profile_identity,
    resolve_profile_short_names,
    short_profile_name,
)


class TestAccountIdentity(unittest.TestCase):
    def setUp(self):
        self.profiles = {
            "【A1-small-19910000005】": {"account_aliases": ["U-A1"]},
            "【A10-large-19910000006】": {"account_aliases": ["U-A10"]},
        }

    def test_short_names_are_bounded_and_exact(self):
        self.assertEqual("A1", short_profile_name("【A1-small-19910000005】"))
        self.assertEqual("A10", short_profile_name("【A10-large-19910000006】"))
        self.assertIsNone(short_profile_name("prefix-A1"))
        self.assertEqual(
            ["【A1-small-19910000005】", "【A10-large-19910000006】"],
            resolve_profile_short_names(("A1", "A10"), self.profiles),
        )

    def test_alias_and_masked_phone_resolve_without_leaking_phone_in_error(self):
        self.assertEqual("【A1-small-19910000005】", resolve_profile_identity("u-a1", self.profiles))
        self.assertEqual("【A1-small-19910000005】", resolve_profile_identity("199****0005", self.profiles))
        self.assertEqual("199****0005", masked_phone("19910000005"))

    def test_duplicate_identity_is_rejected_with_redacted_message(self):
        profiles = {"A1": {"account_aliases": ["shared"]}, "A3": {"account_aliases": ["shared"]}}
        with self.assertRaises(AccountIdentityError) as raised:
            resolve_profile_identity("shared", profiles)
        self.assertNotIn("19910000005", str(raised.exception))

    def test_missing_or_empty_sequence_is_rejected(self):
        self.assertIsNone(resolve_profile_identity("missing", self.profiles))
        with self.assertRaises(AccountIdentityError):
            resolve_profile_short_names((), self.profiles)

    def test_explicit_identity_fields_and_masked_phone_priority(self):
        profiles = {
            "A1": {
                "profile_id": "A1",
                "display_name": "A1",
                "phone": "19910000005",
                "masked_phone": "199****0007",
                "nickname": "夜归",
                "alternate_login_name": "UTEST0001A",
                "game_feature_code": "FC-A1",
            }
        }
        identity = extract_account_identity("A1", profiles["A1"])
        self.assertEqual("199****0007", identity.masked_phone)
        self.assertEqual("UTEST0001A", identity.alternate_login_name)
        self.assertEqual("A1", match_profile_identity("199****0007", profiles))
        self.assertEqual("A1", match_profile_identity("UTEST0001A", profiles))
        self.assertIsNone(match_profile_identity("FC-A1", profiles))
        self.assertEqual("A1", match_profile_identity("FC-A1", profiles, strict_feature_code=True))

    def test_fullwidth_login_identity_matches_ascii_profile(self):
        profiles = {"A3": {"alternate_login_name": "UTEST0003A"}}

        self.assertEqual("utest0003a", normalize_identity("ＵＴＥＳＴ０００３Ａ"))
        self.assertEqual("A3", resolve_profile_identity("ＵTEST0003A", profiles))


if __name__ == "__main__":
    unittest.main()
