"""Chinese split-pane Qt Widgets download workbench."""
import codecs
import json
import os
from pathlib import Path
import re
import sys
import subprocess
from datetime import datetime
from http.cookiejar import MozillaCookieJar
from urllib.parse import urlsplit

from PySide6.QtCore import QDir, QProcess, QProcessEnvironment, QSettings, QTimer, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QSplitter, QStyle, QToolButton, QVBoxLayout, QWidget, QScrollArea, QFrame,
)
from .window_chrome import LogWindow, follow_native_drag
from .records import RecordTable
from .process_control import PausedProcessTree
from .media_button import MediaButton
from .link_list import LinkList
from .settings_controls import ToggleButton, NamingCombo
from .naming import DATE_FORMATS, DEFAULT_DATE_FORMAT, DATE_FORMAT_ENV

ROOT = Path(__file__).resolve().parent.parent
ARCHIVE_NAME = '.gallery-dl-archive.sqlite3'


def human_bytes(value):
    value = float(value or 0)
    for unit in ('B', 'KB', 'MB', 'GB'):
        if value < 1024 or unit == 'GB':
            return f'{value:.1f} {unit}'
        value /= 1024


def validate_inputs(text, cookies, directory):
    urls = list(dict.fromkeys(line.strip()
                for line in text.splitlines() if line.strip()))
    if not urls:
        raise ValueError('请至少输入一个下载链接，每行一个。')
    for url in urls:
        parsed = urlsplit(url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname:
            raise ValueError(f'链接格式不正确：{url}')
    if cookies:
        if not Path(cookies).is_file():
            raise ValueError('Cookies 文件不存在。')
        try:
            MozillaCookieJar(cookies).load(
                ignore_discard=True, ignore_expires=True)
        except Exception:
            raise ValueError(
                'Cookies 文件无法读取或不是 Netscape cookies.txt 格式。') from None
    if not directory.strip():
        raise ValueError('请选择下载目录。')
    folder = Path(directory).expanduser().resolve()
    folder.mkdir(parents=True, exist_ok=True)
    if not folder.is_dir() or not os.access(folder, os.W_OK):
        raise ValueError('下载目录不可写。')
    return urls, str(folder)


class Window(QMainWindow):
    def __init__(self, settings=None):
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.settings = settings or QSettings('gallery-dl', 'ChineseGUI')
        self.proc = None
        self.paused = False
        self.paused_tree = PausedProcessTree()
        self.pending = []
        self.stopping = False
        self.closing = False
        self.success_count = self.skip_count = self.failed_links = 0
        self.active_row = None
        self.setWindowTitle('gallery-dl · 下载工作台')
        self.setWindowIcon(
            QIcon(str(ROOT / 'gui' / 'assets' / 'gallery-dl.ico')))
        self.resize(1180, 800)
        self.setMinimumSize(880, 620)
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(20, 4, 20, 12)
        splitter = QSplitter()
        outer.addWidget(splitter, 1)
        left = QWidget()
        form = QVBoxLayout(left)
        form.setContentsMargins(0, 12, 20, 0)
        form.setSpacing(12)
        config_header = QHBoxLayout()
        config_header.addWidget(self.heading('下载配置'))
        config_header.addStretch()
        config_note = QLabel('按链接顺序下载，保留站点子目录。')
        config_note.setObjectName('muted')
        config_header.addWidget(config_note)
        form.addLayout(config_header)
        self.link_directories = json.loads(str(self.settings.value('link_directories', '{}')))
        self.active_url = None
        self.links = LinkList()
        self.links.open_folder.connect(self.open_link_directory)
        self.links.setAccessibleName('下载链接')
        if self.settings.contains('link_entries'):
            self.links.set_entries(json.loads(str(self.settings.value('link_entries'))))
        else:
            self.links.setPlainText(str(self.settings.value('links', '')))
        form.addWidget(self.links, 1)
        settings_panel = QFrame()
        settings_panel.setObjectName('settingsPanel')
        settings_layout = QVBoxLayout(settings_panel)
        settings_layout.setContentsMargins(12, 12, 12, 12)
        settings_layout.setSpacing(10)
        form.addWidget(settings_panel)

        def separator():
            line = QFrame()
            line.setObjectName('settingsDivider')
            line.setFixedHeight(1)
            settings_layout.addWidget(line)

        cookie_header = QHBoxLayout()
        cookie_title = QLabel('Cookies 文件（可选）')
        cookie_tip = 'Cookies 仅供本地下载使用，不在日志中展示。'
        cookie_title.setToolTip(cookie_tip)
        cookie_header.addWidget(cookie_title)
        cookie_header.addStretch()
        settings_layout.addLayout(cookie_header)
        self.cookies = QLineEdit(QDir.toNativeSeparators(
            str(self.settings.value('cookies', ''))))
        self.cookies.setPlaceholderText('选择 Netscape 格式 cookies.txt')
        self.cookie_button = QPushButton('选择文件')
        self.cookie_button.setObjectName('pathLink')
        self.cookie_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cookie_button.clicked.connect(self.pick_cookies)
        cookie_header.addWidget(self.cookie_button)
        settings_layout.addWidget(self.cookies)
        separator()
        directory_header = QHBoxLayout()
        directory_header.addWidget(QLabel('下载目录'))
        directory_header.addStretch()
        settings_layout.addLayout(directory_header)
        self.directory = QLineEdit(
            str(self.settings.value('directory', str(ROOT / 'downloads'))))
        open_button = QPushButton('打开目录')
        open_button.setObjectName('pathLink')
        open_button.setCursor(Qt.CursorShape.PointingHandCursor)
        open_button.clicked.connect(self.open_directory)
        directory_header.addWidget(open_button)
        self.dir_button = QPushButton('选择目录')
        self.dir_button.setObjectName('pathLink')
        self.dir_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.dir_button.clicked.connect(self.pick_directory)
        directory_header.addWidget(self.dir_button)
        settings_layout.addWidget(self.directory)
        self.normalize_path_fields()
        self.cookies.editingFinished.connect(self.normalize_path_fields)
        self.directory.editingFinished.connect(self.normalize_path_fields)
        self.incremental = ToggleButton('增量下载')
        self.incremental.setChecked(
            self.settings.value('incremental', True, type=bool))
        self.incremental.setToolTip(
            '记录保存在所选下载目录中。已记录的内容即使被移动或删除也会跳过。\n'
            '取消勾选后不使用记录，仍按原下载器规则跳过已有文件。')
        separator()
        incremental_row = QHBoxLayout()
        incremental_row.setSpacing(8)
        incremental_row.addWidget(self.incremental)
        self.latest_only = ToggleButton('只检查最新')
        self.latest_only.setChecked(
            self.settings.value('latest_only', True, type=bool))
        self.latest_only.setEnabled(self.incremental.isChecked())
        self.latest_only.setToolTip(
            '适用于按从新到旧返回内容的网址。遇到首个已下载文件即结束该网址，继续下一个。\n'
            '不会检查或补齐历史遗漏；置顶、乱序或未下载完的多图内容可能被跳过。\n'
            '需要完整检查或补下载时，请取消勾选。')
        self.incremental.toggled.connect(self.latest_only.setEnabled)
        incremental_row.addWidget(self.latest_only)
        incremental_row.addStretch()
        settings_layout.addLayout(incremental_row)
        separator()
        settings_layout.addWidget(QLabel('文件命名'))
        self.date_format = NamingCombo()
        self.date_format.addItem('原文件名', '')
        for label, value in DATE_FORMATS:
            self.date_format.addItem(label, value)
        saved_format = self.settings.value('date_format', DEFAULT_DATE_FORMAT)
        if not self.settings.value('date_naming', True, type=bool):
            saved_format = ''
        selected = self.date_format.findData(saved_format)
        self.date_format.setCurrentIndex(selected if selected >= 0 else 3)
        self.date_format.setToolTip('日期取自发布日期；缺少日期时保留原文件名。')
        settings_layout.addWidget(self.date_format)
        self.start_button = MediaButton('开始下载', 'play')
        self.start_button.setObjectName('downloadAction')
        self.start_button.setProperty('active', False)
        self.start_button.clicked.connect(self.toggle_download)
        self.stop_button = MediaButton('停止下载', 'stop')
        self.stop_button.setObjectName('stopAction')
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop)
        for button in (self.start_button, self.stop_button):
            button.setFixedSize(88, 88)
        form.addStretch()
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QFrame.Shape.NoFrame)
        left_scroll.setMinimumWidth(320)
        left_scroll.setWidget(left)
        splitter.addWidget(left_scroll)
        right = QWidget()
        body = QVBoxLayout(right)
        body.setContentsMargins(20, 12, 0, 0)
        body.setSpacing(12)
        record_bar = QHBoxLayout()
        record_bar.addWidget(self.heading('下载记录'))
        record_bar.addStretch()
        self.log_button = QToolButton()
        self.log_button.setIcon(self.style().standardIcon(
            QStyle.StandardPixmap.SP_FileDialogDetailedView))
        self.log_button.setToolTip('显示 / 隐藏运行日志')
        self.log_button.setAccessibleName('显示或隐藏运行日志')
        self.log_button.setCheckable(True)
        self.log_button.clicked.connect(self.toggle_log)
        record_bar.addWidget(self.log_button)
        body.addLayout(record_bar)
        self.status = QLabel('准备就绪 · 添加链接后开始下载')
        self.status.setObjectName('status')
        self.status.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.table = RecordTable()
        body.addWidget(self.table, 3)
        current_row = QHBoxLayout()
        current_info = QVBoxLayout()
        current_info.addWidget(self.heading('当前文件'))
        self.filename = QLabel('尚未开始下载')
        self.filename.setWordWrap(True)
        current_info.addWidget(self.filename)
        self.progress = QProgressBar()
        self.progress.setValue(0)
        current_info.addWidget(self.progress)
        current_row.addLayout(current_info, 1)
        current_row.addWidget(self.stop_button)
        current_row.addWidget(self.start_button)
        body.addLayout(current_row)
        self.speed = QLabel('—')
        progress_details = QHBoxLayout()
        progress_details.addWidget(self.speed)
        progress_details.addStretch()
        progress_details.addWidget(self.status)
        body.addLayout(progress_details)
        self.log_window = LogWindow(self)
        log_layout = QVBoxLayout(self.log_window)
        logbar = QHBoxLayout()
        logbar.addWidget(self.heading('运行日志'))
        logbar.addStretch()
        for label, callback in [('复制', self.copy_log), ('清空', self.clear_log), ('导出', self.export_log)]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            logbar.addWidget(button)
        log_layout.addLayout(logbar)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(10000)
        log_layout.addWidget(self.log, 1)
        splitter.addWidget(right)
        splitter.setSizes([360, 780])
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        self.setStyleSheet('''
            QMainWindow, QWidget { background: #f6f8fb; color: #233047; font-family: "Microsoft YaHei UI"; font-size: 13px; }
            QFrame#settingsPanel { border: 1px solid #d5dde8; border-radius: 10px; }
            QFrame#settingsDivider { background: #dfe5ee; border: none; }
            QComboBox { background: white; border: 1px solid #cbd5e2; border-radius: 7px; padding: 8px; }
            QComboBox:focus { border-color: #2782ed; }
            QComboBox::drop-down { border: none; width: 22px; }
            QListWidget#namingOptions { background: white; border: 1px solid #cbd5e2; border-radius: 8px; padding: 4px; outline: none; }
            QListWidget#namingOptions::item { padding: 8px 5px; border-radius: 4px; }
            QListWidget#namingOptions::item:selected { background: #eaf3ff; color: #2563eb; }
            QListWidget#namingOptions::item:hover { background: #f0f5fc; }
            QLabel#heading { font-size: 17px; font-weight: 600; }
            QLabel#muted { color: #738096; font-size: 12px; }
            QLabel#status { color: #1767c5; }
            QLineEdit, QPlainTextEdit, QTableWidget { background: white; border: 1px solid #d5dde8; border-radius: 5px; padding: 7px; selection-background-color: #d7e9ff; selection-color: #183253; }
            QPushButton { background: white; border: 1px solid #cbd5e2; border-radius: 5px; padding: 9px 12px; }
            QPushButton:hover { background: #eaf2ff; border-color: #2782ed; }
            QPushButton#pathLink { background: transparent; color: #2563eb; border: none; padding: 0px; min-height: 22px; }
            QPushButton#pathLink:hover { background: transparent; color: #1d4ed8; text-decoration: underline; }
            QPushButton#pathLink:focus { color: #1d4ed8; text-decoration: underline; }
            QPushButton#pathLink:disabled { background: transparent; color: #94a3b8; text-decoration: none; }
            QPushButton#downloadAction { background: #16a34a; color: white; border: none; border-radius: 6px; padding: 0px; font-weight: 600; }
            QPushButton#downloadAction:hover { background: #15803d; }
            QPushButton#downloadAction[active="true"] { background: #facc15; color: #713f12; }
            QPushButton#downloadAction[active="true"]:hover { background: #eab308; }
            QPushButton#stopAction { background: #dc2626; color: white; border: none; border-radius: 6px; padding: 0px; font-weight: 600; }
            QPushButton#stopAction:hover { background: #b91c1c; }
            QPushButton#stopAction:disabled { background: #fee2e2; color: #c88b8b; }
            QPushButton#downloadAction:disabled { background: #e2e8f0; color: #94a3b8; }
            QPushButton:disabled { background: #e9edf3; color: #95a0af; border-color: #dde3eb; }
            QPushButton#settingToggle { background: #e9edf3; color: #64748b; border: 1px solid #d5dde8; border-radius: 8px; padding: 6px 4px; }
            QPushButton#settingToggle:hover { background: #dfe7f1; border-color: #a7bbd5; }
            QPushButton#settingToggle:checked { background: #2563eb; color: white; border-color: #2563eb; }
            QPushButton#settingToggle:checked:hover { background: #1d4ed8; border-color: #1d4ed8; }
            QPushButton#settingToggle:focus { border-color: #173c88; }
            QPushButton#settingToggle:disabled { background: #edf0f4; color: #a0aaba; border-color: #dfe5ee; }
            QHeaderView::section { background: #edf2f8; padding: 9px; border: none; }
            QTableWidget { alternate-background-color: #f4f7fb; gridline-color: #e8edf4; }
            QProgressBar { border: none; border-radius: 5px; background: #e0e8f3; text-align: center; min-height: 24px; }
            QProgressBar::chunk { background: #2284ee; border-radius: 5px; }
            QFrame#linkCard { background: white; border: 1px solid #dce4ef; border-radius: 10px; }
            QFrame#linkCard[selected="true"] { background: #eaf3ff; border-color: #b5d4fc; }
            QFrame#linkCard QLabel, QFrame#linkCard QCheckBox { background: transparent; border: none; }
            QLabel#cardTitle { font-weight: 600; font-size: 14px; }
            QFrame#linkCard QLineEdit { background: transparent; border: none; border-radius: 4px; padding: 0px; color: #64748b; }
            QFrame#linkCard QLineEdit:focus { background: white; border-color: #7fb4f4; }
            QFrame#linkCard QLineEdit[invalid="true"] { border-color: #dc2626; }
            QPushButton#openLinkFolder { background: transparent; border: none; padding: 0px; }
            QPushButton#openLinkFolder:hover { background: #eaf2ff; }
            QPushButton#removeLink { background: transparent; border: none; padding: 0px; color: #94a3b8; }
            QFrame#linkCard:hover QPushButton#removeLink, QPushButton#removeLink:focus { color: #94a3b8; }
            QPushButton#removeLink:hover { color: #dc2626; }
            QPushButton#addLinks { color: #2563eb; background: #f8fbff; border: 1px dashed #b8cae3; border-radius: 8px; }
            QPushButton#addLinks:hover { background: #eaf3ff; }
            QScrollArea { border: none; background: transparent; }
            QScrollBar:vertical { background: transparent; width: 8px; margin: 0px; }
            QScrollBar::handle:vertical { background: #c5d2e2; border-radius: 4px; min-height: 28px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
            QSplitter::handle { background: #dfe5ee; width: 1px; }
        ''')
        # Connect after restoring every field so initialization cannot overwrite
        # saved values with another control's temporary default.
        for signal in (self.links.changed, self.cookies.textChanged,
                       self.directory.textChanged, self.incremental.toggled,
                       self.latest_only.toggled,
                       self.date_format.currentIndexChanged):
            signal.connect(self.save_preferences)
        self.save_preferences()

    def save_preferences(self):
        values = {
            'link_directories': json.dumps(self.link_directories, ensure_ascii=False),
            'links': self.links.toPlainText(),
            'link_entries': json.dumps(self.links.entries(), ensure_ascii=False),
            'cookies': QDir.toNativeSeparators(self.cookies.text()),
            'directory': QDir.toNativeSeparators(self.directory.text()),
            'incremental': self.incremental.isChecked(),
            'latest_only': self.latest_only.isChecked(),
            'date_naming': bool(self.date_format.currentData()),
            'date_format': self.date_format.currentData(),
        }
        for key, value in values.items():
            self.settings.setValue(key, value)
        self.settings.sync()

    def toggle_log(self):
        if self.log_window.isVisible():
            self.log_window.hide()
            return
        self.log_window.show()
        self.sync_log_geometry()
        self.log_window.raise_()
        self.log_window.activateWindow()

    def sync_log_geometry(self):
        log = getattr(self, 'log_window', None)
        if (log is None or not log.isVisible() or self.isMinimized() or
                getattr(self, '_native_dragging', False)):
            return
        frame = self.frameGeometry()
        # resize() uses client height; include native title bar and borders.
        border_height = log.frameGeometry().height() - log.height()
        height = max(log.minimumHeight(), frame.height() - border_height)
        if log.height() != height:
            log.resize(log.width(), height)
        area = self.screen().availableGeometry()
        x = frame.right() + 9
        if self.isMaximized():
            x = max(area.left(), area.right() -
                    log.frameGeometry().width() + 1)
        y = frame.top()
        if log.frameGeometry().x() != x or log.frameGeometry().y() != y:
            log.move(x, y)

    def moveEvent(self, event):
        super().moveEvent(event)
        self.sync_log_geometry()

    def nativeEvent(self, event_type, message):
        follow_native_drag(self, message)
        return super().nativeEvent(event_type, message)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.sync_log_geometry()

    def changeEvent(self, event):
        super().changeEvent(event)
        QTimer.singleShot(0, self.sync_log_geometry)

    @staticmethod
    def heading(text):
        widget = QLabel(text)
        widget.setObjectName('heading')
        return widget

    @staticmethod
    def path_row(field, button):
        row = QHBoxLayout()
        row.addWidget(field, 1)
        row.addWidget(button)
        return row

    def pick_cookies(self):
        path, _ = QFileDialog.getOpenFileName(
            self, '选择 Cookies 文件', self.cookies.text(), 'Cookies (*.txt);;所有文件 (*)')
        if path:
            self.cookies.setText(QDir.toNativeSeparators(path))

    def pick_directory(self):
        path = QFileDialog.getExistingDirectory(
            self, '选择下载目录', self.directory.text())
        if path:
            self.directory.setText(QDir.toNativeSeparators(path))

    def normalize_path_fields(self):
        for field in (self.cookies, self.directory):
            field.setText(QDir.toNativeSeparators(field.text()))

    def link_directory_key(self, url):
        return str(Path(self.directory.text()).expanduser().resolve()) + '\n' + url

    def open_link_directory(self, url):
        folder = self.link_directories.get(self.link_directory_key(url))
        path = Path(folder) if folder else None
        # Twitter's default extractor directory is twitter/{user[name]}.
        # Resolve existing profile folders without making a network request.
        if path is None or not path.is_dir():
            parsed = urlsplit(url)
            parts = parsed.path.strip('/').split('/')
            if (parsed.hostname in ('x.com', 'www.x.com', 'twitter.com', 'www.twitter.com', 'mobile.twitter.com')
                    and parts and re.fullmatch(r'[A-Za-z0-9_]{1,15}', parts[0])
                    and parts[0].lower() not in ('i', 'home', 'search', 'explore', 'settings', 'messages')):
                path = Path(self.directory.text()).expanduser() / 'twitter' / parts[0]
        if path is None or not path.is_dir():
            QMessageBox.information(self, '链接目录', '此链接的本地目录尚不存在或尚未记录，请先下载该链接。')
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve())))

    def open_directory(self):
        path = Path(self.directory.text()).expanduser()
        if not path.is_dir():
            QMessageBox.information(self, '下载目录', '目录尚不存在，请先选择或开始下载。')
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve())))

    def append_log(self, text):
        text = re.sub(r'\x1b\[[0-9;]*[A-Za-z]', '', text).strip()
        if not text:
            return
        cursor = self.log.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor('#c23c3c' if ('[error]' in text.lower(
        ) or '失败' in text) else '#a66c11' if '[warning]' in text.lower() else '#46556b'))
        cursor.insertText(f'[{datetime.now():%H:%M:%S}] {text}\n', fmt)
        self.log.setTextCursor(cursor)
        self.log.ensureCursorVisible()

    def copy_log(self):
        QApplication.clipboard().setText(self.log.toPlainText())

    def clear_log(self):
        self.log.clear()

    def export_log(self):
        path, _ = QFileDialog.getSaveFileName(self, '导出日志', str(
            ROOT / 'downloads' / 'gallery-dl.log'), '日志 (*.log);;文本 (*.txt)')
        if path:
            try:
                Path(path).write_text(self.log.toPlainText(), encoding='utf-8')
            except OSError as exc:
                QMessageBox.warning(self, '导出失败', str(exc))

    def busy(self, value):
        for widget in (self.links, self.cookies, self.directory, self.cookie_button, self.dir_button, self.incremental, self.date_format):
            widget.setEnabled(not value)
        if value:
            self.date_format.hidePopup()
        self.latest_only.setEnabled(not value and self.incremental.isChecked())
        self.stop_button.setEnabled(value)
        self.set_download_action(value)

    def set_download_action(self, active):
        self.start_button.set_symbol('pause' if active and not self.paused else 'play')
        self.start_button.setText('恢复下载' if self.paused else '暂停下载' if active else '开始下载')
        self.start_button.setProperty('active', active)
        self.start_button.setEnabled(not self.stopping if active else True)
        self.start_button.style().unpolish(self.start_button)
        self.start_button.style().polish(self.start_button)

    def toggle_download(self):
        if self.proc is None:
            self.start()
            return
        if self.stopping or self.proc.state() != QProcess.ProcessState.Running:
            return
        try:
            if self.paused:
                self.paused_tree.resume()
                self.paused = False
            else:
                self.paused_tree.pause(self.proc.processId())
                self.paused = True
        except Exception as exc:
            self.append_log(f'暂停或恢复失败：{exc}')
            return
        self.set_download_action(True)
        self.speed.setText('已暂停 · 等待恢复' if self.paused else '正在恢复下载…')
        state = '已暂停' if self.paused else '下载中'
        if self.active_row is not None and self.table.state(self.active_row) in ('下载中', '已暂停'):
            self.table.update_record(self.active_row, state=state)
        self.update_status(state)
        self.append_log('下载已暂停，点击“恢复下载”继续。' if self.paused else '已恢复下载。')

    def start(self):
        if self.proc is not None:
            return
        self.normalize_path_fields()
        if not self.links.commit_edits():
            return
        try:
            selected = self.links.selected_urls()
            if not selected:
                raise ValueError('请至少勾选一个下载链接')
            urls, directory = validate_inputs('\n'.join(selected), self.cookies.text().strip(), self.directory.text())
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, '请检查下载配置', str(exc))
            return
        self.archive_path = None
        if self.incremental.isChecked():
            self.archive_path = str(Path(directory) / ARCHIVE_NAME)
            try:
                # Fail visibly instead of silently downloading without an archive.
                from gallery_dl.archive import connect
                archive = connect(self.archive_path, '', '{id}')
                archive.close()
            except Exception as exc:
                QMessageBox.warning(self, '增量记录无法使用',
                                    f'无法打开下载记录，请检查目录权限或记录文件。\n{exc}')
                return
        self.directory.setText(directory)
        self.save_preferences()
        self.pending = urls
        self.total_links = len(urls)
        self.success_count = self.skip_count = self.failed_links = 0
        self.stopping = False
        self.table.clear_records()
        self.active_row = None
        self.busy(True)
        self.append_log(f'开始下载，共 {len(urls)} 个链接。')
        self.append_log('发布日期命名：' + self.date_format.currentText() + '；无日期时保留原命名。'
                        if bool(self.date_format.currentData()) else '发布日期命名已关闭，保留原命名。')
        self.append_log(f'增量下载已开启，记录文件：{self.archive_path}' if self.archive_path
                        else '增量下载已关闭；仍跳过本地已有文件。')
        self.next_url()

    def next_url(self):
        if self.stopping or not self.pending:
            self.finish_batch()
            return
        url = self.pending.pop(0)
        self.active_url = url
        self.active_row = None
        self.progress.setRange(0, 0)
        self.filename.setText('正在解析链接…')
        self.speed.setText('等待文件信息')
        self.update_status('正在下载')
        self.append_log(f'开始解析链接：{url}')
        if self.incremental.isChecked() and self.latest_only.isChecked():
            self.append_log('只检查最新：遇到已下载文件后结束当前网址，不扫描历史内容。')
        process = QProcess(self)
        self.proc = process
        self.stdout_buffer = ''
        self.stderr_buffer = ''
        self.out_decoder = codecs.getincrementaldecoder('utf-8')('replace')
        self.err_decoder = codecs.getincrementaldecoder('utf-8')('replace')
        env = QProcessEnvironment.systemEnvironment()
        env.insert('PYTHONIOENCODING', 'utf-8')
        env.insert('PYTHONUNBUFFERED', '1')
        env.insert(DATE_FORMAT_ENV, self.date_format.currentData()
                   if bool(self.date_format.currentData()) else '')
        process.setProcessEnvironment(env)
        process.setWorkingDirectory(str(ROOT))
        args = ['-u', '-m', 'gui.worker', '--ignore-config', '--no-colors',
                '-o', 'downloader.http.progress=0.1', '-d', self.directory.text()]
        if self.archive_path:
            args += ['--download-archive', self.archive_path,
                     '-o', 'archive-event=file,skip']
            if self.latest_only.isChecked():
                args += ['-o', 'skip=terminate:1']
        if self.cookies.text().strip():
            args += ['--cookies', self.cookies.text().strip()]
        args += ['--', url]
        process.readyReadStandardOutput.connect(self.read_stdout)
        process.readyReadStandardError.connect(self.read_stderr)
        process.finished.connect(self.process_finished)
        process.errorOccurred.connect(self.process_error)
        process.start(sys.executable, args)

    def read_stdout(self):
        self.stdout_buffer += self.out_decoder.decode(
            bytes(self.proc.readAllStandardOutput()))
        while '\n' in self.stdout_buffer:
            line, self.stdout_buffer = self.stdout_buffer.split('\n', 1)
            try:
                event = json.loads(line)
                if isinstance(event, dict) and 'type' in event:
                    self.handle_event(event)
                else:
                    self.append_log(line)
            except (ValueError, TypeError):
                self.append_log(line)

    def read_stderr(self):
        self.stderr_buffer += self.err_decoder.decode(
            bytes(self.proc.readAllStandardError()))
        while '\n' in self.stderr_buffer:
            line, self.stderr_buffer = self.stderr_buffer.split('\n', 1)
            self.append_log(line)

    def handle_event(self, event):
        kind = event['type']
        if kind in ('start', 'skip', 'success'):
            path = event['path']
            if self.active_url:
                key = self.link_directory_key(self.active_url)
                folder = str(Path(path).resolve().parent)
                if self.link_directories.get(key) != folder:
                    self.link_directories[key] = folder
                    self.save_preferences()
            self.active_row = path
            self.filename.setText(Path(path).name)
            state = {'start': '下载中', 'skip': '已跳过', 'success': '已完成'}[kind]
            if kind == 'start' and self.paused:
                state = '已暂停'
            self.table.update_record(path, state=state)
            if kind == 'start':
                self.progress.setRange(0, 0)
                self.speed.setText('等待进度数据…')
            else:
                self.success_count += kind == 'success'
                self.skip_count += kind == 'skip'
                self.progress.setRange(0, 100)
                self.progress.setValue(100 if kind == 'success' else 0)
                try:
                    size = Path(path).stat().st_size
                    self.table.update_record(path, size=size, size_text=human_bytes(size))
                except OSError:
                    pass
                self.append_log(f'{state}：{path}')
                if kind == 'skip' and self.incremental.isChecked() and self.latest_only.isChecked():
                    self.append_log('已遇到下载记录，结束当前网址的最新检查；历史内容未检查。')
            self.update_status('正在下载')
        elif kind == 'progress':
            total = event.get('total')
            downloaded = event.get('downloaded', 0)
            if total and total > 0:
                self.progress.setRange(0, 100)
                self.progress.setValue(min(100, int(downloaded * 100 / total)))
            else:
                self.progress.setRange(0, 0)
            self.speed.setText(f'{human_bytes(downloaded)} / {human_bytes(total)
                               if total else "大小未知"}  ·  {human_bytes(event.get("speed"))}/s')
            if self.paused:
                self.speed.setText('已暂停 · 等待恢复')
            if self.active_row is not None:
                self.table.update_record(self.active_row, size=total,
                                         size_text=human_bytes(total) if total else '未知')

    def update_status(self, state):
        if self.paused:
            state = '已暂停'
        self.status.setText(f'{state} · 完成 {self.success_count} · 跳过 {
                            self.skip_count} · 失败链接 {self.failed_links} · 文件总数未知')

    def process_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.append_log('下载进程启动失败：' + self.proc.errorString())
            self.process_finished(1, QProcess.ExitStatus.CrashExit)

    def process_finished(self, code, exit_status):
        if self.proc is None:
            return
        self.read_stdout()
        self.read_stderr()
        if self.stderr_buffer:
            self.append_log(self.stderr_buffer)
        if self.stdout_buffer:
            self.append_log(self.stdout_buffer)
        if code != 0 and not self.stopping:
            self.failed_links += 1
            self.append_log(f'链接处理失败（退出码 {code}），继续下一个链接。')
        if self.active_row is not None and self.table.state(self.active_row) in ('下载中', '已暂停'):
            self.table.update_record(self.active_row, state=(
                '已停止' if self.stopping else '已失败' if code else '已结束'))
        self.proc.deleteLater()
        self.proc = None
        self.paused = False
        self.paused_tree.clear()
        self.next_url()

    def finish_batch(self):
        self.pending.clear()
        self.busy(False)
        self.progress.setRange(0, 100)
        if self.stopping:
            self.progress.setValue(0)
        self.speed.setText('下载已结束')
        state = '已停止' if self.stopping else '已结束（存在失败）' if self.failed_links else '全部链接处理完成'
        self.update_status(state)
        self.append_log(f'{state}：完成 {self.success_count} 个，跳过 {
                        self.skip_count} 个，失败链接 {self.failed_links} 个。')
        if self.closing:
            self.close()

    def stop(self):
        self.stopping = True
        self.pending.clear()
        self.stop_button.setEnabled(False)
        self.start_button.setEnabled(False)
        self.append_log('正在停止下载；已完成文件保留，未完成文件按下载器规则保留。')
        if self.proc:
            if sys.platform == 'win32' and self.proc.processId():
                # Stop helper processes (e.g. yt-dlp/ffmpeg) along with the worker.
                try:
                    subprocess.run(['taskkill', '/PID', str(self.proc.processId()), '/T', '/F'],
                                   capture_output=True, timeout=5,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
                except (OSError, subprocess.TimeoutExpired):
                    pass
            self.proc.kill()

    def closeEvent(self, event):
        if self.proc is not None:
            answer = QMessageBox.question(self, '退出下载工具', '正在下载，是否停止并退出？')
            if answer == QMessageBox.StandardButton.Yes:
                self.closing = True
                self.stop()
            event.ignore()
        else:
            self.log_window.hide()
            event.accept()


def run():
    if sys.platform == 'win32':
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            'gallery-dl.ChineseGUI')
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(str(ROOT / 'gui' / 'assets' / 'gallery-dl.ico')))
    app.setStyle('Fusion')
    window = Window()
    window.show()
    return app.exec()
