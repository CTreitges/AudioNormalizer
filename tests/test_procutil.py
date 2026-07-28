import subprocess
import sys

from audionormalizer import procutil


def test_popen_detaches_stdin(monkeypatch):
    """Ohne DEVNULL erben alle parallelen FFmpeg-Prozesse dasselbe Terminal-stdin.

    FFmpeg liest von dort seine interaktiven Tastenkommandos – bei einem
    Stapellauf greifen dann mehrere Prozesse gleichzeitig auf die Konsole zu.
    """
    seen = {}

    class FakePopen:
        def __init__(self, cmd, **kwargs):
            seen.update(kwargs)

    monkeypatch.setattr(procutil.subprocess, "Popen", FakePopen)
    procutil.popen(["ffmpeg", "-i", "x.wav"])
    assert seen["stdin"] is subprocess.DEVNULL


def test_run_detaches_stdin(monkeypatch):
    seen = {}
    monkeypatch.setattr(procutil.subprocess, "run",
                        lambda cmd, **kwargs: seen.update(kwargs))
    procutil.run(["ffmpeg", "-version"])
    assert seen["stdin"] is subprocess.DEVNULL


def test_run_cancellable_returns_output():
    """Echter Subprozess: der communicate-Loop darf nichts verschlucken."""
    rc, out, _err = procutil.run_cancellable(
        [sys.executable, "-c", "print('hallo')"])
    assert rc == 0
    assert "hallo" in out
