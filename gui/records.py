"""Sortable download records with stable item identity during live updates."""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QHeaderView, QTableWidget, QTableWidgetItem


class RecordItem(QTableWidgetItem):
    def __lt__(self, other):
        value = self.data(Qt.ItemDataRole.UserRole)
        other_value = other.data(Qt.ItemDataRole.UserRole)
        if value is not None and other_value is not None:
            if value != other_value:
                return value < other_value
            return self.data(Qt.ItemDataRole.UserRole + 1) < other.data(Qt.ItemDataRole.UserRole + 1)
        return super().__lt__(other)


class RecordTable(QTableWidget):
    def __init__(self):
        super().__init__(0, 4)
        self.records = {}
        self.sequence = 0
        self.setObjectName('downloadRecords')
        self.setHorizontalHeaderLabels(['序号', '文件名', '大小', '状态'])
        header = self.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setMinimumSectionSize(64)
        header.setFixedHeight(38)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.setColumnWidth(0, 72)
        self.setColumnWidth(2, 108)
        self.setColumnWidth(3, 88)
        self.verticalHeader().hide()
        self.verticalHeader().setDefaultSectionSize(36)
        self.setShowGrid(False)
        self.setWordWrap(False)
        self.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.setVerticalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
        self.setAlternatingRowColors(True)
        self.setSortingEnabled(True)
        self.sortItems(0, Qt.SortOrder.AscendingOrder)
        header.sortIndicatorChanged.connect(lambda *_: self.scrollToTop())
        self.setStyleSheet('''
            QTableWidget#downloadRecords {
                background: #ffffff; alternate-background-color: #f8fafc;
                color: #334155; border: 1px solid #e2e8f0;
                border-radius: 7px; padding: 0px;
                selection-background-color: #e8f1fd; selection-color: #1e40af;
            }
            QTableWidget#downloadRecords::item { padding: 0px 10px; border: none; }
            QHeaderView { background: #f1f5f9; }
            QHeaderView::section {
                background: #f1f5f9; color: #64748b; font-weight: 600;
                border: none; border-bottom: 1px solid #e2e8f0;
                padding: 0px 10px;
            }
            QScrollBar:vertical { background: #f8fafc; width: 10px; margin: 3px 1px; }
            QScrollBar::handle:vertical { background: #cbd5e1; min-height: 36px; border-radius: 4px; }
            QScrollBar::handle:vertical:hover { background: #94a3b8; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
            QScrollBar:horizontal { background: #f8fafc; height: 10px; margin: 1px 3px; }
            QScrollBar::handle:horizontal { background: #cbd5e1; min-width: 36px; border-radius: 4px; }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0px; }
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; }
        ''')

    def clear_records(self):
        self.records.clear()
        self.setRowCount(0)
        self.sequence = 0

    def update_record(self, path, state=None, size=None, size_text=None):
        sorting = self.isSortingEnabled()
        created = path not in self.records
        if created:
            self.setSortingEnabled(False)
        try:
            if created:
                if len(self.records) >= 2000:
                    oldest = next(iter(self.records))
                    self.removeRow(self.records.pop(oldest)[0].row())
                self.sequence += 1
                items = [RecordItem(str(self.sequence)), RecordItem(Path(path).name),
                         RecordItem('—'), RecordItem('下载中')]
                self.records[path] = items
                row = self.rowCount()
                self.insertRow(row)
                for col, item in enumerate(items):
                    item.setToolTip(path)
                    item.setData(Qt.ItemDataRole.UserRole + 1, self.sequence)
                    self.setItem(row, col, item)
                for col in (0, 3):
                    items[col].setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                items[2].setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                items[0].setData(Qt.ItemDataRole.UserRole, self.sequence)
                items[1].setData(Qt.ItemDataRole.UserRole, Path(path).name.casefold())
                items[2].setData(Qt.ItemDataRole.UserRole, -1)
            items = self.records[path]
            if state is not None:
                items[3].setText(state)
                items[3].setData(Qt.ItemDataRole.UserRole, state)
                color = {'下载中': '#2563eb', '已完成': '#15803d', '已失败': '#dc2626',
                         '已跳过': '#94a3b8', '已停止': '#b45309'}.get(state, '#64748b')
                items[3].setForeground(QColor(color))
            if size_text is not None:
                items[2].setText(size_text)
                items[2].setData(Qt.ItemDataRole.UserRole, size if size is not None else -1)
        finally:
            if created:
                self.setSortingEnabled(sorting)
        if created:
            self.scrollToItem(items[0])

    def state(self, path):
        return self.records[path][3].text() if path in self.records else None
