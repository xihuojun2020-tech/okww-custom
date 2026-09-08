from __future__ import annotations

import hashlib
import hmac
import json
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

class UpdatePackageError(ValueError):
    pass


@dataclass(frozen=True)
class ValidatedPackage:
    version: str
    framework: str
    files: Mapping[str, str]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inspect_member(name: str) -> None:
    if not isinstance(name, str) or not name or "\\" in name or ":" in name or "\0" in name:
        raise UpdatePackageError("更新包成员路径无效")
    from pathlib import PurePosixPath
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in ("", ".", "..") for part in name.split("/")):
        raise UpdatePackageError("更新包成员路径越界")
    if any(part.casefold() == "configs" for part in path.parts):
        raise UpdatePackageError("更新包不得包含运行配置")


def validate_package(archive: Path, *, expected_version: str, expected_sha256: str,
                     expected_size: int) -> ValidatedPackage:
    archive = Path(archive)
    if archive.stat().st_size != expected_size or not hmac.compare_digest(_sha256(archive), expected_sha256):
        raise UpdatePackageError("更新包外层长度或 SHA-256 不匹配")
    try:
        with zipfile.ZipFile(archive) as package:
            infos = package.infolist()
            names = [item.filename for item in infos]
            if len({name.casefold() for name in names}) != len(names):
                raise UpdatePackageError("更新包存在重复路径")
            for info in infos:
                _inspect_member(info.filename)
                mode = info.external_attr >> 16
                file_type = stat.S_IFMT(mode)
                if file_type and not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
                    raise UpdatePackageError("更新包包含链接或特殊文件")
            try:
                manifest = json.loads(package.read("update-manifest.json"))
            except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise UpdatePackageError("包内更新清单无效") from exc
            if not isinstance(manifest, dict) or set(manifest) != {"version", "framework", "files"}:
                raise UpdatePackageError("包内更新清单字段无效")
            if manifest["version"] != expected_version or not isinstance(manifest["framework"], str):
                raise UpdatePackageError("包内版本或框架信息不匹配")
            files = manifest["files"]
            if not isinstance(files, dict) or set(names) != set(files) | {"update-manifest.json"}:
                raise UpdatePackageError("更新包成员集合不匹配")
            for name, expected in files.items():
                if not isinstance(name, str) or not isinstance(expected, str) or len(expected) != 64:
                    raise UpdatePackageError("包内文件哈希格式无效")
                if not hmac.compare_digest(hashlib.sha256(package.read(name)).hexdigest(), expected):
                    raise UpdatePackageError(f"包内文件 SHA-256 不匹配：{name}")
            return ValidatedPackage(expected_version, manifest["framework"], MappingProxyType(dict(files)))
    except (OSError, zipfile.BadZipFile, ValueError) as exc:
        if isinstance(exc, UpdatePackageError):
            raise
        raise UpdatePackageError("更新包结构无效") from exc
