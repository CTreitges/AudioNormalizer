import os
import threading

import pytest

from audionormalizer import batch
from audionormalizer.batch import (
    BatchCallbacks, build_output_mapping, collect_audio_files,
    compute_reference_lufs, run_batch,
)
from audionormalizer.ffmpeg_locator import FFmpegTools
from audionormalizer.models import FileResult, Measurement, Mode, NormalizeParams


FAKE_TOOLS = FFmpegTools(ffmpeg="ffmpeg", ffprobe="ffprobe")


# ----------------------------- Datei-Sammlung ----------------------------- #
def test_collect_recursive_filtered_dedupe(tmp_path):
    (tmp_path / "a.wav").write_bytes(b"x")
    (tmp_path / "b.flac").write_bytes(b"x")
    (tmp_path / "c.txt").write_bytes(b"x")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "d.mp3").write_bytes(b"x")
    files = collect_audio_files([str(tmp_path), str(tmp_path / "a.wav")])
    names = sorted(os.path.basename(f) for f in files)
    assert names == ["a.wav", "b.flac", "d.mp3"]   # txt raus, a.wav nur 1x


# ----------------------------- Output-Mapping ----------------------------- #
def test_output_mapping_preserves_subdirs(tmp_path):
    f1 = str(tmp_path / "alb" / "1.flac")
    f2 = str(tmp_path / "alb" / "cd2" / "2.flac")
    os.makedirs(os.path.dirname(f1))
    os.makedirs(os.path.dirname(f2))
    open(f1, "w").close()
    open(f2, "w").close()
    out = str(tmp_path / "out")
    mapping = build_output_mapping([f1, f2], out)
    assert mapping[f1] == os.path.join(out, "1.flac")
    assert mapping[f2] == os.path.join(out, "cd2", "2.flac")


def test_output_mapping_single_file(tmp_path):
    f = str(tmp_path / "x.wav")
    open(f, "w").close()
    mapping = build_output_mapping([f], str(tmp_path / "out"))
    assert mapping[f] == os.path.join(str(tmp_path / "out"), "x.wav")


def test_output_mapping_mixed_drive_fallback(tmp_path, monkeypatch):
    # commonpath wirft bei verschiedenen Laufwerken (Windows) -> Fallback basename
    monkeypatch.setattr(os.path, "commonpath",
                        lambda *_a, **_k: (_ for _ in ()).throw(ValueError()))
    f1 = "C:/a/x.wav"
    f2 = "D:/b/y.wav"
    mapping = build_output_mapping([f1, f2], "out")
    assert mapping[f1] == os.path.join("out", "x.wav")
    assert mapping[f2] == os.path.join("out", "y.wav")


# --------------------------- Referenz-LUFS -------------------------------- #
def test_reference_lufs_override_wins():
    assert compute_reference_lufs({}, override=-10.0, fallback=-11.0) == -10.0


def test_reference_lufs_mean():
    meas = {"a": Measurement(lufs=-10.0), "b": Measurement(lufs=-14.0), "c": None}
    assert compute_reference_lufs(meas, None, -11.0) == pytest.approx(-12.0)


def test_reference_lufs_fallback_when_empty():
    assert compute_reference_lufs({}, None, -11.0) == -11.0


# --------------------------- Orchestrierung ------------------------------- #
def _patch_engine(monkeypatch, fail_for=None):
    """Ersetzt die echte Engine durch eine schnelle Fake-Implementierung."""
    fail_for = fail_for or set()

    def fake_normalize(f, out, params, tools, measurement=None, cancel=None,
                       backup_path=None):
        if cancel is not None and cancel.is_set():
            raise batch.engine.CancelledError()
        if os.path.basename(f) in fail_for:
            raise RuntimeError("ffmpeg kaputt")
        mode = batch.engine.decide_actual_mode(params, measurement.lufs if measurement else None)
        return FileResult(input_path=f, output_path=out, mode_used=mode,
                          applied_gain_db=1.0, success=True)

    monkeypatch.setattr(batch.engine, "normalize_file", fake_normalize)
    monkeypatch.setattr(batch._measure, "measure_loudness",
                        lambda f, tools, cancel=None: Measurement(lufs=-12.0, true_peak=-2.0))


def test_run_batch_loudness_success(monkeypatch):
    _patch_engine(monkeypatch)
    files = ["a.flac", "b.flac"]
    mapping = {f: f"out/{f}" for f in files}
    params = NormalizeParams(mode=Mode.LOUDNESS)
    res = run_batch(files, mapping, params, FAKE_TOOLS)
    assert res.success_count == 2
    assert res.error_count == 0
    assert not res.cancelled


def test_run_batch_hybrid_runs_analysis_and_sets_ref(monkeypatch):
    _patch_engine(monkeypatch)
    files = ["a.flac", "b.flac", "c.flac"]
    mapping = {f: f"out/{f}" for f in files}
    params = NormalizeParams(mode=Mode.HYBRID)
    phases = []
    cb = BatchCallbacks(on_phase=lambda name, total: phases.append(name))
    res = run_batch(files, mapping, params, FAKE_TOOLS, cb)
    assert res.success_count == 3
    assert res.ref_lufs == pytest.approx(-12.0)     # Mittelwert der Fakes
    assert any("Analysiere" in p for p in phases)    # Analyse-Phase lief
    assert any("Verarbeite" in p for p in phases)


def test_run_batch_hybrid_manual_ref_still_analyzes(monkeypatch):
    # Bugfix-Regression: manueller Ref-Wert darf die Analyse NICHT überspringen.
    calls = {"n": 0}

    def counting_measure(f, tools, cancel=None):
        calls["n"] += 1
        return Measurement(lufs=-12.0, true_peak=-2.0)

    monkeypatch.setattr(batch._measure, "measure_loudness", counting_measure)
    monkeypatch.setattr(batch.engine, "normalize_file",
                        lambda f, out, params, tools, measurement=None, cancel=None,
                        backup_path=None:
                        FileResult(input_path=f, output_path=out, success=True))
    files = ["a.flac", "b.flac"]
    params = NormalizeParams(mode=Mode.HYBRID, ref_lufs_override=-9.0)
    res = run_batch(files, {f: f for f in files}, params, FAKE_TOOLS)
    assert calls["n"] == 2          # beide Dateien analysiert
    assert res.ref_lufs == -9.0     # Override gewinnt als Ziel


def test_run_batch_counts_errors(monkeypatch):
    _patch_engine(monkeypatch, fail_for={"b.flac"})
    files = ["a.flac", "b.flac"]
    res = run_batch(files, {f: f for f in files}, NormalizeParams(mode=Mode.LOUDNESS),
                    FAKE_TOOLS)
    assert res.success_count == 1
    assert res.error_count == 1
    assert res.ffmpeg_error


def test_run_batch_passes_backup_path(monkeypatch):
    seen = {}

    def rec_normalize(f, out, params, tools, measurement=None, cancel=None,
                      backup_path=None):
        seen[f] = backup_path
        return FileResult(input_path=f, output_path=out, success=True)

    monkeypatch.setattr(batch.engine, "normalize_file", rec_normalize)
    files = ["a.flac", "b.flac"]
    mapping = {f: f for f in files}                       # Überschreiben
    backup = {"a.flac": "bak/a.flac", "b.flac": "bak/b.flac"}
    res = run_batch(files, mapping, NormalizeParams(mode=Mode.LOUDNESS), FAKE_TOOLS,
                    backup_mapping=backup)
    assert res.success_count == 2
    assert seen["a.flac"] == "bak/a.flac"
    assert seen["b.flac"] == "bak/b.flac"


def test_run_batch_cancel(monkeypatch):
    _patch_engine(monkeypatch)
    cancel = threading.Event()
    cancel.set()
    files = ["a.flac", "b.flac"]
    res = run_batch(files, {f: f for f in files}, NormalizeParams(mode=Mode.LOUDNESS),
                    FAKE_TOOLS, cancel=cancel)
    assert res.cancelled
    assert res.success_count == 0
