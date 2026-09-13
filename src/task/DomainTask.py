import re
import time


from ok import Logger, WaitFailedException, TaskDisabledException
from src.runtime.game_runtime_errors import FrameUnavailable, GameProcessLost
from src.config_integrity import ConfigIntegrityBlocked, ConfigWriteBlocked
from src.task.BaseCombatTask import BaseCombatTask, CombatStateUnknown, CharDeadException
from src.task.WWOneTimeTask import WWOneTimeTask

logger = Logger.get_logger(__name__)


class DomainTask(WWOneTimeTask, BaseCombatTask):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.teleport_timeout = 100
        self.stamina_once = 0

    def revive_action(self):
        """副本内死亡恢复：关闭弹窗 → 退出副本 → 传最近传送点回血。"""

        # ① 关闭复活弹窗 (点按钮优先, esc 兜底, 与 BaseCombatTask 共用)
        self.close_revive_popup()

        # ② 打开退出菜单
        self.send_key('esc')
        self.sleep(1)

        # ③ 确认离开
        self.wait_click_feature('gray_confirm_exit_button',
                                relative_x=-1, raise_if_not_found=False,
                                time_out=3, click_after_delay=0.5, threshold=0.7)

        # ④ 必须确认已回到大世界队伍态后，再继续走 F2/传送流程
        if not self.wait_in_team_and_world(time_out=max(self.teleport_timeout, 120), raise_if_not_found=False):
            return False
        self.sleep(0.5)
        self.revive_at_tower_and_heal()
        return True

    def make_sure_in_world(self):
        if self.in_realm():
            self.send_key('esc', after_sleep=1)
            self.wait_click_feature('gray_confirm_exit_button', relative_x=-1, raise_if_not_found=False,
                                    time_out=3, click_after_delay=0.5, threshold=0.7, after_sleep=1)
            self.wait_in_team_and_world(time_out=self.teleport_timeout)
        else:
            self.ensure_main()

    def open_F2_book_and_get_stamina(self):
        self.openF2Book('gray_book_boss')
        return self.get_stamina()

    def farm_domain_with_recovery_loop(self, must_use, teleport_into_domain_once,
                                       activity_ready=None, stamina_budget=0, max_recovery_retries=3,
                                       max_entry_retries=1):
        """包装副本刷取循环：死亡恢复后自动从 F2 重新进入，并限制重试次数。"""
        recovery_retries = 0
        entry_retries = 0
        allow_backup = False
        backup_policy_decided = activity_ready is None
        while True:
            current, back_up, total = self.open_F2_book_and_get_stamina()
            if not backup_policy_decided:
                allow_backup = self.should_use_backup_stamina(
                    activity_ready, current, back_up, stamina_budget)
                backup_policy_decided = True
                self.log_info(
                    f'每日体力策略：current={current}, backup={back_up}, budget={stamina_budget}, '
                    f'allow_backup={allow_backup}')
            available = total if allow_backup else current
            if available < self.stamina_once:
                self.log_info('not enough stamina', notify=True)
                self.back()
                return
            try:
                teleport_into_domain_once()
            except WaitFailedException as error:
                frame = self.require_game_frame()
                self.screenshot('domain_entry_unknown', frame=frame)
                if entry_retries >= max_entry_retries:
                    raise CombatStateUnknown(
                        f'领域进入状态连续超时，已安全恢复 {entry_retries} 次') from error
                entry_retries += 1
                self.log_warning(
                    f'领域进入状态超时，恢复大世界后重试 ({entry_retries}/{max_entry_retries})')
                self.ensure_main(time_out=120)
                continue
            entry_retries = 0
            self.sleep(1)
            finished, must_use = self.farm_in_domain(must_use=must_use, allow_backup=allow_backup)
            if finished:
                return
            recovery_retries += 1
            if recovery_retries >= max_recovery_retries:
                self.log_info(f'farm_domain: exceeded recovery retries ({max_recovery_retries}), stop farming',
                              notify=True)
                self.make_sure_in_world()
                raise CombatStateUnknown('领域死亡恢复次数已耗尽')
            self.log_info('farm_domain: death recovered, re-enter from F2 book')
            self.sleep(1)

    def farm_in_domain(self, must_use=0, allow_backup=True):
        """刷本循环；返回 (是否整段正常结束, 剩余 must_use)。

        第二项在死亡提前退出时仍会带上本局内已扣过的额度，供外层恢复循环继续传参。
        """
        if self.stamina_once <= 0:
            raise RuntimeError('"self.stamina_once" must be override')
        self.info_incr('used stamina', 0)
        while True:
            self.walk_until_f(time_out=4, backward_time=0, raise_if_not_found=True)
            self.pick_f()
            try:
                state = self._finish_domain_combat()
                if state == 'treasure':
                    try:
                        self.walk_to_treasure()
                    except WaitFailedException:
                        if self._domain_reward_state() != 'claim':
                            raise
                    if self._domain_reward_state() != 'claim':
                        self.pick_f(handle_claim=False)
                if not self.wait_until(self.has_claim_stamina, time_out=3, raise_if_not_found=False):
                    raise CombatStateUnknown('未确认领域领取界面，停止领奖')
            except CharDeadException:
                self.log_info('farm_in_domain: death recovered, exiting domain')
                self.make_sure_in_world()
                return False, must_use
            planner = getattr(self, 'material_planner', None)
            policy = getattr(self.executor, '_daily_reserve_policy', None)
            if policy is not None:
                # Combat can itself complete an activity objective. A pre-combat
                # reading cannot authorize reserve even if less than 30s old.
                policy.observe(None)
            if planner:
                planner.begin_claim()
            try:
                options = {'max_claims': planner.max_claims} if planner else {}
                can_continue, used = self.use_stamina(
                    once=self.stamina_once, must_use=must_use, allow_backup=allow_backup, **options)
                if planner:
                    planner.collect_claim(used)
                    can_continue = False  # Refresh cultivation counts before spending again.
            except (TaskDisabledException, FrameUnavailable, GameProcessLost, ConfigIntegrityBlocked, ConfigWriteBlocked):
                raise
            except Exception:
                if planner:
                    try:
                        planner.capture_failure()
                    except Exception as evidence_error:
                        self.log_warning(f'收益补充截图失败，领取意图仍保留：{evidence_error}')
                raise
            self.info_incr('used stamina', used)
            must_use -= used
            self.sleep(4)
            if not can_continue:
                self.log_info("used all stamina")
                break
            self.click(0.68, 0.84, after_sleep=1)  # farm again
            if confirm := self.wait_feature(
                    ['confirm_btn_hcenter_vcenter', 'confirm_btn_highlight_hcenter_vcenter'],
                    raise_if_not_found=False,
                    threshold=0.6,
                    time_out=2):
                self.click(0.49, 0.55, after_sleep=0.5)  # 点击不再提醒
                self.click(confirm, after_sleep=0.5)
                self.wait_click_feature(
                    ['confirm_btn_hcenter_vcenter', 'confirm_btn_highlight_hcenter_vcenter'],
                    relative_x=-1, raise_if_not_found=False,
                    threshold=0.6,
                    time_out=1)
            self.wait_in_team_and_world(time_out=self.teleport_timeout)
            self.sleep(1)
        #
        self.click(0.42, 0.84, after_sleep=2)  # back to world
        self.make_sure_in_world()
        self.refresh_daily_reserve_after_exit()
        return True, must_use

    def _domain_reward_state(self):
        # Absence of enemies is not proof of completion. Positive reward evidence is required.
        if self.has_target() or self.check_health_bar():
            return 'combat'
        if self.has_claim_stamina():
            return 'claim'
        if self.find_f_with_claim_text() or self.find_treasure_icon():
            return 'treasure'
        return 'unknown'

    def _domain_combat_finished(self):
        return self._domain_reward_state() in ('claim', 'treasure')

    def _finish_domain_combat(self):
        for attempt in range(2):
            try:
                self.combat_once(**({'wait_combat_time': 3} if attempt else {}))
            except CombatStateUnknown as error:
                self.log_warning(f'领域战斗状态异常，重新核对当前画面：{error}')
            deadline = time.monotonic() + 5
            state = 'unknown'
            while time.monotonic() < deadline:
                self.executor.check_enabled()
                self.executor.next_frame(time_out=min(1, max(0.01, deadline - time.monotonic())))
                state = self._domain_reward_state()
                if state in ('claim', 'treasure'):
                    return state
                if state == 'combat' and self.in_team()[0]:
                    break
                if self.executor.exit_event.wait(0.1):
                    self.executor.check_enabled()
                    raise CombatStateUnknown('领域状态等待已退出')
            if state != 'combat' or attempt == 1 or not self.in_team()[0]:
                self.screenshot('domain_state_unknown', frame=self.frame)
                raise CombatStateUnknown(f'领域未确认完成：state={state}, recovery_used={attempt}')
            self.log_warning('领域目标仍在，尝试一次原地战斗恢复；不重新开启挑战')
