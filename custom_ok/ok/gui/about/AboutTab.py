from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QPlainTextEdit, QVBoxLayout
from qfluentwidgets import BodyLabel

from ok.gui.about.VersionCard import VersionCard
from ok.gui.util.pyappify_startup import get_startup_version_change
from ok.gui.widget.Tab import Tab
from ok.util.file import get_path_relative_to_exe


class AboutTab(Tab):
    def __init__(self, config):
        super().__init__()
        self.version_card = VersionCard(config, get_path_relative_to_exe(config.get('gui_icon')),
                                        config.get('gui_title'), config.get('version'),
                                        config.get('debug'), self)
        # The About page uses the same section rhythm as the rest of the app.
        self.add_widget(self.version_card)

        if version_change := get_startup_version_change():
            update_note_label = BodyLabel()
            update_note_label.setText(self._format_update_note(version_change.content))
            update_note_label.setWordWrap(True)
            update_note_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            update_note_label.setContentsMargins(0, 0, 0, 0)
            self.add_card(self._startup_version_change_title(version_change), update_note_label)

        # 更新日志（全历史 + 原版更新提醒）
        self._add_update_log_card()
        # 作者的话
        self._add_author_card()

    @staticmethod
    def _read_update_log():
        try:
            return Path(get_path_relative_to_exe('更新日志.md')).read_text(encoding='utf-8')
        except (OSError, UnicodeError):
            return '更新日志未能读取，请检查安装文件是否完整。'

    def _add_update_log_card(self):
        try:
            update_log_text = QPlainTextEdit()
            update_log_text.setReadOnly(True)
            update_log_text.setMaximumHeight(220)
            upstream_note = ''
            try:
                from src.upstream_check import has_upstream_update
                has_upd, msg, found_date = has_upstream_update()
                if has_upd:
                    upstream_note = f'【⚠️ 原版 okww 有更新】\n检测到原版更新（{found_date}）：{msg}\n请及时检查合并原版更新内容\n\n'
            except Exception:
                pass
            update_log_text.setPlainText(upstream_note + self._read_update_log())
            widget = QWidget()
            layout = QVBoxLayout(widget)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(update_log_text)
            self.add_card(self.tr('更新日志'), widget)
        except Exception:
            pass

    def _add_author_card(self):
        try:
            author_text = QPlainTextEdit()
            author_text.setReadOnly(True)
            author_text.setMaximumHeight(225)
            author_text.setPlainText(self.tr(
                '如果有人不小心下载到了这个版本，请注意，这是okww的个人自用AI魔改版本，'
                '作者本身是个小白，没有任何计算机经验，此版本存在大量问题，上传github仅为了方便更新。\n'
                '本作品的原版是okww，点击上方的github链接应该就是，原作者留下的很多东西我都没改，赞助也是他的。\n'
                '如果你下定决心使用这个版本，有什么问题可以反馈，有需求也可以提，但是不一定看得到，我不太会看。\n'
                '此版本的核心是优化了多账号支持，但是做的并不好，多账号每日部分还在尝试。'))
            widget = QWidget()
            layout = QVBoxLayout(widget)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(author_text)
            self.add_card(self.tr('作者的话'), widget)
        except Exception:
            pass

    @staticmethod
    def _format_update_note(content):
        """升级说明统一格式：'内容；v1.03.41' → 'V1.03.41：内容'。"""
        try:
            import re
            m = re.search(r'；?\s*[vV]?(\d+\.\d+\.\d+)\s*$', content or '')
            if m:
                return f'V{m.group(1)}：{(content[:m.start()]).rstrip("； ")}'
        except Exception:
            pass
        return content

    def _startup_version_change_title(self, version_change):
        if version_change.action == "update":
            title = self.tr("Update success {from_version} -> {to_version}")
        elif version_change.action == "downgrade":
            title = self.tr("Downgrade success {from_version} -> {to_version}")
        else:
            return version_change.title
        return title.format(from_version=version_change.from_version, to_version=version_change.to_version)
