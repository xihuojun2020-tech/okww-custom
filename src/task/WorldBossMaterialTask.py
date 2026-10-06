"""Finite material claims using FarmEcho's Boss Challenge traversal/combat."""
import re
from copy import deepcopy
import time
from dataclasses import dataclass
from ok import TaskDisabledException
from ok.task.exceptions import FinishedException
from src.task.FarmEchoTask import FarmEchoTask
from src.task.WeeklyBossTask import WeeklyBossTask
from src.task.BaseCombatTask import CombatStateUnknown
from src.task.world_boss_materials import WORLD_BOSS_TARGETS, TARGETS_BY_ID, material_target_button, matches_target
from src.task.world_boss_material_plan import material_plan, choose_material_target, material_plan_revision, validate_material_request
from src.task.world_boss_material_progress import WorldBossMaterialProgress
from src.task.weekly_boss import compact


@dataclass(frozen=True)
class MaterialRunResult:
    claimed: int
    spent: int
    status: str


class WorldBossMaterialTask(FarmEchoTask):
    navigation_section = 'tasks'
    # Reuse the weekly claim's selected-F detector and bounded reward approach.
    _ocr = WeeklyBossTask._ocr
    _text = WeeklyBossTask._text
    _button = WeeklyBossTask._button
    _story_entry_warning = WeeklyBossTask._story_entry_warning
    _story_entry_confirmation = WeeklyBossTask._story_entry_confirmation
    LIST = WeeklyBossTask.LIST
    TITLE = WeeklyBossTask.TITLE
    SINGLE = WeeklyBossTask.SINGLE
    START = WeeklyBossTask.START
    _selected_reward_interaction = WeeklyBossTask._selected_reward_interaction
    _reward_available = WeeklyBossTask._reward_available
    _seek_reward_interaction = WeeklyBossTask._seek_reward_interaction
    _release_movement = WeeklyBossTask._release_movement
    _claim_confirmation = WeeklyBossTask._claim_confirmation
    _settlement = WeeklyBossTask._settlement
    _leave_settlement = WeeklyBossTask._leave_settlement
    SUCCESS = WeeklyBossTask.SUCCESS
    EXIT = WeeklyBossTask.EXIT
    RETRY = WeeklyBossTask.RETRY
    REWARDS = WeeklyBossTask.REWARDS
    CLAIM_TITLE = WeeklyBossTask.CLAIM_TITLE
    CLAIM_MESSAGE = WeeklyBossTask.CLAIM_MESSAGE
    CLAIM_CONFIRM = WeeklyBossTask.CLAIM_CONFIRM
    CLAIM_CANCEL = WeeklyBossTask.CLAIM_CANCEL
    CLAIM_STAMINA = WeeklyBossTask.CLAIM_STAMINA
    TASK_HINT = WeeklyBossTask.TASK_HINT
    VICTORY = WeeklyBossTask.VICTORY

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = '讨伐强敌'
        self.description = '选择首领关卡和本次领取次数，为每日任务当前账号单独刷取突破材料，共享累计领奖记录。'
        self.visible = True
        self.group_name = None
        self.supported_languages = ['zh_CN']
        self.instructions = '在每日任务选择当前账号，手动登录对应游戏账号；选择首领关卡和本次领取次数后开始。战后检查并吸收声骸，再领取材料奖励；成功领奖才计次，体力不足时结束；计入账号累计，不改每日三目标计划，不自动切换账号。'
        for key in self.default_config.keys() | self.config_type.keys():
            if key not in ('Use Liberation', 'Switch to Healer before and after Combat'):
                self.config_type[key] = {'hidden': True}
        self.default_config.update({'首领关卡': TARGETS_BY_ID['world_crownless'].name, '领取次数': 1})
        self.config_type.update({
            '首领关卡': {'type': 'drop_down', 'options': [target.name for target in WORLD_BOSS_TARGETS]},
            '领取次数': {'min': 1, 'max': 9999},
        })
        self.config_description.update({
            '首领关卡': '本次单独刷取的世界首领；不修改账号每日三目标计划。',
            '领取次数': '本次成功领取奖励的次数，默认1次；实际消耗体力并共享账号累计记录。',
        })
        self._material_target = None
        self._material_progress = None
        self._material_phase = 'idle'
        self._material_retry_plan = None
        self.combat_end_condition = self._material_combat_finished

    def _stage(self, message):
        self.info_set('首领材料阶段', message)
        self.log_info('首领材料：' + message)

    def run(self):
        from src.task.DailyTask import DailyTask
        name = self.config.get('首领关卡')
        boss = next((target.key for target in WORLD_BOSS_TARGETS if target.name == name), None)
        boss, claims = validate_material_request(boss, self.config.get('领取次数'))
        # Executor sleep checks still dispatch to this task during DailyTask navigation.
        self.reset_to_false('material_entry')
        self.skip_combat_check = False
        try:
            return self.get_task_by_class(DailyTask).run_world_boss_material_only(boss, claims)
        finally:
            self.reset_to_false('material_exit')
            self.skip_combat_check = False

    def _current_material_plan(self, read_tasks):
        rows = self.__dict__.get('_material_run_rows')
        return rows if rows is not None else material_plan(read_tasks())

    def on_combat_check(self):
        self.in_realm_check(20)
        return True  # No arbitrary F while the foreground combat owns input.

    def manage_boss_interactions(self):
        if self._in_realm:
            # Challenge entry/retry is already confirmed. FarmEcho's sea-boss
            # menu branch would press Esc while the next enemy is still spawning.
            self._stage('副本等待首领出现，必要时短距离靠近')
            WeeklyBossTask._approach_challenge_enemy(self)
            return
        return super().manage_boss_interactions()

    def _task_hint_phase(self):
        if self._in_realm:
            phase = WeeklyBossTask._task_hint_phase(self)
            if phase:
                return phase
        if self._material_phase in ('post', 'echo', 'reward') and not (
                self.has_target() or self.check_health_bar()):
            return 'post'
        return None

    def handle_claim_button(self):
        if self.has_claim():
            raise CombatStateUnknown('材料领奖界面出现在非领奖阶段，停止消费并保留证据')
        return False

    def _material_combat_finished(self):
        phase = self._task_hint_phase()
        if phase == 'combat' or self.has_target() or self.check_health_bar():
            return False
        return bool(phase == 'post' or self._reward_available() or self.find_treasure_icon()
                    or self.has_claim_stamina() or self._selected_reward_interaction('吸收')
                    or self._button(self.VICTORY, '挑战成功'))

    def _wait_material_post_combat(self, result):
        if not result.combat_entered:
            raise CombatStateUnknown('材料战斗未确认进入，不执行吸收或领取')
        previous = self.__dict__.get('skip_combat_check', False)
        self.skip_combat_check = True
        confirmed = 0
        def read():
            nonlocal confirmed
            self.next_frame()
            if not self.in_team_and_world():
                confirmed = 0
                return None
            if self.has_target() or self.check_health_bar():
                return 'combat'
            # Like weekly challenges, a remaining fight objective forbids handing off mid-phase.
            ready = self._task_hint_phase() != 'combat' and (
                self._material_combat_finished() or self.is_expected_combat_end())
            confirmed = confirmed + 1 if ready else 0
            return 'post' if confirmed >= 2 else None
        try:
            phase = self.wait_until(read, time_out=30, raise_if_not_found=False)
            if not phase:
                raise CombatStateUnknown('材料战后阶段未确认，不执行吸收或领取')
            if phase == 'combat':
                self._stage('敌人仍在或进入下一阶段，继续战斗')
                return False
            self.reset_to_false('material combat returned; verify reward')
            self._material_phase = 'post'
            self._stage('战斗结束，开始检查声骸和领取奖励')
            return True
        finally:
            self.skip_combat_check = previous

    def pick_echo(self):
        # The shared YOLO/walk helpers may encounter reward F prompts on the way.
        if self.has_claim() or self.has_claim_stamina():
            raise CombatStateUnknown('声骸吸收阶段出现领奖页面，未点击任何消费按钮')
        if not self._selected_reward_interaction('吸收'):
            if not self.find_f_with_text(target_text=re.compile(r'^吸收$')):
                return False
            self.next_frame()  # A scroll result alone does not prove the selected interaction.
            if not self._selected_reward_interaction('吸收'):
                return False
        self._release_movement()
        self.send_key('f', after_sleep=.6)
        self.next_frame()
        if self.has_claim() or self.has_claim_stamina():
            raise CombatStateUnknown('吸收后出现未确认的领奖页面，未执行消费')
        return not self._selected_reward_interaction('吸收')

    def pick_f(self, handle_claim=True):
        if self._material_phase == 'echo':
            return self.pick_echo()
        return super().pick_f(handle_claim=handle_claim)

    def _collect_material_echo(self, guard):
        guard()
        self._material_phase = 'echo'
        self._stage('检查声骸掉落并吸收')
        try:
            picked = self.pickup_dropped_echo()
            self._stage('声骸已吸收，继续领取材料奖励' if picked else '未找到可吸收声骸，继续领取材料奖励')
            return picked
        finally:
            self._release_movement()

    def select_configured_boss(self, serial_number, total_number):
        target = self._material_target
        return WeeklyBossTask._select_target(self, target,
            button_match=lambda boxes: material_target_button(boxes, target, self.height),
            title_match=lambda text: matches_target(text, target),
            open_target=self._open_material_target, label='首领材料')

    def _open_material_target(self, target, button):
        def match_button(boxes):
            current = material_target_button(boxes, target, self.height)
            return current if current and compact(current.name) == compact(button.name) else None
        if compact(button.name) == '直接挑战':
            WeeklyBossTask._open_weekly_target(self, target, button_match=match_button,
                title_match=lambda text: matches_target(text, target), label='首领材料',
                formation_ready=self._material_formation_ready)
            return True
        self.navigate_ui('首领材料前往地图',
            lambda frame: match_button(self._ocr(self.LIST, frame)), self._travel_button,
            identity=target.key)
        return False

    def _material_formation_ready(self, frame):
        # A start label alone cannot prove this is the challenge formation.
        return bool(self._button(self.START, '开启挑战', frame)
                    and self._button((.62, .864, .76, .95), '快速编队', frame))

    def teleport_to_configured_boss(self):
        self.openF2Book('gray_book_boss')
        self.open_boss_book('qiangdi')
        is_team = self.select_configured_boss(None, None)
        if is_team:
            target = self._material_target
            WeeklyBossTask._enter_challenge(self, target,
                title_match=lambda text: matches_target(text, target), label='首领材料')
        else:
            self.wait_click_travel()
            self.wait_in_team_and_world(time_out=120)
        self.sleep(2)
        return is_team

    def _resources_for_claim(self, cost, activity_ready, used_stamina):
        self.openF2Book('gray_book_boss')
        budget = self.daily_stamina_budget(activity_ready, cost, used_stamina)
        before = self.get_verified_stamina()
        balance = self.prepare_daily_stamina(cost, budget)
        if before[0] < cost:
            self._material_reenter = True
        self._material_balance = balance
        return balance[0] >= cost

    def _read_claim_cost(self):
        # Require the actual single-claim dialog. Reward quantities are never read.
        if not self.has_claim_stamina():
            return None
        boxes = self.ocr(.2, .30, .5, .72)
        costs = set()
        for box in boxes:
            text = compact(box.name)
            match = re.fullmatch(r'(?:领取奖励需消耗|消耗|消耗结晶波片|消耗結晶波片)[:：]?(\d{1,3})(?:结晶波片|結晶波片)?', text)
            if not match:
                match = re.fullmatch(r'[xX×](\d{1,3})', text)
            if match:
                costs.add(int(match[1]))
        return costs.pop() if len(costs) == 1 else None

    def _claim_dialog(self):
        single = self._claim_confirmation()
        if single:
            return 'confirm', single
        cost = self._read_claim_cost()
        return ('selection', (cost,)) if cost is not None else None

    def _material_settlement_stamina(self):
        previous = None
        def read():
            nonlocal previous
            current = self.get_settlement_stamina()
            stable = current >= 0 and current == previous
            previous = current
            return (current,) if stable else None  # Zero is a valid observed balance.
        observed = self.wait_until(read, time_out=6, raise_if_not_found=False)
        return observed[0] if observed else None

    def _claim_material_reward(self, read_tasks, guard, activity_ready, used_stamina):
        self._material_phase = 'reward'
        self._stage('寻找领取奖励入口')
        self._seek_reward_interaction()
        guard()
        rows = self._current_material_plan(read_tasks)
        choice = choose_material_target(rows, self._material_progress.counts())
        if not choice or choice[0] != self._material_target.key:
            self._stage('目标已修改，未执行领取')
            return None
        # Begin before F: a changed layout must not trigger an unjournaled claim.
        revision = material_plan_revision(rows)
        event = self._material_progress.begin(choice[0], self._material_target.cost, revision)
        self.send_key('f', after_sleep=.6)
        previous = None
        dialog_seen = False
        retries = 0
        last_input = time.monotonic()
        def stable_dialog():
            nonlocal previous, dialog_seen, retries, last_input
            dialog = self._claim_dialog()
            dialog_seen = dialog_seen or bool(dialog) or self.has_claim() or self.has_claim_stamina() or (
                compact(self._text(self.CLAIM_TITLE)) == '领取奖励')
            if not dialog_seen and retries < 2 and time.monotonic() - last_input >= 3:
                self.next_frame()
                if self.in_team_and_world() and self._reward_available():
                    self.send_key('f', after_sleep=.6)
                    retries += 1
                    last_input = time.monotonic()
                    self._stage(f'领奖入口仍在，重试交互 {retries}/2；未重复费用确认')
            identity = (dialog[0], dialog[1][:2]) if dialog else None
            stable = identity is not None and identity == previous
            previous = identity
            return dialog if stable else None
        dialog = self.wait_until(stable_dialog, time_out=20, raise_if_not_found=False)
        if not dialog:
            raise CombatStateUnknown('材料领奖界面未确认，保留待核验记录')
        shape, values = dialog
        actual_cost = values[0]
        if actual_cost != self._material_target.cost:
            raise CombatStateUnknown(f'材料单次费用未确认：{actual_cost}，未点击领取')
        guard()
        latest = choose_material_target(self._current_material_plan(read_tasks), self._material_progress.counts())
        if not latest or latest[0] != choice[0]:
            self.back(after_sleep=.5)
            self._material_progress.resolve(event, False)
            return None
        self._stage(f'{self._material_target.name} 单次领取，费用 {actual_cost}')
        budget = self.daily_stamina_budget(activity_ready, actual_cost, used_stamina)
        current_dialog = self._claim_dialog()
        if not current_dialog or current_dialog[0] != shape or current_dialog[1][0] != actual_cost:
            raise CombatStateUnknown('材料确认前领奖界面变化，未点击领取')
        values = current_dialog[1]
        # This shared reader confirms the actual debit, not a guessed drop count.
        if shape == 'selection':
            _, used = self.use_stamina(once=actual_cost, must_use=budget, allow_backup=False, max_claims=1)
        else:
            _, current, button = values
            if current < actual_cost:
                self.back(after_sleep=.5)
                self._material_progress.resolve(event, False)
                return 0
            reserve = self._material_balance[1]
            before = (current, reserve, current + reserve)
            self.click_box(button)
            if not self.wait_until(lambda: self._claim_confirmation() is None, time_out=8, raise_if_not_found=False):
                raise CombatStateUnknown('材料确认弹窗未结束，禁止重复确认')
            self._confirm_stamina_used(before[2], actual_cost, before_balance=before)
            policy = getattr(self.executor, '_daily_reserve_policy', None)
            if policy:
                policy.spend(actual_cost)
            used = actual_cost
        if used == 0:
            self._material_progress.resolve(event, False)
            return 0
        if used != actual_cost:
            raise CombatStateUnknown('材料领取消耗不符合单次费用，保留待核验记录')
        self._material_progress.resolve(event, True)
        self._stage(f'领取已保存：{self._material_target.name}，累计 {self._material_progress.counts()[choice[0]]}；事件 {event}')
        try:
            self.screenshot('material_reward_confirmed')
        except (TaskDisabledException, FinishedException):
            raise
        except Exception as error:
            self.log_warning(f'材料领奖已保存，证据截图失败：{error}')
        self._has_treasure = True
        self._material_phase = 'idle'
        if self._in_realm:
            self._stage('材料领取已保存，等待结算页决定重新挑战或退出')
            if not self.wait_until(self._settlement, time_out=20, raise_if_not_found=False):
                raise CombatStateUnknown('材料领取已保存，但结算页未确认；未重复领取')
            remaining = self._material_settlement_stamina()
            guard()
            current_rows = self._current_material_plan(read_tasks)
            next_target = choose_material_target(current_rows, self._material_progress.counts())
            policy = getattr(self.executor, '_daily_reserve_policy', None)
            retry = bool(next_target and next_target[0] == choice[0]
                         and material_plan_revision(current_rows) == revision
                         and remaining is not None and remaining >= actual_cost
                         and not getattr(policy, 'refresh_required', False)
                         and not getattr(policy, 'pending_conversion', False))
            self._stage(f'结算剩余体力 {remaining}；' + ('同一目标仍需领取，重新挑战' if retry else '退出副本复核目标与体力'))
            self._leave_settlement(retry)
            if retry:
                reserve = self._material_balance[1]
                self._material_balance = (remaining, reserve, remaining + reserve)
                self._material_retry_plan = (choice[0], revision)
                self._material_reenter = self._has_treasure = False
                self._just_entered_boss_realm = True
                return used
        self._material_retry_plan = None
        # Close any generic reward view before the next guidebook/resource check.
        self.ensure_main(time_out=60)
        self._material_reenter = self._in_realm
        return used

    def run_for_profile(self, profile_id, read_tasks, guard, service, *, activity_ready, used_stamina, request=None, progress=None):
        if request is not None:
            boss, claims = validate_material_request(*request)
        progress = progress if progress is not None else WorldBossMaterialProgress(service, profile_id)
        if progress.pending():
            raise RuntimeError('有首领材料领奖待核验，请在账号设置中核对；未继续消费')
        claimed, spent, current_target = 0, 0, None
        self._material_progress = progress
        # Freeze a one-run cumulative threshold, including counts above the account UI's 9999 cap.
        # Every claim reuses the same scheduler and durable per-account ledger.
        self._material_run_rows = ([{'boss': boss, 'limit': progress.counts().get(boss, 0) + claims}]
                                   if request is not None else None)
        original_config = self.config
        original_liberation = self.use_liberation
        self.config = deepcopy(dict(original_config))
        self.use_liberation = self.config.get('Use Liberation', True)
        self._material_reenter = False
        self._material_retry_plan = None
        self._in_realm = self._just_entered_boss_realm = self._has_treasure = False
        self.reset_to_false('material_profile_entry')
        self.skip_combat_check = False
        try:
            while True:
                guard()
                rows = self._current_material_plan(read_tasks)
                choice = choose_material_target(rows, progress.counts())
                if self._material_retry_plan is not None and (
                        not choice or (choice[0], material_plan_revision(rows)) != self._material_retry_plan):
                    raise CombatStateUnknown('重新挑战后材料目标或计划变化，不继续战斗或领取')
                if not choice:
                    enabled = any(row['boss'] != 'none' and row['limit'] > 0 for row in rows)
                    return MaterialRunResult(claimed, spent, 'complete' if enabled else 'plan_disabled')
                self._material_target = TARGETS_BY_ID[choice[0]]
                self._stage(f'{self._material_target.name}：还需 {choice[1]} 次')
                consumed = None if used_stamina is None else used_stamina + spent
                if self._material_retry_plan is None and not self._resources_for_claim(
                        self._material_target.cost, activity_ready, consumed):
                    return MaterialRunResult(claimed, spent, 'resource_shortfall')
                if self._material_reenter:
                    current_target = None
                    self._material_reenter = False
                if current_target != choice[0]:
                    self.config['Teleport to Boss'] = 'Boss Challenge'
                    self.config['Boss'] = self._material_target.farm_profile
                    self._farm_start_time = time.time()
                    self.is_revived = False
                    self.aim_boss = None
                    self.manage_boss_parameters()
                    self.teleport_to_configured_boss_and_prepare()
                    current_target = choice[0]
                self._material_phase = 'combat'
                result = self.farm_cycle(pickup_echo=False)
                if result.revived:
                    continue
                if not self._wait_material_post_combat(result):
                    continue
                self._collect_material_echo(guard)
                self.next_frame()
                if self.has_target() or self.check_health_bar() or self._task_hint_phase() == 'combat':
                    continue
                used = self._claim_material_reward(read_tasks, guard, activity_ready, consumed)
                if used is None:
                    current_target = None
                    continue
                if not used:
                    return MaterialRunResult(claimed, spent, 'resource_shortfall')
                claimed += 1
                spent += used
        finally:
            try:
                self._release_combat_inputs()
            finally:
                self.config = original_config
                self.use_liberation = original_liberation
                self._material_target = self._material_progress = None
                self._material_run_rows = None
                self._material_retry_plan = None
                self._material_phase = 'idle'
                self._material_balance = None
                self._material_reenter = False
                self.reset_to_false('material_profile_exit')
                self.skip_combat_check = False
