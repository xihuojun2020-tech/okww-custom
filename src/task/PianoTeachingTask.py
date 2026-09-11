"""Play notes highlighted by the Wuthering Waves piano teaching UI."""
import time

from ok import TaskDisabledException

from src.task.BaseWWTask import BaseWWTask
from src.task.WWOneTimeTask import WWOneTimeTask
from src.task.piano import KEY_ORDER, PianoDetector, PianoStateMachine


class PianoTeachingTask(WWOneTimeTask, BaseWWTask):
    navigation_section = "activities"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "Piano Teaching"
        self.description = "Open piano teaching first; single highlighted notes are played until you stop the task."
        self.group_name = "常驻活动"
        self.supported_languages = ["zh_CN"]
        self.support_schedule_task = False
        self.default_config.update({
            "Sample Interval": 0.05,
            "Key Hold Time": 0.03,
            "Post Key Delay": 0.15,
        })
        self.config_description.update({
            "Sample Interval": "Seconds between piano highlight samples (0.03–0.08).",
            "Key Hold Time": "Seconds to hold every detected note (0.02–0.08).",
            "Post Key Delay": "Pause after every note to imitate human input (0.05–0.50 seconds).",
        })
        self._pressed_keys = []

    def validate_config(self, key, value):
        limits = {
            "Sample Interval": (0.03, 0.08),
            "Key Hold Time": (0.02, 0.08),
            "Post Key Delay": (0.05, 0.50),
        }
        if key in limits and (type(value) not in (int, float) or not limits[key][0] <= value <= limits[key][1]):
            return f"{key} must be between {limits[key][0]} and {limits[key][1]}"
        return None

    def _release_pressed(self):
        for key in tuple(reversed(self._pressed_keys)):
            try:
                self.send_key_up(key)
            except Exception as error:
                self.log_warning(f"释放钢琴按键 {key.upper()} 失败: {error}")
            else:
                self._pressed_keys.remove(key)

    def _press_event(self, event, hold_time):
        if len(event.keys) != 1 or event.keys[0] not in KEY_ORDER:
            raise ValueError("piano teaching requires exactly one key")
        try:
            for key in event.keys:
                lower = key.lower()
                self._pressed_keys.append(lower)
                self.send_key_down(lower)
            self.sleep(hold_time)
        finally:
            self._release_pressed()
        if self._pressed_keys:
            raise RuntimeError("钢琴按键未能全部释放，任务已停止")

    @staticmethod
    def _diagnostic_crop(frame):
        if frame is None:
            return None
        height, width = frame.shape[:2]
        return frame[round(height * 0.64):round(height * 0.96),
                     round(width * 0.26):round(width * 0.76)].copy()

    @staticmethod
    def _detection_summary(result):
        valid_dots = sum(reading.dot_luma >= 0.55 for reading in result.readings)
        top = sorted(result.readings, key=lambda reading: reading.score, reverse=True)[:3]
        scores = ",".join(f"{reading.key}:{reading.score:.3f}" for reading in top) or "-"
        return (f"status={result.status} valid_dots={valid_dots}/21 "
                f"on={','.join(result.on_keys) or '-'} "
                f"uncertain={','.join(result.uncertain_keys) or '-'} "
                f"top={scores} reason={result.reason or '-'}")

    def run(self):
        WWOneTimeTask.run(self)
        if self.game_lang != "zh_CN":
            raise RuntimeError("清弦纪流年首版仅支持简体中文游戏")
        detector = PianoDetector()
        tracker = PianoStateMachine()
        interval = float(self.config.get("Sample Interval", 0.05))
        hold_time = float(self.config.get("Key Hold Time", 0.03))
        post_key_delay = float(self.config.get("Post Key Delay", 0.15))
        frame = None
        last_detection_state = None
        self.info_set("弹琴状态", "等待高亮")
        try:
            while True:
                started = time.monotonic()
                frame = self.next_frame()
                if frame is None:
                    raise RuntimeError("无法取得游戏截图")
                result = detector.analyze(frame)
                detection_state = (result.status, result.on_keys, result.uncertain_keys, result.reason)
                if detection_state != last_detection_state:
                    self.log_info(f"弹琴检测 {self._detection_summary(result)}")
                    last_detection_state = detection_state
                if result.status == "invalid_roi":
                    tracker.reset()
                    self.info_set("弹琴状态", "剧情或转场中，等待弹琴界面")
                else:
                    event = tracker.step(result, time.monotonic())
                    if event:
                        self.info_set("弹琴状态", f"按下 {event.keys[0]}")
                        self._press_event(event, hold_time)
                        self.sleep(post_key_delay)
                    elif result.uncertain_keys:
                        self.info_set("弹琴状态", "等待高亮稳定")
                    else:
                        self.info_set("弹琴状态", "等待高亮")
                remaining = interval - (time.monotonic() - started)
                if remaining > 0:
                    self.sleep(remaining)
        except TaskDisabledException:
            raise
        except Exception:
            if (crop := self._diagnostic_crop(frame)) is not None and crop.size:
                self.screenshot("piano_teaching_stopped", frame=crop)
            raise
        finally:
            self._release_pressed()

    def on_destroy(self):
        self._release_pressed()
        parent = getattr(super(), "on_destroy", None)
        if parent:
            parent()
