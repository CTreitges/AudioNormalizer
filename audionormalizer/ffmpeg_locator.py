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


def _ensure_executable(path: str) -> None:
    """Setzt unter POSIX das +x-Bit, falls es fehlt.

    Die gebündelte imageio-ffmpeg-Binary wird als DATA-Datei mitgeliefert und
    verliert auf Linux/macOS dabei oft das Ausführbar-Bit – ohne diesen Fix
    wäre die mitgelieferte Binary dort nicht nutzbar.
    """
    if os.name == "nt" or not os.path.isfile(path):
        return
    if os.access(path, os.X_OK):
        return
    try:
        mode = os.stat(path).st_mode
        os.chmod(path, mode | 0o111)
    except OSError:
        pass


def _is_valid(path: Optional[str]) -> bool:
    if not path:
        return False
    if not (os.path.isfile(path) or shutil.which(path)):
        return False
    _ensure_executable(path)
    try:
        return run([path, "-version"], timeout=15).returncode == 0
    except Exception:
        return False


def _sibling_ffprobe(ffmpeg_path: str, allow_path_lookup: bool) -> Optional[str]:
    """Sucht ffprobe **neben** der gewählten ffmpeg-Binary.

    Ein ffprobe aus dem PATH wird nur akzeptiert, wenn auch das ffmpeg von dort
    stammt. Sonst entsteht ein Versions-Mix (z.B. gebündeltes ffmpeg 7.1 +
    System-ffprobe 8.1.2), dessen Ausgaben nicht zwingend zusammenpassen. Ohne
    passendes ffprobe bleibt es bei ``None`` – ``probe()`` parst dann die
    ``ffmpeg -i``-Ausgabe, was für alle Formate abgedeckt und getestet ist.
    """
    if not ffmpeg_path:
        return None
    base = os.path.dirname(ffmpeg_path) if os.path.isfile(ffmpeg_path) else ""
    cand = os.path.join(base, f"ffprobe{_EXE}") if base else ""
    if cand and os.path.isfile(cand):
        return cand
    return shutil.which("ffprobe") if allow_path_lookup else None


def _bundled_candidates() -> List[str]:
    """Pfade zu Binaries, die mit der App ausgeliefert werden."""
    cands: List[str] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        cands.append(os.path.join(meipass, f"ffmpeg{_EXE}"))
    # Neben der eigenen Executable (portable Distribution).
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    cands.append(os.path.join(exe_dir, f"ffmpeg{_EXE}"))
    return cands


def _imageio_candidate() -> Optional[str]:
    """Die von ``imageio-ffmpeg`` mitgelieferte Binary (bringt kein ffprobe mit)."""
    try:
        import imageio_ffmpeg  # type: ignore

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


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

    # Mit der App ausgeliefertes FFmpeg zuerst – im gepackten Build ist das die
    # einzige garantiert vorhandene Binary.
    candidates += _bundled_candidates()

    # Dann PATH: eine vollständige System-Installation bringt ffprobe mit und ist
    # damit besser als die imageio-Binary, die nur ffmpeg enthält.
    path_ffmpeg = shutil.which("ffmpeg")
    if path_ffmpeg:
        candidates.append(path_ffmpeg)

    imageio = _imageio_candidate()
    if imageio:
        candidates.append(imageio)

    candidates += _common_install_dirs()

    seen = set()
    for cand in candidates:
        if not cand or cand in seen:
            continue
        seen.add(cand)
        if _is_valid(cand):
            from_path = bool(path_ffmpeg) and os.path.normcase(
                os.path.abspath(cand)) == os.path.normcase(os.path.abspath(path_ffmpeg))
            return FFmpegTools(ffmpeg=cand,
                               ffprobe=_sibling_ffprobe(cand, allow_path_lookup=from_path))
    return None


def describe(tools: Optional[FFmpegTools]) -> str:
    """Kurze Statuszeile für UI/CLI."""
    if not tools:
        return "FFmpeg: nicht gefunden"
    probe = tools.ffprobe or "(ffprobe fehlt – nutze ffmpeg-Parsing)"
    return f"FFmpeg: {tools.ffmpeg}\nFFprobe: {probe}"
