"""Compact toggle buttons and a floating, downward-opening naming selector."""
from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QRegion
from PySide6.QtWidgets import QApplication, QComboBox, QListWidget, QPushButton, QSizePolicy, QStyle, QStyleOptionButton


class ToggleButton(QPushButton):
    def __init__(self, text):
        super().__init__(text)
        self.setCheckable(True)
        self.setObjectName('settingToggle')
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setIconSize(QSize(16, 16))
        self.toggled.connect(self.update_check_icon)
        self.update_check_icon()

    def sizeHint(self):
        size = super().sizeHint()
        size.setWidth(4 + self.iconSize().width() + 4 + self.fontMetrics().horizontalAdvance(self.text()) + 4)
        return size

    def minimumSizeHint(self):
        return self.sizeHint()

    def paintEvent(self, event):
        option = QStyleOptionButton()
        self.initStyleOption(option)
        option.text = ''
        option.icon = QIcon()
        painter = QPainter(self)
        self.style().drawControl(QStyle.ControlElement.CE_PushButton, option, painter, self)
        mode = QIcon.Mode.Normal if self.isEnabled() else QIcon.Mode.Disabled
        icon_width = self.iconSize().width()
        self.icon().paint(painter, QRect(4, (self.height() - 16) // 2, icon_width, 16),
                          Qt.AlignmentFlag.AlignCenter, mode)
        painter.setPen(QColor('#a0aaba' if not self.isEnabled() else 'white' if self.isChecked() else '#64748b'))
        painter.drawText(self.rect().adjusted(4 + icon_width + 4, 0, -4, 0),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.text())

    def update_check_icon(self):
        icon = QIcon()
        for mode, color in ((QIcon.Mode.Normal, 'white' if self.isChecked() else '#64748b'),
                            (QIcon.Mode.Disabled, '#a0aaba')):
            pixmap = QPixmap(32, 32)
            pixmap.setDevicePixelRatio(2)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(QPen(QColor(color), 1.4))
            painter.drawEllipse(QRectF(1, 1, 14, 14))
            if self.isChecked():
                check = QPainterPath()
                check.moveTo(4, 8)
                check.lineTo(7, 11)
                check.lineTo(12, 5)
                painter.drawPath(check)
            painter.end()
            for state in (QIcon.State.Off, QIcon.State.On):
                icon.addPixmap(pixmap, mode, state)
        self.setIcon(icon)


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
