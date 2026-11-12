"""One URL per isolated process; stdout carries JSON events, stderr logs."""
import json
import os
import time


def emit(kind, **values):
    print(json.dumps(dict(type=kind, **values), ensure_ascii=False), flush=True)


class ProgressOutput:
    def __init__(self):
        self.last = 0

    def start(self, path):
        self.last = 0
        emit("start", path=str(path))

    def skip(self, path):
        emit("skip", path=str(path))

    def success(self, path):
        emit("success", path=str(path))

    def progress(self, bytes_total, bytes_downloaded, bytes_per_second):
        now = time.monotonic()
        if now - self.last >= 0.15:
            self.last = now
            emit("progress", total=bytes_total, downloaded=bytes_downloaded,
                 speed=bytes_per_second)


def main():
    import gallery_dl
    from gallery_dl import output, path
    from .naming import DATE_FORMAT_ENV, dated_path_format
    # Adapt the existing output hook only in this disposable child process.
    output.select = ProgressOutput
    if date_format := os.environ.get(DATE_FORMAT_ENV):
        path.PathFormat = dated_path_format(path.PathFormat, date_format)
    return gallery_dl.main()


if __name__ == "__main__":
    raise SystemExit(main())
