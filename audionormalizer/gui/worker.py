"""Hintergrund-Thread, der einen Batch-Lauf ausführt und Qt-Signale emittiert."""
from __future__ import annotations

import threading
from typing import Dict, List

from PyQt6.QtCore import QThread, pyqtSignal

from ..batch import BatchCallbacks, BatchResult, run_batch
from ..ffmpeg_locator import FFmpegTools
from ..models import FileResult, NormalizeParams


class NormalizeWorker(QThread):
    """Führt ``run_batch`` außerhalb des UI-Threads aus.

    Die Fortschritts-Callbacks von ``run_batch`` feuern aus Pool-Threads; die
    hier emittierten Signale werden von Qt thread-sicher in den UI-Thread
    zugestellt (Queued Connection).
    """

    phase = pyqtSignal(str, int)        # (name, total)
    progress = pyqtSignal(int, int)     # (done, total)
    file_done = pyqtSignal(object)      # FileResult
    error = pyqtSignal(str)
    done = pyqtSignal(object)           # BatchResult

    def __init__(self, files: List[str], mapping: Dict[str, str],
                 params: NormalizeParams, tools: FFmpegTools, parent=None):
        super().__init__(parent)
        self._files = files
        self._mapping = mapping
        self._params = params
        self._tools = tools
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        callbacks = BatchCallbacks(
            on_phase=lambda name, total: self.phase.emit(name, total),
            on_progress=lambda done, total: self.progress.emit(done, total),
            on_file_done=lambda res: self.file_done.emit(res),
            on_error=lambda msg: self.error.emit(msg),
        )
        try:
            result = run_batch(self._files, self._mapping, self._params,
                               self._tools, callbacks, self._cancel)
        except Exception as exc:  # defensiver Schutz – sollte nicht passieren
            result = BatchResult(error_count=1)
            self.error.emit(f"Unerwarteter Fehler: {exc}")
        self.done.emit(result)
