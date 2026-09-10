"""Continuous helpers, grouped by purpose without changing enable state."""
from ok import og
from ok.gui.tasks.TaskCard import TaskCard
from ok.gui.tasks.TaskTab import TaskTab
from src.gui.navigation_sections import helper_category, HELPER_CATEGORIES


class TriggerTaskTab(TaskTab):
    def __init__(self):
        super().__init__()
        self.taskCardLayout.setSpacing(8)
        self.card_widgets = []
        from ok.gui.Communicate import communicate
        communicate.task_list_updated.connect(self.refresh_ui)
        self.refresh_ui()

    def refresh_ui(self):
        for card in self.card_widgets:
            self.remove_task_card(card)
            card.deleteLater()
        self.card_widgets.clear()
        self.reset_task_groups()
        tasks = [task for task in og.executor.trigger_tasks if getattr(task, 'visible', True)]
        tasks.sort(key=lambda task: HELPER_CATEGORIES.index(helper_category(task)))
        for task in tasks:
            card = TaskCard(task, False)
            self.card_widgets.append(card)
            self.add_task_card(card, helper_category(task))

    def in_current_list(self, task):
        return task in og.executor.trigger_tasks and getattr(task, 'visible', True)
