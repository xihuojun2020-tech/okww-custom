import unittest

from src.task_status import (
    STATUS_ACCOUNT,
    STATUS_DETAIL,
    STATUS_STAGE,
    choose_status_position,
    publish_task_status,
    read_task_status,
)


class FakeTask:
    def __init__(self, name="Multi Account Daily", start_time=100.0):
        self.name = name
        self.start_time = start_time
        self.info = {}
        self.executor = type("Executor", (), {"current_task": self})()

    def info_set(self, key, value):
        self.info[key] = value

    def tr(self, value):
        return {"Error": "错误"}.get(value, value)


class TestTaskStatus(unittest.TestCase):
    def test_child_publication_writes_to_top_level_task(self):
        parent = FakeTask()
        child = FakeTask("Nightmare")
        child.executor.current_task = parent

        publish_task_status(
            child,
            account="A3",
            stage="刷梦魇巢穴",
            detail="落渊南丘残象聚落 · 正在战斗",
        )

        self.assertEqual("A3", parent.info[STATUS_ACCOUNT])
        self.assertEqual("刷梦魇巢穴", parent.info[STATUS_STAGE])
        self.assertEqual("落渊南丘残象聚落 · 正在战斗", parent.info[STATUS_DETAIL])
        self.assertEqual({}, child.info)

    def test_error_has_priority_over_warning_and_detail(self):
        task = FakeTask()
        task.info.update({
            STATUS_ACCOUNT: "A3",
            STATUS_STAGE: "账号切换",
            STATUS_DETAIL: "正在等待登录",
            "Warning": "WGC 暂无新帧",
            "Error": "无法唯一识别当前账号",
        })

        snapshot = read_task_status(task, now=160.0)

        self.assertEqual("error", snapshot.level)
        self.assertEqual("无法唯一识别当前账号", snapshot.message)
        self.assertEqual(60, snapshot.elapsed_seconds)

    def test_localized_executor_error_is_also_visible(self):
        task = FakeTask()
        task.info["错误"] = "子任务异常终止"

        snapshot = read_task_status(task, now=160.0)

        self.assertEqual("error", snapshot.level)
        self.assertEqual("子任务异常终止", snapshot.message)

    def test_position_prefers_a_non_game_monitor(self):
        work_areas = [(0, 0, 1920, 1040), (1920, 0, 1920, 1040)]
        position = choose_status_position(
            work_areas,
            game_rect=(0, 0, 1920, 1040),
            status_size=(340, 110),
        )
        self.assertEqual((3488, 12), position)

    def test_position_returns_none_when_no_safe_space_exists(self):
        position = choose_status_position(
            [(0, 0, 1920, 1040)],
            game_rect=(0, 0, 1920, 1040),
            status_size=(340, 110),
        )
        self.assertIsNone(position)


if __name__ == "__main__":
    unittest.main()
