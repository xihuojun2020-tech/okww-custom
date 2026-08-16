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
    """单实例保护：检测是否已有本应用（同 main.py 绝对路径）实例在运行。

    兼容 cmdline 中相对路径（如 `pythonw.exe main.py`）：用进程工作目录转绝对路径再比较。
    拦截时打印匹配进程信息，便于排查误判。
    """
    try:
        import psutil

        me = os.getpid()
        this = os.path.normpath(os.path.abspath(__file__))
        for p in psutil.process_iter(['pid', 'cmdline']):
            try:
                if p.info['pid'] == me:
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


def _setup_proxy():
    """联网代理自愈：探测可用代理并写入 repo/.git/config 的 [http] proxy。

    即使直接双击 okww-custom.exe（未经过「启动okww.bat」），okww 启动后也会把代理
    配置写进 repo 本地 git 配置 → 下次 PyAppify fetch 稳定走代理，不再直连超时。
    无可用代理时移除代理配置（回退直连）。
    """
    try:
        base = os.path.dirname(os.path.abspath(__file__))  # working 目录
        git_config = os.path.join(base, '..', 'repo', '.git', 'config')
        if not os.path.isfile(git_config):
            return
        import socket as _socket

        def _port_open(host, port, timeout=0.4):
            try:
                with _socket.create_connection((host, port), timeout=timeout):
                    return True
            except Exception:
                return False

        def _find_proxy():
            candidates = []
            # 系统代理（注册表）
            try:
                import winreg
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                     r'Software\Microsoft\Windows\CurrentVersion\Internet Settings')
                enable, _ = winreg.QueryValueEx(key, 'ProxyEnable')
                server, _ = winreg.QueryValueEx(key, 'ProxyServer')
                winreg.CloseKey(key)
                if enable and server:
                    candidates.append(server.strip())
            except Exception:
                pass
            # 常见代理端口
            for p in (7890, 10809, 1080, 7897):
                candidates.append(f'127.0.0.1:{p}')
            seen = set()
            for c in candidates:
                if c in seen:
                    continue
                seen.add(c)
                host, _, port = c.rpartition(':')
                try:
                    port = int(port)
                except ValueError:
                    continue
                if _port_open(host or '127.0.0.1', port):
                    return f'{host or "127.0.0.1"}:{port}'
            return None

        def _set_git_proxy(proxy):
            with open(git_config, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            kept, in_http = [], False
            for line in lines:
                if line.strip().startswith('[http]'):
                    in_http = True
                    continue
                if in_http:
                    if line.strip().startswith('['):
                        in_http = False
                        kept.append(line)
                    continue
                kept.append(line)
            while kept and kept[-1].strip() == '':
                kept.pop()
            if proxy:
                kept.append('\n[http]\n')
                kept.append(f'\tproxy = http://{proxy}\n')
            with open(git_config, 'w', encoding='utf-8') as f:
                f.writelines(kept)
            return proxy

        proxy = _find_proxy()
        result = _set_git_proxy(proxy)
        if result:
            print(f'[okww] 代理已配置: {result}（git fetch 将走代理）')
        else:
            print('[okww] 未发现可用代理，已回退直连')
    except Exception:
        pass


if __name__ == '__main__':
    _sync_custom_ok()
    if not _ensure_single_instance():
        print('[okww] 检测到已有实例在运行，本实例退出（单实例保护）')
        sys.exit(0)
    # 联网代理自愈：探测代理并写入 repo git 配置（下次 fetch 走代理）
    _setup_proxy()
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
    ok = None
    try:
        ok = OK(config)
        ok.start()
    except Exception as e:
        # 启动异常（含 OK 构造）：写日志 + 弹窗（pythonw 无控制台时不再静默崩溃）
        import traceback
        tb = traceback.format_exc()
        try:
            log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
            os.makedirs(log_dir, exist_ok=True)
            with open(os.path.join(log_dir, '启动错误.log'), 'a', encoding='utf-8') as f:
                from datetime import datetime
                f.write(f'\n[{datetime.now():%Y-%m-%d %H:%M:%S}] 启动失败:\n{tb}\n')
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0,
                f'OK-WW 启动失败：\n{str(e)[:300]}\n\n详细信息见 logs\\启动错误.log',
                'OK-WW 错误',
                0x10,  # MB_ICONERROR
            )
        except Exception:
            pass
        sys.exit(1)
