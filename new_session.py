# -*- coding: utf-8 -*-
"""每次启动 okww 前调用：把散落的日志/截图归档到本次会话目录。

背景：ok 框架把主日志写到 logs/{name}.log、截图写到 screenshots/，
均为固定目录平铺。本脚本在每次启动时把这两个目录下"非会话子目录"的
文件/目录移到 session-YYYYMMDD-HHMMSS/ 子目录，实现"每次启动一份日志/截图"，
不修改框架代码。

用法（启动okww.bat 已在 main.py 之前调用）：
    runtime\\python\\python.exe new_session.py
也可手动运行做一次归档。
"""

import datetime
import os
import shutil

ROOT = os.path.dirname(os.path.abspath(__file__))


def archive(folder: str, prefix: str = 'session-'):
    base = os.path.join(ROOT, folder)
    if not os.path.isdir(base):
        return 0
    session = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    session_dir = os.path.join(base, f'{prefix}{session}')
    os.makedirs(session_dir, exist_ok=True)
    moved = 0
    for entry in sorted(os.listdir(base)):
        if entry.startswith(prefix):
            continue  # 已是会话目录，跳过
        src = os.path.join(base, entry)
        dst = os.path.join(session_dir, entry)
        # 目标已存在则加时间戳后缀避免覆盖
        if os.path.exists(dst):
            dst = os.path.join(session_dir, f'{entry}.{session}')
        try:
            shutil.move(src, dst)
            print(f'[归档] {src} -> {dst}')
            moved += 1
        except Exception as e:
            print(f'[归档失败] {src}: {e}')
    return moved


if __name__ == '__main__':
    n1 = archive('logs')
    n2 = archive('screenshots')
    print(f'归档完成: logs {n1} 项, screenshots {n2} 项')
