"""Selectable URL cards with stable inline editing geometry."""
from urllib.parse import urlsplit
import weakref
from PySide6.QtCore import Qt, Signal, QRectF
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QApplication, QCheckBox, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget, QSizePolicy)


def valid_url(url):
    try:
        parsed = urlsplit(url)
        return parsed.scheme in ('http', 'https') and bool(parsed.hostname)
    except ValueError:
        return False


class RoundCheck(QCheckBox):
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        selected = self.checkState() != Qt.CheckState.Unchecked
        p.setPen(QPen(QColor('#2580ed' if selected else '#a4afbf'), 1.4))
        p.setBrush(QColor('#2580ed' if selected else '#ffffff'))
        p.drawEllipse(QRectF(2, (self.height()-20)/2, 20, 20))
        if selected:
            p.setPen(QPen(QColor('white'), 2))
            y = self.height()/2
            if self.checkState() == Qt.CheckState.PartiallyChecked:
                p.drawLine(7, int(y), 17, int(y))
            else:
                p.drawLine(7, int(y), 11, int(y+4))
                p.drawLine(11, int(y+4), 18, int(y-4))
        p.setPen(QColor('#334155' if self.isEnabled() else '#94a3b8'))
        p.drawText(self.rect().adjusted(30, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter, self.text())
        p.end()

    def hitButton(self, pos):
        return self.rect().contains(pos)

    def nextCheckState(self):
        self.setCheckState(Qt.CheckState.Unchecked if self.checkState() == Qt.CheckState.Checked else Qt.CheckState.Checked)


class UrlEdit(QLineEdit):
    def __init__(self, card):
        super().__init__(card.url)
        self.card = weakref.proxy(card)
        self.editing = False
        self.setReadOnly(True)
        self.setFixedHeight(26)
        self.setCursorPosition(0)
        self.setToolTip(card.url)
        self.returnPressed.connect(self.commit)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.isReadOnly():
            self.show_url()

    def show_url(self):
        self.setText(self.fontMetrics().elidedText(self.card.url, Qt.TextElideMode.ElideRight, max(10, self.width()-8)))
        self.setCursorPosition(0)

    def mousePressEvent(self, event):
        if not self.editing:
            self.editing = True
            self.setReadOnly(False)
            self.setText(self.card.url)
        super().mousePressEvent(event)

    def focusInEvent(self, event):
        if not self.editing:
            self.editing = True
            self.setReadOnly(False)
            self.setText(self.card.url)
        super().focusInEvent(event)

    def commit(self):
        url = self.text().strip()
        if not valid_url(url) or any(c.editor is not self and c.url == url for c in self.card.owner.cards):
            self.setProperty('invalid', True)
            self.setToolTip('请输入有效且不重复的 HTTP / HTTPS 地址')
            self.style().unpolish(self)
            self.style().polish(self)
            return False
        self.card.url = url
        self.finish()
        self.card.owner.changed.emit()
        return True

    def finish(self):
        self.editing = False
        self.setReadOnly(True)
        self.setProperty('invalid', False)
        self.show_url()
        self.setToolTip(self.card.url)
        self.card.update_title()
        self.style().unpolish(self)
        self.style().polish(self)

    def focusOutEvent(self, event):
        if self.editing:
            self.commit()
        super().focusOutEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.finish()
        else:
            super().keyPressEvent(event)


class LinkCard(QFrame):
    def __init__(self, owner, url, checked):
        super().__init__()
        self.owner, self.url = weakref.proxy(owner), url
        self.setObjectName('linkCard')
        self.setFixedHeight(64)
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 8, 8, 8)
        self.check = RoundCheck()
        self.check.setFixedSize(26, 28)
        self.check.setAccessibleName('选择 ' + url)
        self.check.setChecked(checked)
        row.addWidget(self.check)
        body = QVBoxLayout()
        body.setSpacing(0)
        self.title = QLabel()
        self.title.setObjectName('cardTitle')
        self.title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        body.addWidget(self.title)
        self.editor = UrlEdit(self)
        body.addWidget(self.editor)
        row.addLayout(body, 1)
        self.remove = QPushButton('×')
        self.remove.setObjectName('removeLink')
        self.remove.setFixedSize(22, 26)
        self.remove.setToolTip('移除此链接')
        self.remove.clicked.connect(self.remove_self)
        row.addWidget(self.remove)
        self.remove.setVisible(False)
        policy = self.remove.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        self.remove.setSizePolicy(policy)
        self.check.toggled.connect(self.checked_changed)
        self.update_title()
        self.refresh(False)

    def remove_self(self):
        self.owner.remove_card(self)

    def checked_changed(self):
        self.refresh()

    def enterEvent(self, event):
        self.remove.show()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.remove.hide()
        super().leaveEvent(event)

    def update_title(self):
        parsed = urlsplit(self.url)
        title = parsed.path.strip('/').split('/')[0] or parsed.hostname or self.url
        self.title.setText(title)
        self.title.setToolTip(title)
        self.check.setAccessibleName('选择 ' + self.url)

    def refresh(self, emit=True):
        self.setProperty('selected', self.check.isChecked())
        self.style().unpolish(self)
        self.style().polish(self)
        if emit is not False:
            self.owner.refresh()
            self.owner.changed.emit()


class LinkList(QWidget):
    changed = Signal()

    def __init__(self):
        super().__init__()
        self.cards = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        toolbar = QHBoxLayout()
        self.all = RoundCheck('全选')
        self.all.setFixedSize(78, 30)
        self.all.clicked.connect(self.select_all)
        toolbar.addWidget(self.all)
        self.count = QLabel()
        toolbar.addStretch()
        toolbar.addWidget(self.count)
        layout.addLayout(toolbar)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        self.rows = QVBoxLayout(content)
        self.rows.setContentsMargins(0, 0, 4, 0)
        self.rows.setSpacing(8)
        self.rows.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)
        self.add = QPushButton('＋ 粘贴链接')
        self.add.setObjectName('addLinks')
        self.add.clicked.connect(self.paste)
        layout.addWidget(self.add)
        self.hint = QLabel('仅下载勾选的链接')
        self.hint.setObjectName('muted')
        layout.addWidget(self.hint)
        self.setMinimumHeight(230)
        self.refresh()

    def entries(self):
        return [{'url': c.url, 'checked': c.check.isChecked()} for c in self.cards]

    def selected_urls(self):
        return [c.url for c in self.cards if c.check.isChecked()]

    def set_entries(self, entries):
        for c in self.cards:
            self.rows.removeWidget(c)
            c.deleteLater()
        self.cards = []
        seen = set()
        for entry in entries:
            url = entry['url'].strip()
            if url and url not in seen:
                seen.add(url)
                card = LinkCard(self, url, entry.get('checked', True))
                self.cards.append(card)
                self.rows.insertWidget(self.rows.count()-1, card)
        self.refresh()
        self.changed.emit()

    def refresh(self):
        count = len(self.selected_urls())
        self.count.setText(f'已选 {count} / {len(self.cards)}')
        self.all.setCheckState(Qt.CheckState.Unchecked if not count else Qt.CheckState.Checked if count == len(self.cards) else Qt.CheckState.PartiallyChecked)

    def select_all(self):
        checked = self.all.isChecked()
        for card in self.cards:
            card.check.setChecked(checked)
        self.refresh()

    def remove_card(self, card):
        self.cards.remove(card)
        self.rows.removeWidget(card)
        card.deleteLater()
        self.refresh()
        self.changed.emit()

    def paste(self):
        urls = list(dict.fromkeys(line.strip() for line in QApplication.clipboard().text().splitlines() if line.strip()))
        if not urls or any(not valid_url(url) for url in urls):
            self.hint.setText('请复制有效的 HTTP / HTTPS 链接，每行一个')
            return
        existing = {c.url for c in self.cards}
        self.set_entries(self.entries() + [{'url': u, 'checked': True} for u in urls if u not in existing])
        self.hint.setText('仅下载勾选的链接')

    def commit_edits(self):
        return all(not c.editor.editing or c.editor.commit() for c in self.cards)

    # Text import/export also supports migration from the previous editor.
    def setPlainText(self, text):
        self.set_entries([{'url': line.strip(), 'checked': True} for line in text.splitlines() if line.strip()])

    def toPlainText(self):
        return '\n'.join(c.url for c in self.cards)

    def clear(self):
        self.set_entries([])
