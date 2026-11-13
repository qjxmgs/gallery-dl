"""Selectable URL cards with stable inline editing geometry."""
from urllib.parse import urlsplit
import weakref
from PySide6.QtCore import Qt, Signal, QRectF, QTimer
from PySide6.QtGui import QColor, QPainter, QPen, QCursor
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
        self.drag_origin = None
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setToolTip('拖动排序：中间 70% 交换，上下边缘插入')
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
        self.title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
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

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_origin = event.globalPosition().toPoint()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.drag_origin is not None and event.buttons() & Qt.MouseButton.LeftButton:
            point = event.globalPosition().toPoint()
            if self.owner.drag_card is None:
                if (point - self.drag_origin).manhattanLength() < QApplication.startDragDistance():
                    return
                if not self.owner.commit_edits():
                    self.drag_origin = None
                    return
                self.owner.drag_card = self
                self.owner.scroll_timer.start()
            self.owner.update_drop(point)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_origin = None
            if self.owner.drag_card is self:
                self.owner.update_drop(event.globalPosition().toPoint())
                self.owner.finish_drag()
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.drag_origin = None
            self.owner.finish_drag(False)
        else:
            super().keyPressEvent(event)

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
        self.drag_card = None
        self.drop_target = None
        self.scroll_timer = QTimer(self)
        self.scroll_timer.setInterval(40)
        self.scroll_timer.timeout.connect(self.scroll_drag)
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
        self.scroll = scroll
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        self.content = content
        self.drop_indicator = QFrame(content)
        self.drop_indicator.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.drop_indicator.hide()
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
        self.hint = QLabel()
        self.hint.setObjectName('muted')
        layout.addWidget(self.hint)
        self.hint.hide()
        self.setMinimumHeight(230)
        self.refresh()

    def target_at(self, y):
        for index, card in enumerate(self.cards):
            top, height = card.y(), card.height()
            if y < top + height * 0.15:
                return ('insert', index)
            if y <= top + height * 0.85:
                return ('swap', index)
            if y < top + height:
                return ('insert', index + 1)
        return ('insert', len(self.cards))

    def update_drop(self, global_pos):
        self.drop_indicator.hide()
        self.drop_target = None
        if not self.isEnabled() or self.drag_card not in self.cards:
            return
        viewport = self.scroll.viewport()
        if not viewport.rect().contains(viewport.mapFromGlobal(global_pos)):
            return
        mode, index = self.target_at(self.content.mapFromGlobal(global_pos).y())
        source = self.cards.index(self.drag_card)
        if (mode == 'swap' and index == source) or (mode == 'insert' and index in (source, source + 1)):
            return
        self.drop_target = (mode, index)
        if mode == 'swap':
            self.drop_indicator.setStyleSheet('background: transparent; border: 2px solid #16a34a; border-radius: 10px;')
            self.drop_indicator.setGeometry(self.cards[index].geometry())
        else:
            self.drop_indicator.setStyleSheet('background: #16a34a; border: none;')
            if index == 0:
                y = self.cards[0].y()
            elif index == len(self.cards):
                y = self.cards[-1].geometry().bottom() + 2
            else:
                y = (self.cards[index - 1].geometry().bottom() + self.cards[index].y()) // 2
            self.drop_indicator.setGeometry(0, y, self.cards[0].width(), 3)
        self.drop_indicator.show()
        self.drop_indicator.raise_()

    def scroll_drag(self):
        if not self.isEnabled() or not QApplication.mouseButtons() & Qt.MouseButton.LeftButton:
            self.finish_drag(False)
            return
        pos = QCursor.pos()
        viewport = self.scroll.viewport()
        local = viewport.mapFromGlobal(pos)
        if viewport.rect().contains(local):
            step = -12 if local.y() < 28 else 12 if local.y() > viewport.height() - 28 else 0
            bar = self.scroll.verticalScrollBar()
            bar.setValue(bar.value() + step)
        self.update_drop(pos)

    def finish_drag(self, apply=True):
        card, target = self.drag_card, self.drop_target
        self.scroll_timer.stop()
        self.drop_indicator.hide()
        self.drag_card = self.drop_target = None
        if card is not None:
            card.drag_origin = None
        if not apply or not self.isEnabled() or card not in self.cards or target is None:
            return
        source = self.cards.index(card)
        mode, index = target
        if mode == 'swap':
            self.cards[source], self.cards[index] = self.cards[index], card
        else:
            self.cards.pop(source)
            self.cards.insert(index - (source < index), card)
        for item in self.cards:
            self.rows.removeWidget(item)
        for index, item in enumerate(self.cards):
            self.rows.insertWidget(index, item)
        self.rows.activate()
        self.changed.emit()

    def entries(self):
        return [{'url': c.url, 'checked': c.check.isChecked()} for c in self.cards]

    def selected_urls(self):
        return [c.url for c in self.cards if c.check.isChecked()]

    def set_entries(self, entries):
        self.finish_drag(False)
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
        self.finish_drag(False)
        self.cards.remove(card)
        self.rows.removeWidget(card)
        card.deleteLater()
        self.refresh()
        self.changed.emit()

    def paste(self):
        urls = list(dict.fromkeys(line.strip() for line in QApplication.clipboard().text().splitlines() if line.strip()))
        if not urls or any(not valid_url(url) for url in urls):
            self.hint.setText('请复制有效的 HTTP / HTTPS 链接，每行一个')
            self.hint.show()
            return
        existing = {c.url for c in self.cards}
        self.set_entries(self.entries() + [{'url': u, 'checked': True} for u in urls if u not in existing])
        self.hint.clear()
        self.hint.hide()

    def commit_edits(self):
        return all(not c.editor.editing or c.editor.commit() for c in self.cards)

    # Text import/export also supports migration from the previous editor.
    def setPlainText(self, text):
        self.set_entries([{'url': line.strip(), 'checked': True} for line in text.splitlines() if line.strip()])

    def toPlainText(self):
        return '\n'.join(c.url for c in self.cards)

    def clear(self):
        self.set_entries([])
