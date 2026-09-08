from __future__ import annotations

import json
import re
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import PurePosixPath

MAX_PACKAGE_BYTES = 512 * 1024 * 1024
_VERSION = re.compile(r"[0-9]+\.[0-9]{2}\.[0-9]{2}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_KEYS = {"schema_version", "channel", "version", "package", "sha256", "size", "published_at"}


class LanManifestError(ValueError):
    pass


def parse_version(value: str) -> tuple[int, int, int]:
    if not isinstance(value, str) or not _VERSION.fullmatch(value):
        raise LanManifestError("更新版本格式无效")
    return tuple(int(part) for part in value.split("."))


@dataclass(frozen=True)
class LanRelease:
    schema_version: int
    channel: str
    version: str
    package: str
    sha256: str
    size: int
    published_at: datetime

    @classmethod
    def from_bytes(cls, data: bytes, *, expected_channel: str = "stable") -> "LanRelease":
        try:
            record = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LanManifestError("更新清单不是有效的 UTF-8 JSON") from exc
        if not isinstance(record, dict) or set(record) != _KEYS:
            raise LanManifestError("更新清单字段不完整或包含未知字段")
        if type(record["schema_version"]) is not int or record["schema_version"] != 1:
            raise LanManifestError("不支持的更新清单版本")
        if record["channel"] != expected_channel or expected_channel != "stable":
            raise LanManifestError("更新通道无效")
        version = record["version"]
        parse_version(version)
        digest = record["sha256"]
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            raise LanManifestError("更新包 SHA-256 无效")
        size = record["size"]
        if type(size) is not int or not 1 <= size <= MAX_PACKAGE_BYTES:
            raise LanManifestError("更新包大小无效")
        package = record["package"]
        if not isinstance(package, str) or any(char in package for char in "\\%?#"):
            raise LanManifestError("更新包路径无效")
        path = PurePosixPath(package)
        parts = package.split("/")
        if path.is_absolute() or any(part in ("", ".", "..") for part in parts):
            raise LanManifestError("更新包路径越界")
        expected_prefix = ("releases", f"v{version}")
        if tuple(path.parts[:2]) != expected_prefix or path.name != f"okww_update_v{version}.zip":
            raise LanManifestError("更新包路径与版本不一致")
        published = record["published_at"]
        try:
            timestamp = datetime.strptime(published, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except (TypeError, ValueError) as exc:
            raise LanManifestError("发布时间必须是 UTC RFC 3339") from exc
        return cls(1, expected_channel, version, package, digest, size, timestamp)

    def is_newer_than(self, current: str) -> bool:
        return parse_version(self.version) > parse_version(current)

    def package_url(self, manifest_url: str) -> str:
        source = urllib.parse.urlsplit(manifest_url)
        joined = urllib.parse.urlsplit(urllib.parse.urljoin(manifest_url.rsplit("/", 1)[0] + "/", self.package))
        if joined.scheme != source.scheme or joined.netloc != source.netloc:
            raise LanManifestError("更新包地址改变了服务器")
        return urllib.parse.urlunsplit(joined)

    def package_path(self, manifest_path: Path) -> Path:
        from pathlib import Path
        base = Path(manifest_path).resolve().parent
        target = base.joinpath(*PurePosixPath(self.package).parts).resolve()
        if not target.is_relative_to(base):
            raise LanManifestError("更新包路径改变了共享目录")
        return target
