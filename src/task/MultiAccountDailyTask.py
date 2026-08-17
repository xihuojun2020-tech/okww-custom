# -*- coding: utf-8 -*-
"""👥 多账号每日任务（增强版）：按序列逐账号跑每日任务，支持断点续跑。

运行机制（原版 + 增强）：
  1. 先从当前已登录账号开始跑一轮每日任务（第一轮即用户手动登录好的起始账号，如 A1）
  2. 跑完后退回登录界面，识别登录界面显示的账号（掩码 180****1088 或扫码 U 开头账号）
  3. 按「已完成记录」跳过今天已打过的账号，从断点账号继续
  4. 每完成一个账号立即写入进度文件（断电/断网/异常中断后恢复，不重复打已完成的账号）
  5. 全部账号完成后：登录回起始账号（不重复执行其每日任务），并提醒用户
  6. 提醒走预留模块 _notify_user（当前：桌面通知 + 日志；后续可扩展 QQ/微信等外部通道）

账号识别：
  - 掩码形式：手机号前3 + **** + 后4（如 180****1088），与方案名中的手机号匹配
  - 扫码登录形式：U 开头的一串字母数字（如 U123456），通过方案里的「账号别名」匹配
  - 两者都作为该账号的身份依据

进度持久化：configs/multi_account_progress.json（按天记录已完成账号方案名）
"""

import os
import re
import time

from ok import Logger
from ok.util.file import get_relative_path, read_json_file, write_json_file
from src.task.DailyTask import DailyTask, DAILY_PROFILE, LOGOUT_AFTER_DAILY as LOGOUT_AFTER_DAILY_KEY
from src.task.WWOneTimeTask import WWOneTimeTask
from src.task.BaseCombatTask import BaseCombatTask
from src.task.BaseWWTask import LOGIN_TEXTS
from src.task.MouseResetTask import MouseResetTask

logger = Logger.get_logger(__name__)

account_pattern = re.compile(r'\*\*\*\*')
# 扫码登录的 U 开头账号（如 U123456，也可能带其他前缀，宽松匹配）
scan_account_pattern = re.compile(r'^U[a-zA-Z0-9]+$', re.IGNORECASE)
# 方案名中的 11 位手机号
phone_in_name_pattern = re.compile(r'(1[3-9]\d{9})')
# 方案短名只匹配开头的完整编号（A1、A3、A10 等），避免 A1 误命中 A10。
profile_short_name_pattern = re.compile(
    r'^\s*【?\s*([a-zA-Z]\d+)(?=[\s\-_.:：】]|$)',
    re.IGNORECASE,
)

CURRENT_SEQUENCE = '当前序列'
CURRENT_ACCOUNT = '当前执行账号'
MANAGE_SEQUENCES = '管理序列'
MAX_SEQUENCES = 10
SEQ_ACCOUNTS = ['序列 %d 账号' % i for i in range(1, MAX_SEQUENCES + 1)]
PROFILE_FILE = get_relative_path('configs', 'daily_profiles.json')
PROGRESS_FILE = get_relative_path('configs', 'multi_account_progress.json')


def normalize_account_name(account):
    """账号归一化（掩码/别名匹配用）：小写、0→o、.con→.com。"""
    if not account:
        return account
    return account.lower().replace('0', 'o').replace('.con', '.com')


def masked_phone(phone):
    """手机号掩码形式：前3 + **** + 后4。"""
    return phone[:3] + '****' + phone[-4:]


def profile_short_name(profile_name):
    """从完整方案名提取精确短名（如 A1/A10）；无法提取时返回 None。"""
    if not profile_name:
        return None
    match = profile_short_name_pattern.search(str(profile_name))
    return match.group(1).upper() if match else None


class MultiAccountDailyTask(WWOneTimeTask, BaseCombatTask):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "👥 多账号每日任务"
        self.description = "按序列逐账号运行每日任务（支持断点续跑）"
        self.add_exit_after_config()
        self.done_set = set()
        self.all_accounts = set()
        self.support_schedule_task = True
        self._profile_cache = {}  # 方案名 → 方案内容（含手机号/别名），用于登录账号识别
        # 当前执行序列（账号归属序列，序列列表来自 daily_profiles 的 sequences，可在下方管理增删）
        self.default_config[CURRENT_SEQUENCE] = '序列1'
        self.config_description[CURRENT_SEQUENCE] = '当前执行的账号序列（按该序列的账号执行；序列可增删）'
        seq_names = self.get_sequence_names()
        # 选择哪个序列，就只显示该序列的账号配置（sub_configs 联动）
        self.config_type[CURRENT_SEQUENCE] = {
            'type': 'drop_down',
            'options': seq_names,
            'sub_configs': {seq: [SEQ_ACCOUNTS[i]] for i, seq in enumerate(seq_names)},
        }
        # 每个序列的账号列表（独立选择、各自记住；账号可跨序列共享，当天已打的账号任何序列都会跳过）
        for i, seq in enumerate(seq_names):
            self.default_config[SEQ_ACCOUNTS[i]] = []
            self.config_description[SEQ_ACCOUNTS[i]] = f'{seq} 包含的账号（按顺序，选过的不会重复出现；无 = 该位置没有账号）'
            self.config_type[SEQ_ACCOUNTS[i]] = {
                'type': 'account_sequence',
                'options': self.get_profile_names(),
                'last_completed_provider': self.get_profile_last_completed,
            }
        # 当前执行账号：选择后从该账号开始执行（选 A3 → A3..A10 完成后继续 A1..A2；留空 = 从当前登录账号开始）
        self.default_config[CURRENT_ACCOUNT] = ''
        self.config_description[CURRENT_ACCOUNT] = '选择从哪个账号开始执行（如选 A3 → A3、A4…A10 完成后继续 A1、A2；留空 = 自动从当前登录账号开始）'
        self.config_type[CURRENT_ACCOUNT] = {
            'type': 'drop_down',
            'options': [''] + self.get_profile_names(),
        }
        # 管理序列（增删/重命名账号归属序列）
        self.default_config[MANAGE_SEQUENCES] = ''
        self.config_description[MANAGE_SEQUENCES] = '增加/删除/重命名账号序列（账号归属随序列保存）'
        self.config_type[MANAGE_SEQUENCES] = {
            'type': 'button', 'text': '管理序列', 'callback': self.manage_sequences,
        }

    def get_profile_last_completed(self, profile_name):
        """返回账号方案的上次完成时间（last_completed 中最新时间，只读展示用）。"""
        try:
            profiles = self._load_profiles()
            profile = profiles.get(profile_name) or {}
            lc = profile.get('last_completed') or {}
            if not isinstance(lc, dict):
                return ''
            times = [str(v) for v in lc.values() if v]
            return max(times) if times else ''
        except Exception:
            return ''

    def get_current_sequence(self):
        """当前执行的序列名（仅作账号分类标识，按「当前序列」配置执行）。"""
        return (self.config.get(CURRENT_SEQUENCE) or '序列1').strip()

    def _sync_local_to_sequences(self):
        """把本任务勾选的序列账号同步到统一归属数据（sequences）。

        多账号任务为归属的编辑入口：用户在此勾选各序列包含的账号，
        同步后每日任务的「方案序列 → 账号配置」联动即可读取。
        """
        try:
            seqs = self._read_sequences()
            if not seqs:
                seqs = {f'序列{i}': [] for i in range(1, 6)}
            changed = False
            for i in range(MAX_SEQUENCES):
                key = f'序列{i + 1}'
                if key not in seqs:
                    continue
                acc = [a for a in (self.config.get(SEQ_ACCOUNTS[i]) or []) if a and a != '无']
                if acc != seqs[key]:
                    seqs[key] = acc
                    changed = True
            if changed:
                self._write_sequences(seqs)
        except Exception as e:
            self.log_error('同步序列账号失败', e)

    def get_sequence_accounts(self, seq_name=None):
        """指定序列（默认当前序列）的账号列表（不含「无」）。

        优先读统一归属数据（daily_profiles 的 sequences）；无归属数据时回退自身配置。
        """
        name = seq_name or self.get_current_sequence()
        idx = self._seq_index(name)
        if idx is None:
            return []
        seq = self.config.get(SEQ_ACCOUNTS[idx]) or []
        # 统一归属数据优先（多账号任务勾选时同步写入 sequences）
        try:
            seqs = self._read_sequences()
            if seqs and name in seqs:
                seq = seqs[name]
        except Exception:
            pass
        return [a for a in seq if a and a != '无']

    def _seq_index(self, seq_name):
        """序列名 → 配置索引（0..MAX-1）；非序列名返回 None。"""
        if not seq_name or not seq_name.startswith('序列'):
            return None
        try:
            n = int(re.search(r'(\d+)', seq_name).group(1))
            if 1 <= n <= MAX_SEQUENCES:
                return n - 1
        except Exception:
            pass
        return None

    def _read_sequences(self):
        """读取统一序列归属数据（daily_profiles.json 顶层 sequences）。"""
        try:
            import json as _json
            if not os.path.isfile(PROFILE_FILE):
                return {}
            with open(PROFILE_FILE, encoding='utf-8') as f:
                data = _json.load(f)
            seqs = data.get('sequences')
            return seqs if isinstance(seqs, dict) else {}
        except Exception:
            return {}

    def _write_sequences(self, sequences):
        """保存统一序列归属数据。"""
        try:
            import json as _json
            data = {}
            if os.path.isfile(PROFILE_FILE):
                with open(PROFILE_FILE, encoding='utf-8') as f:
                    data = _json.load(f)
            data['sequences'] = sequences
            with open(PROFILE_FILE, 'w', encoding='utf-8') as f:
                _json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.log_error('保存序列归属失败', e)

    def get_sequence_names(self):
        """返回序列名列表（统一归属数据的键；无数据时默认 序列1~序列5）。"""
        seqs = self._read_sequences()
        if seqs:
            return [str(k) for k in seqs.keys()]
        return [f'序列{i}' for i in range(1, 6)]

    def manage_sequences(self, *args):
        """管理序列：弹窗增删/重命名账号序列（改动写入统一归属数据并同步自身配置）。"""
        try:
            from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QLineEdit, QMessageBox, QListWidget
            from ok import og

            seqs = self._read_sequences()
            if not seqs:
                seqs = {f'序列{i}': (self.config.get(SEQ_ACCOUNTS[i - 1]) or []) for i in range(1, 6)}

            dlg = QDialog(og.main_window if og.main_window else None)
            dlg.setWindowTitle('管理序列')
            dlg.resize(360, 420)
            lay = QVBoxLayout(dlg)
            lay.addWidget(QLabel('账号序列列表（账号归属随序列保存，每日任务联动使用）：'))
            self._seq_list = QListWidget()
            for k in seqs.keys():
                self._seq_list.addItem(f'{k}（{len(seqs[k])} 个账号）')
            lay.addWidget(self._seq_list)

            name_edit = QLineEdit()
            name_edit.setPlaceholderText('新序列名（如 序列6）')
            lay.addWidget(name_edit)

            btn_lay = QHBoxLayout()
            add_btn = QPushButton('增加序列')
            del_btn = QPushButton('删除选中')
            rename_btn = QPushButton('重命名')
            ok_btn = QPushButton('完成')
            for b in (add_btn, del_btn, rename_btn, ok_btn):
                btn_lay.addWidget(b)
            lay.addLayout(btn_lay)

            def _refresh_list():
                self._seq_list.clear()
                for k in seqs.keys():
                    self._seq_list.addItem(f'{k}（{len(seqs[k])} 个账号）')

            def _add():
                new = name_edit.text().strip() or f'序列{len(seqs) + 1}'
                if new in seqs:
                    QMessageBox.information(dlg, '提示', '该序列已存在')
                    return
                if len(seqs) >= MAX_SEQUENCES:
                    QMessageBox.warning(dlg, '提示', f'最多支持 {MAX_SEQUENCES} 个序列')
                    return
                seqs[new] = []
                name_edit.clear()
                _refresh_list()

            def _del():
                row = self._seq_list.currentRow()
                if row < 0:
                    QMessageBox.information(dlg, '提示', '请先选择要删除的序列')
                    return
                key = list(seqs.keys())[row]
                if len(seqs) <= 1:
                    QMessageBox.warning(dlg, '提示', '至少保留一个序列')
                    return
                del seqs[key]
                _refresh_list()

            def _rename():
                row = self._seq_list.currentRow()
                if row < 0:
                    QMessageBox.information(dlg, '提示', '请先选择要重命名的序列')
                    return
                new = name_edit.text().strip()
                if not new or new in seqs:
                    QMessageBox.information(dlg, '提示', '输入不重复的新序列名')
                    return
                old = list(seqs.keys())[row]
                seqs[new] = seqs.pop(old)
                name_edit.clear()
                _refresh_list()

            add_btn.clicked.connect(_add)
            del_btn.clicked.connect(_del)
            rename_btn.clicked.connect(_rename)
            ok_btn.clicked.connect(dlg.accept)

            if dlg.exec() == 0:
                return
            # 保存统一归属 + 同步自身配置（序列N账号）并刷新序列下拉选项
            self._write_sequences(seqs)
            seq_names = list(seqs.keys())
            for i, k in enumerate(seq_names):
                if i < MAX_SEQUENCES:
                    self.config[SEQ_ACCOUNTS[i]] = [a for a in seqs[k] if a and a != '无']
            self._sync_sequence_ui(seq_names)
            self.log_info(f'序列已更新：{seq_names}', notify=True)
        except Exception as e:
            self.log_error('管理序列失败', e)

    def _sync_sequence_ui(self, seq_names):
        """管理序列后同步「当前序列」下拉选项（含已存在的序列账号配置显示）。"""
        try:
            if CURRENT_SEQUENCE in self.config_type and isinstance(self.config_type[CURRENT_SEQUENCE], dict):
                self.config_type[CURRENT_SEQUENCE]['options'] = seq_names
                self.config_type[CURRENT_SEQUENCE]['sub_configs'] = {
                    seq: [SEQ_ACCOUNTS[i]] for i, seq in enumerate(seq_names)
                }
            # 更新「当前序列」下拉控件选项（单控件更新，不重建）
            from ok import og
            if og.main_window and hasattr(og.main_window, 'onetime_tab'):
                for card in getattr(og.main_window.onetime_tab, 'card_widgets', []):
                    if getattr(card, 'task', None) is not self:
                        continue
                    for w in getattr(card, 'config_widgets', []):
                        if getattr(w, 'key', None) == CURRENT_SEQUENCE and hasattr(w, 'combo_box'):
                            combo = w.combo_box
                            combo.blockSignals(True)
                            combo.clear()
                            combo.addItems(seq_names)
                            combo.blockSignals(False)
                            return
        except Exception:
            pass

    # ==================== 账号方案 ↔ 登录显示 匹配 ====================

    def _load_profiles(self):
        """加载全部方案（含手机号、账号别名）。"""
        try:
            from src.task.DailyTask import PROFILE_FILE
            data = read_json_file(PROFILE_FILE)
            profiles = (data or {}).get('profiles', {})
            return profiles if isinstance(profiles, dict) else {}
        except Exception as e:
            logger.error('load profiles failed', e)
            return {}

    def get_profile_names(self):
        """返回全部方案名。"""
        return list(self._load_profiles().keys())

    def resolve_profile_short_names(self, short_names):
        """按输入顺序把 A1/A3 等精确短名解析为完整方案名。

        短名必须唯一且全部存在。这里不使用前缀/包含匹配，防止 A1 误选 A10。
        """
        requested = []
        for value in short_names or []:
            short = str(value).strip().upper()
            if short:
                requested.append(short)
        if not requested:
            raise ValueError('连续账号顺序不能为空')

        by_short_name = {}
        duplicate_short_names = set()
        for profile_name in self.get_profile_names():
            short = profile_short_name(profile_name)
            if not short:
                continue
            if short in by_short_name:
                duplicate_short_names.add(short)
            else:
                by_short_name[short] = profile_name

        duplicates = [short for short in requested if short in duplicate_short_names]
        if duplicates:
            raise ValueError(f'账号短名存在重复方案: {", ".join(dict.fromkeys(duplicates))}')
        missing = [short for short in requested if short not in by_short_name]
        if missing:
            raise ValueError(f'找不到账号方案: {", ".join(missing)}')
        return [by_short_name[short] for short in requested]

    def _profile_identities(self, profile_name):
        """返回方案的识别标识列表：手机号掩码 + 账号别名（归一化）。"""
        profiles = self._load_profiles()
        profile = profiles.get(profile_name) or {}
        ids = []
        m = phone_in_name_pattern.search(profile_name)
        if m:
            phone = m.group(1)
            ids.append(normalize_account_name(masked_phone(phone)))
        # 账号别名：合并新配置键与旧 account_aliases，兼容中英文逗号和换行分隔。
        aliases = []
        alias_text = profile.get('备用识别名称内容') if isinstance(profile, dict) else None
        if alias_text:
            aliases.extend(a.strip() for a in re.split(r'[,，;；\r\n]+', str(alias_text)) if a.strip())
        old = profile.get('account_aliases') or []
        if isinstance(old, list):
            aliases.extend(old)
        for a in aliases:
            if a:
                normalized = normalize_account_name(str(a).strip())
                if normalized and normalized not in ids:
                    ids.append(normalized)
        return ids

    def match_profile_from_login(self, login_text):
        """根据登录界面显示的账号文本（掩码或 U 开头）匹配方案名，未匹配返回 None。"""
        if not login_text:
            return None
        wanted = normalize_account_name(str(login_text).strip())
        for name in self.get_profile_names():
            if wanted in self._profile_identities(name):
                return name
        return None

    # ==================== 断点持久化（今日已完成账号） ====================

    def _today(self):
        from datetime import datetime
        return datetime.now().strftime('%Y-%m-%d')

    def _load_today_progress(self):
        """读取今天的已完成账号记录。"""
        try:
            data = read_json_file(PROGRESS_FILE) or {}
            return list(data.get(self._today(), []) or [])
        except Exception:
            return []

    def _save_today_progress(self):
        """把 done_set 持久化到今天记录（每完成一个账号立即调用，防中断丢失）。"""
        try:
            data = read_json_file(PROGRESS_FILE) or {}
            if not isinstance(data, dict):
                data = {}
            data[self._today()] = sorted(self.done_set)
            write_json_file(PROGRESS_FILE, data)
        except Exception as e:
            logger.error('save progress failed', e)

    # ==================== 提醒预留模块 ====================

    def _notify_user(self, title, message):
        """提醒用户（预留模块）。

        当前实现：日志 + 桌面通知（notify=True 走 okww 现有通知链路，
        若配置了 QQ 等外部通道也会一并发出）。后续可按需扩展更多通道。
        """
        self.log_info(f'{title}: {message}', notify=True)

    # ==================== 主流程 ====================

    def run(self):
        WWOneTimeTask.run(self)
        self.done_set.clear()
        self.all_accounts.clear()
        # 把本任务勾选的序列账号同步到统一归属数据（多账号任务为归属编辑入口，每日任务联动读取）
        self._sync_local_to_sequences()

        # 临时关闭 DailyTask 的「每日任务完成后自动退登 PC 端」：
        # 多账号任务自己统一管理退登（_switch_to_login），避免重复退登冲突
        # （DailyTask 先退一次回到登录界面，MultiAccount 再按"在游戏内"退一次会误操作）
        daily_task = None
        saved_logout = None
        try:
            daily_task = self.get_task_by_class(DailyTask)
            if daily_task is not None:
                saved_logout = daily_task.config.get(LOGOUT_AFTER_DAILY_KEY, True)
                daily_task.config[LOGOUT_AFTER_DAILY_KEY] = False
                self.log_info(f'多账号运行：临时关闭「每日任务完成后自动退登」')
        except Exception as e:
            self.log_error('关闭自动退登失败（继续运行）', e)

        try:
            self._run_inner()
        finally:
            # 恢复自动退登设置
            if daily_task is not None and saved_logout is not None:
                try:
                    daily_task.config[LOGOUT_AFTER_DAILY_KEY] = saved_logout
                except Exception:
                    pass

    def _run_inner(self):
        # 本轮账号序列（配置）
        sequence = self.get_sequence_accounts()
        if not sequence:
            self.log_info('未配置「本轮账号序列」，仅跑当前账号后结束', notify=True)

        # 断点恢复：加载今日已完成账号
        for done in self._load_today_progress():
            self.done_set.add(done)
        if self.done_set:
            self.log_info(f'检测到今日已完成账号（断点恢复）: {sorted(self.done_set)}', notify=True)

        # 记录起始账号（第一轮当前登录的账号；全部完成后登录回它）
        first_account = None

        # 第一轮：若已在游戏主界面（用户已登录好起始账号）则跑当前账号；
        # 否则（在登录界面）从序列选择下一个未完成账号（登录前核对账号，防误登/防重跑已完成账号）
        try:
            in_main = self.is_main(esc=False)
        except Exception:
            in_main = False
        if in_main:
            self.log_info('检测到已在游戏主界面，先执行当前账号的每日任务', notify=True)
            # 联动：每日任务配置/界面跟随「当前执行账号」（序列中第一个未完成账号），
            # 避免用错账号的配置跑每日任务（如序列是 A 系列却用遗留的 B7 方案）
            try:
                target = self._next_target_account()
                if target:
                    if target in self._load_profiles():
                        if self._link_daily_profile(target):
                            self.log_info(f'主界面分支：每日任务已联动到执行账号 {target}', notify=True)
                        else:
                            self.log_warning(f'主界面分支：联动方案 {target} 失败，按当前 Daily Profile 执行')
                    else:
                        self.log_warning(f'目标账号 {target} 无配置方案，保持当前 Daily Profile')
                    self.config[CURRENT_ACCOUNT] = target
                else:
                    self.log_warning('序列无未完成账号，主界面分支按当前 Daily Profile 执行')
            except Exception as e:
                self.log_error('主界面分支联动失败', e)
            self.run_task_by_class(DailyTask)
            self.ensure_main(time_out=100)
            self._switch_to_login()
            # 主界面分支：记录并保存断点（防中断丢失，与登录界面分支一致）
            try:
                done_acc = self._detect_current_account_from_login() or self.get_active_profile_name()
                self._mark_done(done_acc)
                self._save_today_progress()
            except Exception as e:
                self.log_error('保存断点失败', e)
        else:
            first_target = self._select_and_login_account()
            if first_target:
                self.log_info(f'从登录界面选择下一个未完成账号：{first_target}，开始执行每日任务', notify=True)
                # 联动：当前执行账号 = 目标账号；激活方案仅当目标方案已存在时切换
                # （防止目标方案不存在时 _do_switch_profile 用当前配置创建污染方案）
                try:
                    if first_target in self._load_profiles():
                        self._link_daily_profile(first_target)
                    self.config[CURRENT_ACCOUNT] = first_target
                except Exception:
                    pass
                self.run_task_by_class(DailyTask)
                self.log_info(f'账号 {first_target} 每日任务完成', notify=True)
                self._mark_done(first_target)
                self._save_today_progress()
                self.ensure_main(time_out=100)
                self._switch_to_login()
        configured_start = (self.config.get(CURRENT_ACCOUNT) or '').strip()
        detected = self._detect_current_account_from_login()
        if detected is None:
            detected = self.get_active_profile_name()
        first_account = configured_start or detected
        self._mark_done(first_account)
        self.log_info(f'起始账号：{first_account}（全部完成后登录回）', notify=True)

        self.info_set('Completed', self.done_set)

        while next_account := self._select_and_login_account():
            self.info_set('Completed', self.done_set)
            self.log_info(f'开始执行账号 {next_account} 的每日任务', notify=True)
            # 联动：当前执行账号 = 目标账号；激活方案仅当目标方案已存在时切换
            # （防止目标方案不存在时 _do_switch_profile 用当前配置创建污染方案）
            try:
                if next_account in self._load_profiles():
                    self._link_daily_profile(next_account)
                self.config[CURRENT_ACCOUNT] = next_account
            except Exception:
                pass
            self.run_task_by_class(DailyTask)
            self.log_info(f'账号 {next_account} 每日任务完成', notify=True)
            self._mark_done(next_account)
            self._save_today_progress()
            self.ensure_main(time_out=100)
            self._switch_to_login()

        # 全部账号完成：登录回起始账号（不重复执行其每日任务），并提醒
        self._login_back_to(first_account)

    def _mark_done(self, account):
        if account:
            self.done_set.add(account)

    def _is_done(self, account):
        """账号是否已完成：多账号断点记录，或今天已单独跑过该账号的每日任务（方案文件 last_completed）。"""
        if account in self.done_set:
            return True
        try:
            from datetime import datetime
            profiles = self._load_profiles()
            profile = profiles.get(account) or {}
            lc = profile.get('last_completed') or {}
            today = datetime.now().strftime('%Y-%m-%d')
            if str(lc.get('Daily Task', '')).startswith(today):
                return True
        except Exception:
            pass
        return False

    def _same_account(self, left, right):
        return normalize_account_name(left) == normalize_account_name(right)

    def _click_center_offset(self, offset_x, offset_y, after_sleep=0.5):
        h, w = self.frame.shape[:2]
        rel_x = 0.5 + offset_x / w
        rel_y = 0.5 + offset_y / h
        self.click_relative(rel_x, rel_y, after_sleep=after_sleep)

    def _switch_to_login(self):
        self.log_info(self.tr('Switching back to login screen'))
        # 容错：如果已经在登录界面（能识别到账号下拉框），跳过游戏内退登流程，
        # 避免 DailyTask 自动退登后重复操作导致误点
        try:
            if self.do_find_account_drop_down() is not None:
                self.log_info('已在登录界面，跳过退登流程')
                return
        except Exception:
            pass
        self.log_info('退登步骤1/4：按 ESC 打开设置页')
        self.send_key('esc', after_sleep=1.5)
        self.wait_feature('esc_setting')
        self.log_info('退登步骤2/4：点击退登入口')
        self.click_relative(0.04, 0.96, after_sleep=1)
        self.log_info('退登步骤3/4：点击确认退登')
        self.click_confirm(timeout=10)
        self.log_info('退登步骤4/4：等待登录界面（抗闪烁等待）')
        self._wait_login_screen_stable()
        self.log_info(self.tr('Back at login screen'))

    def _login_screen_feature_count(self, texts):
        """宽松统计登录界面特征数量：掩码账号 / 登录文本 / U账号（扫码），任一 >0 即视为登录界面出现。"""
        count = 0
        if not texts:
            return 0
        try:
            count += len(self.find_boxes(texts, account_pattern))
        except Exception:
            pass
        try:
            count += len(self.find_boxes(texts, LOGIN_TEXTS))
        except Exception:
            pass
        try:
            for t in texts:
                if scan_account_pattern.match(t.name.strip()):
                    count += 1
        except Exception:
            pass
        return count

    def _wait_login_screen_stable(self, time_out=120, settle=2):
        """抗闪烁等待登录界面稳定。

        游戏退登后登录界面有概率闪烁/短暂暗屏（窗口不可见、OCR 无文本），
        直接 60s 一刀切等待会把瞬时的暗屏当成永久失败。本方法分两阶段：
          阶段1 宽松探测：容忍暗屏/闪烁，持续等待登录界面任意特征出现
            - 窗口不可见 → 尝试 bring_to_front 恢复前台
            - OCR 为空 → 视为正常过渡，不限次失败（限频打日志）
            - 检测到启动器界面（KURO GAMES 公告/修复）→ 判为退过头，明确报错
            - 主窗口 OCR 无特征时，回退捕获 #32770 登录对话框窗口再 OCR
          阶段2 严格确认：特征出现后，确认账号下拉框（掩码或 U 账号）
        失败时输出诊断日志（窗口可见性 / OCR 文本数 / 最近文本）并截图。
        """
        self.log_info(f'等待登录界面（宽松探测，超时 {time_out}s，容忍闪烁/暗屏）')
        deadline = time.monotonic() + time_out
        last_log = 0.0
        while time.monotonic() < deadline:
            try:
                hwnd = getattr(self, 'hwnd', None)
                if hwnd is not None and hwnd.exists and not hwnd.visible:
                    try:
                        hwnd.bring_to_front()
                        self.log_warning('游戏窗口不可见，已尝试恢复前台')
                    except Exception:
                        pass
                    self.sleep(1)
                    continue
                texts = self.ocr()
                if self._login_screen_feature_count(texts) > 0:
                    self._login_in_dialog = False
                    break
                # 启动器兜底：退过头回到启动器（KURO GAMES 启动器界面，无登录特征）
                if texts and self._is_launcher_texts(texts):
                    self.log_error('检测到启动器界面（退过头到启动器），请手动重新进入游戏后再试')
                    try:
                        self.screenshot('multi')
                    except Exception:
                        pass
                    raise Exception(self.tr('Logged out to launcher, please re-enter the game'))
                # 主窗口无特征：回退捕获 #32770 登录对话框窗口
                dlg_texts = self._ocr_login_dialog()
                if dlg_texts and self._login_screen_feature_count(dlg_texts) > 0:
                    self._login_in_dialog = True
                    self.log_info(f'已通过登录对话框窗口识别到登录界面（OCR {len(dlg_texts)} 文本）')
                    break
                now = time.monotonic()
                if now - last_log >= 30:
                    last_log = now
                    win_state = 'visible' if (hwnd is not None and hwnd.visible) else 'invisible'
                    self.log_info(f'登录界面暂不可见（闪烁/加载中）: 窗口={win_state}, OCR文本数={len(texts) if texts else 0}')
            except Exception as e:
                if 'launcher' in str(e).lower() or '启动器' in str(e):
                    raise
            self.sleep(1)
        # 阶段2：严格确认（掩码或 U 账号 + 登录特征）
        box = self.wait_until(self.do_find_account_drop_down, time_out=settle + 5,
                              settle_time=settle, raise_if_not_found=False)
        if box is None:
            try:
                self.screenshot('multi')
                texts = self.ocr()
                hwnd = getattr(self, 'hwnd', None)
                win_state = 'visible' if (hwnd is not None and hwnd.visible) else 'invisible'
                snippet = ' | '.join(t.name[:20] for t in texts[:5]) if texts else ''
                self.log_error(f'登录界面等待超时: 窗口={win_state}, OCR文本数={len(texts) if texts else 0}, 最近文本: {snippet}')
            except Exception:
                pass
            raise Exception(self.tr('Timed out waiting for the login screen'))
        return box

    @staticmethod
    def _is_launcher_texts(texts):
        """启动器界面特征：含 KURO GAMES 且无登录特征（登录文本/U账号）。"""
        joined = ' '.join((t.name or '') for t in texts) if texts else ''
        if 'kuro' not in joined.lower() or not joined:
            return False
        if any((t.name or '') in ('登录', '登入', 'Log') for t in texts):
            return False
        if any(scan_account_pattern.match((t.name or '').strip()) for t in texts):
            return False
        return True

    def _find_login_dialog(self):
        """找可见的 #32770 登录对话框，返回 (hwnd, (left, top, right, bottom)) 或 (0, None)。

        排除占满全屏的隐藏背景对话框（如全黑 1920x1080 的那个），取面积最小/居中的 #32770。
        """
        import win32gui
        import win32process
        try:
            import psutil
        except Exception:
            return 0, None
        found = []
        main_exe = None
        try:
            hwnd_main = getattr(self, 'hwnd', None)
            if hwnd_main is not None and getattr(hwnd_main, 'hwnd', 0):
                main_exe = psutil.Process(
                    win32process.GetWindowThreadProcessId(hwnd_main.hwnd)[1]).name().lower()
        except Exception:
            pass

        def cb(hwnd, _):
            try:
                if not win32gui.IsWindowVisible(hwnd):
                    return True
                if win32gui.GetClassName(hwnd) != '#32770':
                    return True
                if main_exe:
                    exe = psutil.Process(
                        win32process.GetWindowThreadProcessId(hwnd)[1]).name().lower()
                    if exe != main_exe:
                        return True
                rect = win32gui.GetWindowRect(hwnd)
                w, h = rect[2] - rect[0], rect[3] - rect[1]
                if w <= 0 or h <= 0:
                    return True
                found.append((hwnd, rect, w * h))
            except Exception:
                pass
            return True
        win32gui.EnumWindows(cb, None)
        if not found:
            return 0, None
        # 取面积最小且非全屏的 #32770（登录对话框通常居中且小于屏幕）
        found = [f for f in found if f[2] > 0]
        found.sort(key=lambda f: f[2])
        best = found[0]
        return best[0], best[1]

    def _capture_hwnd_client(self, hwnd):
        """BitBlt 捕获指定窗口客户端区域，返回 (bgr_frame, 客户区屏幕原点 (ox,oy)) 或 (None, None)。"""
        import win32gui
        import win32ui
        import win32con
        try:
            import numpy as np
            import cv2
        except Exception:
            return None, None
        try:
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            w, h = right - left, bottom - top
            if w <= 0 or h <= 0:
                return None, None
            hwnd_dc = win32gui.GetWindowDC(hwnd)
            mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
            save_dc = mfc_dc.CreateCompatibleDC()
            bmp = win32ui.CreateBitmap()
            bmp.CreateCompatibleBitmap(mfc_dc, w, h)
            save_dc.SelectObject(bmp)
            save_dc.BitBlt((0, 0), (w, h), mfc_dc, (0, 0), win32con.SRCCOPY)
            bits = bmp.GetBitmapBits(True)
            save_dc.DeleteDC()
            mfc_dc.DeleteDC()
            win32gui.ReleaseDC(hwnd, hwnd_dc)
            frame = np.frombuffer(bits, np.uint8).reshape(h, w, 4)
            return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR), (left, top)
        except Exception:
            return None, None

    def _dialog_capture(self):
        """捕获 #32770 登录对话框客户端区域，返回 (bgr_frame, 屏幕原点 (ox,oy)) 或 (None, None)。

        登录账号下拉框位于独立 #32770 对话框（非游戏主窗口），主窗口捕获/OCR 永远看不到它，
        因此登录界面的一切识别与操作都基于本方法捕获的对话框帧。
        """
        hwnd, _rect = self._find_login_dialog()
        if not hwnd:
            return None, None
        return self._capture_hwnd_client(hwnd)

    def _ocr_login_dialog(self):
        """回退方案：捕获 #32770 登录对话框并 OCR，返回文本列表；失败返回 None。"""
        frame, _origin = self._dialog_capture()
        if frame is None:
            return None
        try:
            return self.ocr(frame=frame)
        except Exception:
            return None

    def _find_control_hwnd(self, class_name):
        """找指定窗口类（ComboBox/ComboLBox/Button 等）的可见控件，返回 (hwnd, 屏幕rect) 或 (0, None)。

        用于登录对话框内控件的屏幕坐标定位（ComboBox=账号下拉框，ComboLBox=展开的账号列表）。
        """
        import win32gui
        import win32process
        try:
            import psutil
        except Exception:
            return 0, None
        main_exe = None
        try:
            hwnd_main = getattr(self, 'hwnd', None)
            if hwnd_main is not None and getattr(hwnd_main, 'hwnd', 0):
                main_exe = psutil.Process(
                    win32process.GetWindowThreadProcessId(hwnd_main.hwnd)[1]).name().lower()
        except Exception:
            pass
        best = None

        def cb(hwnd, _):
            nonlocal best
            try:
                if not win32gui.IsWindowVisible(hwnd):
                    return True
                if win32gui.GetClassName(hwnd) != class_name:
                    return True
                if main_exe:
                    exe = psutil.Process(
                        win32process.GetWindowThreadProcessId(hwnd)[1]).name().lower()
                    if exe != main_exe:
                        return True
                rect = win32gui.GetWindowRect(hwnd)
                if rect[2] - rect[0] <= 0 or rect[3] - rect[1] <= 0:
                    return True
                best = (hwnd, rect)
            except Exception:
                pass
            return True
        win32gui.EnumWindows(cb, None)
        return (best[0], best[1]) if best else (0, None)

    def _screen_click(self, x, y, after_sleep=0.5):
        """用系统级鼠标事件在屏幕坐标 (x, y) 处点击（绕过主窗口坐标系，作用于 #32770 对话框）。"""
        import win32api
        import win32con
        import time as _t
        try:
            win32api.SetCursorPos((int(x), int(y)))
            _t.sleep(0.1)
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            _t.sleep(0.05)
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
            if after_sleep:
                self.sleep(after_sleep)
            return True
        except Exception:
            return False

    def _box_center_screen(self, box, origin):
        """把对话框帧 OCR 得到的 Box 中心换算为屏幕坐标。"""
        cx = box.x + box.width / 2.0
        cy = box.y + box.height / 2.0
        return int(origin[0] + cx), int(origin[1] + cy)

    def _log_account_click_delivery(self, mode, box, screen_point=None, hwnd=None):
        """记录账号点击投递诊断；诊断失败不能影响实际点击。"""
        try:
            interaction = getattr(getattr(self, 'executor', None), 'interaction', None)
            if hwnd is None and screen_point is not None and mode.startswith('系统屏幕'):
                try:
                    import win32gui
                    hwnd = win32gui.WindowFromPoint((int(screen_point[0]), int(screen_point[1])))
                except Exception:
                    hwnd = None
            if hwnd is None and interaction is not None:
                # PostMessageInteraction resolves the real child target during
                # click(); prefer that post-dispatch target over a stale one.
                hwnd = getattr(interaction, '_dynamic_target_hwnd', None) or getattr(interaction, 'hwnd', None)
            if hwnd is None:
                hwnd_window = getattr(self, 'hwnd', None)
                hwnd = getattr(hwnd_window, 'top_hwnd', None) or getattr(hwnd_window, 'hwnd', None)
            class_name = '?'
            if hwnd:
                try:
                    import win32gui
                    class_name = win32gui.GetClassName(hwnd)
                except Exception:
                    class_name = '?'
            point = f'({box.x + box.width / 2:.1f},{box.y + box.height / 2:.1f})'
            if screen_point is not None:
                point += f' screen=({screen_point[0]},{screen_point[1]})'
            self.log_info(
                f'账号点击投递诊断：方式={mode}，目标HWND={hwnd or "?"}，'
                f'类={class_name}，坐标={point}'
            )
        except Exception:
            pass

    def _refresh_hwnd_window_snapshot(self):
        """刷新 HwndWindow 的句柄/子窗口快照，失败时仅记录诊断。"""
        try:
            hwnd_window = getattr(self, 'hwnd', None)
            refresh = getattr(hwnd_window, 'do_update_window_size', None)
            if callable(refresh):
                refresh()
                self.log_info('账号点击未确认：已刷新 HwndWindow 句柄快照')
                return True
        except Exception as e:
            try:
                self.log_warning(f'刷新 HwndWindow 句柄快照失败（继续尝试）：{e}')
            except Exception:
                pass
        return False

    def _bring_account_window_to_front(self):
        """兜底屏幕点击前尝试将游戏窗口置前。"""
        try:
            hwnd_window = getattr(self, 'hwnd', None)
            bring_to_front = getattr(hwnd_window, 'bring_to_front', None)
            if callable(bring_to_front):
                return bool(bring_to_front())
        except Exception as e:
            try:
                self.log_warning(f'账号点击兜底置前失败（继续尝试）：{e}')
            except Exception:
                pass
        return False

    def _main_box_center_screen(self, box):
        """把主窗口 OCR 框转换为屏幕坐标；无法安全换算时返回 None。"""
        try:
            hwnd_window = getattr(self, 'hwnd', None)
            get_origin = getattr(hwnd_window, 'get_capture_origin', None)
            if not callable(get_origin):
                return None
            origin = get_origin()
            if not origin:
                return None
            return self._box_center_screen(box, origin)
        except Exception:
            return None

    def _dialog_open_account_list(self):
        """点击 #32770 登录对话框的账号下拉框（ComboBox）展开账号列表，返回是否成功。"""
        hwnd, rect = self._find_control_hwnd('ComboBox')
        if not hwnd:
            self.log_warning('未找到登录对话框的账号下拉框（ComboBox）')
            return False
        cx = (rect[0] + rect[2]) // 2
        cy = (rect[1] + rect[3]) // 2
        self.log_info(f'点击账号下拉框 ComboBox @({cx},{cy})')
        return self._screen_click(cx, cy, after_sleep=2)

    def _dialog_find_and_click_account(self, profile_name):
        """在 #32770 登录对话框/展开的账号列表（ComboLBox）中找到目标账号并点击。

        返回 (是否点击成功, 找到的账号文本或 None)。账号可能是掩码（180****1088）或 U 扫码（U550500484A）。
        """
        # 1) 展开的账号列表（ComboLBox）优先
        hwnd, rect = self._find_control_hwnd('ComboLBox')
        if hwnd:
            frame, origin = self._capture_hwnd_client(hwnd)
            if frame is not None:
                try:
                    texts = self.ocr(frame=frame)
                    for t in texts or []:
                        name = (t.name or '').strip()
                        if self.match_profile_from_login(name) == profile_name:
                            sx, sy = self._box_center_screen(t, origin)
                            diagnose = getattr(self, '_log_account_click_delivery', None)
                            if callable(diagnose):
                                diagnose('系统屏幕点击', t, (sx, sy), hwnd)
                            if self._screen_click(sx, sy, after_sleep=2):
                                self.log_info(f'已发送账号点击（方式=系统屏幕，列表，屏幕 {sx},{sy}）')
                                return True, name
                except Exception:
                    pass
        # 2) 对话框主体里找（当前显示的账号 / 列表内嵌）
        frame, origin = self._dialog_capture()
        if frame is not None:
            try:
                texts = self.ocr(frame=frame)
                for t in texts or []:
                    name = (t.name or '').strip()
                    if self.match_profile_from_login(name) == profile_name:
                        sx, sy = self._box_center_screen(t, origin)
                        diagnose = getattr(self, '_log_account_click_delivery', None)
                        if callable(diagnose):
                            diagnose('系统屏幕点击', t, (sx, sy))
                        if self._screen_click(sx, sy, after_sleep=2):
                            self.log_info(f'已发送账号点击（方式=系统屏幕，对话框，屏幕 {sx},{sy}）')
                            return True, name
            except Exception:
                pass
        return False, None

    def _dialog_click_login(self):
        """在 #32770 登录对话框里点击「登录」按钮，返回是否成功。"""
        frame, origin = self._dialog_capture()
        if frame is None:
            return False
        try:
            texts = self.ocr(frame=frame)
            login_boxes = self.find_boxes(texts, LOGIN_TEXTS)
            if not login_boxes:
                self.log_warning('登录对话框里未找到「登录」按钮')
                return False
            box = login_boxes[0]
            sx, sy = self._box_center_screen(box, origin)
            self.log_info(f'点击登录按钮（屏幕 {sx},{sy}）')
            return self._screen_click(sx, sy, after_sleep=3)
        except Exception:
            return False

    def _detect_current_account_from_login(self):
        """识别登录界面当前显示的账号，返回方案名（掩码或扫码 U 账号均可识别）。

        v1.03.73：主窗口内嵌登录走原路径；#32770 对话框登录走对话框帧。
        """
        if getattr(self, '_login_in_dialog', False):
            frame, origin = self._dialog_capture()
            if frame is not None:
                try:
                    dlg_texts = self.ocr(frame=frame)
                    for t in dlg_texts or []:
                        name = (t.name or '').strip()
                        if account_pattern.search(name) or scan_account_pattern.match(name):
                            profile = self.match_profile_from_login(name)
                            if profile:
                                self.log_info(f'对话框识别当前账号: {name} -> {profile}')
                                return profile
                    if dlg_texts:
                        self.log_info(f'对话框未匹配到方案，账号文本: {[t.name for t in dlg_texts][:8]}')
                except Exception:
                    pass
            return None
        texts = self.ocr(match=account_pattern)
        candidates = [t.name for t in texts] if texts else []
        # 也识别 U 开头账号（扫码登录）
        try:
            all_texts = self.ocr()
            for t in all_texts:
                if scan_account_pattern.match(t.name.strip()):
                    candidates.append(t.name.strip())
        except Exception:
            pass
        for c in candidates:
            profile = self.match_profile_from_login(c)
            if profile:
                self.log_info(self.tr('Current account: {account}').format(account=c))
                return profile
        if candidates:
            self.log_info(f'未匹配到方案，登录界面账号: {candidates}')
        return None

    def _next_target_account(self):
        """序列中第一个未完成的账号（从「当前执行账号」开始旋转：选 A3 → A3..A10, A1..A2）；全部完成返回 None。"""
        sequence = self.get_sequence_accounts()
        if not sequence:
            return None
        start = (self.config.get(CURRENT_ACCOUNT) or '').strip()
        if start:
            for i, acc in enumerate(sequence):
                if self._same_account(acc, start):
                    sequence = sequence[i:] + sequence[:i]
                    break
        for acc in sequence:
            if not self._is_done(acc):
                return acc
        return None

    def _link_daily_profile(self, profile_name):
        """联动：把每日任务（DailyTask）的激活方案切换到 profile_name（并同步本任务自身配置）。

        多账号任务与每日任务是两个独立 Config（各自 configs/*.json），直接改
        self.config[DAILY_PROFILE] 不会影响 DailyTask 实例（执行/界面仍用旧方案）。
        正确做法：调用 DailyTask.switch_profile()（保存旧方案 → 加载新方案配置 → 写 DAILY_PROFILE），
        再刷新每日任务卡片显示。返回是否成功。
        """
        if not profile_name:
            return False
        try:
            daily_task = self.get_task_by_class(DailyTask)
            if daily_task is None:
                self.log_warning(f'未找到 DailyTask 实例，无法联动方案 {profile_name}')
                return False
            if daily_task.config.get(DAILY_PROFILE) == profile_name:
                self.log_info(f'每日任务方案已是 {profile_name}')
            else:
                daily_task.switch_profile(profile_name)
                self.log_info(f'每日任务方案已联动到 {profile_name}', notify=True)
            try:
                self.config[DAILY_PROFILE] = profile_name
            except Exception:
                pass
            try:
                if hasattr(daily_task, '_refresh_gui'):
                    daily_task._refresh_gui()
            except Exception:
                pass
            return True
        except Exception as e:
            self.log_error(f'联动每日任务方案失败: {profile_name}', e)
            return False

    def _click_account_in_list(self, profile_name, interaction_mode='postmessage', require_expanded=False):
        """在登录界面账号列表中点击指定的方案账号，返回是否点击成功。

        v1.03.73：主窗口内嵌登录走原路径；#32770 对话框登录走对话框帧 + 屏幕坐标路径；
        账号匹配支持掩码（180****1088）与 U 扫码账号（U550500484A）。

        ``True`` 仅表示点击事件已投递，不表示登录器已经接受选择；后者由
        ``_wait_for_account_selection_stable`` 单独确认。``interaction_mode=screen``
        只供最后一次兜底使用，并且要求调用方先确认列表仍展开。
        """
        if require_expanded:
            try:
                if not self._account_list_expanded():
                    self.log_warning('账号点击兜底取消：列表未保持展开')
                    return False
            except Exception:
                self.log_warning('账号点击兜底取消：无法确认列表展开状态')
                return False
        if interaction_mode == 'screen' and not getattr(self, '_login_in_dialog', False):
            bring_to_front = getattr(self, '_bring_account_window_to_front', None)
            if not callable(bring_to_front) or not bring_to_front():
                self.log_warning('账号点击兜底取消：无法确认游戏窗口已置前')
                return False
            self.sleep(0.2)
            if require_expanded:
                try:
                    if not self._account_list_expanded():
                        self.log_warning('账号点击兜底取消：窗口置前后列表已收起')
                        return False
                except Exception:
                    self.log_warning('账号点击兜底取消：窗口置前后无法确认列表状态')
                    return False
        if getattr(self, '_login_in_dialog', False):
            ok, name = self._dialog_find_and_click_account(profile_name)
            if ok:
                suffix = (' (U账号 %s)' % name) if name and name.startswith('U') else ''
                self.log_info('已发送账号点击（方式=系统屏幕，对话框）%s' % suffix)
                return True
            self.log_error(f'登录对话框中没有找到目标账号 {profile_name}')
            return False

        # 主登录界面只取一帧 OCR，同时覆盖掩码手机号、U 扫码账号和备用识别名。
        # 两次 OCR 可能跨越登录器刷新，导致目标框与实际点击帧不一致。
        try:
            texts = self.ocr()
        except Exception as e:
            self.log_warning(f'读取登录账号列表 OCR 失败：{e}')
            texts = []
        accounts = []
        for account in texts or []:
            name = (getattr(account, 'name', '') or '').strip()
            if not name:
                continue
            try:
                mapped_profile = self.match_profile_from_login(name)
                matched = mapped_profile == profile_name
            except Exception:
                mapped_profile = None
                matched = False
            is_account_text = bool(account_pattern.search(name) or scan_account_pattern.match(name))
            if is_account_text or mapped_profile:
                accounts.append(account)
            if matched:
                screen_point = None
                if interaction_mode == 'screen':
                    screen_point = self._main_box_center_screen(account)
                    if screen_point is None:
                        self.log_warning('账号点击兜底取消：无法从目标 OCR 框安全换算屏幕坐标')
                        return False
                    diagnose = getattr(self, '_log_account_click_delivery', None)
                    if callable(diagnose):
                        diagnose('系统屏幕点击', account, screen_point)
                    sent = self._screen_click(*screen_point, after_sleep=2)
                    if sent:
                        self.log_info(f'已发送账号点击（方式=系统屏幕，目标={profile_name}，OCR={name}）')
                    return bool(sent)

                try:
                    result = self.click(account, after_sleep=2)
                    sent = result is not False
                except Exception as e:
                    self.log_warning(f'发送账号点击失败（方式=PostMessage）：{e}')
                    sent = False
                diagnose = getattr(self, '_log_account_click_delivery', None)
                if callable(diagnose):
                    diagnose('PostMessage（投递后）', account)
                if sent:
                    self.log_info(f'已发送账号点击（方式=PostMessage，目标={profile_name}，OCR={name}）')
                return sent

        # 找不到目标账号：输出列表内容便于排查（记住列表里没有该账号 / 识别失败）
        visible = [a.name for a in accounts][:15]
        self.log_error(
            f'登录界面账号列表中没有找到目标账号 {profile_name}；'
            f'当前列表可见：{visible}（若目标不在列表，说明该账号未在本设备登录器记住，'
            f'或已被其他账号挤出记住列表，需要扫码登录）'
        )
        return False

    def _open_account_list(self):
        """确保登录账号列表处于展开状态，失败时返回 False。"""
        drop_down = self.find_account_drop_down()
        if self._account_list_expanded():
            self.log_info('账号列表已展开，跳过再次点击下拉框')
        elif getattr(self, '_login_in_dialog', False):
            if not self._dialog_open_account_list():
                self.log_warning('对话框模式下打开账号下拉框失败')
                return False
        else:
            self.click(drop_down, after_sleep=2)

        expanded = self.wait_until(
            self._account_list_expanded,
            time_out=10,
            settle_time=1,
            raise_if_not_found=False,
        )
        if not expanded:
            self.log_warning('账号列表未能展开')
            self.screenshot('multi')
            return False
        return True

    def _wait_for_account_selection_stable(self, target, time_out=8, consecutive=2):
        """等待点击账号后的登录界面稳定显示目标账号。

        游戏登录器在点击列表项后可能短暂保留下拉列表、返回空 OCR 帧，或先
        显示旧账号再切换到新账号。此处把这些状态视为过渡态，要求下拉列表已
        收起且目标账号连续识别 ``consecutive`` 次后才确认，避免把闪烁帧误判
        为账号选择失败并立即重复点击。

        返回 ``(是否稳定确认, 最后识别到的方案名)``，超时后由调用方决定是否
        重新展开列表；不在此方法中执行第二次点击，保证正式任务和测试路径共享
        同一套重试边界。
        """
        state = {
            'matches': 0,
            'last_current': None,
            'last_expanded': None,
        }

        def observe():
            try:
                expanded = bool(self._account_list_expanded())
            except Exception:
                # 某些登录器闪烁帧无法判断列表控件，继续用账号 OCR 做宽松探测。
                expanded = False

            previous_expanded = state['last_expanded']
            expanded_changed = previous_expanded is not expanded
            if expanded:
                state['matches'] = 0
                if expanded_changed:
                    self.log_info('账号选择后列表仍展开，等待界面收起并稳定')
                state['last_expanded'] = True
                return False

            state['last_expanded'] = False
            current = self._detect_current_account_from_login()
            previous = state['last_current']
            state['last_current'] = current
            current_changed = not self._same_account(previous, current)
            if current_changed:
                self.log_info(
                    f'账号选择稳定检测：当前识别为 {current or "未识别"}，'
                    f'目标为 {target}'
                )
            if expanded_changed and previous_expanded is True:
                self.log_info('账号列表已收起，继续等待账号识别稳定')

            if self._same_account(target, current):
                state['matches'] += 1
                if state['matches'] >= consecutive:
                    return True
            else:
                if current_changed:
                    self.log_info('账号选择界面仍在闪烁或切换，继续等待稳定')
                state['matches'] = 0
            return False

        stable = self.wait_until(
            observe,
            time_out=time_out,
            settle_time=0,
            raise_if_not_found=False,
        )
        if stable:
            self.log_info(f'账号选择已稳定确认：{target}（连续 {consecutive} 次）')
        else:
            self.log_warning(
                f'账号选择稳定检测超时：目标 {target}，最后识别 '
                f'{state["last_current"] or "未识别"}，准备重新选择'
            )
        return bool(stable), state['last_current']

    def _select_account_with_retry(self, target, max_retries=5):
        """重复展开、选择并核对目标账号，确认成功后返回 True。

        OCR 显示账号与目标不一致时不会立即终止，而是重新展开列表并再次选择；
        达到重试上限仍无法确认时才安全停止，避免误登录其他账号。
        """
        last_current = None
        unconfirmed_postmessage_deliveries = 0
        for attempt in range(1, max_retries + 1):
            self.sleep(1)
            if unconfirmed_postmessage_deliveries == 1:
                # 第一次 PostMessage 投递未获稳定确认后，下一次展开列表前刷新
                # HwndWindow 的主/子窗口快照，避免继续向已替换的句柄投递。
                refresh = getattr(self, '_refresh_hwnd_window_snapshot', None)
                if callable(refresh):
                    refresh()
            if not self._open_account_list():
                self.log_warning(f'第 {attempt}/{max_retries} 次打开账号列表失败，准备重试')
                continue

            interaction_mode = 'postmessage'
            require_expanded = False
            if unconfirmed_postmessage_deliveries >= 2:
                # 前两次投递均未确认：只在列表仍展开且本帧 OCR 找到目标框时，
                # 置前窗口并使用系统屏幕点击；不会凭坐标盲点或跳过账号核对。
                interaction_mode = 'screen'
                require_expanded = True
            if interaction_mode == 'postmessage':
                click_callback = lambda: self._click_account_in_list(target)
            else:
                click_callback = lambda: self._click_account_in_list(
                    target,
                    interaction_mode=interaction_mode,
                    require_expanded=require_expanded,
                )
            clicked = self.wait_until(
                click_callback,
                time_out=10,
                raise_if_not_found=False,
            )
            if not clicked:
                self.log_warning(
                    f'第 {attempt}/{max_retries} 次未能投递目标账号点击（方式={interaction_mode}），准备重试'
                )
                continue

            stable, last_current = self._wait_for_account_selection_stable(target)
            self.log_info(f'账号点击投递后确认：目标 {target}，当前显示账号：{last_current}')
            if stable:
                self.log_info(f'确认已选择账号：{target}')
                return True

            if interaction_mode == 'postmessage':
                unconfirmed_postmessage_deliveries += 1

            self.log_warning(
                f'账号选择不一致（目标 {target}，当前 {last_current or "未识别"}），'
                f'重新选择（{attempt}/{max_retries}）'
            )

        self.log_error(
            f'账号选择在 {max_retries} 次重试后仍失败；'
            f'目标 {target}，最后识别 {last_current or "未识别"}。为防止误登录已停止。'
        )
        self.screenshot('multi')
        raise Exception(self.tr('Failed to switch account'))

    def _confirm_target_before_login(self, target, max_retries=3):
        """点登录前再次核对目标；不一致时重新选择，而不是立即停止。"""
        last_shown = None
        for attempt in range(1, max_retries + 1):
            last_shown = self._detect_current_account_from_login()
            if self._same_account(last_shown, target):
                return True

            self.log_warning(
                f'登录前账号不一致（目标 {target}，当前 {last_shown or "未识别"}），'
                f'重新选择目标账号（{attempt}/{max_retries}）'
            )
            if attempt < max_retries:
                try:
                    self._select_account_with_retry(target, max_retries=2)
                except Exception as e:
                    self.log_warning(f'重新选择目标账号失败，将继续重试: {e}')
                self.sleep(1)

        self.log_error(
            f'登录前经过 {max_retries} 次重试仍无法确认目标账号；'
            f'目标 {target}，当前 {last_shown or "未识别"}。为防止误登录已停止。'
        )
        self.screenshot('multi')
        raise Exception(self.tr('Login aborted: displayed account does not match target'))

    def _click_login_for_target(self, target):
        """确认当前账号后点击登录按钮，点击失败时抛出异常。"""
        self._confirm_target_before_login(target)
        if getattr(self, '_login_in_dialog', False):
            if not self._dialog_click_login():
                self.log_error('对话框模式下点击登录按钮失败')
                self.screenshot('multi')
                raise Exception(self.tr('Failed to click login button'))
            return

        texts = self.ocr()
        login_btn = self.find_boxes(
            texts,
            boundary=self.box_of_screen(0.3, 0.3, 0.7, 0.8),
            match=LOGIN_TEXTS,
        )
        if login_btn:
            self.click(login_btn, after_sleep=3)
        else:
            self.click_relative(0.5, 0.568, hcenter=True, vcenter=True, after_sleep=3)

    def _visible_login_profiles(self):
        """按登录列表显示顺序返回能映射到本地方案的账号名。"""
        texts = None
        if getattr(self, '_login_in_dialog', False):
            hwnd, _rect = self._find_control_hwnd('ComboLBox')
            if hwnd:
                frame, _origin = self._capture_hwnd_client(hwnd)
                if frame is not None:
                    try:
                        texts = self.ocr(frame=frame)
                    except Exception:
                        texts = None
            if not texts:
                texts = self._ocr_login_dialog()
        else:
            texts = self.ocr()

        profiles = []
        for box in texts or []:
            name = (box.name or '').strip()
            if not name or not (account_pattern.search(name) or scan_account_pattern.match(name)):
                continue
            profile = self.match_profile_from_login(name)
            if profile and profile not in profiles:
                profiles.append(profile)
        return profiles

    def _select_and_login_first_available(self):
        """选择登录列表中第一个能映射到本地方案的账号并登录。"""
        mouse_reset_task = self.executor.get_task_by_class(MouseResetTask)
        mouse_reset_was_enabled = mouse_reset_task.enabled if mouse_reset_task else False
        if mouse_reset_was_enabled:
            mouse_reset_task.disable()
        try:
            if not self._open_account_list():
                raise Exception(self.tr('Failed to open account list'))
            profiles = self.wait_until(
                self._visible_login_profiles,
                time_out=10,
                settle_time=1,
                raise_if_not_found=False,
            )
            if not profiles:
                self.log_error('登录列表中没有能映射到本地方案的账号')
                self.screenshot('multi')
                raise Exception('没有可用的已配置账号')
            target = profiles[0]
            self.log_info(f'自动识别登录列表中的第一个可用账号: {target}')
            self._select_account_with_retry(target)
            self.sleep(4)
            self._click_login_for_target(target)
            self.logged_in = False
            self.ensure_main(time_out=180)
            self.log_info(self.tr('Login successful'))
            return target
        finally:
            if mouse_reset_was_enabled:
                mouse_reset_task.enable()

    def _select_and_login_account(self):
        """从本轮序列取第一个未完成账号，在登录界面选择并登录；全部完成返回 None。"""
        target = self._next_target_account()
        if target is None:
            return None
        mouse_reset_task = self.executor.get_task_by_class(MouseResetTask)
        mouse_reset_was_enabled = mouse_reset_task.enabled if mouse_reset_task else False
        if mouse_reset_was_enabled:
            mouse_reset_task.disable()
        try:
            self._select_account_with_retry(target)
            self.sleep(4)
            self._click_login_for_target(target)
            self.logged_in = False
            self.ensure_main(time_out=180)
            self.log_info(self.tr('Login successful'))
            # 返回确定的目标账号，避免 OCR 临时识别失败被误判为「全部完成」。
            return target
        finally:
            if mouse_reset_was_enabled:
                mouse_reset_task.enable()

    def _login_back_to(self, first_account):
        """全部完成后登录回起始账号，并提醒用户本轮结束。"""
        self.log_info(f'全部账号每日任务已完成，准备登录回起始账号 {first_account}', notify=True)
        if not first_account:
            self._notify_user('多账号每日任务完成', '本轮全部账号已完成')
            return
        try:
            self._select_and_login_specific(first_account)
            self.log_info(f'已登录回起始账号: {first_account}', notify=True)
        except Exception as e:
            self.log_error('登录回起始账号失败，请手动登录', e)
        self._notify_user('多账号每日任务完成',
                          f'序列本轮全部完成，已登录回 {first_account}。可退出游戏进程切换下一个序列。')

    def _select_and_login_specific(self, profile_name):
        """在登录界面选择并登录指定账号（不执行每日任务）。"""
        mouse_reset_task = self.executor.get_task_by_class(MouseResetTask)
        mouse_reset_was_enabled = mouse_reset_task.enabled if mouse_reset_task else False
        if mouse_reset_was_enabled:
            mouse_reset_task.disable()
        try:
            self._select_account_with_retry(profile_name)
            self.sleep(4)
            self._click_login_for_target(profile_name)
            self.logged_in = False
            self.ensure_main(time_out=180)
            self.log_info(f'已登录: {profile_name}')
            return profile_name
        finally:
            if mouse_reset_was_enabled:
                mouse_reset_task.enable()

    def _select_and_login_sequence(self, profile_names, progress_callback=None):
        """连续登录一组账号，只模拟每个账号每日任务完成后的切换部分。

        调用方应从登录界面开始。本方法不执行每日任务、不写完成进度；每次登录都
        复用正式的指定账号流程，并只在相邻账号之间退登。
        """
        targets = list(profile_names or [])
        if not targets:
            raise ValueError('连续切换账号列表不能为空')

        logged_profiles = []
        total = len(targets)
        for index, target in enumerate(targets, start=1):
            if progress_callback:
                progress_callback(index, total, target)
            self.log_info(f'连续切换 {index}/{total}：准备登录 {target}')
            logged_profiles.append(self._select_and_login_specific(target))
            if index < total:
                self.log_info(f'模拟 {target} 每日任务已完成，仅执行退登并切换下一个账号')
                self._switch_to_login()
                self.sleep(2)
        return logged_profiles

    def find_account_drop_down(self):
        return self.wait_until(self.do_find_account_drop_down, time_out=60, settle_time=2, raise_if_not_found=True)

    def _account_entry_count(self, texts):
        """OCR 文本中账号条目（掩码 180****1088 或 U 扫码账号）的框数量。

        同一账号文本出现在不同位置（收起态 ComboBox + 展开列表）各算一个，
        用于区分「收起态（1 个）」与「列表已展开（≥2 个）」。
        """
        count = 0
        for t in texts or []:
            name = (t.name or '').strip()
            if name and (account_pattern.search(name) or scan_account_pattern.match(name)):
                count += 1
        return count

    def _account_list_expanded(self):
        """账号下拉列表是否已展开（账号条目 ≥2）。

        对话框模式：优先检测可见且尺寸正常的 ComboLBox 控件；回退统计对话框帧 OCR 账号条目。
        主窗口模式：统计主窗口 OCR 账号条目。
        """
        if getattr(self, '_login_in_dialog', False):
            try:
                hwnd, rect = self._find_control_hwnd('ComboLBox')
                if hwnd:
                    w = rect[2] - rect[0]
                    h = rect[3] - rect[1]
                    if w >= 200 and h >= 100:
                        return True
            except Exception:
                pass
            dlg_texts = self._ocr_login_dialog()
            return bool(dlg_texts) and self._account_entry_count(dlg_texts) >= 2
        texts = self.ocr()
        return bool(texts) and self._account_entry_count(texts) >= 2

    def do_find_account_drop_down(self) -> object | None:
        """登录界面账号下拉框检测（v1.03.74：收起/展开状态都视为登录就绪）。

        命中条件：登录特征（登录/Log/登入）存在 且 至少 1 个账号条目（掩码或 U 扫码账号）。
        下拉列表展开态（账号条目 ≥2）同样命中——调用方用 _account_list_expanded() 区分
        展开态，避免把「列表已展开」误判为「点击下拉框无效果」。
        先查主窗口帧（登录界面内嵌变体），无则查 #32770 登录对话框帧（独立窗口变体），
        命中对话框帧时置 self._login_in_dialog = True，后续账号操作改用对话框帧。
        """
        def judge(texts, in_dialog):
            account_boxes = self.find_boxes(texts, account_pattern)
            login_boxes = self.find_boxes(texts, LOGIN_TEXTS)
            u_boxes = [t for t in (texts or []) if scan_account_pattern.match((t.name or '').strip())]
            entries = list(account_boxes) + u_boxes
            if not login_boxes or len(entries) < 1:
                return None
            self._login_in_dialog = in_dialog
            return entries[0]

        hit = judge(self.ocr(), False)
        if hit is not None:
            return hit
        # 主窗口无特征 → #32770 登录对话框帧
        dlg_texts = self._ocr_login_dialog()
        if dlg_texts:
            hit = judge(dlg_texts, True)
            if hit is not None:
                return hit
        return None


from ok import run_task
from config import config

if __name__ == "__main__":
    run_task(config, task=MultiAccountDailyTask, debug=True)
