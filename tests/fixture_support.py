from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def require_fixture(test_case, relative_path):
    """Skip an image-based test when its local, untracked fixture is unavailable."""
    if not (REPOSITORY_ROOT / relative_path).is_file():
        test_case.skipTest(f'local image fixture is unavailable: {relative_path}')
    return relative_path
