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

from PySide6.QtCore import QProcess, QProcessEnvironment, QSettings, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QSplitter, QStyle, QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout, QWidget,
)
from .window_chrome import LogWindow, follow_native_drag
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
        self.settings = settings or QSettings('gallery-dl', 'ChineseGUI')
        self.proc = None
        self.pending = []
        self.stopping = False
        self.paste_button = None
        self.closing = False
        self.success_count = self.skip_count = self.failed_links = 0
        self.active_row = None
        self.rows = {}
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
        form.addWidget(self.heading('下载配置'))
        linkbar = QHBoxLayout()
        linkbar.addWidget(QLabel('下载链接'))
        linkbar.addStretch()
        paste = QPushButton('粘贴链接')
        self.paste_button = paste
        paste.clicked.connect(self.paste_links)
        linkbar.addWidget(paste)
        form.addLayout(linkbar)
        self.links = QPlainTextEdit()
        self.links.setPlaceholderText('粘贴要下载的链接\n支持多个链接，每行一个')
        self.links.setMinimumHeight(140)
        form.addWidget(self.links, 1)
        form.addWidget(QLabel('Cookies 文件（可选）'))
        self.cookies = QLineEdit(str(self.settings.value('cookies', '')))
        self.cookies.setPlaceholderText('选择 Netscape 格式 cookies.txt')
        self.cookie_button = QPushButton('选择文件')
        self.cookie_button.clicked.connect(self.pick_cookies)
        form.addLayout(self.path_row(self.cookies, self.cookie_button))
        form.addWidget(QLabel('下载目录'))
        self.directory = QLineEdit(
            str(self.settings.value('directory', str(ROOT / 'downloads'))))
        self.dir_button = QPushButton('选择目录')
        self.dir_button.clicked.connect(self.pick_directory)
        form.addLayout(self.path_row(self.directory, self.dir_button))
        self.incremental = QCheckBox('增量下载（跳过已下载内容）')
        self.incremental.setChecked(True)
        self.incremental.setToolTip(
            '记录保存在所选下载目录中。已记录的内容即使被移动或删除也会跳过。\n'
            '取消勾选后不使用记录，仍按原下载器规则跳过已有文件。')
        form.addWidget(self.incremental)
        self.date_naming = QCheckBox('按发布日期命名')
        self.date_naming.setChecked(
            self.settings.value('date_naming', True, type=bool))
        self.date_naming.setToolTip('在站点原命名前添加发布日期；缺少日期时保留原命名。')
        form.addWidget(self.date_naming)
        self.date_format = QComboBox()
        for label, value in DATE_FORMATS:
            self.date_format.addItem(label, value)
        selected = self.date_format.findData(
            self.settings.value('date_format', DEFAULT_DATE_FORMAT))
        self.date_format.setCurrentIndex(selected if selected >= 0 else 2)
        self.date_format.setEnabled(self.date_naming.isChecked())
        self.date_naming.toggled.connect(self.date_format.setEnabled)
        form.addWidget(self.date_format)
        note = QLabel('按链接顺序下载，保留站点子目录。\nCookies 仅供本地下载使用，不在日志中展示。')
        note.setObjectName('muted')
        note.setWordWrap(True)
        form.addWidget(note)
        actions = QHBoxLayout()
        self.start_button = QPushButton('开始下载')
        self.start_button.setObjectName('primary')
        self.start_button.clicked.connect(self.start)
        self.stop_button = QPushButton('停止')
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop)
        actions.addWidget(self.start_button)
        actions.addWidget(self.stop_button)
        form.addLayout(actions)
        open_button = QPushButton('打开下载目录')
        open_button.clicked.connect(self.open_directory)
        form.addWidget(open_button)
        form.addStretch()
        splitter.addWidget(left)
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
        body.addWidget(self.status)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(['文件名', '大小', '状态'])
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        body.addWidget(self.table, 3)
        body.addWidget(self.heading('当前文件'))
        self.filename = QLabel('尚未开始下载')
        self.filename.setWordWrap(True)
        body.addWidget(self.filename)
        self.progress = QProgressBar()
        self.progress.setValue(0)
        body.addWidget(self.progress)
        self.speed = QLabel('—')
        body.addWidget(self.speed)
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
        outer.addWidget(QLabel('本地下载工具  ·  日志保留最近 10,000 行  ·  文件总数由站点提供'))
        self.setStyleSheet('''
            QMainWindow, QWidget { background: #f6f8fb; color: #233047; font-family: "Microsoft YaHei UI"; font-size: 13px; }
            QLabel#heading { font-size: 17px; font-weight: 600; }
            QLabel#muted { color: #738096; font-size: 12px; }
            QLabel#status { color: #1767c5; padding: 8px 0; }
            QLineEdit, QPlainTextEdit, QTableWidget { background: white; border: 1px solid #d5dde8; border-radius: 5px; padding: 7px; selection-background-color: #d7e9ff; selection-color: #183253; }
            QPushButton { background: white; border: 1px solid #cbd5e2; border-radius: 5px; padding: 9px 12px; }
            QPushButton:hover { background: #eaf2ff; border-color: #2782ed; }
            QPushButton#primary { background: #1675e5; color: white; border-color: #1675e5; }
            QPushButton#primary:disabled { background: #dce5f0; color: #8999ae; border-color: #dce5f0; }
            QPushButton:disabled { background: #e9edf3; color: #95a0af; border-color: #dde3eb; }
            QHeaderView::section { background: #edf2f8; padding: 9px; border: none; }
            QTableWidget { alternate-background-color: #f4f7fb; gridline-color: #e8edf4; }
            QProgressBar { border: none; border-radius: 5px; background: #e0e8f3; text-align: center; min-height: 24px; }
            QProgressBar::chunk { background: #2284ee; border-radius: 5px; }
            QSplitter::handle { background: #dfe5ee; width: 1px; }
        ''')

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

    def paste_links(self):
        text = QApplication.clipboard().text().strip()
        if text:
            self.links.appendPlainText(text)

    def pick_cookies(self):
        path, _ = QFileDialog.getOpenFileName(
            self, '选择 Cookies 文件', self.cookies.text(), 'Cookies (*.txt);;所有文件 (*)')
        if path:
            self.cookies.setText(path)

    def pick_directory(self):
        path = QFileDialog.getExistingDirectory(
            self, '选择下载目录', self.directory.text())
        if path:
            self.directory.setText(path)

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
        for widget in (self.start_button, self.links, self.cookies, self.directory, self.cookie_button, self.dir_button, self.paste_button, self.incremental, self.date_naming):
            widget.setEnabled(not value)
        self.date_format.setEnabled(not value and self.date_naming.isChecked())
        self.stop_button.setEnabled(value)

    def start(self):
        if self.proc is not None:
            return
        try:
            urls, directory = validate_inputs(self.links.toPlainText(
            ), self.cookies.text().strip(), self.directory.text())
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
        self.settings.setValue('directory', directory)
        self.settings.setValue('cookies', self.cookies.text().strip())
        self.settings.setValue('date_naming', self.date_naming.isChecked())
        self.settings.setValue('date_format', self.date_format.currentData())
        self.pending = urls
        self.total_links = len(urls)
        self.success_count = self.skip_count = self.failed_links = 0
        self.stopping = False
        self.table.setRowCount(0)
        self.rows.clear()
        self.active_row = None
        self.busy(True)
        self.append_log(f'开始下载，共 {len(urls)} 个链接。')
        self.append_log('发布日期命名：' + self.date_format.currentText() + '；无日期时保留原命名。'
                        if self.date_naming.isChecked() else '发布日期命名已关闭，保留原命名。')
        self.append_log(f'增量下载已开启，记录文件：{self.archive_path}' if self.archive_path
                        else '增量下载已关闭；仍跳过本地已有文件。')
        self.next_url()

    def next_url(self):
        if self.stopping or not self.pending:
            self.finish_batch()
            return
        url = self.pending.pop(0)
        self.active_row = None
        self.progress.setRange(0, 0)
        self.filename.setText('正在解析链接…')
        self.speed.setText('等待文件信息')
        self.update_status('正在下载')
        self.append_log(f'开始解析链接：{url}')
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
                   if self.date_naming.isChecked() else '')
        process.setProcessEnvironment(env)
        process.setWorkingDirectory(str(ROOT))
        args = ['-u', '-m', 'gui.worker', '--ignore-config', '--no-colors',
                '-o', 'downloader.http.progress=0.1', '-d', self.directory.text()]
        if self.archive_path:
            args += ['--download-archive', self.archive_path,
                     '-o', 'archive-event=file,skip']
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
            row = self.rows.get(path)
            if row is None:
                # Bound the live table; complete details remain in log output.
                if self.table.rowCount() >= 2000:
                    self.table.removeRow(0)
                    self.rows = {key: value - 1 for key,
                                 value in self.rows.items() if value > 0}
                row = self.table.rowCount()
                self.table.insertRow(row)
                self.rows[path] = row
                for col, text in enumerate((Path(path).name, '—', '')):
                    item = QTableWidgetItem(text)
                    item.setToolTip(path)
                    self.table.setItem(row, col, item)
            self.active_row = row
            self.filename.setText(Path(path).name)
            state = {'start': '正在下载', 'skip': '已跳过', 'success': '已完成'}[kind]
            self.table.item(row, 2).setText(state)
            self.table.scrollToBottom()
            if kind == 'start':
                self.progress.setRange(0, 0)
                self.speed.setText('等待进度数据…')
            else:
                self.success_count += kind == 'success'
                self.skip_count += kind == 'skip'
                self.progress.setRange(0, 100)
                self.progress.setValue(100 if kind == 'success' else 0)
                try:
                    self.table.item(row, 1).setText(
                        human_bytes(Path(path).stat().st_size))
                except OSError:
                    pass
                self.append_log(f'{state}：{path}')
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
            if self.active_row is not None:
                self.table.item(self.active_row, 1).setText(
                    human_bytes(total) if total else '未知')

    def update_status(self, state):
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
        if self.active_row is not None and self.table.item(self.active_row, 2).text() == '正在下载':
            self.table.item(self.active_row, 2).setText(
                '已停止' if self.stopping else '失败' if code else '处理结束')
        self.proc.deleteLater()
        self.proc = None
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
