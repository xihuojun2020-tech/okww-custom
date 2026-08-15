import random
import re
import time

import cv2
import numpy as np
from qfluentwidgets import FluentIcon as Icon

from ok import Logger
from src.task.BaseWWTask import BaseWWTask
from src.task.WWOneTimeTask import WWOneTimeTask

logger = Logger.get_logger(__name__)


class EventTask(WWOneTimeTask, BaseWWTask):
    """
    悲鸣行动：无音危机（Tacet Crisis）自动化。
    - 进入 2D 圆形战场后自动绕小圈走位
    - 战斗倒计时结束后进入奖励选择页（带 👍 推荐的卡牌）
    - 之后进入交易所商店（带 👍 推荐和锁定机制的购买）
    """

    # ==================== 屏幕坐标（归一化 0~1，按 16:9 设计） ====================
    # 4 张奖励卡 / 商品 横向中心（按 1000×562 实拍截图像素位置回算，1920×1080 下同比例）
    CARD_X_CENTERS = [0.330, 0.510, 0.700, 0.880]
    # 选卡点击位置：直接点【选择】按钮（pill）中心，确保命中"选择"文字
    # 实测 pill 在 y_norm [0.699, 0.742]，center 0.720；选择文字在 brightest 行 ~0.71~0.72
    CARD_CLICK_Y = 0.720
    # 👍 推荐图标检测位置（卡牌右下角，"选择"按钮上方）
    RECOMMEND_Y = 0.66
    RECOMMEND_X_OFFSET = 0.08  # 相对卡牌中心（实测卡牌右半侧约 0.08）
    # 锁定图标位置（商店商品，右上角）
    LOCK_Y = 0.255
    LOCK_X_OFFSET = 0.070
    # 商店购买区域（卡牌底部白色部分）
    BUY_AREA_Y = 0.720
    # 货币数字（顶部常驻）。商店/奖励页的货币只在右上角（实测确认）；
    # 左上角在战斗里显示的是波次货币、在商店/奖励页里是属性数值，绝不能当活动货币读。
    CURRENCY_BOX = (0.76, 0.02, 0.94, 0.13)  # 右上角
    # 奖励页底部右侧刷新按钮 + 价格
    REFRESH_BUTTON_X = 0.585
    REFRESH_BUTTON_Y = 0.88
    # 刷新价：奖励页/商店页的 R 按钮位置不同（奖励 R≈(0.60,0.93)，商店 R≈(0.72,0.93)），
    # 价格数字就在各自 R 键正上方，必须按页面使用不同检测框。
    # 商店页价是 2 位数，原生 OCR 可读（实测 20/23/25）；奖励页价是 R 键正上方一个
    # 很小的单数字（实测 y≈0.895、x≈0.60），原生分辨率 OCR 读不到，须裁剪放大 4x
    # 再识别（实测 15 张奖励页命中 13）。仍读不到返回 None，由调用方按
    # "货币>0 即可刷新"兜底，不再因此中止任务。
    REWARD_COST_BOX = (0.585, 0.875, 0.625, 0.915)  # 奖励页刷新价（紧贴 R 键上方的小数字）
    SHOP_COST_BOX = (0.66, 0.84, 0.80, 0.94)        # 商店页刷新价
    # 商店页底部右侧 "F 下一波次"
    F_BUTTON_X = 0.92
    F_BUTTON_Y = 0.88
    # 价格区（每张商品底部，OCR 价格数字）
    PRICE_BOX_TEMPLATE = (0.0, 0.68, 0.06, 0.76)  # x 偏移 + 宽度固定

    # ==================== OCR/正则 ====================
    WAVE_RE = re.compile(r'(\d{1,3})\s*/\s*(\d{1,3})')
    NUM_RE = re.compile(r'(\d+)')
    REWARD_TITLE_RE = re.compile(r'(奖励|战利品|选择奖励|Reward|Loot|Buff|等级提升|升级属性|属性选择|升级|Level\s*Up|Talent)', re.IGNORECASE)
    # 奖励页独有强标题：只出现在卡牌选择页（等级提升/升级属性/属性选择/Reward/Loot/Talent/Buff），
    # 战斗 HUD 里绝不会出现。战斗里的"波次奖励"/升级提示等浮动文字会命中上面的弱关键词，
    # 因此单独用弱关键词做页面判定会把战斗误判成奖励页；强标题则战斗安全。
    REWARD_PAGE_TITLE_RE = re.compile(r'(等级提升|升级属性|属性选择|Reward|Loot|Talent|Buff)', re.IGNORECASE)
    SHOP_TITLE_RE = re.compile(r'(交易所|商店|购买|Shop|Exchange|Store|Trade|Purchase)', re.IGNORECASE)
    # 商店底部右侧"下一波次 / F下一波次"按钮文字：商店页恒有、战斗帧绝无。
    # 战斗帧底部只有敌人计数(81/81)，因此这是比"锁定图标"更可靠的商店判定信号。
    SHOP_BOTTOM_RE = re.compile(r'(下一波次|下一波|F\s*下)', re.IGNORECASE)
    ARENA_TITLE_RE = re.compile(r'(波次进度|当前波次|倒计时|第\s*\d+\s*波|Wave)', re.IGNORECASE)
    # 商店按 F 进入下一波时弹出的"当前仍有可购买物品，是否进入下一波次？"对话框
    DIALOG_TITLE_RE = re.compile(r'(进入下一波|可购买物品|是否进入|下一波次|不再提示)', re.IGNORECASE)
    DEATH_TITLE_RE = re.compile(r'(复活|挑战失败|重新挑战|退出挑战|Revive|Defeat|Retry)', re.IGNORECASE)
    # 奖励页卡底【选择】按钮文字。战斗中没有此文字，是比 👍 图标更安全的奖励判定信号
    # （战斗里的金圈/治疗黄字 +2 等会落在卡列扫描区，被 👍 检测误判成推荐）。
    SELECT_BUTTON_RE = re.compile(r'(选择|Select)', re.IGNORECASE)

    # ==================== 黄色推荐/锁定图标阈值 ====================
    # HSV 黄色范围
    YELLOW_LOWER = (10, 80, 130)
    YELLOW_UPPER = (55, 255, 255)
    # 视为"有推荐图标"的最小黄色像素比例
    RECOMMEND_YELLOW_RATIO = 0.04
    # 注：锁定检测不用黄色比例阈值（真锁窗口比例约0.15<0.18会误判为未锁定、
    # 杂乱的黄色又常超阈值误判为已锁定），改用锁图标形状检测，见 _lock_shape。

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 显示名（菜单里看到的就是这个）
        self.name = "悲鸣行动：无音危机"
        self.description = (
            "进入 2D 圆形战场后自动绕小圈走位躲攻击；战斗结束后自动选择"
            "带推荐符号（👍）的奖励；进入交易所后锁定并购买带推荐符号的商品。"
            "由游戏自带自动战斗清理敌人。"
        )
        # 让 okww 自动建一个独立的"限时活动" tab
        self.group_name = "限时活动"
        self.group_icon = Icon.GAME
        default_config = {
            # 绕圈
            'Circle Side Time': 0.8,
            'Circle Scale': 1.0,   # 绕圈范围倍率（每个方向按住时间 × 此值；1.5 = 1.5 倍范围）
            'Circle Pause': 0.05,  # 模拟人手：偶尔停顿的秒数
            'Circle Direction': '顺时针',
            # 状态检测
            'State Check Interval': 0.4,  # 奖励/商店屏需要更频繁
            # 模拟人手
            'Click Random Offset X': 0.04,  # 左右随机偏移比例
            'Click Random Offset Y': 0.012,  # 上下偏移（小于 X）
            'Click Interval': 0.6,           # 每次点击后等待秒数（连续点击间隔）
            # 商店点击节奏
            'Shop Click Interval': 0.8,  # 商店锁定/购买/重读之间的等待秒数（放慢可避免漏买）
            # 刷新策略
            'Max Refresh Count': 20,            # 单次奖励/商店最大刷新次数（防卡死）
            # 失败恢复
            'Auto Restart on Death': True,
            'Max Death Count': 5,
            # 终止条件
            'Stop After Waves': 0,
            'Exit on All Waves Done': True,
        }
        self.default_config = default_config
        self.config_description = {
            'Circle Side Time': '8 方向轮转时每个方向的基准按住秒数。值越小圈越紧、转向越快。',
            'Circle Scale': '绕圈范围倍率：每个方向按住时间 × 此值。1.0 = 原范围；1.5 = 扩大至 1.5 倍。',
            'Circle Pause': '模拟人手：绕圈中偶尔停顿一下的秒数（0 = 不停顿）。',
            'Circle Direction': '顺时针（D 偏航） / 逆时针（A 偏航）。',
            'State Check Interval': '每隔多少秒检测一次页面状态（战场/奖励/商店）。',
            'Click Random Offset X': '点击左右随机偏移比例（占屏幕宽），模拟人手。',
            'Click Random Offset Y': '点击上下随机偏移比例（小于 X，模拟人手）。',
            'Click Interval': '每次点击之后等待的秒数。值越大，连续点击之间的间隔越长、节奏越慢越稳。',
            'Shop Click Interval': '商店区锁定/购买/重读之间的等待秒数。点击太快容易漏买商品，可适当调大。',
            'Max Refresh Count': '单次奖励选择 / 单次商店循环最大刷新次数（防卡死）。',
            'Auto Restart on Death': '检测到角色死亡时，自动点击重新挑战。',
            'Max Death Count': '死亡达到此次数后停止任务。',
            'Stop After Waves': '累计完成多少波后停止（0 = 不限制）。',
            'Exit on All Waves Done': 'OCR 检测到 30/30 时自动退出任务。',
        }
        self.visible = True  # 有 group_name 时，会进"限时活动" tab，不会进默认 Tasks
        self._last_currency = None

    # ===================== 主流程 =====================

    def run(self):
        WWOneTimeTask.run(self)
        # 活动为【手动进入地图】，程序不主动 ensure_main / 按 ESC，
        # 否则会反复打开/关闭暂停菜单。直接进入战场轮询。
        self.sleep(1)

        # 分辨率自适应：打印实际捕获分辨率，校验 16:9（所有坐标均为归一化，按 16:9 设计）
        size = self._frame_size()
        if size:
            h, w = size
            aspect = w / h
            self.log_info(f'捕获分辨率 {w}x{h}，宽高比 {aspect:.3f}')
            if abs(aspect - 16 / 9) > 0.05:
                self.log_info(
                    f'宽高比 {aspect:.3f} 偏离 16:9，卡牌/按钮坐标可能偏移，'
                    f'请在 16:9 下运行或微调 CARD_X_CENTERS 等常量。', notify=True)

        self._last_unknown_diag = 0.0
        death_count = 0

        # 初始识别：确认当前处于哪个阶段（战场/奖励/商店/死亡/未知）
        start = self._detect_page()
        self.log_info(f'程序启动，初始识别：{self._page_label(start)}', notify=True)
        if start == 'unknown':
            # 轮询等待进入任一可操作阶段（战场/奖励/商店）
            if not self._wait_for_any(time_out=30):
                self.log_info(
                    '未识别到活动战场/奖励/商店，请手动确认已进入对应界面后重试。',
                    notify=True,
                )
                return

        last_page = None  # None：保证首轮必输出当前状态（含启动即在【奖励关】/【商店区】时也显示货币）
        while True:
            page = self._detect_page()
            # 实时在 UI 日志展示当前所处阶段（仅在状态变化时输出，避免刷屏）
            if page != last_page:
                label = self._page_label(page)
                if page in ('reward', 'shop'):
                    # 奖励关/商店区：同时显示货币数量与刷新所需货币数量（按页面用对应检测框）
                    currency = self._read_currency(page)
                    refresh = self._read_refresh_cost(page)
                    cur_disp = str(currency) if currency is not None else '读取失败'
                    ref_disp = str(refresh) if refresh is not None else '读取失败'
                    self.log_info(
                        f'当前状态：{label} | 货币 {cur_disp} | 刷新所需 {ref_disp}',
                        notify=True,
                    )
                else:
                    self.log_info(f'当前状态：{label}')
                last_page = page

            if page == 'reward':
                if not self._handle_reward_screen():
                    return
                self.sleep(1)

            elif page == 'shop':
                if not self._handle_shop_screen():
                    return
                self.sleep(1)

            elif page == 'confirm_next':
                self._handle_confirm_next_wave()
                self.sleep(1)

            elif page == 'death':
                death_count += 1
                max_death = self.config.get('Max Death Count', 5)
                if max_death and death_count >= max_death:
                    self.log_info(f'已死亡 {death_count} 次（上限），任务停止', notify=True)
                    return
                if self.config.get('Auto Restart on Death', True):
                    self.log_info(f'检测到死亡（第 {death_count} 次），重新挑战', notify=True)
                    self._click_restart()
                    self.sleep(2)
                    if not self._wait_for_any(time_out=20):
                        self.log_info('重新挑战后未识别到可操作阶段，任务停止', notify=True)
                        return
                else:
                    self.log_info('检测到死亡但未启用自动重开，任务暂停', notify=True)
                    return

            elif page == 'arena':
                # 主玩法：2D 平面 8 方向轮转绕圈
                self._circle_strafe()

            else:  # unknown / transition
                # 未知页面：节流诊断（每 8s 保存截图 + 打印 OCR 文字）便于校准检测
                now = time.time()
                if now - self._last_unknown_diag >= 8:
                    self._last_unknown_diag = now
                    self._diagnose_unknown()
                self.sleep(0.3)

    # ===================== 页面检测 =====================

    def _detect_page(self):
        """识别当前页面：商店 / 奖励 / 确认进入下一波 / 战场 / 死亡 / unknown。

        判定顺序：商店(交易所标题或底部"下一波次"按钮) → 奖励(强标题，或弱标题+选择按钮) →
        确认进入下一波对话框 → 战场(波次进度文字) → 死亡(居中弹窗)。

        战斗安全要点（三次误判的根因都在这）：
        - 商店页顶部一定有"交易所/商店"标题、底部一定有"下一波次/F下一波次"按钮；
          战斗 HUD 两者都没有。战斗里的金色元素（拾取物/伤害数字/高危提示）会大量
          落入"锁定图标"扫描区造成锁定图标误判（实测战斗帧 0~3 张卡都触发过），
          因此页面判定**不再使用锁定图标**，改用顶部标题或底部按钮文字判商店。
          锁定图标只在商店处理内部（_is_locked/_click_lock）用于锁定/解锁判断。
        - 奖励页顶部一定有强标题（等级提升/升级属性/属性选择），且不显示"波次进度"；
          战斗里"波次奖励"等浮动文字会命中弱关键词，所以弱关键词路径必须同时满足
          "选择按钮文字"且帧内无战场进度文字，否则战斗会被误判成奖励页。
        """
        try:
            texts = self.ocr(0.02, 0.02, 0.98, 0.30)  # 放宽到 0.30：捕获波次进度/倒计时
        except Exception:
            texts = []
        joined = ' '.join(str(getattr(b, 'name', b)) for b in texts) if texts else ''
        # 战场进度提示：奖励/商店页都不会显示，用于排除战斗帧对两者的误判
        arena_hint = bool(self.ARENA_TITLE_RE.search(joined)) or bool(self.WAVE_RE.search(joined))
        # 1) 商店：顶部"交易所/商店"标题，或底部"下一波次/F下一波次"按钮。
        #    战斗帧顶部无标题、底部只有敌人计数，两项都不满足 → 不会误判成商店。
        if self.SHOP_TITLE_RE.search(joined) or self._has_shop_bottom():
            return 'shop'
        # 2) 奖励选择：强标题单独命中；或（弱标题 + 卡底【选择】按钮 + 非战场帧）
        if self.REWARD_PAGE_TITLE_RE.search(joined) or (
                not arena_hint and self.REWARD_TITLE_RE.search(joined) and self._has_select_button_text()):
            return 'reward'
        # 2.5) "进入下一波次"确认对话框（商店后按 F 触发，居中弹窗，文字在屏幕中部）
        try:
            dlg_texts = self.ocr(0.20, 0.30, 0.80, 0.66)
        except Exception:
            dlg_texts = []
        joined_dlg = ' '.join(str(getattr(b, 'name', b)) for b in dlg_texts) if dlg_texts else ''
        if self.DIALOG_TITLE_RE.search(joined_dlg):
            return 'confirm_next'
        # 3) 战场：波次进度 / 当前波次 / 倒计时 文字
        if arena_hint:
            return 'arena'
        # 4) 死亡 / 重新挑战：居中弹窗
        try:
            mid_texts = self.ocr(0.30, 0.30, 0.70, 0.55)
        except Exception:
            mid_texts = []
        joined_mid = ' '.join(str(getattr(b, 'name', b)) for b in mid_texts) if mid_texts else ''
        if self.DEATH_TITLE_RE.search(joined_mid):
            return 'death'
        return 'unknown'

    def _has_shop_bottom(self):
        """检测商店底部右侧"下一波次/F下一波次"按钮文字。

        商店页恒有该按钮，战斗帧底部只有敌人计数(81/81)、绝无此文字，
        因此它是比锁定图标更可靠的商店判定信号——战斗金色元素会大量误触
        锁定图标扫描区，但不会伪造出"下一波次"文字。OCR 区域避开底部
        特征码水印(y≥0.98)，也不会命中居中"进入下一波次"对话框(y 0.30~0.66)。
        """
        try:
            texts = self.ocr(0.55, 0.82, 1.0, 0.97)
        except Exception:
            return False
        joined = ' '.join(str(getattr(b, 'name', b)) for b in texts) if texts else ''
        return bool(self.SHOP_BOTTOM_RE.search(joined))

    def _wait_for_any(self, time_out=30):
        """轮询直到识别到任一可操作阶段（战场/奖励/商店）。"""
        self.log_info('等待进入可操作阶段（战场/奖励/商店）...')
        deadline = time.time() + time_out
        while time.time() < deadline:
            p = self._detect_page()
            if p in ('arena', 'reward', 'shop'):
                self.log_info(f'已识别：{self._page_label(p)}')
                return True
            self.sleep(1)
        return False

    def _page_label(self, page):
        """把内部页面标记映射成中文（带【】），便于在 UI 日志展示。"""
        return {
            'arena': '【战斗】',
            'reward': '【奖励关】',
            'shop': '【商店区】',
            'confirm_next': '【确认进入下一波】',
            'death': '【死亡/重新挑战】',
            'unknown': '【未知/过渡】',
        }.get(page, page)

    def _diagnose_unknown(self):
        """未知页面诊断：保存整帧截图并把 OCR 文字打到日志，便于校准检测。"""
        try:
            top = self.ocr(0.02, 0.02, 0.98, 0.16)
            mid = self.ocr(0.30, 0.30, 0.70, 0.55)
            top_txt = ' '.join(str(getattr(b, 'name', b)) for b in top)
            mid_txt = ' '.join(str(getattr(b, 'name', b)) for b in mid)
            self.log_info(f'[诊断]未识别页面 顶部OCR: "{top_txt}" 中部OCR: "{mid_txt}"', notify=True)
            self._save_debug('unknown', None)
        except Exception as e:
            logger.debug(f'diag failed: {e}')

    # ===================== 奖励选择页 =====================

    def _handle_reward_screen(self):
        """奖励选择页：选最左侧推荐卡；无推荐时按规则刷新。"""
        self._save_debug('reward',
                         [(c, self.CARD_CLICK_Y) for c in self.CARD_X_CENTERS]
                         + [(self.REFRESH_BUTTON_X, self.REFRESH_BUTTON_Y)])
        currency = self._read_currency('reward')
        if currency is None:
            self.log_info('奖励页无法读取货币，重试后停止任务', notify=True)
            return False

        refresh_cost = self._read_refresh_cost()
        refresh_used = 0
        max_refresh = self.config.get('Max Refresh Count', 20)

        while refresh_used < max_refresh:
            # 重新检测推荐（刷新后界面会变）
            recommended_idx = self._find_recommended_card()
            if recommended_idx is not None:
                self.log_info(
                    f'奖励页：第 {recommended_idx + 1} 张卡有推荐，'
                    f'货币 {currency} → 点击选择'
                )
                if self._select_and_confirm(recommended_idx):
                    return True
                self.log_info('奖励页点击选择后页面未切换，停止任务，避免误刷新', notify=True)
                return False

            # 没有推荐：尝试刷新。条件：货币 > 刷新价；或刷新价读不到（奖励页数字太小
            # OCR 常失败）但货币 > 0 时也兜底刷新——避免"刷新所需货币识别不到"时中止任务。
            if (refresh_cost is not None and currency > refresh_cost) or (
                    refresh_cost is None and currency > 0):
                self.log_info(
                    f'奖励页：无推荐，刷新价 {refresh_cost}，货币 {currency}，按 R 刷新'
                )
                self.send_key('r', after_sleep=1.2)
                refresh_used += 1
                # 刷新后必须重新读取，不能沿用旧值继续消耗货币。
                self.sleep(0.4)
                new_currency = self._read_currency('reward')
                new_cost = self._read_refresh_cost()
                if new_currency is not None:
                    currency = new_currency
                if new_cost is not None:
                    refresh_cost = new_cost
                continue

            # 没有推荐且不满足刷新条件时不擅自选择错误奖励。
            self.log_info(
                f'奖励页：无推荐且无法刷新（价 {refresh_cost}，货币 {currency}），停止等待人工处理',
                notify=True,
            )
            return False

        self.log_info('奖励页刷新次数达到上限，停止任务', notify=True)
        return False

    def _select_and_confirm(self, card_idx):
        """点击推荐卡的【选择】，并确认奖励页确实已经离开。"""
        for attempt in range(2):
            self._click_select(card_idx)
            if self._wait_for_page_change('reward', time_out=3):
                return True
            if attempt == 0:
                self.log_info('奖励页选择未生效，按较慢节奏重试一次')
        return False

    def _wait_for_page_change(self, old_page, time_out=3):
        """等待页面连续两次不再是 old_page，过滤单帧 OCR 抖动。"""
        deadline = time.time() + time_out
        changed = 0
        while time.time() < deadline:
            page = self._detect_page()
            if page != old_page:
                changed += 1
                if changed >= 2:
                    return True
            else:
                changed = 0
            self.sleep(0.35)
        return False

    def _has_select_button_text(self):
        """检测奖励页卡底是否有【选择】按钮文字（战斗安全的奖励页判定信号）。

        战斗 HUD 的金圈/治疗黄字(+2)会落在卡列扫描区触发 👍 图标误判，但战斗里
        没有【选择】文字，因此用文字判定更可靠。OCR 卡底一条带（4 张卡的"选择"pill
        所在 y 区间，约 0.66~0.78）。"""
        try:
            texts = self.ocr(0.28, 0.66, 0.93, 0.78)
        except Exception:
            return False
        joined = ' '.join(str(getattr(b, 'name', b)) for b in texts) if texts else ''
        return bool(self.SELECT_BUTTON_RE.search(joined))

    def _find_recommended_card(self):
        """从左到右找第一个带 👍 的卡牌索引，返回 0~3，未找到返回 None。"""
        for idx, cx in enumerate(self.CARD_X_CENTERS):
            if self._has_recommend_in_column(cx):
                return idx
        return None

    def _slide_column_max_ratio(self, x_center, x_offset, y_top, y_bottom, win_target_abs):
        """沿卡牌整列（y_top~y_bottom 归一化）垂直滑动一个约 win_target_abs 像素的
        小窗，返回检测到的最大黄色像素比例。

        为什么不用整条带一次扫描：整条带（几百像素高）会把图标面积的黄色比例稀释到
        阈值以下（典型 0.03 左右 < 阈值 0.04），导致"识别不到奖励/商店"。改为滑动小窗
        + 取最大值，既保留了为小窗标定的阈值，又能容忍图标纵向位置偏差。
        横向窗口同时覆盖 卡牌中心(x_center) 与 偏移位(x_center+x_offset) 两种可能，
        避免 👍/锁图标实际相对卡牌中心的横向偏移猜错导致漏检。
        """
        rx, ry = self._recommend_window(target_abs=win_target_abs)
        frame = self._frame()
        if frame is None:
            return 0.0
        h, w = frame.shape[:2]
        cx_lo = x_center
        cx_hi = x_center + x_offset
        cx_px = int(((cx_lo + cx_hi) / 2.0) * w)
        rx_abs = int(rx * w)
        ry_abs = int(ry * h)
        # 窗口宽度 2*rx_abs（约 160px @1080p），中心在 x_center 与 x_center+offset 的中点，
        # 覆盖范围略大于 [x_center, x_center+offset]，两者都落在窗口内 → 容忍偏移猜错。
        # 注意：不再额外外扩，避免窗口太宽稀释黄色比例（之前 extra 让比例从 ~0.08 降到 ~0.04）。
        x1 = max(0, cx_px - rx_abs)
        x2 = min(w, cx_px + rx_abs)
        y1 = int(y_top * h)
        y2 = int(y_bottom * h)
        if y2 <= y1 or x2 <= x1:
            return 0.0
        if y2 - y1 <= ry_abs:
            return self._yellow_ratio(frame[y1:y2, x1:x2])
        best = 0.0
        step = max(1, ry_abs // 2)  # 半窗步进，保证滑动窗口互相重叠覆盖
        for y in range(y1, y2 - ry_abs + 1, step):
            r = self._yellow_ratio(frame[y:y + ry_abs, x1:x2])
            if r > best:
                best = r
        return best

    def _has_recommend_in_column(self, x_center):
        """在卡牌整列下半部分（y 0.45~0.82）滑动小窗扫描黄色 👍 图标，
        取最大比例，避免 👍 纵向位置估算偏差导致漏检，同时避免整条带稀释阈值。"""
        r = self._slide_column_max_ratio(x_center, self.RECOMMEND_X_OFFSET, 0.45, 0.82, 80)
        return r >= self.RECOMMEND_YELLOW_RATIO

    def _frame_size(self):
        """返回当前帧 (h, w)，无帧返回 None。"""
        frame = self._frame()
        if frame is None:
            return None
        return frame.shape[:2]

    def _recommend_window(self, target_abs=80):
        """返回覆盖约 target_abs 绝对像素的归一化宽/高比例。

        用绝对像素而非固定比例，保证 720P / 1080P / 1440P 下
        检测窗口覆盖相同大小的图标（避免低分辨率漏检）。
        """
        size = self._frame_size()
        if not size:
            return 0.04, 0.04
        h, w = size
        rx = max(0.025, target_abs / w)
        ry = max(0.025, target_abs / h)
        return rx, ry

    def _has_recommend_at(self, x_center, y):
        """在指定坐标(y)附近区域检测黄色 👍 图标（分辨率自适应窗口）。
        复用滑动窗口逻辑，横向覆盖卡牌中心与 👍 偏移位，纵向在 y 附近小范围内滑动取最大值。"""
        return self._slide_column_max_ratio(
            x_center, self.RECOMMEND_X_OFFSET, y - 0.06, y + 0.06, 80) >= self.RECOMMEND_YELLOW_RATIO

    def _yellow_ratio(self, bgr):
        if bgr is None or bgr.size == 0:
            return 0.0
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, self.YELLOW_LOWER, self.YELLOW_UPPER)
        return cv2.countNonZero(mask) / (bgr.shape[0] * bgr.shape[1])

    def _click_select(self, card_idx):
        """点击第 N 张卡底部【选择】按钮（y=CARD_CLICK_Y）。

        选择按钮很窄（约屏宽 5%、~90px），默认 ±0.04 的横向随机偏移(±77px@1920)
        有约 50% 概率点出按钮范围。这里把横向抖动倍率降到 0.25(±19px)，
        确保红圈稳稳落在【选择】文字上。
        """
        cx = self.CARD_X_CENTERS[card_idx]
        self._human_click(cx, self.CARD_CLICK_Y, jitter_x=0.25, jitter_y=1.0)

    # ===================== 商店页 =====================

    def _handle_shop_screen(self):
        """交易所：锁定所有推荐 → 从左到右按价格购买 → 余钱够刷新则刷新循环。"""
        self._save_debug('shop',
                         [(c, self.LOCK_Y) for c in self.CARD_X_CENTERS]
                         + [(c, self.BUY_AREA_Y) for c in self.CARD_X_CENTERS]
                         + [(self.REFRESH_BUTTON_X, self.REFRESH_BUTTON_Y),
                            (self.F_BUTTON_X, self.F_BUTTON_Y)])
        shop_interval = float(self.config.get('Shop Click Interval', 0.8))
        currency = self._read_currency('shop')
        if currency is None:
            self.log_info('商店页多次读取货币仍失败，停止任务', notify=True)
            return False
        # 商店页刷新价必须用商店页检测框（R≈(0.72,0.93)），传 page='shop'，
        # 否则默认用奖励页框读不到商店页价格，导致"刷新所需货币识别不到"。
        refresh_cost = self._read_refresh_cost('shop')
        max_refresh = self.config.get('Max Refresh Count', 20)
        currency_ok = True

        refresh_used = 0
        while refresh_used <= max_refresh:
            # 找出推荐商品（带 👍）
            recommended = [i for i, cx in enumerate(self.CARD_X_CENTERS)
                           if self._has_recommend_at(cx, self.RECOMMEND_Y)]
            self.log_info(
                f'商店：推荐商品 {recommended}，货币 {currency}，刷新价 {refresh_cost}'
            )

            # 锁定所有推荐商品（未锁的）
            for idx in recommended:
                if not self._is_locked(idx):
                    self.log_info(f'商店：锁定第 {idx + 1} 个推荐商品')
                    self._click_lock(idx)
                    self.sleep(shop_interval)

            # 从左到右买推荐商品（每次买完重读货币）；同时记录本轮是否买得起推荐商品
            any_buyable = False
            for idx in recommended:
                price = self._read_item_price(idx)
                if price is None:
                    # 价格识别失败：推荐商品直接尝试购买（买不起也无害），避免漏买
                    self.log_info(f'商店：第 {idx + 1} 个价格未识别，按推荐直接尝试购买')
                    self._click_buy_area(idx)
                    self.sleep(shop_interval)
                    new_currency = self._read_currency('shop')
                    if new_currency is not None:
                        currency = new_currency
                    continue
                if price <= currency:
                    any_buyable = True
                    self.log_info(
                        f'商店：买第 {idx + 1} 个（价 {price}，货币 {currency}）'
                    )
                    self._click_buy_area(idx)
                    self.sleep(shop_interval)
                    new_currency = self._read_currency('shop')
                    if new_currency is not None:
                        currency = new_currency
                else:
                    self.log_info(
                        f'商店：第 {idx + 1} 个价 {price} > 货币 {currency}，跳过'
                    )

            # 刷新决策：
            # - 有买得起的推荐商品 → 余钱够刷新价就刷新，继续买（可能刷出更便宜的推荐）
            # - 没有推荐商品 → 余钱够刷新价就刷新，找新的推荐
            # - 有推荐但都买不起 → 不再刷新直接进下一波（刷新只会让钱更少、更买不起）
            can_refresh = currency_ok and refresh_cost is not None and currency > refresh_cost
            if can_refresh and (any_buyable or not recommended):
                self.log_info(
                    f'商店：余钱 {currency} > 刷新价 {refresh_cost}，按 R 刷新'
                )
                self.send_key('r', after_sleep=1.2)
                refresh_used += 1
                self.sleep(shop_interval)
                new_currency = self._read_currency('shop')
                new_cost = self._read_refresh_cost('shop')
                if new_currency is not None:
                    currency = new_currency
                else:
                    # 货币识别失败：保留上次值但不再刷新，随后走购买/F 流程，避免中止任务
                    currency_ok = False
                    self.log_info(
                        f'商店：刷新后货币未识别，保留上次值 {currency}，不再刷新'
                    )
                if new_cost is not None:
                    refresh_cost = new_cost
                continue

            # 无可购买（推荐均买不起 / 无推荐且不刷新）：不再刷新，直接 F 进入下一波
            if recommended and not any_buyable:
                self.log_info(
                    f'商店：推荐商品均买不起（余钱 {currency}），不再刷新，按 F 进入下一波'
                )
            else:
                self.log_info('商店：无可购买，按 F 进入下一波')
            self.send_key('f', after_sleep=1.5)
            return True

        # 刷新过多兜底
        self.log_info('商店刷新过多，按 F 兜底进入下一波', notify=True)
        self.send_key('f', after_sleep=1.5)
        return True

    def _handle_confirm_next_wave(self):
        """处理"当前仍有可购买物品，是否进入下一波次？"居中对话框。

        商店按 F 进入下一波时游戏弹此确认框；若不专门识别，程序会卡在 unknown
        态、既不进战斗也不买东西。这里点击【确定】进入下一波。
        【确定】按钮先用 OCR 动态定位（实测约在归一化 (0.66, 0.63)），定位失败
        再回退到该固定坐标，避免分辨率/布局偏移导致点偏。
        """
        self.log_info('检测到"进入下一波次"确认对话框 → 点击【确定】', notify=True)
        self._save_debug('confirm_next', [(0.66, 0.63)])
        hit = self._click_button_by_text(
            ['确定', '确认', 'OK'],
            box=(0.40, 0.45, 0.95, 0.80),
            fallback=(0.66, 0.63),
        )
        if not hit:
            logger.debug('confirm_next 未 OCR 到【确定】按钮，已回退固定坐标 (0.66,0.63)')

    def _click_button_by_text(self, keywords, box, fallback=None):
        """在 box 区域内 OCR 定位包含任一关键词的按钮并点击。

        命中返回 True；未命中且给了 fallback 归一化坐标则点击 fallback 并返回 False。
        用于居中对话框按钮（如【确定】）这类固定坐标可能因分辨率/布局漂移的目标。
        """
        try:
            texts = self.ocr(*box)
        except Exception as e:
            logger.debug(f'ocr button failed: {e}')
            texts = []
        for b in texts or []:
            name = str(getattr(b, 'name', ''))
            if any(k in name for k in keywords):
                self.click(b, after_sleep=float(self.config.get('Click Interval', 0.6)))
                return True
        if fallback is not None:
            self._human_click(*fallback)
        return False

    def _is_locked(self, card_idx):
        """检查第 N 个商品是否已锁定（锁图标形状检测，而非单纯黄色比例）。

        纯黄色比例阈值不可靠：真锁（实心锁图标）的窗口黄色比例约 0.15，低于旧
        阈值 0.18 会被误判为"未锁定"，程序再点击锁定(toggle)反而把已锁商品解锁，
        导致该商品在下次刷新后被替换消失；而卡面/战斗的杂乱黄色又常超阈值被误判
        为"已锁定"导致漏锁。改用锁图标形状：最大黄色连通域居中、近方形、占比高。
        """
        cx = self.CARD_X_CENTERS[card_idx] + self.LOCK_X_OFFSET
        rx, ry = self._recommend_window(target_abs=55)
        frame = self._frame()
        if frame is None:
            return False
        h, w = frame.shape[:2]
        px, py = int(cx * w), int(self.LOCK_Y * h)
        rx_abs, ry_abs = int(rx * w), int(ry * h)
        x1, y1 = max(0, px - rx_abs), max(0, py - ry_abs)
        x2, y2 = min(w, px + rx_abs), min(h, py + ry_abs)
        if x2 <= x1 or y2 <= y1:
            return False
        crop = frame[y1:y2, x1:x2]
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, self.YELLOW_LOWER, self.YELLOW_UPPER)
        return self._lock_shape(mask)

    def _lock_shape(self, mask):
        """判断黄色 mask 是否呈"锁"图标形状：最大黄色连通域居中、近方形、占比高。

        真锁（实心锁：锁扣横条 + 锁身矩形）的最大连通域集中在窗口中央、宽高比≈1.0、
        占黄色总量绝大部分；卡面/战斗的杂乱黄色则触到窗口边缘、呈横向/纵向长条，
        或分散成许多小碎块。所有判据均用相对比例，跨 720P/1080P/1440P 稳定。
        """
        ch, cw = mask.shape[:2]
        if ch == 0 or cw == 0:
            return False
        total = cv2.countNonZero(mask)
        if total < max(80, int(cw * ch * 0.02)):
            return False  # 黄色太少，无锁
        n, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
        if n <= 1:
            return False
        areas = stats[1:, cv2.CC_STAT_AREA]
        max_idx = int(np.argmax(areas))
        max_area = int(areas[max_idx])
        if max_area / total < 0.6:
            return False  # 黄色分散，最大块占比低，非锁
        s = stats[max_idx + 1]
        x, y, bw, bh = (int(s[cv2.CC_STAT_LEFT]), int(s[cv2.CC_STAT_TOP]),
                        int(s[cv2.CC_STAT_WIDTH]), int(s[cv2.CC_STAT_HEIGHT]))
        if bh <= 0:
            return False
        aspect = bw / bh
        if aspect < 0.7 or aspect > 1.4:
            return False  # 锁身近方形；横向/纵向长条不是锁
        if x < cw * 0.08 or x + bw > cw * 0.92:
            return False  # 锁身应居中，触到窗口边缘的不是锁
        if y < ch * 0.10:
            return False  # 锁扣在上、锁身偏中下，贴着窗口顶部不是锁
        return True

    def _click_lock(self, card_idx):
        """点击第 N 个商品的锁定按钮（卡左上角锁图标）。

        锁图标很小（约 30~50px），默认 ±0.04 的横向随机偏移(±77px@1920) 有约 50%
        概率点出图标范围，导致推荐商品没被锁上（与 _click_select 注释记载的同类问题）。
        这里把横向抖动倍率降到 0.15(±11px)、纵向降到 0.5，确保红圈稳稳落在锁图标上。
        """
        cx = self.CARD_X_CENTERS[card_idx] + self.LOCK_X_OFFSET
        self._human_click(cx, self.LOCK_Y, jitter_x=0.15, jitter_y=0.5)

    def _click_buy_area(self, card_idx):
        cx = self.CARD_X_CENTERS[card_idx]
        self._human_click(cx, self.BUY_AREA_Y)

    def _read_item_price(self, card_idx):
        """OCR 商品底部价格数字。返回 int 或 None（识别不稳定，自动重试）。"""
        cx = self.CARD_X_CENTERS[card_idx]
        x1, y1, x2, y2 = self.PRICE_BOX_TEMPLATE
        x1 = cx + x1
        x2 = cx + x2
        return self._ocr_int_retry((x1, y1, x2, y2))

    # ===================== 通用：货币 / 刷新价 / 死亡重开 =====================

    def _read_currency(self, page=None, retries=3):
        """读取顶部常驻货币数（商店/奖励页只在右上角），识别不稳定，自动重试。

        page 参数仅为调用方语义方便而接受，货币一律读右上角框：左上角在战斗里是
        波次货币、在商店/奖励页里是属性数值，绝不能当成活动货币读取（战斗里曾因此
        被误报成巨额"商店货币"）。
        注意：不能用过宽的顶部扫描——okww 延迟浮层(.xxxxms/1KB/s)会被当货币。
        """
        retries = int(retries)  # 防御：配置/调用方可能传字符串（06:58 曾因此 TypeError 崩溃）
        for attempt in range(retries):
            v = self._ocr_int(*self.CURRENCY_BOX)
            if v is not None:
                self._last_currency = v
                return v
            if attempt < retries - 1:
                self.sleep(0.3)
        return None

    def _read_refresh_cost(self, page=None):
        """读取奖励/商店页底部刷新按钮上的价格数字（识别不稳定，自动重试）。

        奖励页与商店页的 R 按钮位置不同（奖励 R≈(0.60,0.93)，商店 R≈(0.72,0.93)），
        价格数字在其正上方，必须按页面选择不同检测框。奖励价是单个小数字须放大 4x；
        商店价是 2 位数放大 2x 即可稳定读（实测 4/4）。读不到返回 None，由调用方按
        "货币>0 即可刷新"兜底，不再中止任务。
        """
        if page == 'shop':
            return self._ocr_int_upscaled(self.SHOP_COST_BOX, upscale=2)
        return self._ocr_int_upscaled(self.REWARD_COST_BOX, upscale=4)

    def _ocr_int(self, x1, y1, x2, y2):
        try:
            texts = self.ocr(x1, y1, x2, y2)
        except Exception as e:
            logger.debug(f'ocr int failed: {e}')
            return None
        return self._digits_from_boxes(texts)

    def _ocr_int_upscaled(self, box, upscale=4, retries=3, interval=0.3):
        """OCR 数字，先把裁剪区放大 upscale 倍再识别。

        奖励页刷新价是 R 键上方一个很小的单数字（原生分辨率 OCR 读不到），
        紧贴裁剪后放大到 4x 再识别，实测 15 张奖励页命中 13。
        """
        retries = int(retries)      # 防御：避免字符串重试次数导致 TypeError
        interval = float(interval)  # 防御：sleep 需要数值
        upscale = int(upscale)      # 防御：cv2.resize 需要数值
        for attempt in range(retries):
            frame = self._frame()
            if frame is None:
                return None
            h, w = frame.shape[:2]
            x1, y1, x2, y2 = box
            crop = frame[int(y1 * h):int(y2 * h), int(x1 * w):int(x2 * w)]
            if crop.size == 0:
                return None
            crop = cv2.resize(crop, None, fx=upscale, fy=upscale,
                              interpolation=cv2.INTER_CUBIC)
            try:
                texts = self.ocr(0, 0, 1, 1, frame=crop)
            except Exception as e:
                logger.debug(f'ocr upscaled failed: {e}')
                texts = []
            v = self._digits_from_boxes(texts)
            if v is not None:
                return v
            if attempt < retries - 1:
                self.sleep(interval)
        return None

    def _digits_from_boxes(self, texts):
        """从 OCR 结果里抽取数字，取最大值返回；无数字返回 None。

        先去掉千分位逗号（如 1,234），否则 NUM_RE 会拆成 12 / 34，取 max 得到错误值。
        """
        if not texts:
            return None
        values = []
        for box in texts:
            cleaned = str(getattr(box, 'name', box)).replace(',', '')
            for match in self.NUM_RE.finditer(cleaned):
                try:
                    values.append(int(match.group(1)))
                except (ValueError, TypeError):
                    pass
        if not values:
            return None
        return max(values)

    def _ocr_int_retry(self, box, retries=3, interval=0.3):
        """OCR 读取数字，失败时重试（货币/价格识别不稳定，一次常识别不到）。"""
        retries = int(retries)      # 防御：避免字符串重试次数导致 TypeError
        interval = float(interval)  # 防御：sleep 需要数值
        for attempt in range(retries):
            v = self._ocr_int(*box)
            if v is not None:
                return v
            if attempt < retries - 1:
                self.sleep(interval)
        return None

    def _click_restart(self):
        self.click_relative(0.5, 0.5, after_sleep=0.5)
        try:
            texts = self.ocr(0.30, 0.30, 0.70, 0.60)
            for box in texts:
                name = str(getattr(box, 'name', ''))
                if '重新挑战' in name or 'Retry' in name.lower():
                    self.click(box, after_sleep=0.5)
                    return
        except Exception:
            pass

    # ===================== 移动：绕小圈 =====================

    def _circle_strafe(self):
        """2D 平面战场（无镜头跟随）：必须用 WASD 全部方向轮转才能绕圈。
        以 8 个方向（上 / 右上 / 右 / 右下 / 下 / 左下 / 左 / 左上）为一组，
        按顺序各短时按住对应键，轨迹近似一个圆（八边形）。
        顺时针：上→右上→右→右下→下→左下→左→左上；逆时针则反向。

        转圈范围由 Circle Scale 控制：每个方向的按住时间 = Circle Side Time × Circle Scale，
        按得越久走得越远、圈越大（1.5 = 扩大至 1.5 倍范围）。

        模拟人手：每个方向的按住时长在基础值附近随机抖动（±25%），并偶尔停顿一下
        （概率 15%，时长取 Circle Pause），让按键节奏像真人操作而非固定节拍脚本。

        每隔 State Check Interval 检测页面，离开战场即松开全部按键（防卡键）。
        """
        direction = str(self.config.get('Circle Direction', '顺时针'))
        clockwise = ('顺' in direction) or ('cw' in direction.lower())
        step_t = float(self.config.get('Circle Side Time', 0.8))
        scale = float(self.config.get('Circle Scale', 1.0))
        step_t = step_t * scale
        check_interval = float(self.config.get('State Check Interval', 0.4))
        pause = float(self.config.get('Circle Pause', 0.05))

        # 8 方向对应的同按键（屏幕绝对方向；2D 平面无镜头跟随）
        dirs = [['w'], ['w', 'd'], ['d'], ['s', 'd'],
                ['s'], ['s', 'a'], ['a'], ['w', 'a']]
        if not clockwise:
            dirs = dirs[::-1]

        pressed = []

        def set_keys(target):
            nonlocal pressed
            for k in pressed:
                if k not in target:
                    try:
                        self.send_key_up(k)
                    except Exception:
                        pass
            for k in target:
                if k not in pressed:
                    try:
                        self.send_key_down(k)
                    except Exception:
                        pass
            pressed = list(target)

        self.log_info(
            f'开始绕圈走位（每方向 {step_t:.2f}s，范围 {scale:.2f}x，'
            f'方向 {"顺时针" if clockwise else "逆时针"}）')
        last_check = 0.0
        unknown_streak = 0
        i = 0
        try:
            while True:
                set_keys(dirs[i % len(dirs)])
                # 模拟人手：按住时长在 ±25% 内随机抖动（不固定节拍）
                dur = step_t * random.uniform(0.75, 1.25)
                self.sleep(dur)
                i += 1
                # 模拟人手：偶尔停顿一下再继续（像真人迟疑/观察）
                if pause > 0 and random.random() < 0.15:
                    set_keys([])
                    self.sleep(pause * random.uniform(0.5, 1.5))
                now = time.time()
                if now - last_check >= check_interval:
                    last_check = now
                    try:
                        detected = self._detect_page()
                        if detected in ('reward', 'shop', 'confirm_next', 'death'):
                            break
                        # 连续多次未识别（可能出现新界面/弹窗）→ 退出绕圈交主循环诊断，
                        # 避免在未知界面一直盲走。阈值 8 次 × check_interval ≈ 3 秒。
                        if detected == 'unknown':
                            unknown_streak += 1
                            if unknown_streak >= 8:
                                self.log_info(
                                    '绕圈中连续未识别到战场，退出绕圈交主循环诊断处理',
                                    notify=True,
                                )
                                break
                        else:
                            unknown_streak = 0
                    except Exception:
                        pass
        finally:
            set_keys([])  # 松开全部键，防卡键

    # ===================== 人手偏移点击 + 帧 =====================

    def _human_click(self, x_norm, y_norm, jitter_x=1.0, jitter_y=1.0):
        """带左右随机偏移、上下小幅偏移的相对点击，模拟人手。
        按下时长加长到 0.08s，确保游戏 UI 能识别为一次完整点击。
        jitter_x / jitter_y 为偏移倍率（默认 1.0）；点击【选择】等窄按钮时
        传更小的倍率避免点偏漏选。"""
        rx = float(self.config.get('Click Random Offset X', 0.04)) * jitter_x
        ry = float(self.config.get('Click Random Offset Y', 0.012)) * jitter_y
        dx = random.uniform(-rx, rx)
        dy = random.uniform(-ry, ry)
        x = max(0.01, min(0.99, x_norm + dx))
        y = max(0.01, min(0.99, y_norm + dy))
        self.click_relative(
            x, y,
            after_sleep=float(self.config.get('Click Interval', 0.6)),
            down_time=0.08,
        )

    def _save_debug(self, tag, points=None):
        """保存当前帧到 screenshots/event_debug/，并在 points（归一化坐标）处画红圈，
        便于核对点击目标是否命中风云 UI 按钮。"""
        try:
            import os
            frame = self._frame()
            if frame is None:
                return
            h, w = frame.shape[:2]
            img = frame.copy()
            if points:
                for (xn, yn) in points:
                    cx, cy = int(xn * w), int(yn * h)
                    cv2.circle(img, (cx, cy), max(14, int(w * 0.012)), (0, 0, 255), 3)
            d = os.path.join('screenshots', 'event_debug')
            os.makedirs(d, exist_ok=True)
            ts = time.strftime('%H%M%S')
            path = os.path.join(d, f'{tag}_{ts}.png')
            cv2.imwrite(path, img)
            self.log_info(f'调试截图(红圈=点击目标)已保存: {path}', notify=True)
        except Exception as e:
            logger.debug(f'save debug failed: {e}')

    def _frame(self):
        """获取当前游戏帧（numpy ndarray BGR）。失败返回 None。"""
        try:
            return self.frame  # ok 框架 BaseTask.frame 属性
        except Exception as e:
            logger.debug(f'self.frame failed: {e}')
            return None
