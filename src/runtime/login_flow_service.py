"""Production account login orchestration shared by tasks and focused tests."""

from __future__ import annotations

from typing import Any

from ok import TaskDisabledException


class LoginFlowService:
    """Coordinate the existing task OCR, click, retry and evidence primitives."""

    def __init__(self, task: Any):
        self.task = task

    def switch_to_account(self, target: Any, *, max_retries: int = 5):
        if not target:
            raise ValueError("target account is required")
        task = self.task
        task._guard_account_transition()
        task._begin_account_switch_evidence(target)
        mouse_reset_task = None
        mouse_reset_was_enabled = False
        try:
            executor = getattr(task, "executor", None)
            getter = getattr(executor, "get_task_by_class", None)
            if callable(getter):
                from src.task.MouseResetTask import MouseResetTask
                mouse_reset_task = getter(MouseResetTask)
            mouse_reset_was_enabled = mouse_reset_task.enabled if mouse_reset_task else False
            if mouse_reset_was_enabled:
                mouse_reset_task.disable()
            if task.do_find_account_drop_down() is None:
                try:
                    in_team = bool(task.in_team()[0])
                except TaskDisabledException:
                    raise
                except Exception:
                    in_team = False
                if in_team:
                    task.log_info("检测到仍在游戏世界内，先退登再执行账号切换")
                    task._evidence_stage("logout_from_world")
                    task._switch_to_login()
            task._evidence_stage("wait_login_screen")
            task._wait_login_screen_stable(time_out=120)
            task._evidence_stage("select_account")
            task._select_account_with_retry(target, max_retries=max_retries)
            task.sleep(4)
            task._evidence_stage("verify_before_login")
            task._click_login_for_target(target)
            task.logged_in = False
            task._evidence_stage("ensure_main")
            task.ensure_main(time_out=180)
            task.log_info(f"已登录: {target}")
            task._finish_account_switch_evidence(True)
            return target
        except TaskDisabledException as error:
            event_dir = task._finish_account_switch_evidence(
                False, str(error), stage="stopped", stopped=True)
            if event_dir is not None:
                task.log_warning(f"账号切换已停止；审核证据正在保存到: {event_dir}")
            raise
        except Exception as error:
            event_dir = task._finish_account_switch_evidence(
                False, str(error), stage="failed")
            if event_dir is not None:
                task.log_warning(f"账号切换失败；最近证据已保存到: {event_dir}")
            raise
        finally:
            if mouse_reset_was_enabled and mouse_reset_task is not None:
                mouse_reset_task.enable()


__all__ = ["LoginFlowService"]
