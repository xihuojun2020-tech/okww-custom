# -*- coding: utf-8 -*-
"""okww 修改版启动入口。

- 启动前自动同步「定制 ok 框架」（ConfigItemFactory 等，防止 pip 标准版缺类型崩溃）
- 单实例保护：已有实例运行时，本实例直接退出
- 正常退出时联动结束 pyappify 启动器（关窗口 = 所有相关进程全关）
"""
import os
import shutil
import sys
import atexit


def _sync_custom_ok():
    """把 custom_ok 里的定制框架文件同步到 site-packages 的 ok 包（缺才补，每次启动检查）。"""
    try:
        import ok

        base = os.path.dirname(os.path.abspath(__file__))
        custom_dir = os.path.join(base, 'custom_ok', 'ok')
        if not os.path.isdir(custom_dir):
            return
        ok_pkg_dir = os.path.dirname(ok.__file__)
        for dirpath, _dirnames, filenames in os.walk(custom_dir):
            rel = os.path.relpath(dirpath, custom_dir)
            for f in filenames:
                if not f.endswith('.py'):
                    continue
                src = os.path.join(dirpath, f)
                dst = os.path.join(ok_pkg_dir, rel, f)
                try:
                    with open(dst, encoding='utf-8') as fh:
                        existing = fh.read()
                    with open(src, encoding='utf-8') as fh:
                        custom = fh.read()
                    if existing != custom:
                        shutil.copy2(src, dst)
                        print(f'[okww] 已同步定制框架: {rel}\\{f}')
                except FileNotFoundError:
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.copy2(src, dst)
                    print(f'[okww] 已安装定制框架: {rel}\\{f}')
                except Exception:
                    pass
    except Exception:
        pass


def _ensure_single_instance():
    """单实例保护：检测是否已有本应用（同 main.py 路径）实例在运行。"""
    try:
        import psutil

        me = os.getpid()
        this = os.path.abspath(__file__).replace('/', '\\')
        for p in psutil.process_iter(['pid', 'cmdline']):
            try:
                if p.info['pid'] == me:
                    continue
                cmd = ' '.join(p.info['cmdline'] or []).replace('/', '\\')
                if 'main.py' in cmd and this in cmd:
                    return False
            except Exception:
                continue
    except Exception:
        pass
    return True


def _exit_cleanup():
    """正常退出时，联动结束 pyappify 启动器及其 WebView 子进程（关窗口 = 全部进程退出）。

    仅正常退出（python 进程自行结束时 atexit 触发）执行；
    更新/强制结束（外部杀进程）不触发，不会中断 pyappify 更新流程。
    """
    exe = os.environ.get('PYAPPIFY_EXECUTABLE')
    if not exe:
        return
    try:
        import subprocess
        base = os.path.basename(exe)
        exe_dir = os.path.dirname(exe)
        # 1. 终止 pyappify 启动器进程树（连带其 WebView 子进程）
        subprocess.Popen(
            ['taskkill', '/f', '/t', '/im', base],
            creationflags=0x08000000,  # CREATE_NO_WINDOW
        )
        # 2. 清理 okww 相关孤儿 WebView（按 user-data-dir 所在目录匹配，Kill Launcher After Start 残留的）
        ps = (
            "Get-CimInstance Win32_Process -Filter \"Name='msedgewebview2.exe'\" | "
            f"Where-Object {{ $_.CommandLine -like '*{exe_dir}*' }} | "
            "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
        )
        subprocess.Popen(['powershell', '-NoProfile', '-Command', ps],
                         creationflags=0x08000000)
    except Exception:
        pass


if __name__ == '__main__':
    _sync_custom_ok()
    if not _ensure_single_instance():
        print('[okww] 检测到已有实例在运行，本实例退出（单实例保护）')
        sys.exit(0)
    # 使用端诊断：启动时收集环境/登录器/配置信息输出日志（排查账号登录信息问题）
    try:
        from src.diagnose import save_diagnosis
        diag_file = save_diagnosis()
        print(f'[okww] 诊断日志: {diag_file}')
    except Exception:
        pass
    atexit.register(_exit_cleanup)
    from config import config
    from ok import OK

    config = config
    ok = OK(config)
    ok.start()
