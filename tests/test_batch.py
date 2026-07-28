import os
import threading

import pytest

from audionormalizer import batch
from audionormalizer.batch import (
    BatchCallbacks, build_output_mapping, collect_audio_files, collect_selection,
    compute_reference_lufs, exclude_under, find_target_collisions,
    infer_source_folder, run_batch,
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


def test_collect_skips_leftover_temp_and_hidden_files(tmp_path):
    """Reste eines abgestürzten Laufs dürfen nicht erneut normalisiert werden."""
    (tmp_path / "song.mp3").write_bytes(b"x")
    (tmp_path / ".song.mp3.deadbeef.part.mp3").write_bytes(b"x")   # Temp-Rest
    (tmp_path / "._song.mp3").write_bytes(b"x")                    # AppleDouble
    names = [os.path.basename(f) for f in collect_audio_files([str(tmp_path)])]
    assert names == ["song.mp3"]


def test_collect_skips_hidden_directories(tmp_path):
    hidden = tmp_path / ".Trashes"
    hidden.mkdir()
    (hidden / "old.mp3").write_bytes(b"x")
    (tmp_path / "keep.mp3").write_bytes(b"x")
    names = [os.path.basename(f) for f in collect_audio_files([str(tmp_path)])]
    assert names == ["keep.mp3"]


def test_collect_selection_records_folder_as_base(tmp_path):
    sub = tmp_path / "Album"
    sub.mkdir()
    (sub / "a.mp3").write_bytes(b"x")
    sel = collect_selection([str(tmp_path)])
    assert sel.bases[sel.files[0]] == str(tmp_path)


def test_collect_selection_single_file_has_no_base(tmp_path):
    f = tmp_path / "a.mp3"
    f.write_bytes(b"x")
    sel = collect_selection([str(f)])
    assert sel.bases[sel.files[0]] == ""


# ----------------------------- Output-Mapping ----------------------------- #
def test_mapping_keeps_subfolder_when_all_files_share_one(tmp_path):
    """Regression: ``Musik/Album/*.mp3`` kollabierte im Ziel zu flachen Dateien.

    Die Basis wurde aus dem commonpath der Fundstellen geraten – der zeigt hier
    auf ``Album``, wodurch der Ordnername im Ziel verschwand.
    """
    album = tmp_path / "Musik" / "Album"
    album.mkdir(parents=True)
    (album / "a.mp3").write_bytes(b"x")
    (album / "b.mp3").write_bytes(b"x")
    sel = collect_selection([str(tmp_path / "Musik")])
    mapping = build_output_mapping(sel.files, "ZIEL", sel.bases)
    assert sorted(os.path.relpath(p, "ZIEL") for p in mapping.values()) == [
        os.path.join("Album", "a.mp3"), os.path.join("Album", "b.mp3")]


def test_mapping_keeps_deep_structure_for_single_file(tmp_path):
    """Regression: eine einzelne Datei tief im Baum verlor ihre ganze Struktur."""
    deep = tmp_path / "Musik" / "Album" / "Disc1"
    deep.mkdir(parents=True)
    (deep / "only.mp3").write_bytes(b"x")
    sel = collect_selection([str(tmp_path / "Musik")])
    mapping = build_output_mapping(sel.files, "ZIEL", sel.bases)
    assert os.path.relpath(next(iter(mapping.values())), "ZIEL") == \
        os.path.join("Album", "Disc1", "only.mp3")


def test_mapping_loose_files_stay_flat(tmp_path):
    """Direkt ausgewählte Einzeldateien landen flach im Zielordner."""
    a = tmp_path / "x" / "a.mp3"
    a.parent.mkdir()
    a.write_bytes(b"x")
    sel = collect_selection([str(a)])
    mapping = build_output_mapping(sel.files, "ZIEL", sel.bases)
    assert mapping[sel.files[0]] == os.path.join("ZIEL", "a.mp3")


# --------------------------- Ziel-Kollisionen ----------------------------- #
def test_find_collisions_detects_format_clash(tmp_path):
    """``x.wav`` + ``x.flac`` -> beide ``x.mp3``: parallel = stiller Datenverlust."""
    for name in ("x.wav", "x.flac"):
        (tmp_path / name).write_bytes(b"x")
    sel = collect_selection([str(tmp_path)])
    mapping = {src: os.path.join("ZIEL", "x.mp3") for src in sel.files}
    collisions = find_target_collisions(mapping)
    assert len(collisions) == 1
    assert len(next(iter(collisions.values()))) == 2


def test_find_collisions_detects_same_named_subfolders(tmp_path):
    """Zwei ausgewählte Ordner mit gleich benanntem Unterordner."""
    for root in ("R1", "R2"):
        d = tmp_path / root / "Album"
        d.mkdir(parents=True)
        (d / "a.mp3").write_bytes(b"x")
    sel = collect_selection([str(tmp_path / "R1"), str(tmp_path / "R2")])
    mapping = build_output_mapping(sel.files, "ZIEL", sel.bases)
    assert find_target_collisions(mapping)          # muss auffallen


def test_find_collisions_empty_for_clean_mapping():
    assert find_target_collisions({"a.wav": "o/a.wav", "b.wav": "o/b.wav"}) == {}


def test_format_collisions_is_readable():
    txt = batch.format_collisions({"/z/x.mp3": ["/s/x.wav", "/s/x.flac"]})
    assert "x.mp3" in txt and "x.wav" in txt and "x.flac" in txt


# --------------------- Eigenen Output nicht wieder einlesen ---------------- #
def test_exclude_under_skips_previous_output(tmp_path):
    """Zielordner im Quellordner: sonst wird der Gain ein zweites Mal angewandt."""
    (tmp_path / "song.mp3").write_bytes(b"x")
    out = tmp_path / "normalized"
    out.mkdir()
    (out / "song.mp3").write_bytes(b"x")
    files = collect_audio_files([str(tmp_path)])
    assert len(files) == 2
    kept = exclude_under(files, str(out))
    assert [os.path.basename(f) for f in kept] == ["song.mp3"]
    assert os.path.dirname(kept[0]) == str(tmp_path)


def test_exclude_under_without_directory_keeps_all():
    assert exclude_under(["a.wav", "b.wav"], "") == ["a.wav", "b.wav"]


# --------------------------- Log-Ordnername -------------------------------- #
def test_infer_source_folder_uses_selected_root(tmp_path):
    album = tmp_path / "Meine Musik" / "Album"
    album.mkdir(parents=True)
    (album / "a.mp3").write_bytes(b"x")
    sel = collect_selection([str(tmp_path / "Meine Musik")])
    assert infer_source_folder(sel.files, sel.bases) == "Meine Musik"


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


def test_run_batch_reports_file_done_for_failures(monkeypatch):
    """Auch Fehlschläge melden 'Datei fertig' – sonst bleibt die UI-Zeile leer."""
    _patch_engine(monkeypatch, fail_for={"b.flac"})
    seen = []
    cb = BatchCallbacks(on_file_done=lambda r: seen.append((os.path.basename(r.input_path),
                                                            r.success)))
    files = ["a.flac", "b.flac"]
    run_batch(files, {f: f for f in files}, NormalizeParams(mode=Mode.LOUDNESS),
              FAKE_TOOLS, cb)
    assert sorted(seen) == [("a.flac", True), ("b.flac", False)]


def test_run_batch_cancel(monkeypatch):
    _patch_engine(monkeypatch)
    cancel = threading.Event()
    cancel.set()
    files = ["a.flac", "b.flac"]
    res = run_batch(files, {f: f for f in files}, NormalizeParams(mode=Mode.LOUDNESS),
                    FAKE_TOOLS, cancel=cancel)
    assert res.cancelled
    assert res.success_count == 0
