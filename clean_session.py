# -*- coding: utf-8 -*-
"""清理 okww 历史会话日志/截图：删除超过保留天数的 session-* 目录。

- 保留天数默认 7 天，可用环境变量 OKWW_KEEP_DAYS 覆盖
- 每次启动 okww 时自动执行（启动okww.bat 已集成）
- 也可注册为 Windows 计划任务每日运行（见 register_cleanup.bat）
- 可带参数 --dry-run 只预览不删除

用法：
    runtime\\python\\python.exe clean_session.py
    runtime\\python\\python.exe clean_session.py --dry-run
"""

import os
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
try:
    KEEP_DAYS = float(os.environ.get('OKWW_KEEP_DAYS', '7'))
except (TypeError, ValueError):
    # 环境变量非数字时回退默认值，避免 import 即崩
    KEEP_DAYS = 7.0
TARGETS = [('logs', 'session-'), ('screenshots', 'session-')]


def clean(dry_run: bool = False):
    now = time.time()
    removed = 0
    freed_bytes = 0
    for folder, prefix in TARGETS:
        base = os.path.join(ROOT, folder)
        if not os.path.isdir(base):
            continue
        for entry in sorted(os.listdir(base)):
            if not entry.startswith(prefix):
                continue  # 只清理会话子目录
            path = os.path.join(base, entry)
            if not os.path.isdir(path):
                continue
            try:
                age_days = (now - os.path.getmtime(path)) / 86400.0
            except OSError:
                continue
            if age_days > KEEP_DAYS:
                size = _dir_size(path)
                action = '[预览-将删除]' if dry_run else '[已删除]'
                print(f'{action} {path} ({age_days:.1f}天, {size/1024:.0f}KB)')
                if not dry_run:
                    shutil.rmtree(path, ignore_errors=True)
                removed += 1
                freed_bytes += size
    print(f'清理完成: {"预览" if dry_run else "删除"} {removed} 个会话目录, '
          f'释放约 {freed_bytes/1024/1024:.1f}MB (保留 {KEEP_DAYS:g} 天)')


def _dir_size(path: str) -> int:
    total = 0
    for dirpath, _dirnames, filenames in os.walk(path):
        for f in filenames:
            try:
                total += os.path.getsize(os.path.join(dirpath, f))
            except OSError:
                pass
    return total


if __name__ == '__main__':
    clean(dry_run='--dry-run' in sys.argv)
