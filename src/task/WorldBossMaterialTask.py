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
from src.task.world_boss_materials import TARGETS_BY_ID, material_target_button, matches_health_title
from src.task.world_boss_material_plan import material_plan, choose_material_target, material_plan_revision
from src.task.world_boss_material_progress import WorldBossMaterialProgress
from src.task.weekly_boss import compact


@dataclass(frozen=True)
class MaterialRunResult:
    claimed: int
    spent: int
    status: str


class WorldBossMaterialTask(FarmEchoTask):
    # Reuse the weekly claim's selected-F detector and bounded reward approach.
    _ocr = WeeklyBossTask._ocr
    _text = WeeklyBossTask._text
    _button = WeeklyBossTask._button
    _selected_reward_interaction = WeeklyBossTask._selected_reward_interaction
    _reward_available = WeeklyBossTask._reward_available
    _seek_reward_interaction = WeeklyBossTask._seek_reward_interaction
    _release_movement = WeeklyBossTask._release_movement
    _claim_confirmation = WeeklyBossTask._claim_confirmation
    CLAIM_TITLE = WeeklyBossTask.CLAIM_TITLE
    CLAIM_MESSAGE = WeeklyBossTask.CLAIM_MESSAGE
    CLAIM_CONFIRM = WeeklyBossTask.CLAIM_CONFIRM
    CLAIM_CANCEL = WeeklyBossTask.CLAIM_CANCEL
    CLAIM_STAMINA = WeeklyBossTask.CLAIM_STAMINA

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = '世界首领突破材料'
        self.description = '累计领奖达到账号目标后，继续账号原有体力用途。'
        self.visible = False
        self.supported_languages = ['zh_CN']
        self._material_target = None
        self._material_progress = None
        self._material_phase = 'idle'
        self._material_name_verified = False
        self.combat_end_condition = self._material_combat_finished

    def _stage(self, message):
        self.info_set('首领材料阶段', message)
        self.log_info('首领材料：' + message)

    def run(self):
        raise RuntimeError('请通过已核验账号的每日任务执行首领材料')

    def on_combat_check(self):
        self.in_realm_check(20)
        return True  # No arbitrary F while the foreground combat owns input.

    def perform_combat_rotation(self):
        if not self._material_name_verified:
            self._verify_material_boss_title()
        return super().perform_combat_rotation()

    def _task_hint_phase(self):
        return 'post' if not self.has_target() and not self.check_health_bar() else None

    def handle_claim_button(self):
        if self.has_claim():
            raise CombatStateUnknown('材料领奖界面出现在非领奖阶段，停止消费并保留证据')
        return False

    def _material_combat_finished(self):
        return not self.has_target() and not self.check_health_bar() and bool(
            self._reward_available() or self.find_treasure_icon() or self.has_claim_stamina())

    def select_configured_boss(self, serial_number, total_number):
        self._stage('按名称查找讨伐强敌：' + self._material_target.name)
        self.scroll_relative(.92, .5, 30)
        self.sleep(.6)
        previous, stable = None, 0
        for _ in range(18):
            self.next_frame()
            boxes = self.ocr(.365, .25, .965, .89)
            button = material_target_button(boxes, self._material_target, self.height)
            if button:
                self.sleep(.25)
                self.next_frame()
                button = material_target_button(self.ocr(.365, .25, .965, .89), self._material_target, self.height)
                if button is None:
                    continue
                is_team = compact(button.name) == '直接挑战'
                self.click_box(button, after_sleep=1)
                return is_team
            signature = tuple(compact(b.name) for b in boxes)
            stable = stable + 1 if signature and signature == previous else 0
            if stable >= 2:
                break
            previous = signature
            self.scroll_relative(.92, .5, -3)
            self.sleep(.6)
        self.screenshot('material_boss_not_found')
        raise RuntimeError('未在讨伐强敌中确认目标：' + self._material_target.name)

    def check_boss_name(self):
        if self._material_name_verified or not (self.has_target() or self.check_health_bar()):
            return
        self._verify_material_boss_title()

    def _verify_material_boss_title(self):
        target = self._material_target
        def found():
            self.next_frame()
            boxes = self.ocr(.15, .0, .85, .10)
            return any(matches_health_title(box.name, target) for box in boxes)
        if not self.wait_until(found, time_out=5, raise_if_not_found=False):
            raise CombatStateUnknown('首领血条名称未确认，停止材料战斗')
        self._material_name_verified = True
        self.aim_boss = target.name

    def _resources_for_claim(self, cost, activity_ready, used_stamina):
        self.openF2Book('gray_book_boss')
        budget = self.daily_stamina_budget(activity_ready, cost, used_stamina)
        balance = self.prepare_daily_reserve(cost, budget)
        self.back(after_sleep=.5)
        policy = getattr(self.executor, '_daily_reserve_policy', None)
        if balance[0] < cost and policy and callable(policy.refresh):
            policy.refresh()
            self._material_reenter = True
            self.openF2Book('gray_book_boss')
            ready = policy.activity_ready
            balance = self.prepare_daily_reserve(cost, self.daily_stamina_budget(ready, cost, used_stamina))
            self.back(after_sleep=.5)
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

    def _claim_material_reward(self, read_tasks, guard, activity_ready, used_stamina):
        self._material_phase = 'reward'
        self._stage('寻找领取奖励入口')
        self._seek_reward_interaction()
        guard()
        rows = material_plan(read_tasks())
        choice = choose_material_target(rows, self._material_progress.counts())
        if not choice or choice[0] != self._material_target.key:
            self._stage('目标已修改，未执行领取')
            return None
        # Begin before F: a changed layout must not trigger an unjournaled claim.
        event = self._material_progress.begin(choice[0], self._material_target.cost, material_plan_revision(rows))
        self.send_key('f', after_sleep=.6)
        previous = None
        def stable_dialog():
            nonlocal previous
            dialog = self._claim_dialog()
            identity = (dialog[0], dialog[1][:2]) if dialog else None
            stable = identity is not None and identity == previous
            previous = identity
            return dialog if stable else None
        dialog = self.wait_until(stable_dialog, time_out=8, raise_if_not_found=False)
        if not dialog:
            raise CombatStateUnknown('材料领奖界面未确认，保留待核验记录')
        shape, values = dialog
        actual_cost = values[0]
        if actual_cost != self._material_target.cost:
            raise CombatStateUnknown(f'材料单次费用未确认：{actual_cost}，未点击领取')
        guard()
        latest = choose_material_target(material_plan(read_tasks()), self._material_progress.counts())
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
        # Close any generic reward view before the next guidebook/resource check.
        self.ensure_main(time_out=60)
        self._material_reenter = self._in_realm
        return used

    def run_for_profile(self, profile_id, read_tasks, guard, service, *, activity_ready, used_stamina):
        progress = WorldBossMaterialProgress(service, profile_id)
        if progress.pending():
            raise RuntimeError('有首领材料领奖待核验，请在账号设置中核对；未继续消费')
        claimed, spent, current_target = 0, 0, None
        self._material_progress = progress
        original_config = self.config
        original_liberation = self.use_liberation
        self.config = deepcopy(dict(original_config))
        self.use_liberation = self.config.get('Use Liberation', True)
        self._material_reenter = False
        self._in_realm = self._just_entered_boss_realm = self._has_treasure = False
        self._in_combat = False
        self.target_loss_started_at = None
        try:
            while True:
                guard()
                rows = material_plan(read_tasks())
                choice = choose_material_target(rows, progress.counts())
                if not choice:
                    enabled = any(row['boss'] != 'none' and row['limit'] > 0 for row in rows)
                    return MaterialRunResult(claimed, spent, 'complete' if enabled else 'plan_disabled')
                self._material_target = TARGETS_BY_ID[choice[0]]
                self._stage(f'{self._material_target.name}：还需 {choice[1]} 次')
                consumed = None if used_stamina is None else used_stamina + spent
                if not self._resources_for_claim(self._material_target.cost, activity_ready, consumed):
                    return MaterialRunResult(claimed, spent, 'resource_shortfall')
                if self._material_reenter:
                    current_target = None
                    self._material_reenter = False
                if current_target != choice[0]:
                    self.config['Teleport to Boss'] = 'Boss Challenge'
                    self.config['Boss'] = self._material_target.farm_profile
                    self._farm_start_time = time.time()
                    self.is_revived = False
                    self._material_name_verified = False
                    self.aim_boss = None
                    self.manage_boss_parameters()
                    self.teleport_to_configured_boss_and_prepare()
                    current_target = choice[0]
                self._material_phase = 'combat'
                self._material_name_verified = False
                result = self.farm_cycle(pickup_echo=False)
                if result.revived:
                    continue
                self.next_frame()
                if not self._material_name_verified or not self._material_combat_finished():
                    raise CombatStateUnknown('材料战斗未确认结束，不执行领取')
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
                self._material_phase = 'idle'
                self._material_balance = None
                self._material_name_verified = self._material_reenter = False
