"""Findet und validiert die FFmpeg-/FFprobe-Binaries.

Suchreihenfolge (erste funktionierende gewinnt):

1. Explizit übergebener Pfad (z.B. aus den gespeicherten Einstellungen).
2. Gebündelte Binary (PyInstaller ``_MEIPASS`` bzw. ``imageio-ffmpeg``).
3. ``PATH`` (``shutil.which``).
4. Übliche Installationsorte je Betriebssystem.

Eine Binary gilt erst dann als gültig, wenn ``<bin> -version`` Exit 0 liefert.
FFprobe ist optional: fehlt es, fällt die Stream-Analyse (``probe``) auf das
Parsen von ``ffmpeg -i`` zurück.
"""
from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from typing import List, Optional

from .procutil import run

_EXE = ".exe" if os.name == "nt" else ""


@dataclass(frozen=True)
class FFmpegTools:
    ffmpeg: str
    ffprobe: Optional[str] = None

    @property
    def has_ffprobe(self) -> bool:
        return bool(self.ffprobe)


def _is_valid(path: Optional[str]) -> bool:
    if not path:
        return False
    if not (os.path.isfile(path) or shutil.which(path)):
        return False
    try:
        return run([path, "-version"], timeout=15).returncode == 0
    except Exception:
        return False


def _sibling_ffprobe(ffmpeg_path: str) -> Optional[str]:
    """Sucht ffprobe neben einer ffmpeg-Binary."""
    if not ffmpeg_path:
        return None
    base = os.path.dirname(ffmpeg_path) if os.path.isfile(ffmpeg_path) else ""
    cand = os.path.join(base, f"ffprobe{_EXE}") if base else ""
    if cand and os.path.isfile(cand):
        return cand
    which = shutil.which("ffprobe")
    return which


def _bundled_candidates() -> List[str]:
    """Pfade zu mitgelieferten Binaries (PyInstaller / imageio-ffmpeg)."""
    cands: List[str] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        cands.append(os.path.join(meipass, f"ffmpeg{_EXE}"))
    # Neben der eigenen Executable (portable Distribution).
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    cands.append(os.path.join(exe_dir, f"ffmpeg{_EXE}"))
    # imageio-ffmpeg liefert eine eigene Binary mit.
    try:
        import imageio_ffmpeg  # type: ignore

        cands.append(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception:
        pass
    return cands


def _common_install_dirs() -> List[str]:
    out: List[str] = []
    if os.name == "nt":
        for env in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            root = os.environ.get(env)
            if root:
                out.append(os.path.join(root, "ffmpeg", "bin", "ffmpeg.exe"))
        out.append(r"C:\ffmpeg\bin\ffmpeg.exe")
    else:
        out += ["/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/opt/homebrew/bin/ffmpeg",
                "/snap/bin/ffmpeg"]
    return out


def locate(preferred: Optional[str] = None) -> Optional[FFmpegTools]:
    """Findet die beste verfügbare FFmpeg-Installation.

    ``preferred`` kann ein Pfad zur ``ffmpeg``-Binary ODER zu einem Ordner sein,
    der sie enthält (wie es das alte Einstellungsfeld zuließ).
    """
    candidates: List[str] = []

    if preferred:
        preferred = os.path.normpath(preferred)
        if os.path.isdir(preferred):
            candidates.append(os.path.join(preferred, f"ffmpeg{_EXE}"))
            candidates.append(os.path.join(preferred, "ffmpeg"))
        else:
            candidates.append(preferred)

    candidates += _bundled_candidates()

    path = shutil.which("ffmpeg")
    if path:
        candidates.append(path)

    candidates += _common_install_dirs()

    seen = set()
    for cand in candidates:
        if not cand or cand in seen:
            continue
        seen.add(cand)
        if _is_valid(cand):
            return FFmpegTools(ffmpeg=cand, ffprobe=_sibling_ffprobe(cand))
    return None


def describe(tools: Optional[FFmpegTools]) -> str:
    """Kurze Statuszeile für UI/CLI."""
    if not tools:
        return "FFmpeg: nicht gefunden"
    probe = tools.ffprobe or "(ffprobe fehlt – nutze ffmpeg-Parsing)"
    return f"FFmpeg: {tools.ffmpeg}\nFFprobe: {probe}"
