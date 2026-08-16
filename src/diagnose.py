# -*- coding: utf-8 -*-
"""使用端诊断信息收集（排查登录信息丢失/设备识别等问题）。

输出：logs/诊断_YYYYMMDD_HHMMSS.log
- 环境：机器/Windows/当前账户/用户目录/账户列表
- KRLauncher 数据：目录结构、关键文件与修改时间、设备标识（脱敏）
- 注册表、游戏目录标记、okww 配置概况（手机号脱敏）、相关进程
"""
import json
import os
import platform
import re
import socket
import subprocess
import time
from datetime import datetime


def _mask_phone(text):
    """手机号脱敏：保留前3后4。"""
    if not text:
        return text
    return re.sub(r'(?<!\d)(1\d{2})\d{4}(\d{4})(?!\d)', r'\1****\2', str(text))


def _mask_all_sensitive(text):
    """通用脱敏：手机号 + 长串 token。"""
    if not text:
        return text
    text = _mask_phone(text)
    # 长 token/密钥（32+ 位字母数字）打码
    text = re.sub(r'[A-Za-z0-9]{32,}', lambda m: m.group(0)[:8] + '****', text)
    return text


def _run(cmd, timeout=15):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           encoding='utf-8', errors='replace')
        return (r.stdout or '').strip()
    except Exception as e:
        return f'<error: {e}>'


def _dir_snapshot(path, max_files=30, max_depth=3):
    """目录快照：文件路径/大小/修改时间。"""
    out = []
    if not os.path.isdir(path):
        return f'  不存在: {path}'
    try:
        for root, dirs, files in os.walk(path):
            depth = root[len(path):].count(os.sep)
            if depth > max_depth:
                dirs[:] = []
                continue
            for f in sorted(files):
                try:
                    fp = os.path.join(root, f)
                    st = os.stat(fp)
                    mtime = datetime.fromtimestamp(st.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                    rel = os.path.relpath(fp, path)
                    out.append(f'    {rel} | {st.st_size}B | {mtime}')
                    if len(out) >= max_files:
                        out.append('    ...(截断)')
                        return '\n'.join(out)
                except Exception:
                    continue
    except Exception as e:
        return f'  <error: {e}>'
    return '\n'.join(out) if out else '  (空)'


def _read_text(path, limit=500, mask=True):
    """读取文本文件（截断；mask=False 时保留设备标识原文）。"""
    if not os.path.isfile(path):
        return '  (文件不存在)'
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            data = f.read(limit)
        if mask:
            data = _mask_all_sensitive(data)
        return data.strip() or '  (空)'
    except Exception as e:
        return f'  <error: {e}>'


def collect_diagnosis():
    """收集诊断信息，返回文本。"""
    L = []
    ap = L.append
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    ap(f'===== okww 使用端诊断日志 =====')
    ap(f'生成时间: {now}')
    ap(f'')
    ap('【1. 环境】')
    ap(f'  主机名: {socket.gethostname()}')
    ap(f'  系统: {platform.system()} {platform.version()} (build {platform.platform()})')
    ap(f'  当前账户: {os.environ.get("USERNAME", "?")} ({os.environ.get("USERDOMAIN", "?")})')
    ap(f'  用户目录: {os.environ.get("USERPROFILE", "?")}')
    ap(f'  APPDATA: {os.environ.get("APPDATA", "?")}')
    users = os.listdir(r'C:\Users') if os.path.isdir(r'C:\Users') else []
    # 账户名脱敏（保留首字符 + ***；系统内置目录原样），防止诊断日志泄露账户清单
    _KNOWN = ('Public', 'All Users', 'Default', 'Default User', 'desktop.ini')
    _masked_users = [u if u in _KNOWN else (u[:1] + '***') for u in users]
    ap(f'  C:\\Users 账户数: {len(users)}（名称已脱敏）: {_masked_users}')
    ap(f'')

    ap('【2. KRLauncher 登录器数据】')
    kr = os.path.join(os.environ.get('APPDATA', ''), 'KRLauncher')
    ap(f'  KRLauncher 路径: {kr}')
    ap(_dir_snapshot(kr, max_files=40, max_depth=3))
    ap(f'')
    # 关键标记文件内容（设备标识类原文输出，便于对比；账号类脱敏）
    if os.path.isdir(kr):
        for f in sorted(os.listdir(kr)):
            fp = os.path.join(kr, f)
            if f.endswith('_kurodata') or f.endswith('_tag') or 'cached' in f.lower():
                # 设备标识文件（unique_id/distinctId/accountId/device）保留原文用于对比；含 username 的脱敏
                if any(k in f.lower() for k in ('unique_id', 'distinctid', 'accountid', 'device')):
                    ap(f'  [{f}] -> {_read_text(fp, 200, mask=False)}')
                else:
                    ap(f'  [{f}] -> {_read_text(fp, 200)}')
        # leveldb 明细（记住列表本地缓存的存放位置与文件）
        ldb_found = False
        for root, dirs, files in os.walk(kr):
            if 'leveldb' in os.path.basename(root).lower():
                ldb_found = True
                ap(f'  [leveldb] {root}（{len(files)} 个文件）')
                for lf in sorted(files)[:20]:
                    lp = os.path.join(root, lf)
                    try:
                        st = os.stat(lp)
                        mt = datetime.fromtimestamp(st.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                        ap(f'      {lf} | {st.st_size}B | {mt}')
                    except Exception:
                        continue
        if not ldb_found:
            ap('  [leveldb] 未在 KRLauncher 下找到 leveldb 目录')
        # WebView user-data 目录（登录器界面缓存，可能含账号记录）
        for root, dirs, files in os.walk(kr):
            base = os.path.basename(root).lower()
            if base in ('webview2', 'ebwebview', 'user data', 'usercache') or 'webview' in base:
                ap(f'  [WebView 缓存] {root}（{len(files)} 个文件）')
                break
    ap(f'')

    ap('【3. 注册表（KuroGame）】')
    reg = _run(['reg', 'query', r'HKCU\Software\KuroGame', '/s'])
    ap(_mask_all_sensitive(reg) if reg else '  (无 KuroGame 注册表或读取失败)')
    ap(f'')

    ap('【4. 游戏目录标记（Binaries\\Win64）】')
    # 常见安装位置探测
    candidates = [
        r'C:\Program Files\Wuthering Waves\Wuthering Waves Game\Client\Binaries\Win64',
        r'C:\Program Files\Wuthering Waves\Client\Binaries\Win64',
        r'D:\Wuthering Waves\Client\Binaries\Win64',
        r'D:\Game\Wuthering Waves\Client\Binaries\Win64',
    ]
    found_mark = False
    for c in candidates:
        if os.path.isdir(c):
            ap(f'  游戏目录: {c}')
            for f in sorted(os.listdir(c)):
                if '_kurodata' in f or 'username' in f.lower():
                    fp = os.path.join(c, f)
                    ap(f'    [{f}] -> {_read_text(fp, 200)}')
                    found_mark = True
    if not found_mark:
        ap('  (未在常见位置找到标记文件，可能游戏装在别处)')
    ap(f'')

    ap('【5. okww 配置概况】')
    try:
        ver = _read_file_try('config.py')
        m = re.search(r'version\s*=\s*["\']([^"\']+)["\']', ver)
        ap(f'  代码版本: {m.group(1) if m else "?"}')
    except Exception:
        ap('  version: ?')
    working = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    profiles_path = os.path.join(working, 'configs', 'daily_profiles.json')
    if os.path.isfile(profiles_path):
        try:
            with open(profiles_path, encoding='utf-8') as f:
                profiles = json.load(f)
            n = len(profiles) if isinstance(profiles, (list, dict)) else '?'
            ap(f'  daily_profiles 账号数: {n}')
            # 列出账号标识（脱敏）
            if isinstance(profiles, dict):
                for k in list(profiles.keys())[:30]:
                    ap(f'    - {_mask_all_sensitive(str(k)[:60])}')
            elif isinstance(profiles, list):
                for p in profiles[:30]:
                    ap(f'    - {_mask_all_sensitive(str(p)[:60])}')
        except Exception as e:
            ap(f'  daily_profiles 读取失败: {e}')
    else:
        ap(f'  daily_profiles: 不存在 ({profiles_path})')
    ap(f'')

    ap('【6. 相关进程】')
    try:
        import psutil
        for p in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                n = (p.info['name'] or '').lower()
                cmd = ' '.join(p.info['cmdline'] or [])
                if (any(k in n for k in ('krlauncher', 'wuthering', 'client-win64'))
                        or 'kuro' in cmd.lower() or 'krlauncher' in cmd.lower()):
                    ap(f'  PID={p.info["pid"]} {p.info["name"]}')
                    ap(f'    cmd: {_mask_all_sensitive(cmd[:200])}')
            except Exception:
                continue
    except Exception as e:
        ap(f'  psutil 不可用: {e}')
    ap(f'')
    ap('===== 诊断结束 =====')
    return '\n'.join(L)


def _read_file_try(name):
    base = os.path.dirname(os.path.abspath(__file__))
    for root in (os.path.dirname(base), base):
        p = os.path.join(root, name)
        if os.path.isfile(p):
            with open(p, encoding='utf-8', errors='replace') as f:
                return f.read(2000)
    return ''


def save_diagnosis():
    """生成诊断日志文件（存放于 logs/实验性日志，按类别归并；每次启动生成新文件），返回文件路径。"""
    text = collect_diagnosis()
    working = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    log_dir = os.path.join(working, 'logs', '实验性日志')
    os.makedirs(log_dir, exist_ok=True)
    fname = os.path.join(log_dir, f'诊断_{datetime.now():%Y%m%d_%H%M%S}.log')
    with open(fname, 'w', encoding='utf-8') as f:
        f.write(text)
    return fname


if __name__ == '__main__':
    f = save_diagnosis()
    print(f'诊断日志已生成: {f}')
