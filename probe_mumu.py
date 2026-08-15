#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MuMu 模拟器 ADB 实测脚本（独立于 okww 主程序，不改动任何现有代码）

目标：验证「okww 通过 adb 遥控 MuMu 扫码登录 PC 端」的三项关键能力：
  1) adb 能否自动发现并连接 MuMu
  2) 截图延迟（决定模拟器端识别的可用性）
  3) 点击 / swipe（决定能否自动打开扫码界面、拖动扫描框）

用法：
  python probe_mumu.py            # 全自动：探测 adb + 端口 + 截图/tap/swipe 测试
  python probe_mumu.py --port 7555    # 指定 MuMu adb 端口（跳过自动探测）

测试说明：
  - tap / swipe 会真的在模拟器上产生点击，建议先切到模拟器桌面（空白处）再跑
  - 全程只读探测 + 少量安全点击，不会安装任何东西
"""

import glob
import os
import re
import subprocess
import sys
import time

# MuMu 常见 adb 端口（V6 默认 7555，MuMu12 默认 16384）
MUMU_PORTS = [7555, 16384, 16416, 5555, 5554]

# 常见 adb 可执行文件位置（系统 PATH + MuMu 安装目录）
MUMU_ADB_PATTERNS = [
    r"C:\Program Files\Netease\MuMu*\shell\adb.exe",
    r"C:\Program Files\Netease\MuMu*\vms\adb.exe",
    r"C:\Program Files\Netease\MuMu*\nx_main\adb.exe",
    r"C:\Program Files (x86)\Netease\MuMu*\shell\adb.exe",
    r"C:\Program Files (x86)\Netease\MuMu*\vms\adb.exe",
    r"C:\Program Files (x86)\Netease\MuMu*\nx_main\adb.exe",
    r"D:\Program Files\Netease\MuMu*\shell\adb.exe",
    r"D:\Program Files\Netease\MuMu*\vms\adb.exe",
    r"D:\Program Files\Netease\MuMu*\nx_main\adb.exe",
]


def run_cmd(cmd, timeout=20):
    """执行命令并返回 (returncode, stdout, stderr)。"""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout, encoding='utf-8', errors='replace')
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except Exception as e:
        return -1, "", str(e)


def find_adb():
    """优先系统 PATH 的 adb，其次找 MuMu 自带的 adb。"""
    # 1. PATH 里是否有 adb
    rc, out, err = run_cmd(["adb", "version"])
    if rc == 0 and "Android Debug Bridge" in out:
        return "adb"

    # 2. 找 MuMu 安装目录的 adb.exe
    for pattern in MUMU_ADB_PATTERNS:
        matches = glob.glob(pattern)
        for m in sorted(matches, key=lambda p: os.path.getmtime(p), reverse=True):
            if os.path.isfile(m):
                return m
    return None


def probe_mumu_serial(adb, port=None):
    """连接 MuMu：先试指定端口，否则逐个探测常见端口。"""
    ports = [port] if port else MUMU_PORTS
    for p in ports:
        if not p:
            continue
        rc, out, err = run_cmd([adb, "connect", f"127.0.0.1:{p}"])
        if rc == 0:
            # 确认设备可见
            rc2, out2, err2 = run_cmd([adb, "devices"])
            for line in out2.splitlines():
                if f"127.0.0.1:{p}" in line and "device" in line:
                    return f"127.0.0.1:{p}"
        # 连接失败也断开，避免残留
        run_cmd([adb, "disconnect", f"127.0.0.1:{p}"])
    return None


def test_screencap(adb, serial, count=10):
    """连续截图，测平均延迟。"""
    times = []
    for i in range(count):
        t0 = time.perf_counter()
        rc, out, err = run_cmd([adb, "-s", serial, "exec-out", "screencap", "-p"], timeout=30)
        dt = (time.perf_counter() - t0) * 1000
        if rc == 0 and out:
            times.append(dt)
    if not times:
        return None
    return {
        "count": len(times),
        "avg_ms": sum(times) / len(times),
        "min_ms": min(times),
        "max_ms": max(times),
    }


def test_tap(adb, serial, x, y):
    """单次点击延迟。"""
    t0 = time.perf_counter()
    rc, out, err = run_cmd([adb, "-s", serial, "shell", "input", "tap", str(x), str(y)])
    return (time.perf_counter() - t0) * 1000, rc == 0


def test_swipe(adb, serial, x1, y1, x2, y2, duration_ms=300):
    """滑动（拖动）延迟与是否执行成功。"""
    t0 = time.perf_counter()
    rc, out, err = run_cmd([adb, "-s", serial, "shell", "input", "swipe",
                            str(x1), str(y1), str(x2), str(y2), str(duration_ms)])
    return (time.perf_counter() - t0) * 1000, rc == 0


def get_screen_size(adb, serial):
    """获取模拟器分辨率，用于生成安全点击坐标。"""
    rc, out, err = run_cmd([adb, "-s", serial, "shell", "wm", "size"])
    m = re.search(r"(\d+)x(\d+)", out)
    if m:
        return int(m.group(1)), int(m.group(2))
    return 1280, 720


def banner(title):
    print("\n" + "=" * 62)
    print(f"  {title}")
    print("=" * 62)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="MuMu 模拟器 ADB 实测脚本")
    parser.add_argument("--port", type=int, default=None, help="MuMu adb 端口（默认自动探测）")
    parser.add_argument("--shots", type=int, default=10, help="截图测试次数（默认 10）")
    args = parser.parse_args()

    banner("① 查找 adb")
    adb = find_adb()
    if not adb:
        print("✗ 未找到 adb。请安装 Android SDK platform-tools，或在 MuMu 设置里开启 ADB 调试。")
        sys.exit(1)
    print(f"✓ 使用 adb: {adb}")

    banner("② 连接 MuMu 模拟器")
    serial = probe_mumu_serial(adb, args.port)
    if not serial:
        print("✗ 无法连接 MuMu。请确认：")
        print("   1) MuMu 已启动")
        print("   2) MuMu 设置 → 其他 → 开启 ADB 调试（并记下端口，用 --port 指定）")
        print(f"   3) 若端口不是常见值，请从 MuMu 设置里查看后手动指定")
        sys.exit(1)
    print(f"✓ 已连接: {serial}")
    rc, out, err = run_cmd([adb, "-s", serial, "shell", "getprop", "ro.product.model"])
    print(f"  设备型号: {out.strip()}")

    w, h = get_screen_size(adb, serial)
    print(f"  分辨率: {w}x{h}")

    banner("③ 截图延迟测试（关键：决定模拟器端识别可用性）")
    stat = test_screencap(adb, serial, count=args.shots)
    if stat:
        print(f"  ✓ 截图 {stat['count']} 次")
        print(f"    平均: {stat['avg_ms']:.0f} ms/帧  (~{1000/max(stat['avg_ms'],1):.1f} fps)")
        print(f"    最小: {stat['min_ms']:.0f} ms   最大: {stat['max_ms']:.0f} ms")
        if stat["avg_ms"] < 150:
            print("  ✅ 截图速度优秀：模拟器端识别可用")
        elif stat["avg_ms"] < 300:
            print("  ⚠️ 截图速度一般：可做低频识别（扫码场景够用）")
        else:
            print("  ❌ 截图速度过慢：仅适合极低频操作")
    else:
        print("  ✗ 截图失败")

    banner("④ 点击 / 滑动测试（会在模拟器上产生真实点击！）")
    print(f"  请确认模拟器当前在【桌面/空白区域】…… 3 秒后开始")
    time.sleep(3)

    # 安全坐标：屏幕中间偏下的空白区（尽量避开图标）
    tap_x, tap_y = w // 2, h // 2
    print(f"  点击测试: tap ({tap_x}, {tap_y})")
    ms, ok = test_tap(adb, serial, tap_x, tap_y)
    print(f"    {'✓' if ok else '✗'} tap 命令延迟: {ms:.0f} ms")

    # swipe：从屏幕中上部拖到中下部（模拟"拖动扫描框"的动作）
    sx1, sy1 = w // 2, int(h * 0.35)
    sx2, sy2 = w // 2, int(h * 0.65)
    print(f"  滑动测试: swipe ({sx1},{sy1}) → ({sx2},{sy2}) 300ms")
    ms, ok = test_swipe(adb, serial, sx1, sy1, sx2, sy2)
    print(f"    {'✓' if ok else '✗'} swipe 命令延迟: {ms:.0f} ms")

    banner("⑤ 结论")
    print("  若 ②③④ 全部通过，则「okww + adb 遥控 MuMu 扫码登录」的底层链路可用：")
    print("    - 截图：可用来识别模拟器界面按钮/账号")
    print("    - tap ：可自动点开扫一扫 → 实时截屏")
    print("    - swipe：可拖动扫描框到 PC 二维码位置")
    print("  下一步即可进入 MVP：PC 端定位二维码 + adb 遥控拖框。")
    run_cmd([adb, "disconnect", serial])


if __name__ == "__main__":
    main()
