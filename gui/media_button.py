"""Player-style download controls with a large icon above the caption."""
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPolygonF
from PySide6.QtWidgets import QPushButton, QStyle, QStyleOptionButton


class MediaButton(QPushButton):
    def __init__(self, text, symbol):
        super().__init__(text)
        self.symbol = symbol

    def set_symbol(self, symbol):
        self.symbol = symbol
        self.update()

    def paintEvent(self, event):
        option = QStyleOptionButton()
        self.initStyleOption(option)
        option.text = ''
        painter = QPainter(self)
        self.style().drawControl(QStyle.ControlElement.CE_PushButton, option, painter, self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        active = self.property('active')
        color = QColor('#713f12' if active else '#ffffff')
        if not self.isEnabled():
            color = QColor('#c88b8b' if self.symbol == 'stop' else '#94a3b8')
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        # Upper two thirds are reserved for the symbol; the caption stays below.
        icon_height = self.height() * 2 / 3
        cx, cy = self.width() / 2, icon_height / 2 + 3
        size = min(self.width() * 0.45, icon_height * 0.66)
        if self.symbol == 'play':
            painter.drawPolygon(QPolygonF([
                QPointF(cx - size * 0.38, cy - size / 2),
                QPointF(cx - size * 0.38, cy + size / 2),
                QPointF(cx + size * 0.5, cy),
            ]))
        elif self.symbol == 'pause':
            for x in (cx - size / 2, cx + size * 0.15):
                painter.drawRoundedRect(QRectF(x, cy - size / 2, size * 0.35, size), 2, 2)
        else:
            painter.drawRoundedRect(QRectF(cx - size / 2, cy - size / 2, size, size), 3, 3)
        painter.setPen(color)
        painter.setFont(self.font())
        painter.drawText(QRectF(0, icon_height, self.width(), self.height() - icon_height - 5),
                         Qt.AlignmentFlag.AlignCenter, self.text())
