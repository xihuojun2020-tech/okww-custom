# -*- coding: utf-8 -*-
"""账号切换测试的兼容入口。

账号切换曾经有一份独立的 ``test_account_switch.py`` 实现，其中自行维护了
窗口坐标、OCR、账号别名匹配和退登流程。这些逻辑很容易与正式任务分叉，
也会让“测试通过”不能代表程序实际使用的路径通过。

现在正式入口是 OKWW 中注册的 :class:`TestAccountSwitchTask`。本文件只保留
一个兼容的命令行转发入口，不再实现任何账号切换逻辑。请在 OKWW 界面中
运行“🔄 账号切换测试”，或执行本文件启动同一个正式任务。
"""
from __future__ import annotations

import argparse
import sys
from typing import Any

from src.task.TestAccountSwitchTask import (
    CONTINUOUS_MODE,
    DEFAULT_CONTINUOUS_ORDER,
    SINGLE_MODE,
    TestAccountSwitchTask,
)


def get_task_class():
    """返回正式账号切换测试任务类。"""
    return TestAccountSwitchTask


def run_task(config: dict[str, Any] | None = None):
    """通过 OKWW 正式注册流程启动账号切换测试任务。"""
    from ok import run_task as ok_run_task
    from config import config as default_config

    return ok_run_task(config or default_config, task=TestAccountSwitchTask, debug=True)


def run_test(
    target: str | None = None,
    rounds: int = 1,
    diag_only: bool = False,
    save_screenshots: bool = True,
):
    """兼容旧调用方，但不再执行独立的账号切换实现。

    ``target``、``diag_only`` 和 ``save_screenshots`` 仅为兼容旧命令行参数保留；
    目标账号、连续顺序和截图均由 ``TestAccountSwitchTask`` 的正式配置管理。
    ``rounds`` 仍在入口处校验，以保留旧脚本对非法参数的快速反馈。
    """
    del target, diag_only, save_screenshots
    if rounds < 1:
        print("  ✗ 测试轮数必须大于等于 1")
        return False
    return run_task()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="转发到 OKWW 正式的 TestAccountSwitchTask 账号切换测试"
    )
    parser.add_argument(
        "--target", "-t", default=None,
        help="兼容参数；请在 OKWW 的‘目标账号’配置中选择",
    )
    parser.add_argument(
        "--rounds", "-n", type=int, default=1,
        help="兼容参数；请在 OKWW 的‘测试轮数’配置中选择",
    )
    parser.add_argument(
        "--diag", action="store_true",
        help="兼容参数；诊断请使用正式任务的日志和截图",
    )
    parser.add_argument(
        "--no-screenshots", action="store_true",
        help="兼容参数；截图策略由正式任务统一管理",
    )
    args = parser.parse_args(argv)
    result = run_test(
        target=args.target,
        rounds=args.rounds,
        diag_only=args.diag,
        save_screenshots=not args.no_screenshots,
    )
    # ok.run_task 通常由 GUI 生命周期接管；只有显式返回 False 时才报告失败。
    return 0 if result is not False else 1


__all__ = [
    "CONTINUOUS_MODE",
    "DEFAULT_CONTINUOUS_ORDER",
    "SINGLE_MODE",
    "TestAccountSwitchTask",
    "get_task_class",
    "main",
    "run_task",
    "run_test",
]


if __name__ == "__main__":
    sys.exit(main())
