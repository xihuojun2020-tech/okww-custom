"""Validate fixed-width product version metadata and an optional Git tag."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


VERSION_RE = re.compile(r'version\s*=\s*"([0-9]+\.[0-9]{2}\.[0-9]{2})"')


def validate_release(root: Path, tag: str = "") -> str:
    config_text = (root / "config.py").read_text(encoding="utf-8")
    match = VERSION_RE.search(config_text)
    if match is None:
        raise ValueError("config.py 缺少固定宽度版本号 X.YY.ZZ")
    version = match.group(1)
    if version not in (root / "更新日志.md").read_text(encoding="utf-8"):
        raise ValueError("更新日志版本与 config.py 不一致")
    if f"V{version}" not in (root / "custom_ok/ok/gui/about/AboutTab.py").read_text(encoding="utf-8"):
        raise ValueError("About 页面版本与 config.py 不一致")
    if tag and tag != f"v{version}":
        raise ValueError(f"标签 {tag} 与版本 v{version} 不一致")
    return version


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--tag", default="")
    args = parser.parse_args()
    print(validate_release(args.root.resolve(), args.tag.strip()))


if __name__ == "__main__":
    main()
