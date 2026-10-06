import cv2

from ok import Logger, find_color_rectangles
from src.task.DomainTask import DomainTask

logger = Logger.get_logger(__name__)


class ForgeryTask(DomainTask):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = '⚒️ Forgery Challenge'
        self.description = 'Farms the selected Forgery Challenge. Must be able to teleport (F2).'
        self.support_schedule_task = True
        self.default_config = {
            'Which Forgery Challenge to Farm': 1,  # starts with 1
        }
        self.config_description = {
            'Which Forgery Challenge to Farm': 'The Forgery Challenge number in the F2 list.',
        }
        self.stamina_once = 40
        self.structure = [5, 5, 5, 5]
        self.total_number = sum(self.structure)
        self.material_mat = None
        # 精简版：凝素领域已融入每日任务模块，不在任务列表单独显示
        self.visible = False

    def run(self):
        super().run()
        self.make_sure_in_world()
        self.farm_forgery()

    def farm_forgery(self, daily=False, used_stamina=0, config=None, activity_ready=False):
        must_use = self.daily_stamina_budget(activity_ready, self.stamina_once, used_stamina) if daily else 0
        if config is None:
            config = self.config
        serial = config.get('Which Forgery Challenge to Farm', 1)

        def teleport_once():
            self.teleport_into_domain(serial, daily)

        self.farm_domain_with_recovery_loop(
            must_use, teleport_once,
            activity_ready=activity_ready if daily else None,
            stamina_budget=must_use,
            exhaust_current=daily,
        )

    def purification_material(self):
        self.send_key("esc")
        self.sleep(1)
        self.click_relative(0.62, 0.7)
        self.sleep(1)
        box = self.box_of_screen(243 / 2560, 162 / 1440, 928 / 2560, 559 / 1440, name='ascension_materials')
        self.draw_boxes(box.name, box)
        self.wait_book()
        if self.material_mat is not None and \
            (target := self.wait_until(lambda: self.find_one(template=self.material_mat, box=box, threshold=0.7), time_out=1)):
            self.click_box(target, after_sleep=1)
        self.click_relative(0.75, 0.90, after_sleep=1)
        self.ensure_main()

    def farm_quota(self, profile_id, read_tasks, service, guard, *, activity_ready=False, used_stamina=0):
        from src.task.forgery_quota_plan import forgery_plan, forgery_limited, next_forgery_goal, claim_width
        from src.task.forgery_quota_progress import ForgeryQuotaProgress
        from src.config_integrity import fingerprint
        progress = ForgeryQuotaProgress(service, profile_id)
        task = self

        class ClaimTracker:
            def __init__(self, row, rows, width):
                self.row, self.rows, self.max_claims = row, rows, width
                self.event_id = None

            def begin_claim(self):
                guard()
                current_tasks = read_tasks()
                if (current_tasks.get('Which to Farm', 'Forgery Challenge') != 'Forgery Challenge'
                        or not forgery_limited(current_tasks)
                        or forgery_plan(current_tasks) != self.rows):
                    raise RuntimeError('凝素目标已修改，停止本次领奖，请重新运行')
                if progress.pending():
                    raise RuntimeError('凝素领奖待核验，请先在账号设置核对')
                self.event_id = progress.begin(self.row['goal_id'], self.row['domain'],
                                              self.max_claims * 40, fingerprint(self.rows))

            def collect_claim(self, used):
                progress.resolve(self.event_id, used)

            def capture_failure(self):
                task.screenshot('forgery_quota_pending')

        try:
            while True:
                guard()
                if progress.pending():
                    raise RuntimeError('凝素领奖待核验，请先在账号设置核对')
                current_tasks = read_tasks()
                if current_tasks.get('Which to Farm', 'Forgery Challenge') != 'Forgery Challenge' or not forgery_limited(current_tasks):
                    return 'disabled'
                rows = forgery_plan(current_tasks)
                choice = next_forgery_goal(rows, progress.earned())
                if choice is None:
                    return 'complete' if rows else 'disabled'
                row, remaining = choice
                policy = getattr(self.executor, '_daily_reserve_policy', None)
                consumed = policy.stamina_used if policy is not None else used_stamina
                ready = policy.activity_ready if policy is not None else activity_ready
                budget = self.daily_stamina_budget(ready, 40, consumed)
                self.open_F2_book_and_get_stamina()
                current, _, total = self.prepare_daily_stamina(40, budget)
                width = claim_width(remaining, current)
                if not width:
                    self._note_daily_resource_shortfall(total, max(40, budget))
                    self.back()
                    return 'resource_shortfall'
                self.claim_tracker = ClaimTracker(row, rows, width)
                before = progress.earned()
                self.info_set('凝素目标', f'领域 {row["domain"]}，剩余 {remaining} 绿色当量，本次 {width * 40} 体力')
                self.farm_domain_with_recovery_loop(budget,
                    lambda: self.teleport_into_domain(row['domain'], True),
                    activity_ready=ready, stamina_budget=budget, exhaust_current=True)
                if progress.earned() == before:
                    return 'resource_shortfall'
        finally:
            self.claim_tracker = None

    def teleport_into_domain(self, serial_number, daily=False):
        self.open_boss_book('ningsu')
        self.info_set('Teleport to Forgery Challenge', serial_number - 1)
        if serial_number > self.total_number:
            raise IndexError(f'Index out of range, max is {self.total_number}')
        self.click_on_book_target(serial_number, self.total_number, self.structure)
        self.click(0.891, 0.910, after_sleep=1)
        self.click_team_challenge()
        self.wait_in_team_and_world(time_out=self.teleport_timeout)

    def get_material_mat(self):
        min_width = self.width_of_screen(80 / 2560)
        min_height = self.height_of_screen(80 / 1440)
        box = self.box_of_screen(2205 / 2560, 566 / 1440, 2357 / 2560, 984 / 1440)
        self.draw_boxes(box.name, box)
        material_boxes = find_color_rectangles(self.frame, material_box_color, min_width, min_height,
                                               box=box, threshold=0.6)
        if material_boxes:
            box_start = self.width_of_screen(20 / 2560)
            box_len = self.width_of_screen(90 / 2560)
            target = min(material_boxes, key=lambda box: box.y)
            logger.info(f"Found {len(material_boxes)} material boxes, selected target at y={target.y}")
            mat_box = target.copy(box_start, box_start, box_len - target.width, box_len - target.height, 'material_mat')
            self.draw_boxes(mat_box.name, mat_box)
            self.material_mat = cv2.resize(mat_box.crop_frame(self.frame), None,
                                           fx=1.1, fy=1.1, interpolation=cv2.INTER_LINEAR)


material_box_color = {
    'r': (45, 75),  # Red range
    'g': (45, 75),  # Green range
    'b': (45, 75)  # Blue range
}
