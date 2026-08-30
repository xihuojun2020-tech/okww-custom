from pathlib import Path
from uuid import UUID


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

_SYNTHETIC_IDENTITIES = {
    "A1": {
        "short_name": "A1",
        "nickname": "测试账号一",
        "phone": "19910000001",
        "masked_phone": "199****0001",
        "alternate_login_name": "UTEST0001A",
        "game_feature_code": "TEST-FEATURE-A1",
        "profile_id": str(UUID(int=1)),
    },
    "A3": {
        "short_name": "A3",
        "nickname": "测试账号三",
        "phone": "19910000003",
        "masked_phone": "199****0003",
        "alternate_login_name": "UTEST0003A",
        "game_feature_code": "TEST-FEATURE-A3",
        "profile_id": str(UUID(int=3)),
    },
    "A4": {
        "short_name": "A4",
        "nickname": "测试账号四",
        "phone": "19910000004",
        "masked_phone": "199****0004",
        "alternate_login_name": "UTEST0004A",
        "game_feature_code": "TEST-FEATURE-A4",
        "profile_id": str(UUID(int=4)),
    },
}


def synthetic_identity(short_name):
    """Return an isolated synthetic account identity for tests and examples."""
    return dict(_SYNTHETIC_IDENTITIES[short_name])


def require_fixture(test_case, relative_path):
    """Skip an image-based test when its local, untracked fixture is unavailable."""
    if not (REPOSITORY_ROOT / relative_path).is_file():
        test_case.skipTest(f'local image fixture is unavailable: {relative_path}')
    return relative_path
