from datetime import datetime

from audionormalizer.logwriter import build_log_text, write_log_file
from audionormalizer.models import Mode, NormalizeParams


WHEN = datetime(2026, 2, 19, 1, 31, 35)


def test_log_text_hybrid_matches_legacy_format():
    p = NormalizeParams(mode=Mode.HYBRID, target_peak=-3.0, target_tp=-3.0,
                        target_dev=3.0)
    p.ref_lufs = -12.52
    text = build_log_text(p, success_count=10, error_count=0, when=WHEN)
    assert "Audio Normalizer Log" in text
    assert "====================" in text
    assert "Datum/Zeit: 19.02.2026 01:31:35" in text
    assert "Modus: Hybrid-Normalizing" in text
    assert "Ziel Peak: -3.0 dB" in text
    assert "Max True Peak: -3.0 dB" in text
    assert "Max. Abweichung: 3.0 dB" in text
    assert "Verwendete Referenz LUFS: -12.52 LUFS" in text
    assert "Erfolgreich verarbeitet: 10" in text
    assert "Fehler: 0" in text


def test_log_text_loudness():
    p = NormalizeParams(mode=Mode.LOUDNESS, target_lufs=-8.0, target_tp=-3.0)
    text = build_log_text(p, 1, 0, WHEN)
    assert "Modus: Loudness-Normalizing" in text
    assert "Ziel Loudness: -8.0 LUFS" in text
    assert "Max True Peak: -3.0 dB" in text


def test_log_text_peak():
    p = NormalizeParams(mode=Mode.PEAK, target_peak=-3.0)
    text = build_log_text(p, 5, 1, WHEN)
    assert "Modus: Peak-Normalizing" in text
    assert "Ziel Peak: -3.0 dB" in text


def test_log_text_hybrid_manual_ref_note():
    p = NormalizeParams(mode=Mode.HYBRID, ref_lufs_override=-10.0)
    p.ref_lufs = -10.0
    text = build_log_text(p, 3, 0, WHEN)
    assert "(Manuelle Referenz: -10.0 LUFS)" in text


def test_write_log_file_creates_named_file(tmp_path):
    p = NormalizeParams(mode=Mode.PEAK, target_peak=-3.0)
    path = write_log_file(str(tmp_path), "MeinePlaylist", p, 4, 0, WHEN)
    assert path is not None
    assert path.endswith("Audio-Normalizer-Log-2026-02-19_01-31-MeinePlaylist.txt")
    content = open(path, encoding="utf-8").read()
    assert "Erfolgreich verarbeitet: 4" in content
