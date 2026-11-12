"""Native log window attached to its owner."""
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QWidget
import sys

if sys.platform == 'win32':
    import ctypes
    from ctypes import wintypes
    _user32 = ctypes.WinDLL('user32', use_last_error=True)
    _user32.GetWindowRect.argtypes = (
        wintypes.HWND, ctypes.POINTER(wintypes.RECT))
    _user32.GetWindowRect.restype = wintypes.BOOL
    _user32.SetWindowPos.argtypes = (wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                     ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT)
    _user32.SetWindowPos.restype = wintypes.BOOL
    _user32.GetDpiForWindow.argtypes = (wintypes.HWND,)
    _user32.GetDpiForWindow.restype = wintypes.UINT


def follow_native_drag(owner, message):
    """Update the owned HWND inside Windows' modal move loop, without timers."""
    if sys.platform != 'win32':
        return
    msg = wintypes.MSG.from_address(int(message))
    if msg.message == 0x0231:  # WM_ENTERSIZEMOVE
        owner._native_dragging = True
    elif msg.message in (0x0216, 0x0214, 0x0232):  # MOVING, SIZING, EXITSIZEMOVE
        log = getattr(owner, 'log_window', None)
        if log is not None and log.isVisible():
            rect = wintypes.RECT()
            if msg.message == 0x0232:
                _user32.GetWindowRect(int(owner.winId()), ctypes.byref(rect))
            else:
                rect = wintypes.RECT.from_address(msg.lParam)
            child = wintypes.RECT()
            hwnd = int(log.winId())
            if _user32.GetWindowRect(hwnd, ctypes.byref(child)):
                gap = round(
                    8 * (_user32.GetDpiForWindow(int(owner.winId())) or 96) / 96)
                # Native rectangles use physical pixels, including both title bars.
                _user32.SetWindowPos(hwnd, None, rect.right + gap, rect.top,
                                     child.right - child.left, rect.bottom - rect.top,
                                     0x0014)  # SWP_NOZORDER | SWP_NOACTIVATE
        if msg.message == 0x0232:
            owner._native_dragging = False


class LogWindow(QWidget):
    def __init__(self, owner):
        super().__init__(owner, Qt.WindowType.Window | Qt.WindowType.WindowTitleHint |
                         Qt.WindowType.WindowSystemMenuHint | Qt.WindowType.WindowCloseButtonHint)
        self.owner = owner
        self.setWindowTitle('gallery-dl · 运行日志')
        self.setWindowIcon(owner.windowIcon())
        self.resize(470, 650)
        self.setMinimumSize(320, 100)

    def hideEvent(self, event):
        self.owner.log_button.setChecked(False)
        super().hideEvent(event)

    def showEvent(self, event):
        self.owner.log_button.setChecked(True)
        super().showEvent(event)
        QTimer.singleShot(0, self.owner.sync_log_geometry)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not getattr(self.owner, '_native_dragging', False):
            self.owner.sync_log_geometry()
