"""Display revisions are release metadata, never filesystem/user-edit times."""
from src.activity_catalog import ACTIVITIES
ACTIVITY_REVISIONS = {'ResonanceSimulationTask': 2026091601, 'EchoesRemainTask': 2026091401,
                      'PianoTeachingTask': 2026091101, 'CharacterTrialTask': 2026091100,
                      'SecondSolTask': 2026091001}
PLACEHOLDER_REVISION = 2026091101
PLACEHOLDERS = tuple((key, ACTIVITIES[key]) for key in ('tiangong_treasure', 'dango_brawl', 'dream_box'))


def current_placeholders():
    from src.evidence.model import current_projects
    current = current_projects()
    return tuple(entry for entry in PLACEHOLDERS if entry[0] in current)


def current_activity_task(task):
    from src.evidence.model import TASK_PROJECTS, current_projects
    project = TASK_PROJECTS.get(type(task).__name__)
    return project is None or project in current_projects()


def activity_revision(task):
    return ACTIVITY_REVISIONS.get(type(task).__name__, 0)


def placeholder_card(project, title, parent):
    from qfluentwidgets import PushButton
    from src.gui.SectionPanel import SectionPanel
    from ok import og
    class PlaceholderCard(SectionPanel):
        @property
        def isExpand(self):
            return self.toggle_button.isChecked()

        def setExpand(self, expanded):
            self.set_expanded(expanded)
    from src.evidence.cycles import cycle_label
    card = PlaceholderCard(title, cycle_label(project), parent, collapsible=True)
    card.task = project
    card.set_summary('手动留证')
    from src.gui.CodexTheme import COLORS
    card.layout().setContentsMargins(0, 0, 0, 0)
    card.layout().setSpacing(0)
    card.header.layout_row.setContentsMargins(16, 8, 12, 8)
    card.content_layout.setContentsMargins(16, 8, 16, 12)
    card.setStyleSheet(f'QWidget#codexSection {{ background: {COLORS["panel"]}; '
                      f'border: 1px solid {COLORS["border"]}; border-radius: 8px; }}')
    button = PushButton('保存当前画面为证据', card)
    def capture():
        page = getattr(og.main_window, 'completion_check_tab', None)
        if page is not None:
            og.main_window.switchTo(page)
            page.capture_evidence(project)
    button.clicked.connect(capture)
    card.add_widget(button)
    return card
