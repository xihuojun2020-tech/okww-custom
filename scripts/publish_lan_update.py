from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.verify_update_package import verify_update


class PublishError(RuntimeError):
    pass


def _digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def _replace(source: Path, destination: Path) -> None:
    os.replace(source, destination)


def _atomic_bytes(path: Path, data: bytes) -> None:
    pending = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    try:
        with pending.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        _replace(pending, path)
    finally:
        pending.unlink(missing_ok=True)


def publish(archive: Path, destination: Path, *, channel: str = "stable", previous_ref: str,
            published_at: datetime | None = None, root: Path | None = None) -> Path:
    if channel != "stable":
        raise PublishError("首版只支持 stable 通道")
    archive, destination = Path(archive).resolve(), Path(destination).resolve()
    root = Path(root or ROOT).resolve()
    verified = verify_update(archive, root, previous_ref)
    version, digest = verified["version"], verified["sha256"]
    release_root = (destination / channel / "releases").resolve()
    version_dir = (release_root / f"v{version}").resolve()
    if not version_dir.is_relative_to(release_root):
        raise PublishError("发布目录越界")
    version_dir.mkdir(parents=True, exist_ok=True)
    final_archive = version_dir / archive.name
    if final_archive.exists():
        if final_archive.stat().st_size != archive.stat().st_size or _digest(final_archive) != digest:
            raise PublishError("同版本 NAS 更新包内容冲突")
    else:
        pending = final_archive.with_name(final_archive.name + ".tmp-" + uuid.uuid4().hex)
        try:
            with archive.open("rb") as source, pending.open("xb") as target:
                shutil.copyfileobj(source, target, 1024 * 1024)
                target.flush()
                os.fsync(target.fileno())
            if _digest(pending) != digest:
                raise PublishError("NAS 写入后校验失败")
            _replace(pending, final_archive)
        finally:
            pending.unlink(missing_ok=True)
    checksum = f"{digest}  {archive.name}\n".encode("ascii")
    checksum_path = version_dir / "SHA256SUMS.txt"
    if checksum_path.exists() and checksum_path.read_bytes() != checksum:
        raise PublishError("同版本校验文件冲突")
    if not checksum_path.exists():
        _atomic_bytes(checksum_path, checksum)
    timestamp = (published_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    manifest = {
        "schema_version": 1, "channel": channel, "version": version,
        "package": f"releases/v{version}/{archive.name}", "sha256": digest,
        "size": final_archive.stat().st_size,
        "published_at": timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    latest = destination / channel / "latest.json"
    latest.parent.mkdir(parents=True, exist_ok=True)
    _atomic_bytes(latest, (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    return latest


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish a verified OK-WW update to a NAS directory")
    parser.add_argument("archive", type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--previous-ref", required=True)
    parser.add_argument("--channel", default="stable")
    args = parser.parse_args()
    print(publish(args.archive, args.destination, channel=args.channel, previous_ref=args.previous_ref))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
