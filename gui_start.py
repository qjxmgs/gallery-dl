"""Launch the optional Qt GUI from the repository checkout."""
import sys


def main():
    try:
        from gui.app import run
    except ModuleNotFoundError as exc:
        if exc.name not in ("PySide6", "psutil"):
            raise
        message = ('缺少 GUI 依赖，请先安装 gui/requirements.txt 中的依赖。\n'
                   'uv pip install --python .venv\\Scripts\\python.exe '
                   '-r gui\\requirements.txt')
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, "gallery-dl", 16)
        else:
            print(message, file=sys.stderr)
        return 1
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
