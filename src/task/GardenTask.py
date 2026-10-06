import re
import cv2
from src.task.weekly_garden import (GardenRunResult, garden_week_key,
                                  garden_weekly_page, garden_current_points)


from ok import Logger, run_task
from config import config
from src.Labels import Labels
from src.task.BaseWWTask import BaseWWTask
from src.task.WWOneTimeTask import WWOneTimeTask

logger = Logger.get_logger(__name__)


class GardenTask(WWOneTimeTask, BaseWWTask):
    GARDEN_TARGET_POINTS = re.compile('6000')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "🎡 自动周常乐园"
        self.description = "Detect and click garden actions until the task is stopped."
        self.garden_features = [
            label.value for label in Labels
            if label.value.startswith("garden_")
        ]
        self.garden_priority_features = [
            "garden_get_skip",
            "garden_not_interested_confirm",
        ]

    def run(self):
        WWOneTimeTask.run(self)
        started_week = garden_week_key()
        self.last_result = GardenRunResult('pending', started_week)
        self.ensure_main()
        self.open_garden_weekly_page()
        opening_scores = []
        for attempt in range(3):
            if attempt:
                self.sleep(0.6)
            opening_scores.append(self.read_weekly_garden_points())
            if (len(opening_scores) >= 2 and opening_scores[-2] is not None
                    and opening_scores[-2] >= 6000 and opening_scores[-1] is not None
                    and opening_scores[-1] >= 6000):
                week_key = garden_week_key()
                evidence_ref = self.record_verified_result(opening_scores[-1], week_key)
                self.last_result = GardenRunResult(
                    'already_completed', week_key, opening_scores[-1], True, evidence_ref)
                self.ensure_main(time_out=180)
                self.log_info('乐园任务完成, 已达到上限', notify=True)
                return
            # One explicit below-target score is enough to begin; missing OCR is not.
            if opening_scores[-1] is not None and opening_scores[-1] < 6000:
                break
        else:
            self.last_result = GardenRunResult(
                'pending', started_week, error='乐园入口积分无法确认，已达到有限重读上限')
            self.ensure_main(time_out=180)
            raise RuntimeError(self.last_result.error)
        self.enter_weekly_garden()
        unknown_end_observations = 0
        while True:
            self.sleep(0.1)
            target = self.find_best_garden_feature()
            self.sleep(0.2)
            if target:
                self.info_set("current task", target.name)
                if target.name == 'garden_get_skip':
                    self.sleep(1)
                    self.log_info(f"click garden_get_confirm")
                    if gold := self.find_one('garden_get_gold', horizontal_variance=0.9):
                        self.click(gold, after_sleep=1)
                    elif purple := self.find_one('garden_get_purple', horizontal_variance=0.9):
                        self.click(purple, after_sleep=1)
                    else:
                        self.click(0.5, 0.2, after_sleep=1)
                    self.click(self.get_box_by_name('garden_get_confirm_gray'), after_sleep=1)
                    continue
                elif target.name == 'garden_not_interested':
                    not_interested = self.find_feature('garden_not_interested', vertical_variance=0.4)
                    self.click(not_interested[-1], after_sleep=1)
                    self.click(self.get_box_by_name('garden_not_interested_confirm'), after_sleep=1)
                    continue
                elif target.name == 'garden_start_game':
                    # At Garden Entrance, choose blessing1
                    self._choose_first_blessing()
                self.log_info(f"click {target.name} {target.confidence:.3f}")
                self.click(target, after_sleep=1)
            else:
                garden_restart = self.find_one('a_garden_restart')
                garden_back = self.find_one('a_garden_back')
                if garden_restart and garden_back:
                    # 避免因点击太快，导致[挑战失败]页面中点击[返回主页]失败
                    self.sleep(2)
                    frame = self.next_frame()
                    texts = self.ocr(0.373, 0.346, 0.859, 0.615, frame=frame) if frame is not None else []
                    self.log_info('garden end {}'.format(texts))
                    end_points = self.garden_points_from_texts(texts)
                    if end_points is not None and end_points >= 6000:
                        self.click(garden_back, after_sleep=1)
                        if self.wait_feature('garden_start_game', settle_time=1, time_out=5):
                            self.back(after_sleep=1)
                        if self.wait_book('gray_book_quest', time_out=30):
                            self.click(0.927, 0.893, after_sleep=2)
                            self.click(0.927, 0.893, after_sleep=1)
                        break
                    elif end_points is not None:
                        # A numeric score below target confirms this run did not finish.
                        unknown_end_observations = 0
                        self.click(garden_restart, after_sleep=1)
                    else:
                        # OCR uncertainty is not evidence that another game should start.
                        unknown_end_observations += 1
                        if unknown_end_observations >= 3:
                            self.last_result = GardenRunResult(
                                'pending', started_week, error='终局积分无法确认，达到有限重读上限')
                            # Both result controls were detected. Return to the
                            # authoritative weekly page instead of guessing a restart.
                            back = self.find_one('a_garden_back')
                            if not back or not self.find_one('a_garden_restart'):
                                raise RuntimeError(self.last_result.error)
                            self.click(back, after_sleep=1)
                            self.ensure_main(time_out=180)
                            break
                        self.sleep(0.6)
                self.sleep(0.2)
        self.open_garden_weekly_page()
        final_week = garden_week_key()
        if final_week != started_week:
            self.log_warning('乐园执行期间跨越周重置，重新读取新周积分')
        first = self.read_weekly_garden_points()
        self.sleep(0.6)
        second = self.read_weekly_garden_points()
        verified = first is not None and first >= 6000 and second is not None and second >= 6000
        status = 'completed' if verified else 'pending'
        self.last_result = GardenRunResult(status, final_week, second,
                                           verified=verified,
                                           error=None if verified else '积分未通过两次新画面复核')
        if not verified:
            from src.evidence.service import record_task_evidence
            record_task_evidence(self, 'weekly_garden', 'pending',
                                 f'乐园结束后复核不足；积分读数：{first!r}, {second!r}',
                                 week_key=final_week, verified=False)
            raise RuntimeError('乐园结束后积分未通过两次新画面复核')
        evidence_ref = self.record_verified_result(second, final_week)
        self.last_result = GardenRunResult('completed', final_week, second, True, evidence_ref)
        self.ensure_main(time_out=180)
        self.log_info('乐园任务完成, 已达到上限', notify=True)

    def open_garden_weekly_page(self):
        self.openF2Book('gray_book_quest')
        self.sleep(1)
        self.click(0.343, 0.129, after_sleep=1)
        self.click(0.927, 0.893, after_sleep=3)
        self.click(0.927, 0.893, after_sleep=2)

    def is_weekly_garden_completed(self):
        first = self.read_weekly_garden_points()
        self.sleep(0.6)
        second = self.read_weekly_garden_points()
        self.log_info(f"Garden current points: {first}, {second}")
        if first is not None and first >= 6000 and second is not None and second >= 6000:
            from src.evidence.service import record_task_evidence
            record_task_evidence(self, 'weekly_garden', 'completed',
                                 f'周常积分 {second}/6000 已达标；不代表奖励已领取')
        return first is not None and first >= 6000 and second is not None and second >= 6000

    def record_verified_result(self, points, week_key, profile_id=None):
        profile_id = (profile_id or getattr(self, '_garden_evidence_profile_id', None)
                      or getattr(self, '_verified_profile_id', None) or 'current-profile')
        evidence_ref = f'weekly_garden:{profile_id}:{week_key}'
        from src.evidence.service import record_task_evidence
        record_task_evidence(self, 'weekly_garden', 'completed',
                             f'周常积分 {points}/6000 已达标；不代表奖励已领取',
                             week_key=week_key, points=points, verified=True,
                             evidence_ref=evidence_ref)
        return evidence_ref

    def read_weekly_garden_points(self):
        """Confirm the page, then read only the current value above 游历值."""
        frame = self.next_frame()
        if frame is None:
            return None
        header = self.ocr(.02, .03, .45, .17, frame=frame)
        anchor = self.ocr(.185, .89, .285, .935, frame=frame)
        has_anchor = any('游历值' in str(getattr(b, 'name', b)) for b in anchor or [])
        page_confirmed = garden_weekly_page(header)
        if has_anchor and not page_confirmed:
            # A missed header word must not send the new layout to the old n/6000 parser.
            cards = self.ocr(.11, .18, .67, .79, frame=frame)
            card_text = ''.join(str(getattr(b, 'name', b)) for b in cards or [])
            header_text = ''.join(str(getattr(b, 'name', b)) for b in header or [])
            has_card = '幻梦游园' in card_text or '千道门扉' in card_text
            page_confirmed = has_card and ('活跃行迹' in header_text or '周度游历' in header_text
                                           or ('幻梦游园' in card_text and '千道门扉' in card_text))
            self.log_info(f'Garden page fallback: header={header_text!r}, cards={card_text!r}, confirmed={page_confirmed}')
        if has_anchor and page_confirmed:
            for scale in (2160, 3240):
                digits = self.ocr(.185, .83, .285, .883, frame=frame,
                                  frame_processor=lambda image, scale=scale: cv2.resize(
                                      image, None, fx=scale/1080, fy=scale/1080))
                value = garden_current_points(digits)
                self.log_info(f'Garden current value OCR: {[b.name for b in digits or []]!r}; value={value}')
                if value is not None:
                    return value
            # A lone 0 can be missed by the detector in a tight crop.
            # Use full-page context but accept digits only inside the same region.
            h, w = frame.shape[:2]
            digits = [b for b in self.ocr(frame=frame) or []
                      if .185*w <= b.center()[0] <= .285*w
                      and .83*h <= b.center()[1] <= .883*h]
            return garden_current_points(digits)
        if has_anchor or page_confirmed:
            return None
        # Legacy layouts show an earned/target pair in this anchored region.
        texts = self.ocr(0.102, 0.793, 0.284, 0.956, frame=frame)
        rendered = ' '.join(str(getattr(box, 'name', box)) for box in (texts or []))
        self.log_info(f'Garden score OCR: {rendered!r}')
        match = re.search(r'(?<!\d)(\d{1,5})\s*/\s*6000(?!\d)', rendered.replace(',', ''))
        return min(int(match.group(1)), 6000) if match else None

    def enter_weekly_garden(self):
        def source(frame):
            if not garden_weekly_page(self.ocr(.02, .03, .45, .17, frame=frame)):
                return None
            boxes = self.ocr(.11, .18, .39, .79, frame=frame)
            matches = [b for b in boxes or [] if '幻梦游园' in b.name and '狂想' in b.name]
            return matches[0] if len(matches) == 1 else None
        self.navigate_ui('周度游历进入幻梦游园', source,
                         lambda frame: self.find_one('garden_start_game', frame=frame),
                         identity='weekly_garden', attempts=2, timeout=30)

    @staticmethod
    def garden_points_from_texts(texts):
        text = " ".join(str(getattr(box, "name", box)) for box in texts)
        if not text.strip():
            return None
        match = re.search(r'(?<!\d)(\d{1,5})\s*/\s*6000(?!\d)', text.replace(',', ''))
        return min(int(match.group(1)), 6000) if match else None

    def is_garden_done(self, texts):
        points = self.garden_points_from_texts(texts)
        return points is not None and points >= 6000

    def find_best_garden_feature(self):
        matches = []
        for feature_name in self.garden_features:
            if not self.feature_exists(feature_name):
                continue
            if feature_name == 'garden_get_confirm_gray' or feature_name == 'garden_not_interested_confirm':
                continue
            if feature_name == 'garden_not_interested':
                matches.extend(self.find_feature(feature_name, vertical_variance=0.4))
            else:
                matches.extend(self.find_feature(feature_name))
        for priority_feature in self.garden_priority_features:
            priority_matches = [
                match for match in matches
                if match.name == priority_feature
            ]
            if priority_matches:
                return max(priority_matches, key=lambda box: box.confidence)
        return max(matches, key=lambda box: box.confidence, default=None)

    def _choose_first_blessing(self):
        """At Garden Entrance, choose first blessing"""
        # click blessing botton
        self.click(965 / 1920, 860 / 1080, after_sleep=2)
        # choose blessing1(Add-on)
        self.click(700 / 1920, 666 / 1080, after_sleep=2)
        # confirm
        self.click(1600 / 1920, 900 / 1080, after_sleep=2)


if __name__ == "__main__":
    run_task(config, task=GardenTask, debug=True)
