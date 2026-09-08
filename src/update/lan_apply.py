from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .package_validation import ValidatedPackage, validate_package


class ApplyError(RuntimeError):
    pass


@dataclass(frozen=True)
class ApplyResult:
    schema_version: int
    from_version: str
    to_version: str
    status: str
    message: str
    finished_at: str
    backup_dir: str


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(path.suffix + ".tmp")
    with pending.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(pending, path)


def _running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _wait_parent(pid: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while _running(pid) and time.monotonic() < deadline:
        time.sleep(0.1)
    return not _running(pid)


def _load_request(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ApplyError("更新请求无效") from exc
    keys = {"schema_version", "from_version", "to_version", "archive", "sha256", "size",
            "install_root", "parent_pid", "restart_command"}
    if not isinstance(value, dict) or set(value) != keys or value["schema_version"] != 1:
        raise ApplyError("更新请求字段无效")
    if type(value["parent_pid"]) is not int or type(value["size"]) is not int:
        raise ApplyError("更新请求类型无效")
    if not isinstance(value["restart_command"], list) or not value["restart_command"] or not all(
            isinstance(item, str) and item for item in value["restart_command"]):
        raise ApplyError("重启命令无效")
    return value


def _require_unchanged_dependencies(package: zipfile.ZipFile, root: Path, validated: ValidatedPackage) -> None:
    for name in ("requirements.txt", "requirements.in"):
        if name in validated.files and (not (root / name).is_file() or package.read(name) != (root / name).read_bytes()):
            raise ApplyError("运行依赖发生变化，请安装完整版本")
    current = next((line.strip() for line in (root / "requirements.txt").read_text(encoding="utf-8").splitlines()
                    if line.startswith("ok-script==")), "")
    if validated.framework != current:
        raise ApplyError("框架版本发生变化，请安装完整版本")


def apply_request(request_path: Path, *, wait_timeout: float = 30.0,
                  fault_hook: Callable[[str, Path], None] | None = None) -> ApplyResult:
    request = _load_request(Path(request_path).resolve())
    root = Path(request["install_root"]).resolve()
    archive = Path(request["archive"]).resolve()
    staging_root = (root / "configs" / "update-staging").resolve()
    if not request_path.resolve().is_relative_to(staging_root) or not archive.is_relative_to(staging_root):
        raise ApplyError("更新请求不在受控暂存目录")
    if not _wait_parent(request["parent_pid"], wait_timeout):
        raise ApplyError("主程序未在期限内退出")
    validated = validate_package(archive, expected_version=request["to_version"],
                                 expected_sha256=request["sha256"], expected_size=request["size"])
    backup = root / "configs" / "update-backups" / f"v{request['from_version']}-to-v{request['to_version']}"
    extracted = request_path.parent / "extracted"
    journal_path = backup / "journal.json"
    operations: list[dict] = []
    result_path = root / "configs" / "update-result.json"
    status, message = "failed", "更新未执行"
    try:
        with zipfile.ZipFile(archive) as package:
            _require_unchanged_dependencies(package, root, validated)
            for name in validated.files:
                target = (extracted / name).resolve()
                if not target.is_relative_to(extracted.resolve()):
                    raise ApplyError("更新成员路径越界")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(package.read(name))
        stale = []
        for folder in ("src", "custom_ok"):
            base = root / folder
            if base.is_dir():
                stale.extend(path for path in base.rglob("*.py")
                             if path.relative_to(root).as_posix() not in validated.files)
        affected = [root / name for name in validated.files] + stale
        backup.mkdir(parents=True, exist_ok=True)
        for target in affected:
            resolved = target.resolve()
            if not resolved.is_relative_to(root) or resolved.is_relative_to(root / "configs"):
                raise ApplyError("更新目标越界")
            relative = target.relative_to(root)
            existed = target.is_file()
            if existed:
                saved = backup / "files" / relative
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, saved)
            operations.append({"path": relative.as_posix(), "existed": existed, "applied": False})
        _write_json(journal_path, {"operations": operations})
        package_names = set(validated.files)
        for operation in operations:
            relative = Path(operation["path"])
            target = root / relative
            if fault_hook:
                fault_hook("before_replace", target)
            if relative.as_posix() in package_names:
                source = extracted / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(source, target)
            else:
                target.unlink(missing_ok=True)
            operation["applied"] = True
            _write_json(journal_path, {"operations": operations})
        status, message = "succeeded", "局域网更新安装成功"
    except Exception as exc:
        rollback_ok = True
        for operation in reversed(operations):
            if not operation["applied"]:
                continue
            target = root / operation["path"]
            try:
                if operation["existed"]:
                    saved = backup / "files" / operation["path"]
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(saved, target)
                else:
                    target.unlink(missing_ok=True)
            except OSError:
                rollback_ok = False
        status = "rolled_back" if rollback_ok else "rollback_incomplete"
        message = f"更新失败，{'已恢复原版本' if rollback_ok else '恢复不完整'}：{type(exc).__name__}"
    result = ApplyResult(1, request["from_version"], request["to_version"], status, message,
                         datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), str(backup))
    _write_json(result_path, asdict(result))
    try:
        subprocess.Popen(request["restart_command"], cwd=root,
                         creationflags=0x08000000 if os.name == "nt" else 0)
    except OSError:
        pass
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("request", type=Path)
    args = parser.parse_args()
    try:
        result = apply_request(args.request)
    except ApplyError:
        return 2
    return {"succeeded": 0, "rolled_back": 3, "rollback_incomplete": 4}.get(result.status, 2)


if __name__ == "__main__":
    raise SystemExit(main())
