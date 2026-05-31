"""Ermittelt Quell-Stream-Parameter (Codec, SR, Kanäle, Bittiefe).

Primärpfad ist das Parsen von ``ffmpeg -i`` – das funktioniert mit JEDER
FFmpeg-Binary, auch wenn ffprobe (z.B. im gebündelten Build) fehlt. Ist
ffprobe vorhanden, wird sein präziseres JSON bevorzugt.
"""
from __future__ import annotations

import json
import re
from typing import Optional

from .ffmpeg_locator import FFmpegTools
from .models import AudioInfo
from .procutil import run

# Kanal-Layout-Namen -> Kanalzahl.
_LAYOUT_CHANNELS = {
    "mono": 1, "stereo": 2, "2.1": 3, "3.0": 3, "quad": 4, "4.0": 4,
    "5.0": 5, "5.1": 6, "6.1": 7, "7.1": 8, "downmix": 2,
}

_RE_HZ = re.compile(r"(\d+)\s*Hz")
_RE_KBPS = re.compile(r"(\d+)\s*kb/s")
_RE_BITS = re.compile(r"\((\d+)\s*bit\)")
_RE_NCHAN = re.compile(r"(\d+)\s*channels?")
_RE_DURATION = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
# Sample-Format-Tokens, die FFmpeg in der Stream-Zeile listet.
_SAMPLE_FMTS = ("u8", "s16", "s32", "s64", "flt", "dbl",
                "u8p", "s16p", "s32p", "s64p", "fltp", "dblp")


def _bits_from_sample_fmt(sfmt: str) -> int:
    sfmt = sfmt.lower()
    if "u8" in sfmt:
        return 8
    if "s16" in sfmt:
        return 16
    if "s32" in sfmt:
        return 32
    if "s64" in sfmt or "dbl" in sfmt:
        return 64
    if "flt" in sfmt:
        return 32
    return 0


def parse_ffmpeg_stream_info(stderr: str) -> AudioInfo:
    """Parst die erste Audio-Stream-Zeile aus ``ffmpeg -i``-stderr."""
    codec = ""
    channels = 0
    sample_rate = 0
    bits = 0
    sample_fmt = ""
    bit_rate = 0
    duration = 0.0

    dm = _RE_DURATION.search(stderr)
    if dm:
        h, m, s = dm.groups()
        duration = int(h) * 3600 + int(m) * 60 + float(s)

    for line in stderr.splitlines():
        if "Audio:" not in line:
            continue
        after = line.split("Audio:", 1)[1].strip()
        # Codec ist das erste Token bis Leerzeichen, Komma oder Klammer.
        codec = re.split(r"[\s,(]", after, maxsplit=1)[0]

        hz = _RE_HZ.search(line)
        if hz:
            sample_rate = int(hz.group(1))

        # Kanäle: erst benannte Layouts, dann "N channels".
        for name, ch in _LAYOUT_CHANNELS.items():
            if re.search(rf"\b{re.escape(name)}\b", line):
                channels = ch
                break
        if not channels:
            nch = _RE_NCHAN.search(line)
            if nch:
                channels = int(nch.group(1))

        # Sample-Format: nach Codec/SR/Layout getrennt durch Kommata.
        for part in (p.strip() for p in after.split(",")):
            token = part.split()[0] if part.split() else ""
            if token in _SAMPLE_FMTS:
                sample_fmt = token
                break

        bm = _RE_BITS.search(line)
        if bm:
            bits = int(bm.group(1))
        elif sample_fmt:
            bits = _bits_from_sample_fmt(sample_fmt)

        kb = _RE_KBPS.search(line)
        if kb:
            bit_rate = int(kb.group(1)) * 1000
        break

    return AudioInfo(
        codec_name=codec, channels=channels, sample_rate=sample_rate,
        bits_per_sample=bits, sample_fmt=sample_fmt, bit_rate=bit_rate,
        duration=duration,
    )


def _parse_ffprobe_json(stdout: str) -> Optional[AudioInfo]:
    try:
        data = json.loads(stdout or "{}")
    except json.JSONDecodeError:
        return None
    streams = data.get("streams") or []
    if not streams:
        return None
    s = streams[0]

    def _int(x, default=0):
        try:
            return int(x)
        except (TypeError, ValueError):
            return default

    def _float(x, default=0.0):
        try:
            return float(x)
        except (TypeError, ValueError):
            return default

    sfmt = (s.get("sample_fmt") or "").lower()
    # bits_per_sample ist bei FLAC/ALAC oft 0; bits_per_raw_sample trägt dann
    # die echte Bittiefe (z.B. 24). Sample-Format ist nur die letzte Reserve.
    bits = (_int(s.get("bits_per_sample"), 0)
            or _int(s.get("bits_per_raw_sample"), 0)
            or _bits_from_sample_fmt(sfmt))
    return AudioInfo(
        codec_name=s.get("codec_name") or "",
        channels=_int(s.get("channels")),
        sample_rate=_int(s.get("sample_rate")),
        bits_per_sample=bits,
        sample_fmt=sfmt,
        bit_rate=_int(s.get("bit_rate")),
        duration=_float(s.get("duration")),
    )


def probe(file_path: str, tools: FFmpegTools) -> AudioInfo:
    """Ermittelt die Audio-Parameter einer Datei (ffprobe bevorzugt)."""
    if tools.has_ffprobe:
        try:
            res = run([
                tools.ffprobe, "-v", "error", "-select_streams", "a:0",
                "-show_entries",
                "stream=codec_name,channels,sample_rate,bits_per_sample,"
                "bits_per_raw_sample,sample_fmt,bit_rate,duration",
                "-of", "json", file_path,
            ])
            if res.returncode == 0:
                info = _parse_ffprobe_json(res.stdout)
                if info:
                    return info
        except Exception:
            pass

    # Fallback / Primärpfad ohne ffprobe: ffmpeg -i parsen.
    try:
        res = run([tools.ffmpeg, "-hide_banner", "-i", file_path])
        # ffmpeg ohne Output-Datei liefert Exit != 0, aber die Stream-Infos
        # stehen trotzdem auf stderr.
        return parse_ffmpeg_stream_info(res.stderr or "")
    except Exception:
        return AudioInfo()
