"""Claim the observed weekly allowance, then verify it in the guidebook."""
import re
import time

from ok import TaskDisabledException
from src.task.BaseCombatTask import (
    BaseCombatTask, CharDeadException, CombatStateUnknown, NotInCombatException,
)
from src.task.WWOneTimeTask import WWOneTimeTask
from src.task.weekly_boss import (
    WEEKLY_BOSSES, WEEKLY_AUTO, WeeklyBossResult, compact, boss_title, match_target_button,
    combat_phase, parse_cost, parse_remaining, parse_stamina,
)


class WeeklyPageTimeout(RuntimeError):
    pass


class WeeklyBossTask(WWOneTimeTask, BaseCombatTask):
    navigation_section = 'tasks'
    owns_switch_healer_config = True

    BOOK_COUNT = (0.365, 0.13, 0.68, 0.18)
    DETAIL_COUNT = (0.635, 0.825, 0.855, 0.871)
    LIST = (0.365, 0.25, 0.965, 0.89)
    TITLE = (0.02, 0.03, 0.38, 0.095)
    SINGLE = (0.63, 0.875, 0.969, 0.944)
    START = (0.775, 0.864, 0.95, 0.95)
    EXIT = (0.285, 0.82, 0.465, 0.89)
    RETRY = (0.54, 0.82, 0.72, 0.89)
    SUCCESS = (0.4, 0.265, 0.6, 0.325)
    VICTORY = (0.4, 0.235, 0.6, 0.315)
    REWARDS = (0.24, 0.46, 0.765, 0.595)
    COST = (0.914, 0.829, 0.967, 0.869)
    STAMINA = (0.78, 0.033, 0.89, 0.079)
    CLAIM_TITLE = (0.23, 0.30, 0.36, 0.35)
    CLAIM_MESSAGE = (0.30, 0.45, 0.70, 0.51)
    CLAIM_CONFIRM = (0.56, 0.60, 0.75, 0.66)
    CLAIM_CANCEL = (0.24, 0.60, 0.43, 0.66)
    CLAIM_STAMINA = (0.735, 0.035, 0.805, 0.078)
    TASK_HINT = (0.01, 0.12, 0.28, 0.30)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = 'Weekly Boss Challenge'
        self.description = 'Claim all remaining weekly rewards from one boss, then verify zero remaining. Current stamina only; keep default difficulty and team.'
        self.group_name = None
        self.supported_languages = ['zh_CN']
        self.default_config.update({
            'Weekly Boss': WEEKLY_AUTO,
            'Use Liberation': True,
            'Switch to Healer before and after Combat': True,
        })
        self.config_type['Weekly Boss'] = {
            'type': 'drop_down', 'options': [WEEKLY_AUTO, *(boss.key for boss in WEEKLY_BOSSES)],
        }
        self.config_description['Weekly Boss'] = 'Use this boss for every remaining reward this run. Does not change difficulty or team.'
        self.target_enemy_time_out = 3
        self.switch_char_time_out = 5
        self.combat_end_condition = self._battle_finished
        self.last_result = None

    def _stage(self, message):
        self.info_set('周本阶段', message)
        self.log_info(message)

    def _ocr(self, region, frame=None):
        return self.ocr(*region, frame=self.frame if frame is None else frame)

    def _text(self, region, frame=None):
        return ''.join(b.name for b in self._ocr(region, frame))

    def _button(self, region, text, frame=None):
        boxes = [b for b in self._ocr(region, frame) if compact(b.name) == text]
        return boxes[0] if len(boxes) == 1 else None

    def _wait_for(self, probe, message, timeout=15):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.next_frame()
            value = probe()
            if value:
                return value
            self.sleep(0.25)
        raise WeeklyPageTimeout(message)

    def _stable_value(self, probe, message, timeout=12):
        previous = None
        def read():
            nonlocal previous
            value = probe()
            stable = value is not None and value == previous
            previous = value
            return (value,) if stable else None
        return self._wait_for(read, message, timeout)[0]

    def _read_remaining(self, detail=False):
        region = self.DETAIL_COUNT if detail else self.BOOK_COUNT
        return self._stable_value(lambda: parse_remaining(self._text(region)),
                                  '无法稳定识别本周剩余可收取次数，停止周本')

    def _open_weekly_book(self):
        self.reset_to_false('weekly guidebook')
        self.ensure_main(time_out=120)
        self.openF2Book('gray_book_boss')
        self.open_boss_book('zhange')
        self._wait_for(lambda: '本周剩余可收取次数' in compact(self._text(self.BOOK_COUNT)),
                       '未进入战歌重奏页面')

    def _select_target(self, boss):
        self._stage(f'寻找周本：{boss.name}')

        def scan(label):
            self.next_frame()
            boxes = self._ocr(self.LIST)
            signature = tuple((compact(b.name), round(b.y / self.height, 2)) for b in boxes)
            titles = [boss_title(b.name) for b in boxes if '战歌重奏' in compact(b.name)]
            self.log_info(f'周本搜索 {label}：可见标题={titles}，OCR框数={len(boxes)}')
            target = match_target_button(boxes, boss.name, self.height)
            if target:
                self.log_info(f'周本目标与同行挑战按钮已确认：{boss.name}')
                self.click_box(target)
                self._wait_for(lambda: self._detail_ready(boss), '挑战页面与所选周本不一致')
            return target is not None, signature

        self.log_info('周本列表：滚轮回顶 x=0.92 y=0.50 count=30')
        self.scroll_relative(0.92, 0.5, 30)
        self.sleep(1)
        previous = None
        unchanged = 0
        for index in range(16):
            found, signature = scan(f'滚轮第{index + 1}轮')
            if found:
                return
            unchanged = unchanged + 1 if signature and signature == previous else 0
            self.log_info(f'周本列表：连续未变化={unchanged}')
            if unchanged >= 2:
                break
            previous = signature
            self.log_info('周本列表：滚轮下翻 x=0.92 y=0.50 count=-3')
            self.scroll_relative(0.92, 0.5, -3)
            self.sleep(0.7)

        # Same track x as BaseWWTask.click_on_book_target; small overlapping
        # steps avoid skipping rows. A click inside the thumb need not move it.
        self.log_info('周本滚轮搜索未定位目标，改用右侧滚动条从上到下分段搜索')
        progressed = False
        for index in range(14):
            y = min(0.25 + index * 0.05, 0.88)
            self.log_info(f'周本滚动条：第{index + 1}/14段 x=0.973 y={y:.3f}')
            self.click_relative(0.973, y)
            self.sleep(0.7)
            found, signature = scan(f'滚动条第{index + 1}段')
            if found:
                return
            changed = bool(signature and previous and signature != previous)
            progressed = progressed or changed
            self.log_info(f'周本滚动条：页面内容变化={changed}')
            previous = signature
        if not progressed:
            raise RuntimeError(f'未确认列表翻页，无法完成周本搜索：{boss.name}；未选择其他目标')
        raise RuntimeError(f'滚动条分段搜索后仍未找到周本：{boss.name}，未选择其他目标')

    def _detail_ready(self, boss):
        frame = self.frame
        return (boss_title(self._text(self.TITLE, frame)) == boss.name
                and self._button(self.SINGLE, '单人挑战', frame))

    def _read_entry_resources(self):
        def read():
            frame = self.frame
            cost = parse_cost(self._text(self.COST, frame))
            stamina = parse_stamina(self._text(self.STAMINA, frame))
            return (cost, stamina) if cost is not None and stamina is not None else None
        return self._stable_value(read, '无法确认周本费用或当前体力')

    def _enter_challenge(self):
        button = self._wait_for(lambda: self._button(self.SINGLE, '单人挑战'), '未找到单人挑战')
        self.click_box(button)
        button = self._wait_for(lambda: self._button(self.START, '开启挑战'), '未进入周本编队页')
        self.click_box(button)
        self._wait_for(lambda: not self._button(self.START, '开启挑战'), '开启挑战未生效')
        self._wait_for(self.in_team_and_world, '进入周本加载超时', 120)

    def _reward_available(self):
        # The quest label at the left is not an interaction: require the F icon
        # and the text attached to it. No input from the combat end probe.
        frame = self.frame
        f = self.find_one('pick_up_f_hcenter_vcenter',
                          box=self.box_of_screen(0.625, 0.49, 0.66, 0.545), threshold=0.8, frame=frame)
        if not f:
            return None
        claim = self._button((0.69, 0.49, 0.80, 0.545), '领取奖励', frame)
        return claim if f and claim and abs(f.y - claim.y) <= self.height * 0.015 else None

    def _task_hint_phase(self, log=False):
        hints = [compact(box.name) for box in self._ocr(self.TASK_HINT)]
        phase = combat_phase(hints)
        signature = (tuple(hints), phase)
        if log and signature != getattr(self, '_last_task_hint', None):
            self._last_task_hint = signature
            self.log_info(f'周本左侧任务提示 OCR={hints or ["<empty>"]}，阶段={phase or "unknown"}')
        return phase

    def _battle_finished(self):
        # A phase transition can briefly look out of combat or show victory.
        # The left objective is authoritative while it still says to fight.
        phase = self._task_hint_phase()
        if phase == 'combat':
            return False
        return bool(phase == 'post' or self._reward_available() or
                    self._button(self.VICTORY, '挑战成功'))

    def _wait_combat_phase(self, timeout=30):
        def read():
            phase = self._task_hint_phase(log=True)
            if phase:
                return phase
            if self._reward_available() or self._button(self.VICTORY, '挑战成功'):
                return 'post'
            return None
        return self._stable_value(read, '过场后无法确认周本战斗阶段', timeout)

    def on_combat_check(self):
        # FarmEcho's hook presses arbitrary F prompts; weekly rewards are only
        # claimed by the explicit post-combat state below.
        return True

    def revive_action(self):
        return False

    def _release_movement(self):
        for key in ('w', 'a', 's', 'd'):
            self.send_key_up(key)
        self.mouse_up(key='right')

    def _fight(self):
        self._stage('周本自动战斗')
        # Reuse the normal boss targeting/rotation. Only approach if no target
        # appears after loading; never run the overworld teleport/restart loop.
        if not self.wait_until(lambda: self.in_combat(target=True), time_out=5,
                               raise_if_not_found=False):
            try:
                self.run_until(lambda: self.in_combat(target=True), 'w', time_out=10,
                               running=True, target=True, raise_if_not_found=True)
            finally:
                self._release_movement()
        while True:
            self.skip_combat_check = False
            combat_error = None
            try:
                self.combat_once(wait_combat_time=10, raise_if_not_found=True)
            except CharDeadException:
                raise
            except (CombatStateUnknown, NotInCombatException) as error:
                combat_error = error
            finally:
                self.skip_combat_check = True
                self._release_movement()

            self._stage('战斗状态待确认：检查左侧任务提示')
            try:
                phase = self._wait_combat_phase()
            except WeeklyPageTimeout as verification_error:
                if combat_error:
                    raise combat_error from verification_error
                raise
            if phase == 'combat':
                self._stage('周本仍需击败敌人，等待下一阶段')
                post_seen = False
                def next_phase():
                    nonlocal post_seen
                    if (self._task_hint_phase(log=True) == 'post' or
                            self._reward_available() or self._button(self.VICTORY, '挑战成功')):
                        if post_seen:
                            return 'post'
                        post_seen = True
                        return None
                    post_seen = False
                    return 'combat' if self.in_combat(target=True) else None
                phase = self._wait_for(next_phase, '下一阶段 Boss 未出现', 45)
            if phase == 'post':
                if isinstance(combat_error, CombatStateUnknown):
                    self.combat_end()
                self.log_info('周本战后阶段已连续确认；尚未计入领奖次数')
                break
        self.reset_to_false('weekly combat returned; verify reward')

    def _settlement(self):
        frame = self.frame
        if compact(self._text(self.SUCCESS, frame)) != '挑战成功':
            return None
        exit_button = self._button(self.EXIT, '退出副本', frame)
        retry_button = self._button(self.RETRY, '重新挑战', frame)
        rewards = self._ocr(self.REWARDS, frame)
        quantities = sum(bool(re.fullmatch(r'[xX×]\d+', compact(b.name))) for b in rewards)
        return (exit_button, retry_button) if exit_button and retry_button and quantities >= 2 else None

    def _claim_confirmation(self):
        frame = self.frame
        if compact(self._text(self.CLAIM_TITLE, frame)) != '领取奖励':
            return None
        message = compact(self._text(self.CLAIM_MESSAGE, frame))
        match = re.fullmatch(r'领取奖励需消耗(\d{1,3})点结晶波片[,，]请确认是否领取[?？]', message)
        confirm = self._button(self.CLAIM_CONFIRM, '确认', frame)
        cancel = self._button(self.CLAIM_CANCEL, '取消', frame)
        stamina = parse_stamina(self._text(self.CLAIM_STAMINA, frame))
        if match and 0 < int(match[1]) <= 240 and confirm and cancel and stamina is not None:
            return int(match[1]), stamina, confirm
        return None

    def _confirm_claim_if_needed(self, cost):
        self._stage('检查领奖费用确认弹窗或结算页')
        previous = None

        def read():
            nonlocal previous
            if self._settlement():
                return ('settled', None)
            dialog = self._claim_confirmation()
            resources = dialog[:2] if dialog else None
            stable = resources is not None and resources == previous
            previous = resources
            return ('confirm', dialog) if stable else None

        state, dialog = self._wait_for(read, '未确认领奖弹窗或结算页，未点击确认', 20)
        if state == 'settled':
            return
        actual_cost, stamina, button = dialog
        if actual_cost != cost:
            raise RuntimeError(f'领奖费用不一致：预期 {cost}，弹窗 {actual_cost}；未确认领取')
        if stamina < actual_cost:
            raise RuntimeError(f'领奖体力不足：当前 {stamina}，需要 {actual_cost}；未确认领取')
        self.log_info(f'周本领奖确认：费用 {actual_cost}，当前体力 {stamina}；仅点击一次确认')
        self.click_box(button)

    def _fight_and_claim(self, cost):
        self._fight()
        self._stage('寻找领取奖励交互')
        if not self._reward_available():
            try:
                self.walk_to_box(self.find_treasure_icon, time_out=30,
                                 end_condition=self._reward_available, y_offset=0.1)
            finally:
                self._release_movement()
        self._wait_for(self._reward_available, '战后未找到领取奖励交互')
        self.send_key('f')
        # Only the verified current-stamina confirmation is supported. Never
        # use the generic cancellation handler or click replenishment dialogs.
        self._confirm_claim_if_needed(cost)
        self._stage('等待领奖结算，不重复确认')
        self._wait_for(self._settlement, '领奖结果未确认，停止再次挑战', 20)
        self._stage('已进入领奖结算页')
        # The result page hides the top bar; use the existing anchored reader.
        def balance():
            value = self.get_settlement_stamina()
            return value if value >= 0 else None
        try:
            return self._stable_value(balance, '结算体力未识别', 6)
        except WeeklyPageTimeout:
            # The reward screen is already proven. Unknown stamina forbids
            # retry, but must still allow exit and an authoritative count read.
            return None

    def _leave_settlement(self, retry):
        buttons = self._wait_for(self._settlement, '结算页丢失，无法确认退出或重开')
        self.click_box(buttons[1 if retry else 0])
        # Explicitly observe departure before accepting another world frame.
        self._wait_for(lambda: not self._settlement(), '结算按钮未生效，未重复点击', 20)
        self._wait_for(self.in_team_and_world, '重开加载超时' if retry else '退出副本加载超时', 120)

    def _recheck(self, initial, claimed, reason=''):
        self._stage('返回战歌重奏复核剩余次数')
        self._open_weekly_book()
        remaining = self._read_remaining()
        self.last_result = WeeklyBossResult(initial, claimed, remaining)
        self.info_set('复核剩余', remaining)
        from src.evidence.service import record_task_evidence
        record_task_evidence(self, 'weekly_boss', 'completed' if remaining == 0 else 'partial',
                             f'战歌重奏复核：本周剩余 {remaining} 次；{reason}',
                             progress=dict(initial=initial, claimed=claimed, remaining=remaining))
        self.ensure_main(time_out=60)
        if remaining:
            raise RuntimeError(f'{reason or "周本未完成"}，本周仍剩余 {remaining} 次；未记录完成')
        self._stage('已复核 0/3，本周奖励全部领取')
        return self.last_result

    def run_weekly(self, target_key=None):
        target_key = target_key if target_key is not None else self.config.get('Weekly Boss',WEEKLY_AUTO)
        self.last_result = None
        self.info['已确认领奖'] = 0
        self.use_liberation = self.config.get('Use Liberation', True)
        boss = next((b for b in WEEKLY_BOSSES if b.key == (target_key if target_key is not None else self.config.get('Weekly Boss'))), None)
        if boss is None and target_key != WEEKLY_AUTO:
            raise ValueError('请选择有效的周本名称')
        self._stage('检查本周剩余次数')
        self._open_weekly_book()
        if target_key == WEEKLY_AUTO:
            self.scroll_relative(.92,.5,30)
            self.sleep(1)
            self.next_frame()
            titles = sorted((b for b in self._ocr(self.LIST) if '战歌重奏' in compact(b.name)), key=lambda b:b.y)
            boss = next((b for b in WEEKLY_BOSSES if titles and b.name == boss_title(titles[0].name)),None)
            if boss is None:
                raise WeeklyPageTimeout('未识别游戏列表首个周本，停止自动选择')
        initial = self._read_remaining()
        self.info_set('计划领奖', initial)
        if initial == 0:
            self.last_result = WeeklyBossResult(0, 0, 0)
            from src.evidence.service import record_task_evidence
            record_task_evidence(self, 'weekly_boss', 'completed', '战歌重奏已识别本周剩余 0 次',
                                 progress=dict(remaining=0))
            self.ensure_main(time_out=60)
            self._stage('本周奖励已全部领取')
            return self.last_result
        self._select_target(boss)
        if self._read_remaining(detail=True) != initial:
            raise RuntimeError('列表与难度页的次数不一致，停止周本')
        cost, stamina = self._read_entry_resources()
        if stamina < cost:
            return self._recheck(initial, 0, '当前体力不足')
        self._enter_challenge()
        claimed = 0
        reason = ''
        while claimed < initial:
            stamina = self._fight_and_claim(cost)
            claimed += 1
            self.info['已确认领奖'] = claimed
            retry = claimed < initial and stamina is not None and stamina >= cost
            self._stage(f'已领取 {claimed}/{initial}，' + ('重新挑战' if retry else '退出副本'))
            self._leave_settlement(retry)
            if not retry:
                if claimed < initial:
                    reason = '结算体力未知' if stamina is None else '当前体力不足'
                break
        return self._recheck(initial, claimed, reason)

    def run(self):
        WWOneTimeTask.run(self)
        return self.run_for_target(self.config.get('Weekly Boss'))

    def run_for_target(self, target_key):
        if self.game_lang != 'zh_CN':
            raise RuntimeError('周本首版仅支持简体中文游戏')
        if abs(self.width / self.height - 16 / 9) > 0.02:
            raise RuntimeError('周本首版需要 16:9 游戏画面')
        previous = self.skip_combat_check
        self.skip_combat_check = True
        try:
            return self.run_weekly(target_key)
        except TaskDisabledException:
            raise
        except Exception:
            self._stage('周本中断，未确认本周完成；重新运行将读取游戏剩余次数')
            self.screenshot('weekly_boss_unconfirmed')
            raise
        finally:
            self.skip_combat_check = previous
            self._release_movement()
