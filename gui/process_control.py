"""Suspend only the owned download worker and its helper processes."""
import psutil


class PausedProcessTree:
    def __init__(self):
        self.processes = []

    def pause(self, pid):
        if self.processes:
            return
        root = psutil.Process(pid)
        try:
            root.suspend()
            self.processes.append(root)
            # Freeze the parent first so it cannot spawn more helpers.
            for child in root.children(recursive=True):
                try:
                    child.suspend()
                    self.processes.append(child)
                except psutil.NoSuchProcess:
                    pass
        except Exception:
            self.resume()
            raise

    def resume(self):
        failed = []
        error = None
        # Resume helpers before the parent; Process tracks PID reuse safely.
        for process in reversed(self.processes):
            try:
                process.resume()
            except psutil.NoSuchProcess:
                pass
            except psutil.Error as exc:
                failed.append(process)
                error = exc
        self.processes = list(reversed(failed))
        if error:
            raise error

    def clear(self):
        self.processes.clear()
