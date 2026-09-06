"""Validate fixed-width product version metadata and an optional Git tag."""

from __future__ import annotations

import argparse
import ast
import re
from pathlib import Path


VERSION_RE = re.compile(r'version\s*=\s*"([0-9]+\.[0-9]{2}\.[0-9]{2})"')


def validate_release(root: Path, tag: str = "") -> str:
    config_text = (root / "config.py").read_text(encoding="utf-8")
    match = VERSION_RE.search(config_text)
    if match is None:
        raise ValueError("config.py 缺少固定宽度版本号 X.YY.ZZ")
    version = match.group(1)
    changelog = (root / "更新日志.md").read_text(encoding="utf-8")
    headings = re.findall(r'^##\s+([0-9]+\.[0-9]{2}\.[0-9]{2})(?=\s|（|$)', changelog, re.M)
    if not headings or headings[0] != version or headings.count(version) != 1:
        raise ValueError("更新日志版本与 config.py 不一致")
    about = ast.parse((root / 'custom_ok/ok/gui/about/AboutTab.py').read_text(encoding='utf-8'))
    if not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
               and node.func.id == 'get_path_relative_to_exe' and node.args
               and isinstance(node.args[0], ast.Constant) and node.args[0].value == '更新日志.md'
               for node in ast.walk(about)):
        raise ValueError('About 页面必须读取随包更新日志')
    if not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
               and node.func.attr == '_read_update_log' for node in ast.walk(about)):
        raise ValueError('About 页面未使用共同更新日志来源')
    if tag and tag != f"v{version}":
        raise ValueError(f"标签 {tag} 与版本 v{version} 不一致")
    return version


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--tag", default="")
    parser.add_argument('--notes-output', type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    version = validate_release(root, args.tag.strip())
    if args.notes_output is not None:
        changelog = (root / '更新日志.md').read_text(encoding='utf-8')
        notes = re.search(rf'^##\s+{re.escape(version)}(?=\s|（|$).*?(?=^##\s|\Z)',
                          changelog, re.M | re.S).group(0).strip()
        args.notes_output.parent.mkdir(parents=True, exist_ok=True)
        args.notes_output.write_text(notes + '\n', encoding='utf-8')
    print(version)


if __name__ == "__main__":
    main()
