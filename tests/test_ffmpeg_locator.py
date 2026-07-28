import os

from audionormalizer import ffmpeg_locator
from audionormalizer.ffmpeg_locator import FFmpegTools, describe


def test_locate_prefers_valid_preferred(monkeypatch):
    exp = os.path.normpath("/opt/ffmpeg")
    monkeypatch.setattr(ffmpeg_locator, "_is_valid", lambda p: p == exp)
    monkeypatch.setattr(ffmpeg_locator, "_sibling_ffprobe",
                        lambda p, allow_path_lookup=False: "/opt/ffprobe")
    tools = ffmpeg_locator.locate("/opt/ffmpeg")
    assert tools is not None
    assert tools.ffmpeg == exp
    assert tools.ffprobe == "/opt/ffprobe"
    assert tools.has_ffprobe


def test_locate_returns_none_when_nothing_valid(monkeypatch):
    monkeypatch.setattr(ffmpeg_locator, "_is_valid", lambda p: False)
    monkeypatch.setattr(ffmpeg_locator, "_bundled_candidates", lambda: [])
    monkeypatch.setattr(ffmpeg_locator, "_common_install_dirs", lambda: [])
    monkeypatch.setattr(ffmpeg_locator.shutil, "which", lambda *_a, **_k: None)
    assert ffmpeg_locator.locate(None) is None


def test_locate_falls_back_to_path(monkeypatch):
    exp = os.path.normpath("/usr/bin/ffmpeg")
    monkeypatch.setattr(ffmpeg_locator, "_bundled_candidates", lambda: [])
    monkeypatch.setattr(ffmpeg_locator.shutil, "which",
                        lambda name, *a, **k: exp if name == "ffmpeg" else None)
    monkeypatch.setattr(ffmpeg_locator, "_is_valid", lambda p: p == exp)
    monkeypatch.setattr(ffmpeg_locator, "_sibling_ffprobe",
                        lambda p, allow_path_lookup=False: None)
    tools = ffmpeg_locator.locate(None)
    assert tools is not None and tools.ffmpeg == exp
    assert not tools.has_ffprobe


def test_sibling_ffprobe_rejects_foreign_path_binary(monkeypatch, tmp_path):
    """Gebündeltes ffmpeg darf sich kein ffprobe aus dem PATH danebenholen.

    Sonst entsteht ein Versions-Mix (gebündeltes ffmpeg + fremdes System-ffprobe).
    """
    bundled = tmp_path / "ffmpeg.exe"
    bundled.write_bytes(b"x")           # kein ffprobe daneben
    monkeypatch.setattr(ffmpeg_locator.shutil, "which",
                        lambda name, *a, **k: "/usr/bin/ffprobe")
    assert ffmpeg_locator._sibling_ffprobe(str(bundled), allow_path_lookup=False) is None
    assert ffmpeg_locator._sibling_ffprobe(str(bundled), allow_path_lookup=True) \
        == "/usr/bin/ffprobe"


def test_sibling_ffprobe_prefers_real_neighbour(tmp_path):
    ffmpeg = tmp_path / f"ffmpeg{ffmpeg_locator._EXE}"
    ffprobe = tmp_path / f"ffprobe{ffmpeg_locator._EXE}"
    ffmpeg.write_bytes(b"x")
    ffprobe.write_bytes(b"x")
    assert ffmpeg_locator._sibling_ffprobe(str(ffmpeg), allow_path_lookup=False) \
        == str(ffprobe)


def test_describe():
    assert "nicht gefunden" in describe(None)
    txt = describe(FFmpegTools(ffmpeg="/x/ffmpeg", ffprobe="/x/ffprobe"))
    assert "/x/ffmpeg" in txt and "/x/ffprobe" in txt
