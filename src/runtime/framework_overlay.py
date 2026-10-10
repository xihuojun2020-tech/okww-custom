"""Process-local overrides for the pinned ok-script runtime; no package writes."""

import importlib.abc
import importlib.util
import stat
import sys
from pathlib import Path


class CustomFrameworkFinder(importlib.abc.MetaPathFinder):
    def __init__(self, source_root):
        self.source_root = Path(source_root).resolve()
        self.overrides = self.source_root / 'custom_ok'

    def find_spec(self, fullname, path=None, target=None):
        if not fullname.startswith('ok.'):
            return None
        source = self.overrides.joinpath(*fullname.split('.'))
        for candidate in (source.with_suffix('.py'), source / '__init__.py'):
            try:
                mode = candidate.stat().st_mode
            except FileNotFoundError:
                continue
            if stat.S_ISREG(mode):
                return importlib.util.spec_from_file_location(fullname, candidate)
        return None


def install_framework_overlay(source_root):
    """Install before the first ok import, or return this root's existing finder."""
    root = Path(source_root).resolve()
    for finder in sys.meta_path:
        if isinstance(finder, CustomFrameworkFinder):
            if finder.source_root != root:
                raise RuntimeError('Cannot mix framework overrides from different source roots')
            return finder
    if any(name == 'ok' or name.startswith('ok.') for name in sys.modules):
        raise RuntimeError('Framework overlay must be installed before importing ok')
    framework = root / 'custom_ok' / 'ok'
    if not stat.S_ISDIR(framework.stat().st_mode):
        raise NotADirectoryError(str(framework))
    finder = CustomFrameworkFinder(root)
    sys.meta_path.insert(0, finder)
    return finder
