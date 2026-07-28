"""Lautheits- und Pegelmessung über FFmpeg.

- ``loudnorm=print_format=json``  -> integrierte LUFS + True Peak (EBU R128)
- ``volumedetect``                -> Sample Peak (max_volume)

Die reinen Parser sind von den Subprozess-Aufrufen getrennt, damit sie mit
festen stderr-Fixtures unit-getestet werden können (kein FFmpeg im Test nötig).
"""
from __future__ import annotations

import json
import re
import threading
from typing import Optional

from .ffmpeg_locator import FFmpegTools
from .models import Measurement
from .procutil import run_cancellable

_RE_JSON = re.compile(r"\{[^{}]*\}", re.DOTALL)
_RE_MAXVOL = re.compile(r"max_volume:\s*([\-\d.]+)\s*dB")


def _extract_loudnorm_block(stderr: str) -> Optional[dict]:
    """Sucht gezielt den loudnorm-Block, nicht irgendeinen ``{...}`` auf stderr.

    Andere Filter und Fehlermeldungen können ebenfalls geschweifte Klammern
    ausgeben; wird davon der erste Treffer genommen, schlägt die Messung fehl
    oder liefert Unsinn. Maßgeblich ist der letzte Block mit ``input_i``.
    """
    found = None
    for match in _RE_JSON.finditer(stderr or ""):
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and "input_i" in data:
            found = data
    return found


def parse_loudnorm_json(stderr: str) -> Measurement:
    """Extrahiert LUFS + True Peak aus dem loudnorm-JSON-Block auf stderr."""
    data = _extract_loudnorm_block(stderr)
    if data is None:
        raise ValueError("Kein loudnorm-JSON im FFmpeg-Output gefunden.")

    def _f(key: str) -> Optional[float]:
        raw = data.get(key)
        if raw is None:
            return None
        try:
            val = float(raw)
        except (TypeError, ValueError):
            return None
        # loudnorm meldet bei Stille Sentinel-Werte wie -inf / -99/-120.
        if val <= -120.0 or val != val:  # -inf-Schutz + NaN
            return None
        return val

    lufs = _f("input_i")
    tp = _f("input_tp")
    if lufs is None and tp is None:
        raise ValueError("loudnorm lieferte keine verwertbaren Messwerte.")
    return Measurement(lufs=lufs, true_peak=tp)


def parse_volumedetect(stderr: str) -> float:
    """Extrahiert den Sample-Peak (max_volume) aus volumedetect-stderr."""
    match = _RE_MAXVOL.search(stderr or "")
    if not match:
        raise ValueError("max_volume nicht im FFmpeg-Output gefunden.")
    return float(match.group(1))


def measure_loudness(
    file_path: str, tools: FFmpegTools,
    cancel: Optional[threading.Event] = None,
) -> Measurement:
    """Misst integrierte LUFS + True Peak (ein voller Decode-Pass, abbrechbar)."""
    rc, _out, err = run_cancellable([
        tools.ffmpeg, "-hide_banner", "-nostats", "-nostdin", "-i", file_path,
        "-af", "loudnorm=print_format=json",
        "-vn", "-sn", "-dn", "-f", "null", "-",
    ], cancel)
    if rc != 0:
        raise RuntimeError(
            f"FFmpeg-Lautheitsmessung fehlgeschlagen (Exit {rc}): "
            f"{(err or '').strip()[-800:]}"
        )
    return parse_loudnorm_json(err or "")


def measure_sample_peak(
    file_path: str, tools: FFmpegTools,
    cancel: Optional[threading.Event] = None,
) -> float:
    """Misst den Sample-Peak via volumedetect (ein voller Decode-Pass, abbrechbar)."""
    rc, _out, err = run_cancellable([
        tools.ffmpeg, "-hide_banner", "-nostats", "-nostdin", "-i", file_path,
        "-af", "volumedetect", "-vn", "-sn", "-dn", "-f", "null", "-",
    ], cancel)
    if rc != 0:
        raise RuntimeError(
            f"FFmpeg-Peakmessung fehlgeschlagen (Exit {rc}): "
            f"{(err or '').strip()[-800:]}"
        )
    return parse_volumedetect(err or "")
