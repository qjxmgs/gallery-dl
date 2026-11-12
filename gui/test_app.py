"""Integration checks against a local HTTP server, without site credentials."""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
import sys
from pathlib import Path
import threading
import time
import unittest

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from gui.app import ARCHIVE_NAME, Window, validate_inputs
from gui.naming import DEFAULT_DATE_FORMAT, DATE_FORMAT_ENV

QA = Path(os.environ.get('GALLERY_GUI_QA', r'D:\Develop\QA\gallery-dl')
          ) / time.strftime('%Y%m%d-%H%M%S')
PAYLOAD = b'gallery-dl integration fixture\n' * 65536


class Handler(BaseHTTPRequestHandler):
    requests = []

    def log_message(self, *args):
        pass

    def do_GET(self):
        self.requests.append(self.path)
        if self.path == '/missing.jpg':
            self.send_error(404)
            return
        self.send_response(200)
        if self.path != '/unknown.jpg':
            self.send_header('Content-Length', str(len(PAYLOAD)))
        self.send_header('Content-Type', 'image/jpeg')
        self.end_headers()
        try:
            for offset in range(0, len(PAYLOAD), 65536):
                self.wfile.write(PAYLOAD[offset:offset + 65536])
                self.wfile.flush()
                time.sleep(0.025)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass


class WorkbenchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        QA.mkdir(parents=True, exist_ok=True)
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle('Fusion')
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.window = Window(QSettings(
            str(QA / (self._testMethodName + '.ini')), QSettings.Format.IniFormat))
        self.window.directory.setText(
            str(QA / self._testMethodName / '中文下载目录'))
        self.window.show()

    def tearDown(self):
        if self.window.proc:
            self.window.stop()
            self.wait_for(lambda: self.window.proc is None)
        (QA / (self._testMethodName + '.log')
         ).write_text(self.window.log.toPlainText(), encoding='utf-8')
        self.window.close()
        self.app.processEvents()

    def wait_for(self, condition, timeout=15):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.app.processEvents()
            if condition():
                return
            time.sleep(0.01)
        self.fail('Timed out: ' + self.window.log.toPlainText())

    def test_download_progress_skip_and_unknown_size(self):
        self.assertTrue(self.window.date_naming.isChecked())
        self.assertEqual(self.window.date_format.currentData(),
                         DEFAULT_DATE_FORMAT)
        self.window.links.setPlainText(self.base + '/image.jpg')
        self.window.start()
        self.assertEqual(self.window.proc.processEnvironment().value(
            DATE_FORMAT_ENV), DEFAULT_DATE_FORMAT)
        self.assertFalse(self.window.date_format.isEnabled())
        self.wait_for(lambda: 0 < self.window.progress.value() <
                      100 and self.window.progress.maximum() == 100)
        self.window.grab().save(str(QA / 'C-workbench-running.png'))
        self.assertFalse(self.window.start_button.isEnabled())
        self.wait_for(lambda: self.window.proc is None)
        files = list(Path(self.window.directory.text()).rglob('*image.jpg'))
        self.assertEqual(len(files), 1)
        self.assertEqual(hashlib.sha256(
            files[0].read_bytes()).digest(), hashlib.sha256(PAYLOAD).digest())
        self.assertEqual(self.window.success_count, 1)
        self.assertTrue(self.window.date_format.isEnabled())
        self.window.start()
        self.wait_for(lambda: self.window.proc is None)
        self.assertEqual(self.window.skip_count, 1)
        self.window.links.setPlainText(self.base + '/unknown.jpg')
        self.window.start()
        self.wait_for(lambda: '大小未知' in self.window.speed.text())
        self.assertEqual(self.window.progress.maximum(), 0)
        self.wait_for(lambda: self.window.proc is None)
        self.assertEqual(self.window.success_count, 1)

    def test_failure_continues_queue(self):
        self.window.links.setPlainText(
            self.base + '/missing.jpg\n' + self.base + '/good.jpg')
        self.window.start()
        self.wait_for(lambda: self.window.proc is None)
        self.assertEqual(self.window.failed_links, 1)
        self.assertEqual(self.window.success_count, 1)
        self.window.grab().save(str(QA / 'C-workbench-results.png'))

    def test_stop_clears_queue(self):
        self.window.links.setPlainText(
            self.base + '/stop.jpg\n' + self.base + '/never.jpg')
        self.window.start()
        self.wait_for(lambda: self.window.active_row is not None)
        self.window.stop()
        self.wait_for(lambda: self.window.proc is None)
        self.assertEqual(self.window.pending, [])
        self.assertIn('已停止', self.window.status.text())
        self.assertEqual(
            list(Path(self.window.directory.text()).rglob('*never.jpg')), [])
        self.assertTrue(self.window.start_button.isEnabled())

    def test_validation_and_cookies(self):
        folder = str(QA / 'validation')
        with self.assertRaises(ValueError):
            validate_inputs('not a URL', '', folder)
        cookie = QA / 'cookies-test.txt'
        cookie.write_text('invalid format', encoding='utf-8')
        with self.assertRaises(ValueError):
            validate_inputs(self.base, str(cookie), folder)
        cookie.write_text('# Netscape HTTP Cookie File\n', encoding='utf-8')
        urls, _ = validate_inputs(
            self.base + '\n' + self.base, str(cookie), folder)
        self.assertEqual(urls, [self.base])
        self.window.cookies.setText(str(cookie))
        self.window.date_naming.setChecked(False)
        self.assertFalse(self.window.date_format.isEnabled())
        self.window.links.setPlainText(self.base + '/cookie.jpg')
        self.window.start()
        self.assertEqual(
            self.window.proc.processEnvironment().value(DATE_FORMAT_ENV), '')
        self.wait_for(lambda: self.window.proc is None)
        self.assertEqual(self.window.success_count, 1)

    def test_native_windows_follow_geometry(self):
        log = self.window.log_window
        self.assertFalse(self.window.windowFlags() &
                         Qt.WindowType.FramelessWindowHint)
        self.assertFalse(log.windowFlags() & Qt.WindowType.FramelessWindowHint)
        self.window.move(40, 50)
        self.window.resize(950, 650)
        self.window.log_button.click()
        for x, y, width, height in ((60, 70, 1000, 700), (100, 90, 920, 640)):
            self.window.move(x, y)
            self.window.resize(width, height)
            self.wait_for(lambda: log.frameGeometry().top() == self.window.frameGeometry().top() and
                          log.frameGeometry().height() == self.window.frameGeometry().height())
            expected_x = self.window.frameGeometry().right() + 9
            self.assertEqual(log.frameGeometry().left(), expected_x)
        self.window.showMaximized()
        QTest.qWait(300)
        self.wait_for(lambda: log.frameGeometry().height() ==
                      self.window.frameGeometry().height())
        self.window.showNormal()
        QTest.qWait(300)
        self.wait_for(lambda: log.frameGeometry().height() == self.window.frameGeometry().height() and
                      log.frameGeometry().top() == self.window.frameGeometry().top() and
                      self.window.height() == 640)
        # Native decorations are included in the desktop capture.
        self.window.screen().grabWindow(0).save(str(QA / 'native-follow-desktop.png'))

    @unittest.skipUnless(sys.platform == 'win32', 'Windows native drag loop')
    def test_native_drag_updates_without_qt_event_pump(self):
        import ctypes
        from ctypes import wintypes
        from gui.window_chrome import follow_native_drag, _user32
        self.window.log_button.click()
        self.app.processEvents()
        msg = wintypes.MSG()
        msg.message = 0x0231
        follow_native_drag(self.window, ctypes.addressof(msg))
        self.assertTrue(self.window._native_dragging)
        gap = round(
            8 * (_user32.GetDpiForWindow(int(self.window.winId())) or 96) / 96)
        # A burst of native move proposals: no processEvents()/timer flush.
        for step in range(100):
            rect = wintypes.RECT(100 + step * 3, 80 + step,
                                 1100 + step * 3, 780 + step)
            msg.message = 0x0216
            msg.lParam = ctypes.addressof(rect)
            follow_native_drag(self.window, ctypes.addressof(msg))
            actual = wintypes.RECT()
            self.assertTrue(_user32.GetWindowRect(
                int(self.window.log_window.winId()), ctypes.byref(actual)))
            self.assertEqual((actual.left, actual.top, actual.bottom - actual.top),
                             (rect.right + gap, rect.top, rect.bottom - rect.top))
        msg.message = 0x0232
        follow_native_drag(self.window, ctypes.addressof(msg))
        self.assertFalse(self.window._native_dragging)

    def test_log_window_toggle_and_lifetime(self):
        button = self.window.log_button
        self.assertFalse(self.window.log_window.isVisible())
        self.window.append_log('隐藏时仍然记录日志')
        button.click()
        self.app.processEvents()
        self.assertTrue(self.window.log_window.isVisible())
        self.assertTrue(button.isChecked())
        self.assertIs(self.window.log.window(), self.window.log_window)
        self.assertIn('隐藏时仍然记录日志', self.window.log.toPlainText())
        self.window.grab().save(str(QA / 'compact-main.png'))
        self.window.log_window.grab().save(str(QA / 'independent-log.png'))
        self.window.log_window.close()
        self.app.processEvents()
        self.assertFalse(button.isChecked())
        self.window.append_log('关闭后新增日志')
        button.click()
        self.assertIn('关闭后新增日志', self.window.log.toPlainText())
        button.click()
        self.assertFalse(self.window.log_window.isVisible())
        self.window.showMaximized()
        self.app.processEvents()
        self.assertTrue(self.window.isMaximized())
        self.window.showNormal()
        self.assertFalse(self.window.isMaximized())
        button.click()
        self.window.close()
        self.assertFalse(self.window.log_window.isVisible())

    def test_incremental_archive_and_disabled_recovery(self):
        self.assertTrue(self.window.incremental.isChecked())
        self.window.links.setPlainText(self.base + '/incremental.jpg')
        self.window.start()
        self.assertFalse(self.window.incremental.isEnabled())
        self.wait_for(lambda: self.window.proc is None)
        folder = Path(self.window.directory.text())
        self.assertTrue((folder / ARCHIVE_NAME).is_file())
        downloaded = next(folder.rglob('*incremental.jpg'))
        downloaded.unlink()  # Only this test's generated QA fixture.
        before = Handler.requests.count('/incremental.jpg')
        self.window.start()
        self.wait_for(lambda: self.window.proc is None)
        self.assertEqual(self.window.skip_count, 1)
        self.assertFalse(downloaded.exists())
        self.assertEqual(Handler.requests.count('/incremental.jpg'), before)
        self.window.incremental.setChecked(False)
        self.window.start()
        self.wait_for(lambda: self.window.proc is None)
        self.assertTrue(downloaded.exists())
        self.assertEqual(self.window.success_count, 1)
        self.assertEqual(Handler.requests.count(
            '/incremental.jpg'), before + 1)
        self.window.incremental.setChecked(True)
        self.window.directory.setText(str(QA / self._testMethodName / '另一目录'))
        self.window.start()
        self.wait_for(lambda: self.window.proc is None)
        self.assertEqual(self.window.success_count, 1)

    def test_incremental_import_existing_and_retry_failed(self):
        self.window.incremental.setChecked(False)
        self.window.links.setPlainText(self.base + '/existing.jpg')
        self.window.start()
        self.wait_for(lambda: self.window.proc is None)
        folder = Path(self.window.directory.text())
        self.assertFalse((folder / ARCHIVE_NAME).exists())
        self.window.incremental.setChecked(True)
        self.window.start()
        self.wait_for(lambda: self.window.proc is None)
        self.assertEqual(self.window.skip_count, 1)
        next(folder.rglob('*existing.jpg')).unlink()
        before = Handler.requests.count('/existing.jpg')
        self.window.start()
        self.wait_for(lambda: self.window.proc is None)
        self.assertEqual(Handler.requests.count('/existing.jpg'), before)
        self.assertEqual(self.window.skip_count, 1)
        self.window.links.setPlainText(self.base + '/missing.jpg')
        for _ in range(2):
            before = Handler.requests.count('/missing.jpg')
            self.window.start()
            self.wait_for(lambda: self.window.proc is None)
            self.assertEqual(self.window.failed_links, 1)
            self.assertGreater(Handler.requests.count('/missing.jpg'), before)


if __name__ == '__main__':
    unittest.main()
