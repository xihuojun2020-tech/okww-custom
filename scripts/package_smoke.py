"""Reject empty release output and archives containing local runtime data."""

from __future__ import annotations

import argparse
import json
import stat
import zipfile
from pathlib import Path, PurePosixPath


FORBIDDEN_PARTS = {
    "working", "logs", "账号备份", "config_bundle_transactions",
    "config_integrity_incidents",
    "configs_backup", "运行状态", "ok仓库", "export_accounts",
}
FORBIDDEN_PARTS_LOWER = {part.lower() for part in FORBIDDEN_PARTS}
NOTIFICATION_TEMPLATE = {
    'System Notification': False,
    'Discord Notification': False, 'Discord Webhook': '',
    'Telegram Notification': False, 'Telegram Bot Token': '', 'Telegram Chat ID': '',
    'Enterprise WeChat Webhook Notification': False, 'Enterprise WeChat Webhook URL': '',
    'QQ Bot API Notification': False, 'QQ Bot API App ID': '', 'QQ Bot API Token': '',
    'QQ Bot API Channel ID': '', 'QQ Desktop Notification (Not Reliable)': False,
    'QQ Desktop Nickname': '', 'WeChat Desktop Notification (Not Reliable)': False,
    'WeChat Desktop Nickname': '',
}


def inspect_member(name: str, *, is_dir=False, read_bytes=None):
    """Apply the same rules at any wrapper depth in a distribution tree."""
    normalized = name.replace('\\', '/')
    path = PurePosixPath(normalized)
    if (not path.parts or path.is_absolute() or '..' in path.parts or
            ':' in normalized or '\x00' in normalized):
        raise ValueError(f'产物包含不安全路径：{name}')
    parts = [part.casefold() for part in path.parts]
    if set(parts) & FORBIDDEN_PARTS_LOWER:
        raise ValueError(f'产物包含本地运行数据目录：{name}')
    if 'configs' not in parts:
        return
    position = parts.index('configs')
    if is_dir and position == len(parts) - 1:
        return  # An empty configs directory contains no private state.
    if is_dir or parts[position:] != ['configs', 'notification.json']:
        raise ValueError(f'产物包含未授权配置：{name}')
    raw = read_bytes()
    if len(raw) > 16384:
        raise ValueError('通知模板大小异常')
    data = json.loads(raw)
    if not isinstance(data, dict) or any(
            key not in NOTIFICATION_TEMPLATE or type(value) is not type(NOTIFICATION_TEMPLATE[key]) or
            value != NOTIFICATION_TEMPLATE[key] for key, value in data.items()):
        raise ValueError('通知模板必须为空配置或已关闭通知、清空身份与密钥的默认值')


def inspect_distribution(dist: Path) -> tuple[Path, ...]:
    assets = tuple(sorted(path for path in dist.rglob("*") if path.is_file()))
    if not assets:
        raise ValueError("打包目录中没有发布文件")
    if not any(path.suffix.lower() in {".exe", ".msi", ".zip"} for path in assets):
        raise ValueError("打包目录中没有安装包或压缩包")
    for archive in (path for path in assets if path.suffix.lower() == ".zip"):
        with zipfile.ZipFile(archive) as package:
            names = set()
            for member in package.infolist():
                normalized = PurePosixPath(member.filename.replace('\\', '/')).as_posix().casefold()
                if normalized in names or stat.S_ISLNK(member.external_attr >> 16):
                    raise ValueError('压缩包包含重复路径或符号链接')
                names.add(normalized)
                if member.file_size > 16384 and normalized.endswith('/configs/notification.json'):
                    raise ValueError('通知模板大小异常')
                inspect_member(member.filename, is_dir=member.is_dir(),
                               read_bytes=lambda: package.open(member).read(16385))
    return assets


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist", type=Path, required=True)
    args = parser.parse_args()
    assets = inspect_distribution(args.dist.resolve())
    print(f"assets={len(assets)} zip_contents_checked={sum(p.suffix.lower() == '.zip' for p in assets)} "
          f"installer_payloads_unverified={sum(p.suffix.lower() in {'.exe', '.msi'} for p in assets)}")


if __name__ == "__main__":
    main()
