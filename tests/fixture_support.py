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
        "profile_id": str(UUID(int=1, version=4)),
    },
    "A3": {
        "short_name": "A3",
        "nickname": "测试账号三",
        "phone": "19910000003",
        "masked_phone": "199****0003",
        "alternate_login_name": "UTEST0003A",
        "game_feature_code": "TEST-FEATURE-A3",
        "profile_id": str(UUID(int=3, version=4)),
    },
    "A4": {
        "short_name": "A4",
        "nickname": "测试账号四",
        "phone": "19910000004",
        "masked_phone": "199****0004",
        "alternate_login_name": "UTEST0004A",
        "game_feature_code": "TEST-FEATURE-A4",
        "profile_id": str(UUID(int=4, version=4)),
    },
}


def synthetic_identity(short_name):
    """Return an isolated synthetic account identity for tests and examples."""
    if short_name in _SYNTHETIC_IDENTITIES:
        return dict(_SYNTHETIC_IDENTITIES[short_name])
    import re
    if not re.fullmatch(r'A[1-9][0-9]{0,3}', short_name):
        raise ValueError('synthetic short name must be A1–A9999')
    number = int(short_name[1:])
    return {
        'short_name': short_name, 'nickname': f'合成测试账号{number}',
        'phone': str(19910000000 + number), 'masked_phone': f'199****{number:04d}',
        'alternate_login_name': f'UTEST{number:04d}A',
        'game_feature_code': f'TEST-FEATURE-{short_name}',
        'profile_id': str(UUID(int=number, version=4)),
    }


def make_account_environment(root, *, names=('A1', 'A3', 'A4'), publish=True):
    """Build a real, trusted schema-v1 store using synthetic identities only."""
    import copy
    from types import SimpleNamespace
    from src.account_repository import AccountRepository
    from src.config_integrity import ConfigIntegrityService, _atomic_write_json_unchecked, fingerprint, normalize_master
    from src.account_publish_service import AccountPublishService

    service = ConfigIntegrityService(root)
    profiles = {}
    for name in names:
        identity = synthetic_identity(name)
        profiles[identity['profile_id']] = {
            **identity, 'display_name': name, 'account_aliases': [], 'schedule': {}, 'extensions': {},
            'task_config': {
                'Which to Farm': 'Tacet Suppression', 'Which Tacet Suppression to Farm': 1,
                'Which Forgery Challenge to Farm': 1, 'Material Selection': 'Shell Credit',
                'Farm Nightmare Nest for Daily Echo': False, 'Nightmare Which to Farm': [],
                'Tacet Discord Nests to Farm': [], 'Auto Farm all Nightmare Nest': False,
                'Weekly Garden Check Day': '无', 'Merge Echo on Sunday': False,
                '备用识别名称': '使用', '备用识别名称内容': identity['alternate_login_name'],
            },
        }
    master = {'schema_version': 1, 'config_id': 'synthetic-test', 'timezone': 'Asia/Shanghai',
              'profiles': profiles, 'sequences': {'S1': list(profiles)}, 'extensions': {}}
    _atomic_write_json_unchecked(service.paths.master, master)
    _atomic_write_json_unchecked(service.paths.working, service._rebuild_working(master, {}))
    _atomic_write_json_unchecked(service.paths.runtime, {
        'accepted_master_fingerprint': fingerprint(normalize_master(master)), 'completed_at': {}, 'progress': {}})
    publisher = AccountPublishService(root)
    if publish:
        publisher.publish(profiles=profiles, index=master, sequences=master['sequences'], expected_revision='')
    return SimpleNamespace(root=Path(root), integrity=service, master=copy.deepcopy(master),
                           repository=AccountRepository(root, integrity_service=service), publisher=publisher)


def require_fixture(test_case, relative_path):
    """Skip an image-based test when its local, untracked fixture is unavailable."""
    if not (REPOSITORY_ROOT / relative_path).is_file():
        test_case.skipTest(f'local image fixture is unavailable: {relative_path}')
    return relative_path
