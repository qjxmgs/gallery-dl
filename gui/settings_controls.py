"""Compact switches and a floating, downward-opening naming selector."""
from PySide6.QtCore import QEvent, QPoint, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QRegion
from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QListWidget


class ToggleSwitch(QCheckBox):
    def sizeHint(self):
        return QSize(self.fontMetrics().horizontalAdvance(self.text()) + 46, 32)

    def minimumSizeHint(self):
        return self.sizeHint()

    def hitButton(self, pos):
        return self.rect().contains(pos)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QColor('#233047' if self.isEnabled() else '#94a3b8'))
        p.drawText(self.rect().adjusted(0, 0, -42, 0), Qt.AlignmentFlag.AlignVCenter, self.text())
        x, y = self.width() - 34, (self.height() - 20) / 2
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(('#2563eb' if self.isChecked() else '#a4afbf') if self.isEnabled() else '#cbd5e2'))
        p.drawRoundedRect(QRectF(x, y, 34, 20), 10, 10)
        p.setBrush(QColor('white'))
        p.drawEllipse(QRectF(x + (16 if self.isChecked() else 2), y + 2, 16, 16))
        if self.hasFocus():
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QColor('#2782ed'))
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 4, 4)


class NamingCombo(QComboBox):
    """Open a separate popup without changing the surrounding layout."""
    def __init__(self):
        super().__init__()
        self.options = None
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(12)

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor('#64748b' if self.isEnabled() else '#94a3b8'), 1.5))
        x, y = self.width() - 15, self.height() // 2
        p.drawLine(x - 4, y - 2, x, y + 2)
        p.drawLine(x, y + 2, x + 4, y - 2)

    def showPopup(self):
        if not self.isEnabled():
            return
        if self.options is not None and self.options.isVisible():
            self.hidePopup()
            return
        if self.options is None:
            self.options = QListWidget(self.parentWidget())
            self.options.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
            self.options.setObjectName('namingOptions')
            self.options.setAccessibleName('文件命名选项')
            self.options.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.options.itemClicked.connect(self.choose)
            self.options.itemActivated.connect(self.choose)
        self.options.clear()
        for index in range(self.count()):
            self.options.addItem(self.itemText(index))
            self.options.item(index).setToolTip(self.itemText(index))
        self.options.setCurrentRow(self.currentIndex())
        self.options.ensurePolished()
        self.options.setFixedHeight(sum(self.options.sizeHintForRow(i) for i in range(self.count())) + 14)
        self.options.setFixedWidth(self.width())
        self.options.move(self.mapToGlobal(QPoint(0, self.height() + 4)))
        outline = QPainterPath()
        outline.addRoundedRect(QRectF(self.options.rect()), 8, 8)
        self.options.setMask(QRegion(outline.toFillPolygon().toPolygon()))
        self.options.show()
        self.options.setFocus()
        QApplication.instance().installEventFilter(self)

    def choose(self, item):
        self.setCurrentIndex(self.options.row(item))
        self.hidePopup()
        self.setFocus()

    def hidePopup(self):
        if self.options is not None:
            self.options.hide()
        QApplication.instance().removeEventFilter(self)
        super().hidePopup()

    def eventFilter(self, watched, event):
        if watched is self.options and event.type() == QEvent.Type.Hide:
            QApplication.instance().removeEventFilter(self)
        if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
            self.hidePopup()
            self.setFocus()
            return True
        if event.type() == QEvent.Type.MouseButtonPress:
            point = event.globalPosition().toPoint()
            if self.rect().contains(self.mapFromGlobal(point)):
                # Popup windows receive outside presses before the combo does.
                # Consume this press so Qt cannot replay it and reopen the list.
                self.options.setAttribute(Qt.WidgetAttribute.WA_NoMouseReplay)
                self.hidePopup()
                self.setFocus()
                return True
            if not self.options.rect().contains(self.options.mapFromGlobal(point)):
                self.hidePopup()
        return super().eventFilter(watched, event)
