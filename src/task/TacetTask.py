
import time

from ok import Logger
from src.task.BaseCombatTask import BaseCombatTask, CharRevivedException, CombatStateUnknown
from src.task.WWOneTimeTask import WWOneTimeTask
from src.task.tacet_targets import TACET_STRUCTURE, TACET_NAMES, TACET_OPTIONS, TACET_BUTTON_LABELS, tacet_serial
from src.task.ui_transition import TargetUnavailable

logger = Logger.get_logger(__name__)


class TacetTask(WWOneTimeTask, BaseCombatTask):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.description = "Farms the selected Tacet Suppression, until no stamina. Must be able to teleport (F2)."
        self.name = "🌊 Tacet Suppression"
        self.support_schedule_task = True
        default_config = {
            'Which Tacet Suppression to Farm': 1,  # starts with 1
        }
        self.structure = list(TACET_STRUCTURE)
        self.total_number = sum(self.structure)
        self.target_enemy_time_out = 10
        default_config.update(self.default_config)
        self.config_description = {
            'Which Tacet Suppression to Farm': 'Select a Tacet Field. Existing choices keep their locations after list updates.',
        }
        self.default_config = default_config
        self.config_type['Which Tacet Suppression to Farm'] = {
            'type': 'integer_drop_down', 'options': TACET_OPTIONS,
        }
        self.door_walk_method = {  # starts with 0
            0: [],
            1: [],
            2: [],
            3: [],
            4: [],
            5: [],
            6: [],
            7: [["a", 0.3]],
            8: [["d", 0.6]],
            9: [["a", 1.5], ["w", 3], ["a", 2.5]],
        }
        self.stamina_once = 60
        # 精简版：无音区已融入每日任务模块，不在任务列表单独显示
        self.visible = False

    def run(self):
        super().run()
        self.ensure_main(time_out=180)
        self.wait_in_team_and_world(esc=True)
        self.farm_tacet()

    def farm_tacet(self, daily=False, used_stamina=0, config=None, activity_ready=False, stamina_budget=None):
        if config is None:
            config = self.config
        target_id = config.get('Which Tacet Suppression to Farm', 1)
        tacet_serial(target_id)
        must_use = self.daily_stamina_budget(activity_ready, self.stamina_once, used_stamina) if daily else 0
        if stamina_budget is not None:
            if stamina_budget < self.stamina_once:
                return
            must_use = stamina_budget - stamina_budget % self.stamina_once
        allow_backup = False
        backup_policy_decided = not daily
        self.info_incr('used stamina', 0)
        while True:
            self.sleep(1)
            self.openF2Book("gray_book_boss")
            current, back_up, total = self.get_verified_stamina()
            if daily and current < self.stamina_once and must_use > 0:
                current, back_up, total = self.prepare_daily_reserve(self.stamina_once, must_use)
            if not backup_policy_decided:
                allow_backup = self.should_use_backup_stamina(
                    activity_ready, current, back_up, must_use)
                backup_policy_decided = True
                self.log_info(
                    f'每日体力策略：current={current}, backup={back_up}, budget={must_use}, '
                    f'allow_backup={allow_backup}')
            available = current if daily else (total if allow_backup else current)
            if available < self.stamina_once:
                self._note_daily_resource_shortfall(total, max(self.stamina_once, must_use))
                return self.not_enough_stamina()

            self.open_boss_book('wuyin')
            index = target_id - 1
            self.teleport_to_tacet(index)
            self.click_team_challenge()
            self._tacet_retry_pending = False
            while True:
                stage = self._wait_tacet_combat_or_reward()
                if stage == 'combat':
                    self.combat_once(target=True)
                if not self.has_claim_stamina():
                    self.walk_to_treasure()
                    self.pick_f(handle_claim=False)
                self.sleep(2)
                if not self.has_claim_stamina():
                    self.screenshot('tacet_claim_unconfirmed', frame=self.frame)
                    raise CombatStateUnknown('无音区领奖入口未确认，保留现场，不重新开启挑战')
                policy = getattr(self.executor, '_daily_reserve_policy', None)
                if policy is not None:
                    policy.observe(None)
                can_continue, used = self.use_stamina(
                    once=self.stamina_once, must_use=must_use, allow_backup=allow_backup)
                self.info_incr('used stamina', used)
                self.sleep(4)
                if not can_continue:
                    self.click_relative(0.365, 0.853, hcenter=True)
                    self._leave_tacet_after_claim()
                    return None
                else:
                    self._tacet_retry_pending = True
                    self.click_relative(0.640, 0.851, hcenter=True, after_sleep=0.2)
                    self.wait_click_skip_dialog_confirm()
                must_use -= used

    def _wait_tacet_combat_or_reward(self):
        """Inspect the current challenge before requiring an open-world HUD."""
        deadline = time.monotonic() + 35
        retries = 0
        victory_seen = False
        while time.monotonic() < deadline:
            self.executor.check_enabled()
            self.next_frame()
            if self.has_claim_stamina():
                return 'claim'
            failed = self.recover_failed_challenge()
            if failed is not None:
                raise CombatStateUnknown('无音区挑战失败，已退出并保留补跑' if failed else
                                         '无音区挑战失败页无法确认退出，保留现场')
            if self.get_settlement_stamina() >= 0:
                if not self._tacet_retry_pending or retries >= 2:
                    self.screenshot('tacet_settlement_pending', frame=self.frame)
                    raise CombatStateUnknown('无音区停在结算页，领奖或重试状态待核验')
                retries += 1
                self.click_relative(0.640, 0.851, hcenter=True, after_sleep=0.2)
                continue
            if self.find_f_with_claim_text() or self.find_treasure_icon():
                return 'treasure'
            victory_seen = victory_seen or self.has_challenge_success()
            if not victory_seen and self.in_team_and_world():
                self._tacet_retry_pending = False
                return 'combat'
            self.sleep(.3)
        self.screenshot('tacet_scene_unconfirmed', frame=self.frame)
        raise CombatStateUnknown('无音区成功动画或加载页面未进入可确认状态，保留现场')

    def _leave_tacet_after_claim(self):
        for _ in range(3):
            if self.wait_in_team_and_world(time_out=15, raise_if_not_found=False):
                self.refresh_daily_reserve_after_exit()
                return
            if self.get_settlement_stamina() < 0:
                break
            self.click_relative(0.365, 0.853, hcenter=True)
        self.screenshot('tacet_exit_unconfirmed', frame=self.frame)
        raise CombatStateUnknown('无音区已确认领奖，但退出结算页未确认；保留现场')

    def not_enough_stamina(self, back=True):
        self.log_info(f"used all stamina")
        if back:
            self.back(after_sleep=1)

    def teleport_to_tacet(self, index):
        if type(index) is not int:
            raise ValueError('请选择有效的无音区目标')
        self.info_set('Teleport to Tacet Suppression', index)
        target_id = index + 1
        serial = tacet_serial(target_id)
        name = TACET_NAMES.get(target_id) if self.game_lang == 'zh_CN' else None
        self.log_info(f'无音区目标：保存值={target_id}，当前列表第{serial}项，名称={name or "按列表位置"}')
        self.scroll_relative(.75, .5, 30)
        self.sleep(.5)
        try:
            is_team = self.click_on_book_target(serial, self.total_number, self.structure,
                target_name=name, button_labels=TACET_BUTTON_LABELS)
        except TargetUnavailable:
            self.screenshot('tacet_target_unavailable')
            raise
        if not is_team:
            self.wait_click_travel()
            self.walk_until_f(time_out=10, backward_time=0, raise_if_not_found=True)
            self.pick_f(handle_claim=False)
        return True
