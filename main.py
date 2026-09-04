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
import time


def _load_pth_paths():
    """加载 .venv site-packages 的 .pth 声明路径（pywin32 的 win32 等子目录）。

    当用 runtime python + PYTHONPATH 启动（bat 方案）时，PYTHONPATH 只提供
    site-packages 顶层，.pth 声明的子目录（win32/win32\\lib/Pythonwin 等）不会
    自动生效——这里手动补齐，否则 import win32api 等会失败。
    """
    try:
        base = os.path.dirname(os.path.abspath(__file__))
        sp = os.path.join(base, '.venv', 'Lib', 'site-packages')
        if not os.path.isdir(sp):
            return
        for f in os.listdir(sp):
            if not f.endswith('.pth'):
                continue
            try:
                with open(os.path.join(sp, f), encoding='utf-8', errors='replace') as fh:
                    for line in fh:
                        line = line.strip()
                        if not line or line.startswith('#'):
                            continue
                        if line.startswith('import'):
                            # 仅执行白名单引导模块的 import 行（如 pywin32_bootstrap：
                            # 注册 DLL 目录）；其余 import 一律跳过，防止被篡改的
                            # .pth 在启动时注入任意代码。
                            _PTH_IMPORT_ALLOWLIST = {'import pywin32_bootstrap', 'import pywin32_postinstall'}
                            try:
                                if line in _PTH_IMPORT_ALLOWLIST:
                                    exec(line)
                            except Exception:
                                pass
                            continue
                        p = os.path.normpath(os.path.join(sp, line))
                        if os.path.isdir(p) and p not in sys.path:
                            sys.path.insert(0, p)
            except Exception:
                continue
    except Exception:
        pass


# 必须最先执行（在 import ok/config 之前），确保 pywin32 等路径可用
_load_pth_paths()


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
    """单实例保护：检测是否已有本应用（同 main.py 绝对路径）实例在运行。

    兼容 cmdline 中相对路径（如 `pythonw.exe main.py`）：用进程工作目录转绝对路径再比较。
    拦截时打印匹配进程信息，便于排查误判。
    """
    try:
        import psutil

        me = os.getpid()
        this = os.path.normpath(os.path.abspath(__file__))
        for p in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                if p.info['pid'] == me:
                    continue
                # 只匹配 python/pythonw 进程（bash/cmd/其他工具 cmdline 含 main.py 不误拦）
                pname = (p.info['name'] or '').lower()
                if pname not in ('python.exe', 'pythonw.exe'):
                    continue
                parts = p.info['cmdline'] or []
                for part in parts:
                    part = part.strip().strip('"').replace('/', '\\')
                    if not part.endswith('main.py'):
                        continue
                    match = False
                    if os.path.isabs(part):
                        match = os.path.normpath(part) == this
                    else:
                        try:
                            cwd = psutil.Process(p.info['pid']).cwd()
                            match = os.path.normpath(os.path.join(cwd, part)) == this
                        except Exception:
                            pass
                    if match:
                        try:
                            cwd_info = psutil.Process(p.info['pid']).cwd()
                        except Exception:
                            cwd_info = '?'
                        print(f'[okww] 单实例拦截: PID={p.info["pid"]} cwd={cwd_info} '
                              f'cmdline={" ".join(parts)[:120]}')
                        # 三选弹窗：继续使用现有 / 结束旧实例并重启 / 取消
                        try:
                            import ctypes
                            res = ctypes.windll.user32.MessageBoxW(
                                0,
                                'OK-WW 已有实例在运行。\n\n'
                                '[是] 结束旧实例并重新启动（注意：旧实例正在运行的任务会被中断）\n'
                                '[否] 继续使用现有实例\n'
                                '[取消] 放弃本次启动',
                                'OK-WW 单实例',
                                0x3 | 0x20,  # MB_YESNOCANCEL | MB_ICONQUESTION
                            )
                            if res == 6:  # IDYES：结束旧实例（含其子进程）并继续启动
                                import subprocess
                                old_pid = p.info['pid']
                                subprocess.Popen(
                                    ['taskkill', '/f', '/t', '/pid', str(old_pid)],
                                    creationflags=0x08000000,
                                )
                                time.sleep(1.5)
                                return True
                            # IDNO(7)/IDCANCEL(2)：本实例退出
                            return False
                        except Exception:
                            return False
                    break
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


def _set_owned_git_proxy(git_config, proxy):
    """Change only http.proxy, preserving every other repository setting."""
    from auto_proxy import set_git_proxy

    set_git_proxy(git_config, proxy)
    return proxy


def _setup_proxy():
    """Verify GitHub routing and repair the packaged repository for next fetch."""
    try:
        from auto_proxy import configure_repo_proxy, find_bootstrap_log, find_packaged_git_config

        base = os.path.dirname(os.path.abspath(__file__))
        git_config = find_packaged_git_config(base)
        if git_config:
            configure_repo_proxy(
                git_config,
                log_path=find_bootstrap_log(base),
            )
    except Exception as error:
        print(f'[okww] 代理自愈失败: {error}')


def _report_startup_error(error, traceback_text=None):
    """Persist and surface startup failures, including integrity hook errors."""
    import traceback
    from src.observability import redact_message
    tb = redact_message(traceback_text or traceback.format_exc())
    safe_error = redact_message(error)
    try:
        log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
        os.makedirs(log_dir, exist_ok=True)
        with open(os.path.join(log_dir, '启动错误.log'), 'a', encoding='utf-8') as stream:
            from datetime import datetime
            stream.write(f'\n[{datetime.now():%Y-%m-%d %H:%M:%S}] 启动失败:\n{tb}\n')
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            0,
            f'OK-WW 启动失败：\n{safe_error[:300]}\n\n详细信息见 logs\\启动错误.log',
            'OK-WW 错误',
            0x10,
        )
    except Exception:
        pass


if __name__ == '__main__':
    _sync_custom_ok()
    if not _ensure_single_instance():
        print('[okww] 检测到已有实例在运行，本实例退出（单实例保护）')
        sys.exit(0)
    # 联网代理自愈：探测代理并写入 repo git 配置（下次 fetch 走代理）
    _setup_proxy()
    atexit.register(_exit_cleanup)
    # 后台检查原版 okww 是否有更新（不阻塞启动；有更新写入标志，首页显示提醒）
    try:
        import threading
        from src.upstream_check import check_upstream
        threading.Thread(target=check_upstream, daemon=True).start()
    except Exception:
        pass
    # Read-only account integrity preflight must happen before OK constructs
    # task objects or any start controller can refresh/activate a device.
    from config import version as _program_version
    from src.runtime.account_runtime_bootstrap import initialize_account_runtime
    _integrity_root = os.path.dirname(os.path.abspath(__file__))
    try:
        initialize_account_runtime(_integrity_root, _program_version)
    except Exception as _integrity_hook_error:
        _report_startup_error(_integrity_hook_error)
        raise RuntimeError(f'account integrity start hook unavailable: {_integrity_hook_error}')

    from config import config
    from ok import OK

    config = config
    ok = None
    try:
        ok = OK(config)
        ok.start()
    except Exception as e:
        # 启动异常（含 OK 构造）：写日志 + 弹窗（pythonw 无控制台时不再静默崩溃）
        import traceback
        tb = traceback.format_exc()
        _report_startup_error(e, tb)
        sys.exit(1)
