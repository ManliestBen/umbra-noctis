"""Background workers: long operations never block the UI."""

from __future__ import annotations

import traceback

from PySide6.QtCore import QThread, Signal


class FnWorker(QThread):
    """Run ``fn(*args, progress=..., log=...)`` off the UI thread.

    Signals:
      progressed(stage, done, total), logged(str),
      succeeded(object result), failed(str traceback)
    """

    progressed = Signal(str, int, int)
    logged = Signal(str)
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, fn, *args, wants_progress=True, wants_log=True, **kwargs):
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs
        self._wants_progress = wants_progress
        self._wants_log = wants_log

    def run(self):
        try:
            kwargs = dict(self._kwargs)
            if self._wants_progress:
                kwargs["progress"] = self._emit_progress
            if self._wants_log:
                kwargs["log"] = self.logged.emit
            result = self._fn(*self._args, **kwargs)
            self.succeeded.emit(result)
        except Exception:
            self.failed.emit(traceback.format_exc())

    def _emit_progress(self, *args):
        # accepts (done, total) or (stage, done, total)
        if len(args) == 2:
            self.progressed.emit("", int(args[0]), int(args[1]))
        else:
            self.progressed.emit(str(args[0]), int(args[1]), int(args[2]))
