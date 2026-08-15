# -*- coding: utf-8 -*-
"""🔀 KRLauncher 序列切换任务：通过切换 %APPDATA%\\KRLauncher 目录联接（Junction）隔离多批账号登录数据。

背景：鸣潮登录器（KRLauncher）的登录数据存在 %APPDATA%\\KRLauncher\\，同一 Windows 用户共享
一份数据、最多保存 10 个账号。本任务把数据目录按「序列」切分（KRLauncher_b1/b2/...），
通过切换 %APPDATA%\\KRLauncher 的目录联接指向，实现多批（每批 10 个）账号的隔离登录。

功能：
  - 初始化：把当前实体登录数据备份为「序列1」，并创建目录联接
  - 切换序列：自动关闭登录器/游戏 → 切换联接点 → （可选）启动登录器
  - 与每日任务账号方案联动：账号方案 ↔ 序列 映射
  - 顺序托管：按账号顺序逐个切换序列 + （可选）运行每日任务

来源：E:\\AI work\\wuwa changange（鸣潮多账号方案），集成到 okww 修改版。
"""

import glob
import os
import re
import subprocess
import time

from ok import Logger
from src.task.BaseWWTask import BaseWWTask
from src.task.WWOneTimeTask import WWOneTimeTask

logger = Logger.get_logger(__name__)

LAUNCHER_PATH = '登录器路径'
DATA_ROOT = '数据根目录'
SEQ_NAMES = ['序列 %d 名称' % i for i in range(1, 6)]
TARGET_SEQUENCE = '切换序列'
CURRENT_SEQUENCE_LABEL = '当前序列'
LAUNCH_AFTER = '切换后启动登录器'
BACKUP_DIR = '备份目录'
SYNC_GAME_DATA = '同步切换游戏登录缓存'
GAME_INSTALL_DIR = '游戏安装目录'

# 登录器常见路径（自动探测）
LAUNCHER_PATTERNS = [
    r"C:\Program Files\Wuthering Waves\launcher.exe",
    r"C:\game\Wuthering Waves\launcher.exe",
    r"E:\game\Wuthering Waves\launcher.exe",
    r"D:\game\Wuthering Waves\launcher.exe",
]

# 需要自动关闭的进程
PROC_PATTERNS = ['launcher.exe', 'launcher_main.exe', 'launcher_updater.exe',
                 'Wuthering Waves.exe', 'Client-Win64-Shipping.exe']


class KRLauncherSwitchTask(WWOneTimeTask, BaseWWTask):
    """序列切换任务（精简版）：只负责切换账号数据所在文件夹（Junction 指向的序列），
    不涉及账号方案/每日任务。账号与序列的归属关系由「多账号每日任务」模块管理。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = '🔀 KRLauncher 序列切换'
        self.description = '切换账号数据所在文件夹（KRLauncher 登录数据序列）'
        self.support_schedule_task = False
        self.default_config = {
            LAUNCHER_PATH: '',
            DATA_ROOT: os.path.join(os.environ.get('APPDATA', ''), 'KRLauncher'),
            TARGET_SEQUENCE: '序列1',
            CURRENT_SEQUENCE_LABEL: '',
            # 切换序列期间保持启动器关闭（数据安全，避免数据被占用/损坏）；
            # 切换完成后由用户手动打开登录器登录账号
            LAUNCH_AFTER: False,
            BACKUP_DIR: '',
            # 同步切换游戏本体登录缓存（LocalStorage 等），实现账号完整隔离
            SYNC_GAME_DATA: True,
            GAME_INSTALL_DIR: '',
        }
        for i in range(1, 6):
            self.default_config[SEQ_NAMES[i - 1]] = f'序列{i}'
        self.config_description = {
            LAUNCHER_PATH: '',
            DATA_ROOT: '',
            TARGET_SEQUENCE: '',
            CURRENT_SEQUENCE_LABEL: '当前激活的序列（只读，从登录数据联接点实时读取）',
            LAUNCH_AFTER: '切换完成后是否自动启动登录器（默认关闭：切换期间保持启动器关闭，数据安全，由你手动打开登录器）',
            BACKUP_DIR: '序列登录数据备份目录（留空默认 %APPDATA%\\KRLauncher_backup）',
            SYNC_GAME_DATA: '切换序列时同步切换游戏本体登录缓存（Client\\Saved 的 LocalStorage 等，需已初始化）',
            GAME_INSTALL_DIR: '鸣潮游戏安装目录（留空自动探测）',
        }
        for i in range(1, 6):
            self.config_description[SEQ_NAMES[i - 1]] = f'序列{i} 的名称（日志显示用）。'
        self.config_type = {
            TARGET_SEQUENCE: {'type': 'drop_down', 'options': [f'序列{i}' for i in range(1, 6)]},
            CURRENT_SEQUENCE_LABEL: {'type': 'label'},
        }
        # SYNC_GAME_DATA（bool 默认值）由框架自动渲染为开关，无需显式类型

    # ==================== 基础操作 ====================

    def find_launcher(self):
        """查找登录器路径（配置 > 自动探测）。"""
        configured = (self.config.get(LAUNCHER_PATH) or '').strip()
        if configured and os.path.exists(configured):
            return configured
        for pattern in LAUNCHER_PATTERNS:
            matches = sorted(glob.glob(pattern))
            if matches:
                return matches[0]
        return None

    def _kr_data(self):
        """数据根目录。"""
        return (self.config.get(DATA_ROOT) or os.path.join(os.environ.get('APPDATA', ''), 'KRLauncher')).strip()

    def _seq_dir(self, seq_id):
        """序列 N 的实体目录。"""
        return f'{self._kr_data()}_b{seq_id}'

    def is_junction(self, path):
        """检测路径是否为目录联接（Junction）。"""
        if not os.path.exists(path):
            return False
        try:
            # 注意：不要传 errors/text 参数（会让 stdout 变成 str 且编码错乱），保持 bytes
            r = subprocess.run(['fsutil', 'reparsepoint', 'query', path],
                               capture_output=True, timeout=10)
            return r.returncode == 0
        except Exception:
            # fsutil 不可用时回退到 Python 判断
            return os.path.islink(path)

    def junction_target(self, path):
        """返回联接点指向的目标路径（非联接点返回 None）。"""
        if not self.is_junction(path):
            return None
        try:
            r = subprocess.run(['fsutil', 'reparsepoint', 'query', path],
                               capture_output=True, timeout=10)
            out = r.stdout.decode('gbk', errors='replace')
            # 目标路径在「替换名称 / Substitute Name」行（\\??\\ 前缀），
            # 注意区分「打印名称偏移/长度」等元数据行（必须紧跟冒号）
            m = re.search(r'(?:Substitute Name|替换名称|替代名稱)\s*[:：]\s*(.+?)\s*$', out, re.MULTILINE)
            if m:
                target = m.group(1).strip()
                return target.lstrip('\\??\\') or None
        except Exception:
            pass
        return None

    def _make_junction(self, link, target):
        """创建目录联接（与 MC_Manager 一致：PowerShell New-Item -ItemType Junction）。"""
        ps = f"New-Item -ItemType Junction -Path '{link}' -Target '{target}' -Force"
        r = subprocess.run(['powershell', '-NoProfile', '-Command', ps],
                           capture_output=True, text=True, timeout=30)
        return os.path.exists(link) and self.is_junction(link)

    def _remove_junction(self, link):
        """删除目录联接（junction 用 rmdir 只删链接不删目标）。"""
        if self.is_junction(link):
            os.rmdir(link)
            return not os.path.exists(link)
        return False

    def close_game_procs(self, wait_timeout=10):
        """自动关闭登录器/游戏及其 WebView2 界面进程，并等待确认退出。

        关键：登录器的 WebView2（msedgewebview2.exe）持有旧数据句柄，切换序列时
        若不杀掉，会继续向（已指向新序列的）KRLauncher 目录写入序列1 的账号缓存，
        导致新序列里出现旧账号。仅杀命令行含 KRLauncher/Wuthering 的 WebView2，
        避免误杀 Windows 搜索等其他应用的 WebView2。
        """
        import psutil
        import time as _t
        killed = []
        # 收集目标：PROC_PATTERNS 匹配 + 登录器 WebView2
        for p in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                name = (p.info['name'] or '').lower()
                is_target = any(name == pat.lower() or (pat.lower() in name) for pat in PROC_PATTERNS)
                if not is_target and name == 'msedgewebview2.exe':
                    cmd = ' '.join(p.info['cmdline'] or []).lower()
                    if 'krlauncher' in cmd or 'wuthering' in cmd:
                        is_target = True
                if is_target:
                    p.kill()
                    killed.append((p.info['pid'], p.info['name']))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        # 补杀被杀进程的子进程（WebView2 子进程等）
        for pid, _name in list(killed):
            try:
                for child in psutil.Process(pid).children(recursive=True):
                    try:
                        child.kill()
                        killed.append((child.pid, child.name()))
                    except Exception:
                        continue
            except Exception:
                continue
        if killed:
            self.log_info(f'已关闭进程: {sorted(set(n for _, n in killed))}，等待退出确认...')
            deadline = _t.time() + wait_timeout
            dead_names = {n.lower() for _, n in killed}
            while _t.time() < deadline:
                still = [p.info['name'] for p in psutil.process_iter(['name'])
                         if (p.info['name'] or '').lower() in dead_names]
                if not still:
                    break
                _t.sleep(0.5)
            if still:
                self.log_warning(f'部分进程仍未退出: {still}')
        return [n for _, n in killed]

    def get_active_sequence(self):
        """当前激活的序列号（从 KRLauncher 联接点指向解析），未激活返回 None。"""
        target = self.junction_target(self._kr_data())
        if not target:
            return None
        m = re.search(r'KRLauncher_b(\d+)\s*$', target)
        return int(m.group(1)) if m else None

    # ==================== 游戏本体登录缓存（Client\\Saved）序列切换 ====================
    # 游戏本体的登录缓存（LocalStorage/DeviceSaved/SaveGames）存在游戏安装目录，
    # 与登录器数据（%APPDATA%\\KRLauncher）独立；同步切换才能做到账号完整隔离。

    GAME_SAVED_SUBDIRS = ['LocalStorage', 'DeviceSaved', 'SaveGames']

    def _game_saved_dir(self):
        """探测游戏登录缓存目录 Client\\Saved（配置 > 从登录器路径推断）。"""
        configured = (self.config.get('游戏安装目录') or '').strip()
        if configured and os.path.isdir(os.path.join(configured, 'Client', 'Saved')):
            return os.path.join(configured, 'Client', 'Saved')
        launcher = self.find_launcher()
        if launcher:
            candidate = os.path.join(os.path.dirname(launcher), 'Wuthering Waves Game', 'Client', 'Saved')
            if os.path.isdir(candidate):
                return candidate
        for pattern in [r'C:\Program Files\Wuthering Waves',
                        r'C:\game\Wuthering Waves', r'E:\game\Wuthering Waves', r'D:\game\Wuthering Waves']:
            candidate = os.path.join(pattern, 'Wuthering Waves Game', 'Client', 'Saved')
            if os.path.isdir(candidate):
                return candidate
        return None

    def _game_seq_root(self):
        """游戏登录缓存序列数据根（%APPDATA%\\WW_GameData）。"""
        return os.path.join(os.environ.get('APPDATA', ''), 'WW_GameData')

    def game_data_initialized(self):
        """游戏登录缓存是否已序列化（Saved\\LocalStorage 是联接点）。"""
        saved = self._game_saved_dir()
        return bool(saved) and self.is_junction(os.path.join(saved, 'LocalStorage'))

    def get_active_game_sequence(self):
        """当前游戏登录缓存的序列号（从 LocalStorage 联接点指向解析）。"""
        saved = self._game_saved_dir()
        if not saved:
            return None
        target = self.junction_target(os.path.join(saved, 'LocalStorage'))
        if not target:
            return None
        m = re.search(r'序列(\d+)[\\/]LocalStorage\s*$', target)
        return int(m.group(1)) if m else None

    def _switch_game_junction(self, link, seq_dir):
        """切换单个游戏数据联接点：删旧 → 建新。

        删除联接点必须用 [System.IO.Directory]::Delete()（.NET junction 专用，
        只删链接不动目标数据）；cmd rmdir 对带空格路径解析失败，PowerShell
        Remove-Item 对指向非空目录的联接点报"目录不为空"。
        """
        try:
            subprocess.run(['powershell', '-NoProfile', '-Command',
                            f"[System.IO.Directory]::Delete('{link}')"],
                           capture_output=True, timeout=30)
        except Exception:
            pass
        os.makedirs(seq_dir, exist_ok=True)
        ps = f"New-Item -ItemType Junction -Path '{link}' -Target '{seq_dir}' -Force"
        r = subprocess.run(['powershell', '-NoProfile', '-Command', ps],
                           capture_output=True, timeout=30)
        return os.path.exists(link) and r.returncode == 0

    def switch_game_data(self, seq_id):
        """把游戏登录缓存（Client\\Saved 的数据子目录）切到指定序列。未初始化返回 False。"""
        saved = self._game_saved_dir()
        if not saved:
            self.log_warning('未找到游戏安装目录，跳过游戏登录缓存切换')
            return False
        if not self.game_data_initialized():
            self.log_warning('游戏登录缓存未初始化（LocalStorage 非联接点），跳过切换；'
                             '请先初始化：把 Saved\\LocalStorage 等移入 %APPDATA%\\WW_GameData\\序列1 并建联接点')
            return False
        seq_dir = os.path.join(self._game_seq_root(), f'序列{seq_id}')
        ok_all = True
        for d in self.GAME_SAVED_SUBDIRS:
            link = os.path.join(saved, d)
            ok = self._switch_game_junction(link, os.path.join(seq_dir, d))
            if not ok:
                self.log_error(f'游戏登录缓存 {d} 切换失败')
                ok_all = False
        if ok_all:
            self.log_info(f'游戏登录缓存已切到序列{seq_id}: {seq_dir}', notify=True)
        return ok_all

    # ==================== 游戏目录账号标记（Binaries\\Win64）序列切换 ====================
    # 游戏登录界面显示的"上次账号"来自游戏运行目录 Binaries\\Win64 下的标记文件
    # （*_username_kurodata 等），这些文件不随 Client\\Saved 切换，需单独按序列保存内容。

    BIN64_FILES = ['KDData-data.db', 'TDData-data.db',
                   'cdbe868d4f6248bbbb123f76123e0173_accountId_tag',
                   'cdbe868d4f6248bbbb123f76123e0173_distinctId_tag',
                   'cdbe868d4f6248bbbb123f76123e0173_unique_id_kurodata',
                   'cdbe868d4f6248bbbb123f76123e0173_username_kurodata']
    BIN64_USERNAME_TAG = 'cdbe868d4f6248bbbb123f76123e0173_username_kurodata'

    def _bin64_dir(self):
        """游戏运行目录 Binaries\\Win64（Saved 的父目录 Client 下的 Binaries\\Win64）。"""
        saved = self._game_saved_dir()
        if not saved:
            return None
        return os.path.join(os.path.dirname(saved), 'Binaries', 'Win64')

    def _bin_seq_root(self):
        return os.path.join(self._game_seq_root(), 'Binaries')

    def _bin_seq_dir(self, seq_id):
        return os.path.join(self._bin_seq_root(), f'序列{seq_id}')

    def _bin_current_seq(self):
        """识别 Binaries 当前账号标记对应序列。"""
        bin64 = self._bin64_dir()
        if not bin64:
            return None
        f1 = os.path.join(bin64, self.BIN64_USERNAME_TAG)
        if not os.path.isfile(f1):
            return None
        try:
            v1 = open(f1, 'rb').read()
        except Exception:
            return None
        for i in range(1, 6):
            f2 = os.path.join(self._bin_seq_dir(i), self.BIN64_USERNAME_TAG)
            try:
                if os.path.isfile(f2) and open(f2, 'rb').read() == v1:
                    return i
            except Exception:
                continue
        return None

    def _bin_save_seq(self, seq_id):
        """把 Binaries 当前标记回存到序列副本。"""
        bin64 = self._bin64_dir()
        if not bin64:
            return
        d = self._bin_seq_dir(seq_id)
        os.makedirs(d, exist_ok=True)
        import shutil
        for f in self.BIN64_FILES:
            s = os.path.join(bin64, f)
            if os.path.isfile(s):
                try:
                    shutil.copy2(s, os.path.join(d, f))
                except Exception:
                    pass

    def _bin_apply_seq(self, seq_id):
        """序列副本覆盖到 Binaries。"""
        bin64 = self._bin64_dir()
        if not bin64:
            return False
        d = self._bin_seq_dir(seq_id)
        import shutil
        ok_all = True
        for f in self.BIN64_FILES:
            s = os.path.join(d, f)
            if os.path.isfile(s):
                try:
                    shutil.copy2(s, os.path.join(bin64, f))
                except Exception as e:
                    self.log_error(f'账号标记 {f} 应用失败', e)
                    ok_all = False
            else:
                self.log_warning(f'序列{seq_id} 缺少账号标记文件: {f}（未初始化？）')
                ok_all = False
        return ok_all

    def switch_game_binaries(self, seq_id):
        """切换游戏目录账号标记到指定序列（回存当前 + 应用目标）。未初始化返回 False。"""
        if not os.path.isdir(self._bin_seq_dir(seq_id)):
            self.log_warning(f'游戏账号标记序列{seq_id} 未初始化，跳过（先初始化 Binaries 标记副本）')
            return False
        cur = self._bin_current_seq()
        if cur is not None and cur != seq_id:
            self._bin_save_seq(cur)
            self.log_info(f'已回存当前账号标记(序列{cur})')
        ok = self._bin_apply_seq(seq_id)
        if ok:
            self.log_info(f'游戏账号标记已切到序列{seq_id}', notify=True)
        return ok

    def get_last_completed_display(self):
        """只读标签显示：当前激活序列（框架 label 组件通过此方法取值）。"""
        active = self.get_active_sequence()
        game = self.get_active_game_sequence()
        if active is None and game is None:
            if not os.path.exists(self._kr_data()):
                return '未初始化'
            return '未初始化（KRLauncher 非联接点）'
        parts = [f'登录器序列{active}' if active else '', f'游戏序列{game}' if game else '']
        return '，'.join([p for p in parts if p])

    def seq_has_data(self, seq_id):
        """序列是否有登录数据（G152\\C10003 存在）。"""
        return os.path.exists(os.path.join(self._seq_dir(seq_id), 'G152', 'C10003'))

    def list_sequences(self):
        """列出已有序列（返回 [{id, name, has_data}]）。"""
        seqs = []
        for i in range(1, 6):
            if os.path.exists(self._seq_dir(i)):
                seqs.append({
                    'id': i,
                    'name': self.config.get(SEQ_NAMES[i - 1], f'序列{i}'),
                    'has_data': self.seq_has_data(i),
                })
        return seqs

    # ==================== 序列数据备份 / 恢复（吸收自 mc_manager） ====================

    def _backup_root(self):
        """备份根目录（配置 > 默认 %APPDATA%\\KRLauncher_backup）。"""
        configured = (self.config.get(BACKUP_DIR) or '').strip()
        if configured:
            return configured
        return os.path.join(os.environ.get('APPDATA', ''), 'KRLauncher_backup')

    def _copy_seq_data(self, src_root, dst_root, seq_id):
        """robocopy 复制序列数据目录 G152（更稳，处理大目录/占用）。"""
        src = os.path.join(src_root, 'G152')
        dst = os.path.join(dst_root, 'G152')
        if not os.path.isdir(src):
            return False
        os.makedirs(dst, exist_ok=True)
        r = subprocess.run(['robocopy', src, dst, '/E', '/COPY:DAT', '/R:1', '/W:1',
                            '/NFL', '/NDL', '/NJH', '/NJS'],
                           capture_output=True, timeout=600)
        return r.returncode < 8  # robocopy 0-7 均视为成功

    def backup_sequence(self, seq_id, backup_dir=None):
        """备份指定序列的登录数据（G152）到备份目录。"""
        self.close_game_procs()
        if not self.seq_has_data(seq_id):
            self.log_info(f'序列{seq_id} 暂无登录数据，跳过备份')
            return False
        root = backup_dir or self._backup_root()
        dst = os.path.join(root, f'KRLauncher_b{seq_id}')
        try:
            ok = self._copy_seq_data(self._seq_dir(seq_id), dst, seq_id)
            if ok:
                self.log_info(f'序列{seq_id} 已备份到 {dst}', notify=True)
            else:
                self.log_error(f'序列{seq_id} 备份失败: {dst}')
            return ok
        except Exception as e:
            self.log_error(f'序列{seq_id} 备份异常', e)
            return False

    def restore_sequence(self, seq_id, backup_dir=None):
        """从备份目录恢复指定序列的登录数据。"""
        self.close_game_procs()
        root = backup_dir or self._backup_root()
        src = os.path.join(root, f'KRLauncher_b{seq_id}', 'G152')
        if not os.path.isdir(src):
            self.log_error(f'备份不存在: {src}')
            return False
        try:
            ok = self._copy_seq_data(src, self._seq_dir(seq_id), seq_id)
            if ok:
                self.log_info(f'序列{seq_id} 已从备份恢复: {src}', notify=True)
            else:
                self.log_error(f'序列{seq_id} 恢复失败')
            return ok
        except Exception as e:
            self.log_error(f'序列{seq_id} 恢复异常', e)
            return False

    def backup_all_sequences(self, backup_dir=None):
        """备份所有有数据的序列。返回成功数。"""
        self.close_game_procs()
        done = 0
        for seq in self.list_sequences():
            if seq['has_data'] and self.backup_sequence(seq['id'], backup_dir):
                done += 1
        self.log_info(f'全量备份完成：{done} 个序列', notify=True)
        return done

    def init_sequence(self):
        """初始化：把当前实体登录数据备份为序列1，并创建目录联接。"""
        kr = self._kr_data()
        seq1 = self._seq_dir(1)
        if self.is_junction(kr):
            self.log_info('KRLauncher 已是目录联接，无需初始化（序列方案已启用）')
            return True
        if not os.path.exists(kr):
            self.log_info('KRLauncher 数据目录不存在，创建空的序列1')
            os.makedirs(seq1, exist_ok=True)
        else:
            if os.path.exists(seq1):
                self.log_error(f'序列1目录已存在: {seq1}，请先手动处理（如需重新初始化请先备份）')
                return False
            os.rename(kr, seq1)
            self.log_info(f'当前登录数据已备份为序列1: {seq1}')
        if not self._make_junction(kr, seq1):
            self.log_error('创建目录联接失败（可能需要管理员权限）')
            return False
        self.log_info('初始化完成：KRLauncher → 序列1（目录联接已创建）', notify=True)
        return True

    def switch_sequence(self, seq_id):
        """切换序列：关进程 → 切联接点 → （可选）启动登录器。"""
        kr = self._kr_data()
        seq_dir = self._seq_dir(seq_id)
        if not os.path.exists(seq_dir):
            os.makedirs(seq_dir, exist_ok=True)
            self.log_info(f'序列{seq_id} 目录不存在，已创建: {seq_dir}')

        # 关闭登录器/游戏
        self.close_game_procs()

        # 处理当前 KRLauncher
        if self.is_junction(kr):
            self._remove_junction(kr)
            self.log_info('已移除旧目录联接')
        elif os.path.exists(kr):
            # 实体目录（未初始化场景）
            backup = f'{kr}_tmp_backup'
            os.rename(kr, backup)
            self.log_warning(f'KRLauncher 是实体目录（未初始化），已临时改名为 {backup}')

        # 创建新联接点
        if not self._make_junction(kr, seq_dir):
            self.log_error(f'创建目录联接到序列{seq_id} 失败')
            return False
        self.log_info(f'已切换到序列{seq_id}: {kr} → {seq_dir}', notify=True)

        # 同步切换游戏本体登录缓存（若已启用且已初始化）
        if self.config.get(SYNC_GAME_DATA, True):
            self.switch_game_data(seq_id)
            self.switch_game_binaries(seq_id)
        else:
            self.log_info('未启用「同步切换游戏登录缓存」，仅切换登录器数据')

        # 启动登录器
        if self.config.get(LAUNCH_AFTER, True):
            launcher = self.find_launcher()
            if launcher:
                self.log_info(f'启动登录器: {launcher}')
                subprocess.Popen([launcher], cwd=os.path.dirname(launcher))
            else:
                self.log_warning('未找到登录器，跳过启动')
        return True

    # ==================== 主流程 ====================

    def check_launcher_running(self):
        """检测启动器/游戏进程是否在运行，返回进程名列表（切换前数据安全检查）。"""
        import psutil
        running = []
        for p in psutil.process_iter(['name']):
            try:
                name = (p.info['name'] or '').lower()
                if any(name == pat.lower() or (pat.lower() in name) for pat in PROC_PATTERNS):
                    if p.info['name'] not in running:
                        running.append(p.info['name'])
            except Exception:
                continue
        return running

    def run(self):
        WWOneTimeTask.run(self)
        self.info_set('current task', 'kr launcher switch')
        self.log_info('KRLauncher 序列切换任务启动')

        # ⚠️ 切换前检查：启动器/游戏是否仍在运行（数据安全，避免切换时数据被占用/损坏）
        running = self.check_launcher_running()
        if running:
            self.log_warning(f'检测到启动器/游戏仍在运行: {running}，切换前将自动关闭（数据安全）', notify=True)
        else:
            self.log_info('启动器/游戏未在运行，可以直接切换')

        # 安全检查：数据根目录
        kr = self._kr_data()
        if not kr or not os.path.isdir(os.path.dirname(kr)):
            self.log_error(f'数据根目录无效: {kr}')
            raise RuntimeError('KRLauncher data root invalid')

        # 切换用户选择的序列（纯粹：只切换账号数据所在文件夹）
        target = (self.config.get(TARGET_SEQUENCE) or '序列1').strip()
        seq_id = int(target.replace('序列', '')) if target.startswith('序列') else 1
        seq_id = max(1, min(5, seq_id))
        self.switch_sequence(seq_id)
        self.log_info('KRLauncher 序列切换任务完成', notify=True)

    # ==================== PC 端退登（从原 ADB 任务迁移，供 DailyTask 自动退登调用） ====================

    def _ensure_pc_login_screen(self):
        """确保 PC 端处于登录界面（切换下一个账号前调用）。

        每日任务正常结束后自动退登 PC 端，准备下一个账号。
        流程（用户实测校准）：
          等20s → ESC → 等10s → 点退出登录(0.040,0.942) → 识别「返回登录」点击
          → 等20s → 识别「登录」点击 → 等待下一个账号
        """
        self.log_info('每日任务完成，自动退登 PC 端准备下一个账号', notify=True)
        self.sleep(20)

        # ESC 退出当前界面
        try:
            self.send_key('esc')
            self.log_info('已发送 ESC 键')
        except Exception as e:
            self.log_error('发送 ESC 失败', e)
        self.sleep(10)

        # 点「退出登录」按钮（用户实测屏幕归一化坐标 0.040,0.942）
        import ctypes
        sw = ctypes.windll.user32.GetSystemMetrics(0)
        sh = ctypes.windll.user32.GetSystemMetrics(1)
        px, py = int(0.040 * sw), int(0.942 * sh)
        self._mouse_click(px, py)
        self.log_info(f'点击退出登录 ({px},{py})')
        self.sleep(3)

        # 识别「返回登录」字样并点击（OCR，找不到则提示）
        if not self._screen_tap_text('返回登录'):
            self.log_info('未识别到「返回登录」，继续流程')
        self.sleep(20)

        # 识别鸣潮界面「登录」字样并点击
        if not self._screen_tap_text('登录'):
            self.log_info('未识别到「登录」，继续流程')
        self.log_info('已退登，等待下一个账号登录', notify=True)

    def _screen_grab(self):
        """Windows 桌面全屏截图，返回 BGR ndarray。"""
        import ctypes
        from ctypes import wintypes
        import numpy as np
        import cv2
        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32
        sw = user32.GetSystemMetrics(0)
        sh = user32.GetSystemMetrics(1)
        hdc = user32.GetDC(0)
        mdc = gdi32.CreateCompatibleDC(hdc)
        hbmp = gdi32.CreateCompatibleBitmap(hdc, sw, sh)
        gdi32.SelectObject(mdc, hbmp)
        gdi32.BitBlt(mdc, 0, 0, sw, sh, hdc, 0, 0, 0x00CC0020)  # SRCCOPY

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long),
                        ("biHeight", ctypes.c_long), ("biPlanes", wintypes.WORD),
                        ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                        ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD),
                        ("biClrImportant", wintypes.DWORD)]
        bmi = BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.biWidth = sw
        bmi.biHeight = -sh  # top-down
        bmi.biPlanes = 1
        bmi.biBitCount = 32
        bmi.biCompression = 0
        buf = ctypes.create_string_buffer(sw * sh * 4)
        gdi32.GetDIBits(mdc, hbmp, 0, sh, buf, ctypes.byref(bmi), 0)
        img = np.frombuffer(buf, np.uint8).reshape(sh, sw, 4)
        bgr = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
        gdi32.DeleteObject(hbmp)
        gdi32.DeleteDC(mdc)
        user32.ReleaseDC(0, hdc)
        return bgr

    def _screen_find_text(self, text, threshold=0.4):
        """全屏 OCR 找文字，返回屏幕像素中心 (x,y)；未找到返回 None。"""
        frame = self._screen_grab()
        results = self.ocr_text(frame, threshold=threshold)
        text = text.strip()
        for t, x, y, w, h in results:
            if t.strip() == text:
                return int(x + w / 2), int(y + h / 2)
        best, best_diff = None, 10 ** 9
        for t, x, y, w, h in results:
            t = t.strip()
            if t and (text in t or t in text):
                diff = abs(len(t) - len(text))
                if diff < best_diff:
                    best_diff = diff
                    best = (int(x + w / 2), int(y + h / 2))
        return best

    def _mouse_click(self, px, py):
        """Windows 鼠标移动+左键点击（屏幕像素坐标）。"""
        import ctypes
        user32 = ctypes.windll.user32
        user32.SetCursorPos(int(px), int(py))
        user32.mouse_event(0x0002, 0, 0, 0, 0)  # MOUSEEVENTF_LEFTDOWN
        user32.mouse_event(0x0004, 0, 0, 0, 0)  # MOUSEEVENTF_LEFTUP
        self.sleep(0.2)

    def _screen_tap_text(self, text, fallback=None, threshold=0.4):
        """全屏 OCR 找文字 → 鼠标点击。找不到用 fallback 归一化屏幕坐标。"""
        pos = self._screen_find_text(text, threshold=threshold)
        if pos:
            self._mouse_click(pos[0], pos[1])
            self.log_info(f'屏幕 OCR 点击「{text}」于 {pos} (屏幕像素)')
            return True
        if fallback:
            import ctypes
            sw = ctypes.windll.user32.GetSystemMetrics(0)
            sh = ctypes.windll.user32.GetSystemMetrics(1)
            px, py = int(fallback[0] * sw), int(fallback[1] * sh)
            self._mouse_click(px, py)
            self.log_info(f'屏幕 OCR 未找到「{text}」，兜底点击 ({px},{py})')
            return True
        self.log_info(f'屏幕 OCR 未找到「{text}」且无兜底')
        return False


from ok import run_task
from config import config

if __name__ == '__main__':
    run_task(config, task=KRLauncherSwitchTask, debug=True)
