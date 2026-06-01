"""Gemeinsame Subprozess-Helfer.

Stellt sicher, dass unter Windows nie ein Konsolenfenster aufblitzt
(STARTUPINFO + CREATE_NO_WINDOW) und kapselt das robuste Dekodieren von
FFmpeg-Output (immer ``errors="replace"`` – FFmpeg gibt bei exotischen
Dateinamen gern nicht-UTF8-Bytes auf stderr aus).
"""
from __future__ import annotations

import os
import subprocess
import threading
from subprocess import TimeoutExpired
from typing import Optional, Sequence, Tuple

# Unter Windows: Fenster der gestarteten Konsolenprozesse unterdrücken.
_CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


class CancelledError(Exception):
    """Wird ausgelöst, wenn ein Lauf über das Cancel-Event abgebrochen wird."""


def hidden_kwargs() -> dict:
    """Liefert subprocess-kwargs, die unter Windows jedes Fenster verhindern."""
    kwargs: dict = {}
    if os.name == "nt":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        kwargs["startupinfo"] = si
        kwargs["creationflags"] = _CREATE_NO_WINDOW
    return kwargs


def run(cmd: Sequence[str], timeout: Optional[float] = None) -> subprocess.CompletedProcess:
    """``subprocess.run`` mit versteckten Fenstern und robustem Decoding."""
    return subprocess.run(
        list(cmd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        **hidden_kwargs(),
    )


def popen(cmd: Sequence[str]) -> subprocess.Popen:
    """``subprocess.Popen`` mit versteckten Fenstern und robustem Decoding.

    Wird für abbrechbare Läufe verwendet (siehe ``run_cancellable``)."""
    return subprocess.Popen(
        list(cmd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        **hidden_kwargs(),
    )


def run_cancellable(
    cmd: Sequence[str],
    cancel: "Optional[threading.Event]" = None,
    poll: float = 0.25,
) -> Tuple[int, str, str]:
    """Führt einen Prozess aus, der über ``cancel`` abbrechbar ist.

    Gibt ``(returncode, stdout, stderr)`` zurück. Bei gesetztem Cancel-Event
    wird der Prozess terminiert (und nötigenfalls gekillt) und ``CancelledError``
    geworfen. Ohne Cancel-Event entspricht das Verhalten einem normalen Lauf,
    nutzt aber denselben deadlock-freien ``communicate``-Loop.
    """
    proc = popen(cmd)
    stdout = ""
    stderr = ""
    while True:
        try:
            out, err = proc.communicate(timeout=poll)
            stdout = out or ""
            stderr = err or ""
            break
        except TimeoutExpired:
            if cancel is not None and cancel.is_set():
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except TimeoutExpired:
                    proc.kill()
                raise CancelledError()
    return proc.returncode, stdout, stderr
