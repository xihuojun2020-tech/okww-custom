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

from ok import Logger
from ok.util.file import get_relative_path, read_json_file, write_json_file
from src.task.DailyTask import DailyTask, LOGOUT_AFTER_DAILY as LOGOUT_AFTER_DAILY_KEY
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

    def _profile_identities(self, profile_name):
        """返回方案的识别标识列表：手机号掩码 + 账号别名（归一化）。"""
        profiles = self._load_profiles()
        profile = profiles.get(profile_name) or {}
        ids = []
        m = phone_in_name_pattern.search(profile_name)
        if m:
            phone = m.group(1)
            ids.append(normalize_account_name(masked_phone(phone)))
        # 账号别名：优先新配置键「备用识别名称内容」（逗号分隔），兼容旧 account_aliases 字段
        aliases = []
        alias_text = profile.get('备用识别名称内容') if isinstance(profile, dict) else None
        if alias_text:
            aliases = [a.strip() for a in str(alias_text).split(',') if a and a.strip()]
        if not aliases:
            old = profile.get('account_aliases') or []
            aliases = list(old) if isinstance(old, list) else []
        for a in aliases:
            if a:
                ids.append(normalize_account_name(str(a).strip()))
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
            self.run_task_by_class(DailyTask)
            self.ensure_main(time_out=100)
            self._switch_to_login()
        else:
            first_target = self._select_and_login_account()
            if first_target:
                self.log_info(f'从登录界面选择下一个未完成账号：{first_target}，开始执行每日任务', notify=True)
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
        return account in self.done_set

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
        self.send_key('esc', after_sleep=1.5)
        self.wait_feature('esc_setting')
        self.click_relative(0.04, 0.96, after_sleep=1)
        self.click_confirm(timeout=10)
        self.find_account_drop_down()
        self.log_info(self.tr('Back at login screen'))

    def _detect_current_account_from_login(self):
        """识别登录界面当前显示的账号，返回方案名（掩码或扫码 U 账号均可识别）。"""
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

    def _click_account_in_list(self, profile_name):
        """在登录界面账号列表中点击指定的方案账号，返回是否点击成功。"""
        accounts = self.ocr(match=account_pattern)
        for account in accounts:
            if self.match_profile_from_login(account.name) == profile_name:
                self.click(account, after_sleep=2)
                self.log_info(f'点击账号 {profile_name}')
                return True
        # 找不到目标账号：输出列表内容便于排查（记住列表里没有该账号 / 识别失败）
        visible = [a.name for a in accounts][:15]
        self.log_error(
            f'登录界面账号列表中没有找到目标账号 {profile_name}；'
            f'当前列表可见：{visible}（若目标不在列表，说明该账号未在本设备登录器记住，'
            f'或已被其他账号挤出记住列表，需要扫码登录）'
        )
        return False

    def _select_and_login_account(self):
        """从本轮序列取第一个未完成账号，在登录界面选择并登录；全部完成返回 None。"""
        target = self._next_target_account()
        if target is None:
            return None
        current_account = None
        mouse_reset_task = self.executor.get_task_by_class(MouseResetTask)
        mouse_reset_was_enabled = mouse_reset_task.enabled if mouse_reset_task else False
        if mouse_reset_was_enabled:
            mouse_reset_task.disable()
        try:
            max_retries = 5
            for attempt in range(1, max_retries + 1):
                self.sleep(1)
                drop_down = self.find_account_drop_down()
                if drop_down:
                    self.click(drop_down, after_sleep=2)
                if self.do_find_account_drop_down():
                    self.log_error('click drop down no effect')
                    self.screenshot('multi')
                    continue
                account = self.wait_until(
                    lambda: self._click_account_in_list(target),
                    time_out=10, raise_if_not_found=True
                )
                self.sleep(1)
                current_account = self._detect_current_account_from_login()
                self.log_info(self.tr('Selected account: {selected}, displayed account: {displayed}').format(
                    selected=account, displayed=current_account))
                if self._same_account(account, current_account):
                    self.log_info(self.tr('Confirmed selected account: {account}').format(account=account))
                    break
                if attempt < max_retries:
                    self.log_info(self.tr('Account display does not match, retrying ({attempt}/{max_retries})').format(
                        attempt=attempt, max_retries=max_retries))
                else:
                    self.log_error(self.tr(
                        'Account selection failed after {max_retries} retries; {account} is still not displayed. Continuing login attempt'
                    ).format(max_retries=max_retries, account=account))
                    raise Exception(self.tr('Failed to switch account'))
            self.sleep(4)
            texts = self.ocr()
            login_btn = self.find_boxes(texts, boundary=self.box_of_screen(0.3, 0.3, 0.7, 0.8),
                                        match=LOGIN_TEXTS)
            if login_btn:
                # 点登录前核对当前显示的账号是否为目标账号（防误登其他账号）
                shown = self._detect_current_account_from_login()
                if shown and not self._same_account(shown, target):
                    self.log_error(
                        f'登录界面当前显示账号 {shown} 与目标 {target} 不一致，'
                        f'取消点击登录（防误登），请检查账号选择'
                    )
                    raise Exception(self.tr('Login aborted: displayed account does not match target'))
                self.click(login_btn, after_sleep=3)
            else:
                self.click_relative(0.5, 0.568, hcenter=True, vcenter=True, after_sleep=3)
            self.logged_in = False
            self.ensure_main(time_out=180)
            self.log_info(self.tr('Login successful'))
            return current_account
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
            drop_down = self.find_account_drop_down()
            if drop_down:
                self.click(drop_down, after_sleep=2)
            deadline_account = None
            self.wait_until(lambda: self._click_specific_account(profile_name),
                            time_out=10, raise_if_not_found=True)
            self.sleep(4)
            texts = self.ocr()
            login_btn = self.find_boxes(texts, boundary=self.box_of_screen(0.3, 0.3, 0.7, 0.8),
                                        match=LOGIN_TEXTS)
            if login_btn:
                self.click(login_btn, after_sleep=3)
            else:
                self.click_relative(0.5, 0.568, hcenter=True, vcenter=True, after_sleep=3)
            self.logged_in = False
            self.ensure_main(time_out=180)
            self.log_info(f'已登录: {profile_name}')
        finally:
            if mouse_reset_was_enabled:
                mouse_reset_task.enable()

    def _click_specific_account(self, profile_name):
        """在账号列表中点击指定的方案账号，返回是否点击成功。"""
        accounts = self.ocr(match=account_pattern)
        for account in accounts:
            if self.match_profile_from_login(account.name) == profile_name:
                self.click(account, after_sleep=2)
                return True
        return False

    def find_account_drop_down(self):
        return self.wait_until(self.do_find_account_drop_down, time_out=60, settle_time=2, raise_if_not_found=True)

    def do_find_account_drop_down(self) -> object | None:
        texts = self.ocr()
        account_boxes = self.find_boxes(texts, account_pattern)
        login_boxes = self.find_boxes(texts, LOGIN_TEXTS)
        if len(account_boxes) == 1 and login_boxes:
            return account_boxes[0]
        return None


from ok import run_task
from config import config

if __name__ == "__main__":
    run_task(config, task=MultiAccountDailyTask, debug=True)
