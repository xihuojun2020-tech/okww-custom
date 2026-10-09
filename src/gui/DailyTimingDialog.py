"""Read-only account daily duration history."""
from datetime import datetime

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QTreeWidget, QTreeWidgetItem, QVBoxLayout
from src.daily_timing import PROCESS_SESSION, duration_text

RESULTS = {'running': '运行中', 'completed': '完成', 'failed': '失败',
           'stopped': '已停止', 'partial_failure': '部分失败'}


def history_rows(batches, profile_id):
    days = {}
    for batch in batches:
        day = days.setdefault(batch['game_day'], {'total': 0, 'rows': []})
        for attempt in batch['attempts']:
            if attempt['profile_id'] != profile_id:
                continue
            finished = attempt['finished_at']
            elapsed = attempt['elapsed_seconds']
            result = RESULTS[attempt['result']]
            if finished is None:
                if batch['session'] == PROCESS_SESSION and batch['finished_at'] is None:
                    result = '运行中'
                    elapsed = (datetime.now(datetime.fromisoformat(attempt['started_at']).tzinfo)
                               - datetime.fromisoformat(attempt['started_at'])).total_seconds()
                else:
                    result = '中断（结束时间未知）'
            else:
                day['total'] += elapsed
            day['rows'].append([
                f'第{attempt["attempt_number"]}次 · {attempt["phase"]}',
                datetime.fromisoformat(attempt['started_at']).strftime('%m-%d %H:%M:%S'),
                datetime.fromisoformat(finished).strftime('%m-%d %H:%M:%S') if finished else '—',
                duration_text(elapsed) if finished or result == '运行中' else '未知', result,
                attempt['reason'], duration_text(batch['elapsed_seconds']) if batch['finished_at'] else '—'])
    return days


class DailyTimingDialog(QDialog):
    def __init__(self, repository, profile_id, parent=None):
        super().__init__(parent)
        self.repository, self.profile_id = repository, profile_id
        self.setWindowTitle('每日耗时记录')
        self.resize(1000, 500)
        layout = QVBoxLayout(self)
        self.tree = QTreeWidget(self)
        self.tree.setHeaderLabels(['日期 / 轮次', '开始时间', '结束时间', '本次耗时', '结果', '原因', '整轮耗时'])
        layout.addWidget(self.tree)
        buttons = QDialogButtonBox(QDialogButtonBox.Close, self)
        buttons.button(QDialogButtonBox.Close).setText('关闭')
        buttons.rejected.connect(self.reject)
        buttons.addButton('刷新', QDialogButtonBox.ActionRole).clicked.connect(self.refresh)
        layout.addWidget(buttons)
        self.refresh()

    def refresh(self):
        self.tree.clear()
        try:
            days = history_rows(self.repository.daily_timings(self.profile_id), self.profile_id)
        except Exception as error:
            QTreeWidgetItem(self.tree, ['读取时间记录失败', '', '', '', type(error).__name__])
            return
        for date, day in days.items():
            group = QTreeWidgetItem(self.tree, [date, '', '', '累计已记录 ' + duration_text(day['total'])])
            for row in day['rows']:
                QTreeWidgetItem(group, row)
            group.setExpanded(True)
        if not days:
            QTreeWidgetItem(self.tree, ['暂无每日耗时记录'])
        for column in range(5):
            self.tree.resizeColumnToContents(column)
