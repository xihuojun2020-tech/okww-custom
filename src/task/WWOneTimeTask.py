from src.runtime.combat_api import is_native, is_post_message_interaction


class WWOneTimeTask:

    def run(self):
        if getattr(self, '_android_boundary', lambda: None)() is not None:
            self.sleep(0.5)
            return
        if is_native():
            # Native input targets the foreground device; the legacy cursor reset
            # repairs background PostMessage capture and has no native owner.
            self.ensure_in_front()
            self.sleep(0.5)
            return
        from src.task.MouseResetTask import MouseResetTask
        mouse_reset_task = self.executor.get_task_by_class(MouseResetTask)
        mouse_reset_task.run()
        if is_post_message_interaction(self.executor.interaction):
            self.executor.interaction.activate()
        self.sleep(0.5)
