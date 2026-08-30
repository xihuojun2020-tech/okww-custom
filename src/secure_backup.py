"""Local-machine protection for sensitive configuration snapshots.

Portable exports remain deliberately redacted.  This module is for local
backups only and refuses to silently fall back to plaintext when Windows
DPAPI is unavailable.
"""

from __future__ import annotations

import base64
import ctypes
import json
import os
import secrets
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class SecureBackupError(RuntimeError):
    """Base error for local encrypted backup operations."""


class SecureBackupUnavailable(SecureBackupError):
    """Raised when the host cannot provide the required OS protection."""


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _dpapi_transform(payload: bytes, *, decrypt: bool) -> bytes:
    if os.name != "nt":
        raise SecureBackupUnavailable("本机不是 Windows，无法使用 DPAPI 本机备份保护")
    try:
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
    except AttributeError as exc:  # pragma: no cover - exercised on non-Windows hosts
        raise SecureBackupUnavailable("Windows DPAPI 不可用，已拒绝明文备份") from exc
    source = ctypes.create_string_buffer(payload)
    in_blob = _DataBlob(len(payload), ctypes.cast(source, ctypes.POINTER(ctypes.c_ubyte)))
    out_blob = _DataBlob()
    func = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
    func.argtypes = [ctypes.POINTER(_DataBlob), ctypes.c_void_p, ctypes.c_void_p,
                     ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32,
                     ctypes.POINTER(_DataBlob)]
    func.restype = ctypes.c_bool
    if not func(ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)):
        raise SecureBackupError("Windows DPAPI 操作失败")
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)


class SecureBackupService:
    """Encrypt and decrypt one local snapshot payload with current-user DPAPI."""

    format = "okww-dpapi-v1"

    def encrypt_snapshot(self, payload: bytes | bytearray | str) -> bytes:
        raw = payload.encode("utf-8") if isinstance(payload, str) else bytes(payload)
        envelope = {
            "format": self.format,
            "scope": "current-user",
            "nonce": secrets.token_hex(16),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "ciphertext": base64.b64encode(_dpapi_transform(raw, decrypt=False)).decode("ascii"),
        }
        return json.dumps(envelope, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":")).encode("utf-8")

    def decrypt_snapshot(self, envelope: bytes | bytearray | str) -> bytes:
        raw = envelope.encode("utf-8") if isinstance(envelope, str) else bytes(envelope)
        try:
            value = json.loads(raw.decode("utf-8"))
            if value.get("format") != self.format or value.get("scope") != "current-user":
                raise ValueError("unsupported secure backup format")
            ciphertext = base64.b64decode(value["ciphertext"], validate=True)
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise SecureBackupError("本机加密备份格式无效") from exc
        return _dpapi_transform(ciphertext, decrypt=True)


def _raw_parts(path: Path) -> tuple[str, ...]:
    return tuple(part for part in path.parts if part not in (path.anchor, ""))


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def validate_restore_path(source: os.PathLike | str, target: os.PathLike | str,
                          data_root: os.PathLike | str | None = None) -> tuple[Path, Path]:
    """Validate source/target before a restore copy or directory swap.

    ``data_root`` is the configured boundary.  When omitted, existing
    symlinks and traversal are still rejected; callers restoring application
    data should pass the common configured root for a strict boundary check.
    """
    source_path = Path(source)
    target_path = Path(target)
    if ".." in _raw_parts(source_path) or ".." in _raw_parts(target_path):
        raise ValueError("恢复路径不允许包含 ..")
    source_abs, target_abs = source_path.absolute(), target_path.absolute()
    root = Path(data_root).resolve() if data_root is not None else None
    if root is not None and (not _inside(source_abs.resolve(), root) or
                             not _inside(target_abs.resolve(), root)):
        raise ValueError("恢复路径超出配置数据根目录")
    # A symlink at any existing component is rejected rather than guessed
    # safe.  This prevents an attacker from swapping a directory between
    # validation and copy and escaping the configured restore boundary.
    for path in (source_abs, target_abs):
        current = path
        while current != current.parent:
            if current.is_symlink():
                raise ValueError("恢复路径不允许使用符号链接")
            current = current.parent
    if source_abs == target_abs or _inside(target_abs, source_abs) or _inside(source_abs, target_abs):
        raise ValueError("恢复源与目标路径不能相互包含")
    return source_abs, target_abs


def harden_directory_permissions(path: os.PathLike | str) -> Path:
    """Restrict a backup directory to the current user plus OS administrators.

    Windows SIDs are used for SYSTEM/Administrators so this remains valid on
    localized installations.  Non-Windows hosts fail closed because this
    service promises Windows ACL semantics.
    """
    if os.name != "nt":
        raise SecureBackupUnavailable("当前平台不支持 Windows ACL 备份保护")
    target = Path(path).resolve()
    target.mkdir(parents=True, exist_ok=True)
    icacls = shutil.which("icacls")
    username = os.environ.get("USERNAME")
    if not icacls or not username:
        raise SecureBackupUnavailable("找不到 icacls 或当前 Windows 用户")
    grants = (
        f"{username}:(OI)(CI)F",
        "*S-1-5-18:(OI)(CI)F",       # Local System
        "*S-1-5-32-544:(OI)(CI)F",   # Built-in Administrators
    )
    try:
        subprocess.run([icacls, str(target), "/inheritance:r", "/grant:r", *grants],
                       check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SecureBackupUnavailable("无法设置本机备份目录 ACL") from exc
    return target


class SecureStoragePolicy:
    """Prepare and prune one sensitive directory without following links."""

    def __init__(self, root: os.PathLike | str, *, max_entries=20, max_age_days=30):
        self.root = Path(root).resolve()
        self.max_entries = max(1, int(max_entries))
        self.max_age_seconds = max(1, int(max_age_days)) * 24 * 60 * 60

    def prepare(self) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            harden_directory_permissions(self.root)
        return self.root

    @staticmethod
    def _is_link(path: Path) -> bool:
        return path.is_symlink() or (
            hasattr(path, "is_junction") and path.is_junction()
        )

    def cleanup(self, *, now=None) -> None:
        root = self.prepare()
        current = time.time() if now is None else float(now)
        entries = sorted(
            (path for path in root.iterdir() if path.parent == root),
            key=lambda path: path.stat(follow_symlinks=False).st_mtime,
            reverse=True,
        )
        for index, path in enumerate(entries):
            stat = path.stat(follow_symlinks=False)
            if index < self.max_entries and current - stat.st_mtime <= self.max_age_seconds:
                continue
            if self._is_link(path) or path.is_file():
                path.unlink(missing_ok=True)
            elif path.is_dir():
                shutil.rmtree(path)


__all__ = [
    "SecureBackupError", "SecureBackupService", "SecureBackupUnavailable",
    "SecureStoragePolicy", "harden_directory_permissions", "validate_restore_path",
]
