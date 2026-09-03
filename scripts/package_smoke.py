"""Reject empty release output and archives containing local runtime data."""

from __future__ import annotations

import argparse
import zipfile
from pathlib import Path, PurePosixPath


FORBIDDEN_PARTS = {
    "working", "logs", "账号备份", "config_bundle_transactions",
    "config_integrity_incidents",
}
FORBIDDEN_PARTS_LOWER = {part.lower() for part in FORBIDDEN_PARTS}
ALLOWED_CONFIG_PATHS = {"configs/notification.json"}


def inspect_distribution(dist: Path) -> tuple[Path, ...]:
    assets = tuple(sorted(path for path in dist.rglob("*") if path.is_file()))
    if not assets:
        raise ValueError("打包目录中没有发布文件")
    if not any(path.suffix.lower() in {".exe", ".msi", ".zip"} for path in assets):
        raise ValueError("打包目录中没有安装包或压缩包")
    for archive in (path for path in assets if path.suffix.lower() == ".zip"):
        with zipfile.ZipFile(archive) as package:
            for name in package.namelist():
                path = PurePosixPath(name.replace("\\", "/"))
                parts = {part.lower() for part in path.parts}
                if parts & FORBIDDEN_PARTS_LOWER:
                    raise ValueError(f"压缩包包含本地运行数据目录：{archive.name}")
                normalized = path.as_posix().lower()
                if path.parts and path.parts[0].lower() == "configs" and normalized not in ALLOWED_CONFIG_PATHS:
                    raise ValueError(f"压缩包包含未授权配置：{archive.name}:{name}")
    return assets


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist", type=Path, required=True)
    args = parser.parse_args()
    print(f"verified_assets={len(inspect_distribution(args.dist.resolve()))}")


if __name__ == "__main__":
    main()
