"""Read-only MuMu V6.5.5 preflight probe.

This command never sends tap/swipe/semantic_action.  Pass an explicit
``--serial`` after reviewing the discovered candidates.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

# Allow direct ``python scripts/preflight_mumu.py`` from the repository root.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.android import (
    AdbRunner,
    AgentArtifactInspector,
    DevicePreflightService,
    MuMuDiscovery,
    MuMuVersionProbe,
    NemuIpcFrameProvider,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MuMu V6.5.5 只读预检")
    parser.add_argument("--serial", help="已确认的 ADB serial，例如 127.0.0.1:7555")
    parser.add_argument("--manager", help="MuMuManager.exe 路径；默认自动定位")
    parser.add_argument("--adb", help="adb 可执行文件路径；默认自动定位")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    discovery = MuMuDiscovery(args.manager) if args.manager else MuMuDiscovery()
    candidates = discovery.discover()
    if not args.serial:
        payload = [asdict(candidate) for candidate in candidates]
        manager_version = None
        manager_error = None
        try:
            manager_version = MuMuVersionProbe.from_manager(discovery.executable)
        except Exception as exc:
            manager_error = str(exc)
        print(json.dumps({"manager": discovery.executable, "manager_version": manager_version,
                          "manager_error": manager_error, "candidates": payload,
                          "message": "请人工确认候选后使用 --serial；当前不会自动启动实例或连接设备"},
                         ensure_ascii=False, indent=2))
        return 2

    usable = tuple(candidate for candidate in candidates if candidate.error is None)
    if usable and args.serial not in {candidate.adb_serial for candidate in usable}:
        payload = {
            "ready": False,
            "serial": args.serial,
            "known_serials": [candidate.adb_serial for candidate in usable],
            "error": "指定 serial 不属于 MuMuManager 返回的候选；为避免误控设备，预检已拒绝",
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 2

    adb = AdbRunner(MuMuDiscovery.find_adb(args.adb))
    jar = ROOT / "assets" / "android" / "okww-combat-agent.jar"
    artifact = AgentArtifactInspector(jar).inspect(adb, args.serial)
    candidate = next((item for item in usable if item.adb_serial == args.serial), None)
    frame_capture = None
    install_root = Path(discovery.executable).resolve().parent.parent
    if candidate is not None:
        frame_capture = NemuIpcFrameProvider(
            install_root,
            instance_name=candidate.emulator,
            instance_index=candidate.instance_index,
        )
    service = DevicePreflightService(
        adb=adb,
        frame_capture=frame_capture,
        emulator_version=MuMuVersionProbe.from_manager(discovery.executable),
        emulator_root=str(install_root),
        agent_probe=lambda _channel: {
            "jar_present": artifact.jar_present,
            "hash_valid": artifact.hash_valid,
            "heartbeat": False,
            "error": "阶段01 CLI 尚未启动 Agent，仅完成资产检查" if not artifact.error else artifact.error,
        },
    )
    try:
        report = service.collect({
            "adb_serial": args.serial,
            "serial_unique": True,
            "emulator": candidate.emulator if candidate else None,
            "instance_index": candidate.instance_index if candidate else None,
        })
    finally:
        if frame_capture is not None:
            frame_capture.close()
    data = asdict(report)
    data["ready"] = report.ready
    if args.as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
    else:
        print(f"MuMu 版本: {report.emulator_version or '未知'}")
        print(f"ADB: {report.adb_serial} ({report.adb_state or '未知'})")
        print(f"鸣潮包名: {report.game_package or '未检测到'}")
        print(f"分辨率: {report.logical_resolution or '未知'} / DPI: {report.density or '未知'}")
        print(f"Nemu IPC: {'通过' if report.nemu_ipc_ready else '未接入'}")
        print(f"Agent: {'通过' if report.agent_heartbeat else '未验证'}")
        print(f"结果: {'就绪' if report.ready else '未就绪'}")
        for error in report.errors:
            print(f"错误: {error}")
    return 0 if report.ready else 1


if __name__ == "__main__":
    sys.exit(main())
