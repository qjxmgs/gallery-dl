"""Worker-local bounded RAM staging for HTTP downloads.

Archive writes and completion events follow successful file commits. Existing
partial files and external downloaders keep their normal disk-based behavior.
"""
import copy
import io
import os
import threading

BATCH_ENV = 'GALLERY_DL_GUI_BATCH_WRITE'
LIMIT = 200 * 1024 * 1024


class MemoryFile:
    def __init__(self, batch, path):
        self.batch, self.path = batch, path
        self.stream = io.BytesIO()
        self.memory = True
        self.opened = False
        self.finalize = None
        self.final_path = None

    def __enter__(self):
        self.opened = True
        return self

    def __exit__(self, *args):
        self.opened = False
        if not self.memory:
            self.stream.close()

    def __getattr__(self, name):
        return getattr(self.stream, name)

    def write(self, data):
        if self.memory:
            before = self.stream.getbuffer().nbytes
            # Spill before the next chunk could exceed the shared RAM budget.
            growth = max(0, self.stream.tell() + len(data) - before)
            if self.batch.size + growth > self.batch.limit:
                self.batch.flush()
            if self.memory:
                result = self.stream.write(data)
                self.batch.size += self.stream.getbuffer().nbytes - before
                if self.batch.size >= self.batch.limit:
                    self.batch.flush()
                return result
        return self.stream.write(data)

    def spill(self):
        position = self.stream.tell()
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        target = open(self.path, 'w+b')
        try:
            with self.stream.getbuffer() as data:
                target.write(data)
            target.flush()
            target.seek(position)
        except BaseException:
            target.close()
            raise
        self.stream.close()
        self.stream = target
        self.memory = False
        if not self.opened:
            target.close()
        if self.finalize:
            self.finalize()


class BatchWriter:
    def __init__(self, emit, limit=LIMIT):
        self.emit, self.limit = emit, limit
        self.files = {}
        self.size = 0
        self.callbacks = []

    def flush(self):
        # Keep callbacks pending if any write/finalize fails: never mark an
        # unwritten file as complete or put it into the download archive.
        for name, stream in list(self.files.items()):
            if stream.memory:
                size = stream.stream.getbuffer().nbytes
                try:
                    stream.spill()
                finally:
                    if not stream.memory:
                        self.size -= size
            elif stream.finalize:
                stream.finalize()
            del self.files[name]
        callbacks, self.callbacks = self.callbacks, []
        for callback in callbacks:
            callback()

    def defer(self, callback):
        if self.files:
            self.callbacks.append(callback)
        else:
            callback()

    def install(self):
        from gallery_dl import path, job, archive
        from gallery_dl.downloader.http import HttpDownloader
        batch = self
        base = path.PathFormat

        class BufferedPath(base):
            _batch_http = False

            def open(self, mode='wb'):
                if not self._batch_http:
                    return super().open(mode)
                name = self.temppath
                if name in batch.files:
                    stream = batch.files[name]
                    if 'w' in mode:
                        batch.size -= stream.stream.getbuffer().nbytes
                        stream.stream.seek(0)
                        stream.stream.truncate()
                    else:
                        stream.stream.seek(0)
                    return stream
                if 'w' not in mode or os.path.exists(name):
                    return super().open(mode)
                stream = batch.files[name] = MemoryFile(batch, name)
                return stream

            def part_size(self):
                stream = batch.files.get(self.temppath)
                return stream.stream.getbuffer().nbytes if stream else super().part_size()

            def exists(self):
                return any(s.final_path == self.realpath for s in batch.files.values()) or super().exists()

            def finalize(self):
                stream = batch.files.get(self.temppath)
                if stream is None:
                    return super().finalize()
                snapshot = copy.copy(self)
                snapshot.kwdict = self.kwdict.copy()
                stream.final_path = self.realpath
                stream.finalize = lambda: base.finalize(snapshot)

        path.PathFormat = BufferedPath
        original_download = HttpDownloader.download

        def download(downloader, url, pathfmt):
            pathfmt._batch_http = True
            try:
                return original_download(downloader, url, pathfmt)
            finally:
                pathfmt._batch_http = False

        HttpDownloader.download = download
        original_finalize = job.DownloadJob.handle_finalize

        def finalize(current_job):
            batch.flush()
            return original_finalize(current_job)

        job.DownloadJob.handle_finalize = finalize
        original_add = archive.DownloadArchive.add
        original_check = archive.DownloadArchive.check
        pending = set()

        def add(current_archive, data):
            data = data.copy()
            key = (id(current_archive), data.get(current_archive._cache_key) or current_archive.keygen(data))
            pending.add(key)
            def commit():
                original_add(current_archive, data)
                pending.discard(key)
            batch.defer(commit)

        def check(current_archive, data):
            key = current_archive.keygen(data)
            if (id(current_archive), key) in pending:
                data[current_archive._cache_key] = key
                return True
            return original_check(current_archive, data)

        archive.DownloadArchive.add = add
        archive.DownloadArchive.check = check


def listen_for_stop():
    import sys
    from gallery_dl.util import FLAGS
    for line in sys.stdin:
        if line.strip() == 'stop':
            FLAGS.FILE = FLAGS.DOWNLOAD = 'abort'
            return


def start_stop_listener():
    threading.Thread(target=listen_for_stop, daemon=True).start()
