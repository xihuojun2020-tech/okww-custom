import re
import cv2
from dataclasses import dataclass

from ok import Logger, TaskDisabledException
from src.task.BaseCombatTask import BaseCombatTask, CharRevivedException
from src.task.WWOneTimeTask import WWOneTimeTask
from src.task_status import publish_task_status

logger = Logger.get_logger(__name__)
TRAVEL_FEATURES = ['fast_travel_custom', 'gray_teleport', 'remove_custom']
CONFIRM_FEATURES = ['confirm_btn_hcenter_vcenter', 'confirm_btn_highlight_hcenter_vcenter']

# 残象聚落（Tacet Discord Nest）名称，按游戏内 F2 残象页面从上到下的顺序
NEST_NAMES = ['落渊南丘残象聚落', '盲望之塌残象聚落', '复生丘原残象聚落', '陷足流川残象聚落']
# 每个位置的聚落怪物总数（用于校验行位置是否对应正确，48 出现两次所以不能单独用总数定位）
NEST_TOTAL_BY_POSITION = [41, 48, 48, 24]
# 可识别的聚落总数（保留 36 以兼容旧版本/历史数据）
NEST_TOTALS = {'24', '36', '41', '48'}
# 要刷的残象聚落（勾选 = 刷，不勾选 = 不打）
FARM_TACET_DISCORD_NESTS = 'Tacet Discord Nests to Farm'


@dataclass
class NestTarget:
    box: object
    cache_key: str
    display_name: str = '未知目标'
    ordinal: int = 0
    current: int = 0
    total: int = 0


class NightmareNestTask(WWOneTimeTask, BaseCombatTask):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.default_config = {'_enabled': True}
        self.trigger_interval = 0.1
        self.target_enemy_time_out = 10
        self.name = "🌙 Nightmare Nest Task"
        self.description = "Auto Farm all Nightmare Nest"
        self.support_schedule_task = True
        # 已整合进每日任务模块（经每日任务附加任务【自动刷梦魇巢穴】触发，配置合并到每日任务）。
        # 隐藏独立入口，任务列表不再单独显示本卡片；executor 仍注册实例，DailyTask 可照常调用。
        self.visible = False
        self.count_re = re.compile(r"(\d{1,2})/(\d{1,2})")
        self.queues = []
        self._capture_success = False
        self._capture_mode = False
        self._unreachable_nests = set()
        self._nest_progress = {}
        self._nest_stagnation = {}
        self._incomplete_targets = {}
        self.default_config.update({'Which to Farm': ['Nightmare Purification', 'Tacet Discord Nest']})
        self.config_type['Which to Farm'] = {'type': "multi_selection",
                                             'options': ['Nightmare Purification', 'Tacet Discord Nest']}
        # 要刷的残象聚落：勾选 = 刷，不勾选 = 不打（默认全刷）
        self.default_config.update({FARM_TACET_DISCORD_NESTS: list(NEST_NAMES)})
        self.config_type[FARM_TACET_DISCORD_NESTS] = {
            'type': 'multi_selection',
            'options': NEST_NAMES,
        }
        self.config_description = {
            FARM_TACET_DISCORD_NESTS: 'Tacet Discord Nests to farm (checked = farm, unchecked = skip).',
        }

    def run(self):
        publish_task_status(self, stage='刷梦魇巢穴', detail='正在打开 F2 梦魇页面')
        self._capture_mode = False
        self._capture_success = False
        self._unreachable_nests.clear()
        self._reset_progress_tracking()
        WWOneTimeTask.run(self)
        self.ensure_main(time_out=30)
        self._init_queue()
        self.log_info('opened gray_book_boss')
        while nest := self.get_nest_to_go():
            self.combat_nest(nest)
        self._assert_selected_targets_complete()
        self.ensure_main(time_out=30)

    def run_capture_mode(self):
        publish_task_status(self, stage='刷梦魇巢穴', detail='正在打开 F2 梦魇页面')
        self._capture_mode = True
        self._capture_success = False
        self._unreachable_nests.clear()
        self._reset_progress_tracking()
        WWOneTimeTask.run(self)
        self.ensure_main(time_out=30)
        self._init_queue()
        self.log_info('opened gray_book_boss')
        while nest := self.get_nest_to_go():
            self.combat_nest(nest)
            if self._capture_success:
                break
        self.ensure_main(time_out=30)

    def on_combat_check(self):
        if self._capture_mode:
            self.pick_f(handle_claim=False)
            if self.has_echo_notification():
                return self.reset_to_false(reason='echo captured')
        return True

    def has_echo_notification(self):
        if self.find_best_match_in_box(self.box_of_screen(0.078, 0.488, 0.094, 0.514),
                                       ['char_1_text', 'char_3_text'], 0.6,
                                       frame_processor=convert_image_to_negative):
            self._capture_success = True
        return self._capture_success

    def combat_nest(self, nest):
        target_box = nest.box if isinstance(nest, NestTarget) else nest
        target_name = nest.display_name if isinstance(nest, NestTarget) else '当前目标'
        publish_task_status(self, stage='刷梦魇巢穴', detail=f'{target_name} · 正在进入挑战')
        self.click(target_box, after_sleep=2)
        feature = self.wait_feature(['fast_travel_custom', 'gray_teleport', 'remove_custom', 'team_close'], time_out=10,
                                    settle_time=0.5, raise_if_not_found=True)
        is_team = feature.name == 'team_close'
        if is_team:
            self.click_team_challenge()
            self.wait_in_team_and_world(time_out=120)
        else:
            publish_task_status(self, stage='刷梦魇巢穴', detail=f'{target_name} · 正在传送')
            if not self._travel_to_nest_or_skip(nest):
                return
            self.sleep(1)
            while self.find_f_with_text():
                self.send_key('f', after_sleep=1)
                self.wait_in_team_and_world(time_out=40, raise_if_not_found=False)
            self.sleep(2)
            publish_task_status(self, stage='刷梦魇巢穴', detail=f'{target_name} · 正在战斗')
            self.run_until(self.in_combat, 'w', time_out=10, running=False, target=True)
        wait_combat_time = 10
        while True:
            try:
                need_find = self.combat_once(wait_combat_time=wait_combat_time, target=True,
                                             raise_if_not_found=False)
            except CharRevivedException:
                self.log_info('nightmare nest: death recovered, re-enter from F2 book')
                return
            captured_early = False
            if self._capture_mode:
                if self._capture_success or self.wait_until(self.has_echo_notification, time_out=3):
                    self.log_info("Captured echo during combat, skipping search.")
                    captured_early = True
            if not captured_early:
                publish_task_status(self, stage='刷梦魇巢穴', detail=f'{target_name} · 正在拾取声骸')
                self.sleep(3)
                if need_find and not self.walk_find_echo(time_out=5, backward_time=2.5):
                    dropped = self.yolo_find_echo(turn=True, use_color=False, time_out=30)[0]
                    logger.info(f'farm echo yolo find {dropped}')
                else:
                    dropped = True
                    self.log_info(f'farm echo walk find true')
                self._capture_success = dropped
            if not self._should_continue_combat_after_pickup():
                break
            self.log_info('nightmare nest: combat detected after pickup')
            wait_combat_time = 1
        # 与刷全部一致：退本后再结束 combat_nest，避免还在巢穴内回 Daily/开书
        if is_team:
            self.esc_world_confirm()
        self.sleep(1)

    def _should_continue_combat_after_pickup(self):
        return not self._capture_mode and self.wait_combat(
            target=True, time_out=3, raise_if_not_found=False)

    def _travel_to_nest_or_skip(self, nest):
        travel = self.wait_until(self._find_travel_button, raise_if_not_found=False, time_out=3)
        if travel:
            self.click(travel, after_sleep=1)
            if confirm := self._find_first_feature(CONFIRM_FEATURES, threshold=0.6):
                self.click(confirm, after_sleep=1)

            button_gone = self.wait_until(
                lambda: not self.find_one(travel.name, threshold=0.7),
                time_out=5,
                raise_if_not_found=False,
            )
            if button_gone:
                if self.wait_in_team_and_world(time_out=120, raise_if_not_found=False):
                    return True
            elif self.wait_in_team_and_world(time_out=10, raise_if_not_found=False):
                return True

        if isinstance(nest, NestTarget):
            self._unreachable_nests.add(nest.cache_key)
            publish_task_status(
                self,
                stage='刷梦魇巢穴',
                detail=f'{nest.display_name} · 不可到达，已跳过',
            )
            self.log_info(f'nightmare nest unreachable, skip this run: {nest.cache_key}')
        else:
            publish_task_status(self, stage='刷梦魇巢穴', detail='当前目标 · 不可到达，已跳过')
            self.log_info('nightmare nest unreachable, skip this run')
        self.back(after_sleep=1)
        return False

    def _find_travel_button(self):
        return self._find_first_feature(TRAVEL_FEATURES, threshold=0.7)

    def _find_first_feature(self, feature_names, threshold):
        for feature_name in feature_names:
            if feature := self.find_one(feature_name, threshold=threshold):
                return feature

    def get_nest_to_go(self):
        self._open_book_with_retry("gray_book_boss")

        while self.queues:
            self.queues[0]()
            if nest := self.find_nest():
                return nest
            self.queues.pop(0)

    def _open_book_with_retry(self, feature, attempts=3):
        for attempt in range(1, attempts + 1):
            try:
                return self.openF2Book(feature)
            except TaskDisabledException:
                raise
            except Exception:
                if attempt >= attempts:
                    raise
                self.log_warning(f'打开 F2 页面失败，正在恢复后重试（{attempt}/{attempts}）')
                self.ensure_main(time_out=30)
                self.sleep(1)

    def _init_queue(self):
        quests = self.config.get('Which to Farm') or ['Nightmare Purification', 'Tacet Discord Nest']
        actions = []
        if 'Tacet Discord Nest' in quests:
            actions.append(self.go_nest)
        if 'Nightmare Purification' in quests:
            actions.append(self.go_nightmare)
            actions.append(self.go_nightmare_scroll)
        self.queues = actions

    def go_nightmare(self):
        self.open_boss_book('mengyan')
        self.log_info('go nightmare')

    def go_nightmare_scroll(self):
        self.open_boss_book('mengyan')
        self.click(3737 / 3840, 0.54, after_sleep=1)
        self.log_info('go nightmare scroll')

    def go_nest(self):
        self.open_boss_book('canxiang')

    def find_nest(self):
        counts = self.ocr(0.35, 0.13, 1, 0.96, match=self.count_re)
        farm_nests = self.config.get(FARM_TACET_DISCORD_NESTS)
        # None（从未配置过）时默认全刷；显式空列表表示什么都不刷
        farm_nests = set(NEST_NAMES) if farm_nests is None else set(farm_nests)
        # 先按行位置排序，再用位置映射聚落名称（不能用总数定位，因为 48 出现两次）
        sorted_counts = sorted(counts, key=lambda box: box.y)
        nest_index = 0
        for count_box in sorted_counts:
            for match in re.finditer(self.count_re, count_box.name):
                numerator = match.group(1)
                denominator = match.group(2)
                if denominator not in NEST_TOTALS:
                    continue
                # 行位置 → 聚落名称；超过已知聚落数量则忽略
                if nest_index >= len(NEST_NAMES):
                    continue
                nest_name = NEST_NAMES[nest_index]
                nest_index += 1
                expected_total = NEST_TOTAL_BY_POSITION[nest_index - 1]
                if int(denominator) != expected_total:
                    self.log_info(f'warning: {nest_name} expected {expected_total} monsters but got {denominator}')
                current = int(numerator)
                total = int(denominator)
                action_name = self.queues[0].__name__ if self.queues else 'unknown'
                display_name = (
                    nest_name
                    if action_name == 'go_nest'
                    else f'梦魇拔除第 {nest_index} 项'
                )
                cache_key = self._make_nest_cache_key(count_box, denominator)
                if current < total:
                    if nest_name not in farm_nests:
                        self._clear_target_progress(cache_key)
                        self.log_info(f'skip tacet discord nest {nest_name} (not selected to farm)')
                        continue
                    self._record_target_progress(cache_key, display_name, current, total)
                    if cache_key in self._unreachable_nests:
                        self.log_info(f'skip cached unreachable nightmare nest: {cache_key}')
                        continue
                    self.log_info(f'{count_box} is not complete ({current}/{total})')
                    count_box.x = self.width_of_screen(0.9)
                    count_box.y -= count_box.height * 0.9
                    count_box.height = 1
                    count_box.width = 1
                    publish_task_status(
                        self,
                        stage='刷梦魇巢穴',
                        detail=f'当前目标：{display_name}',
                    )
                    return NestTarget(
                        count_box,
                        cache_key,
                        display_name=display_name,
                        ordinal=nest_index,
                        current=current,
                        total=total,
                    )
                self._clear_target_progress(cache_key)

    def _reset_progress_tracking(self):
        self._nest_progress = {}
        self._nest_stagnation = {}
        self._incomplete_targets = {}

    def _record_target_progress(self, cache_key, display_name, current, total):
        progress = getattr(self, '_nest_progress', None)
        if progress is None:
            self._reset_progress_tracking()
            progress = self._nest_progress
        previous = progress.get(cache_key)
        if previous is None or current > previous:
            self._nest_stagnation[cache_key] = 0
        else:
            self._nest_stagnation[cache_key] = self._nest_stagnation.get(cache_key, 0) + 1
        progress[cache_key] = current
        self._incomplete_targets[cache_key] = (display_name, current, total)
        if self._nest_stagnation[cache_key] >= 3:
            raise RuntimeError(f'{display_name} 连续 3 次执行后进度未增长（{current}/{total}）')

    def _clear_target_progress(self, cache_key):
        getattr(self, '_incomplete_targets', {}).pop(cache_key, None)
        getattr(self, '_nest_stagnation', {}).pop(cache_key, None)

    def _assert_selected_targets_complete(self):
        incomplete = list(getattr(self, '_incomplete_targets', {}).values())
        if not incomplete:
            return
        detail = '、'.join(f'{name} {current}/{total}' for name, current, total in incomplete)
        raise RuntimeError(f'所选梦魇巢穴仍未完成：{detail}')

    def _make_nest_cache_key(self, count_box, denominator):
        action_name = self.queues[0].__name__ if self.queues else 'unknown'
        screen_height = max(self.height_of_screen(1), 1)
        row_y = (count_box.y + count_box.height / 2) / screen_height
        row_slot = round(row_y / 0.02)
        # 使用粗粒度行槽位，避免 OCR 坐标轻微抖动导致同一目标被重复点击。
        return f'{action_name}:{denominator}:{row_slot}'


def convert_image_to_negative(img):
    to_gray = False
    _mat = img
    if len(_mat.shape) == 3:
        to_gray = True
        _mat = cv2.cvtColor(_mat, cv2.COLOR_BGR2GRAY)
    _, _mat = cv2.threshold(_mat, 80, 255, cv2.THRESH_BINARY)
    _mat = cv2.bitwise_not(_mat)
    if to_gray:
        _mat = cv2.cvtColor(_mat, cv2.COLOR_GRAY2BGR)
    return _mat


from ok import run_task
from config import config

if __name__ == "__main__":
    run_task(config, task=NightmareNestTask, debug=True)
