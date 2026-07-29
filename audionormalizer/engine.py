"""Kern-Engine der Normalisierung.

Die Gain-Berechnung und Modus-Entscheidung sind reine Funktionen (ohne I/O),
damit sie exakt gegen die bisherige Semantik unit-getestet werden können. Die
eigentliche Datei-Verarbeitung schreibt **atomar** (Temp-Datei + ``os.replace``)
– das verhindert In-Place-Korruption (Ziel == Quelle) und halbfertige Dateien
bei Abbruch/Fehler.

Philosophie (unverändert ggü. v1): **lineare Verstärkung, keine Kompression** –
die Dynamik bleibt zu 100 % erhalten. Ein True-Peak-Limit dient nur als
Clipping-Schutz, indem der Gain gedeckelt wird (nicht durch einen Limiter).
"""
from __future__ import annotations

import os
import shutil
import threading
import uuid
from typing import List, Optional

from .ffmpeg_locator import FFmpegTools
from .models import AudioInfo, FileResult, Measurement, Mode, NormalizeParams
from .probe import probe
from .procutil import CancelledError, run_cancellable
from . import measure as _measure


# --------------------------------------------------------------------------- #
# Reine Berechnungs-Logik (kein I/O – voll testbar)
# --------------------------------------------------------------------------- #
def decide_actual_mode(params: NormalizeParams, measured_lufs: Optional[float]) -> str:
    """Bestimmt das tatsächlich angewandte Verfahren ("Peak"/"Loudness").

    Semantik exakt wie v1:
    - Loudness-Modus  -> immer "Loudness"
    - Peak-Modus      -> immer "Peak"
    - Hybrid-Modus    -> Abweichung von der Referenz >= max. Abweichung
                         => "Loudness" (Ausreißer angleichen),
                         sonst         => "Peak" (Dynamik im Album bewahren).
      Fehlt die Messung, wird auf "Loudness" zurückgefallen.
    """
    if params.mode is Mode.LOUDNESS:
        return "Loudness"
    if params.mode is Mode.PEAK:
        return "Peak"
    # Hybrid:
    if measured_lufs is None or params.ref_lufs is None:
        return "Loudness"
    deviation = abs(measured_lufs - params.ref_lufs)
    return "Loudness" if deviation >= params.target_dev else "Peak"


def compute_loudness_gain(params: NormalizeParams, m: Measurement) -> float:
    """Linearer Gain für Loudness-Normalisierung, gedeckelt durch True-Peak-Limit.

    ``gain = ziel_lufs - gemessene_lufs`` und ``max_gain = tp_limit - true_peak``;
    angewandt wird das Minimum (nie Übersteuerung, nie Kompression).
    """
    if m.lufs is None:
        raise ValueError("Loudness-Gain benötigt eine LUFS-Messung.")
    actual_target_lufs = params.ref_lufs if params.mode is Mode.HYBRID else params.target_lufs
    if actual_target_lufs is None:
        actual_target_lufs = params.target_lufs
    tp_limit = min(params.target_tp, params.target_peak) if params.mode is Mode.HYBRID else params.target_tp

    gain = actual_target_lufs - m.lufs
    if m.true_peak is not None:
        max_allowed_gain = tp_limit - m.true_peak
        gain = min(gain, max_allowed_gain)
    return gain


def compute_peak_gain(params: NormalizeParams, sample_peak: float) -> float:
    """Linearer Gain für Peak-Normalisierung (Sample-Peak auf Ziel-Peak)."""
    return params.target_peak - sample_peak


# Container, die ein eingebettetes Cover als Bild-Stream (attached_pic) tragen.
_COVER_IMAGE_EXTS = (".mp3", ".flac", ".m4a", ".aac", ".mp4")


def build_map_args(output_ext: str) -> List[str]:
    """Explizites Stream-Mapping.

    Ohne explizites Mapping wählt FFmpeg automatisch Audio + Cover-Bild – das
    crasht aber bei Opus/M4A und macht aus dem Cover bei OGG ein Theora-Video.
    Daher: Cover-Bild nur in Container kopieren, die es als attached_pic halten;
    sonst ausschließlich Audio mappen (Cover wird verworfen, kein Crash).

    ``0:v?`` ist optional – Dateien ohne Cover (z.B. reine WAV) funktionieren so
    unverändert.
    """
    ext = output_ext.lower()
    if ext in _COVER_IMAGE_EXTS:
        # -c:v copy übernimmt die attached_pic-Disposition vom Input; ein
        # explizites -disposition würde bei Dateien OHNE Cover crashen.
        return ["-map", "0:a", "-map", "0:v?", "-c:v", "copy"]
    return ["-map", "0:a"]


# --------------------------------------------------------------------------- #
# Codec-/Format-Argumente (formattreue Ausgabe)
# --------------------------------------------------------------------------- #
# Rekordbox-Limits: max. 24-bit Integer, max. 96 kHz Samplerate.
_REKORDBOX_MAX_SR = 96000


def _pcm_codec(bits: int, sample_fmt: str, rekordbox: bool) -> Optional[str]:
    sfmt = (sample_fmt or "").lower()
    if rekordbox:
        # Rekordbox akzeptiert nur 16-/24-bit Integer-PCM (kein f32/u8/s32).
        if bits >= 24:
            return "pcm_s24le"
        if bits >= 16:
            return "pcm_s16le"
        if "s32" in sfmt or "flt" in sfmt or "s24" in sfmt:
            return "pcm_s24le"
        return "pcm_s16le"
    if bits >= 32:
        return "pcm_f32le" if "flt" in sfmt else "pcm_s32le"
    if bits >= 24:
        return "pcm_s24le"
    if bits >= 16:
        return "pcm_s16le"
    if bits > 0:
        return "pcm_u8"
    if "s16" in sfmt:
        return "pcm_s16le"
    if "s32" in sfmt:
        return "pcm_s32le"
    if "flt" in sfmt:
        return "pcm_f32le"
    return None


def build_codec_args(output_ext: str, info: Optional[AudioInfo], dither: bool,
                     rekordbox: bool = True) -> List[str]:
    """Baut die FFmpeg-Codec-Argumente passend zum Ziel-Container.

    Verlustfreie Ziele (wav/flac) übernehmen SR/Kanäle/Bittiefe der Quelle.
    Verlustbehaftete Ziele übernehmen die Quell-Bitrate, sonst sinnvolle
    Defaults.

    Mit ``rekordbox=True`` (Default) werden WAV/FLAC Rekordbox-kompatibel
    erzeugt: max. 24-bit Integer, max. 96 kHz, Standard-RIFF-WAV (kein RF64).
    """
    ext = output_ext.lower()
    args: List[str] = []
    info = info or AudioInfo()
    ch = info.channels or 0
    bps = info.bits_per_sample or 0
    sfmt = info.sample_fmt or ""
    src_br = info.bit_rate or 0
    sr = info.sample_rate or 0
    out_sr = min(sr, _REKORDBOX_MAX_SR) if (rekordbox and sr) else sr

    def _common_rate_chan():
        out = []
        if out_sr:
            out += ["-ar", str(out_sr)]
        if ch:
            out += ["-ac", str(ch)]
        return out

    if ext == ".wav":
        codec = _pcm_codec(bps, sfmt, rekordbox) or "pcm_s24le"
        args += ["-c:a", codec]
        args += _common_rate_chan()
        if dither and codec == "pcm_s16le":
            args += ["-dither_method", "triangular_hp"]
        if rekordbox:
            # Standard-RIFF-WAV erzwingen (kein RF64) für Rekordbox.
            args += ["-rf64", "never"]
    elif ext == ".flac":
        args += ["-c:a", "flac"]
        args += _common_rate_chan()
        if bps >= 24 or (bps == 0 and ("s32" in sfmt or "s24" in sfmt or "flt" in sfmt)):
            args += ["-sample_fmt", "s32"]   # 24-bit-FLAC-Output
        else:
            args += ["-sample_fmt", "s16"]
            if dither:
                args += ["-dither_method", "triangular_hp"]
    elif ext == ".mp3":
        args += ["-c:a", "libmp3lame"]
        args += _common_rate_chan()
        args += (["-b:a", str(src_br)] if src_br else ["-q:a", "0"])
    elif ext in (".m4a", ".aac"):
        args += ["-c:a", "aac"]
        args += _common_rate_chan()
        args += ["-b:a", str(src_br) if src_br else "256000"]
    elif ext == ".ogg":
        args += ["-c:a", "libvorbis"]
        args += _common_rate_chan()
        args += (["-b:a", str(src_br)] if src_br else ["-q:a", "6"])
    elif ext == ".opus":
        # libopus akzeptiert nur 48/24/16/12/8 kHz -> Quell-SR NICHT erzwingen,
        # FFmpeg resampled automatisch auf 48 kHz.
        args += ["-c:a", "libopus"]
        if ch:
            args += ["-ac", str(ch)]
        args += ["-b:a", str(src_br) if src_br else "192000"]
    return args


def build_metadata_args(output_ext: str, track_num: str, rekordbox: bool = True) -> List[str]:
    """Metadaten-Argumente. Bei WAV im Rekordbox-Modus werden Quell-Metadaten
    komplett entfernt (``-map_metadata -1``), um problematische RIFF-Chunks zu
    vermeiden; ansonsten bleiben Tags + Cover erhalten (``-map_metadata 0``).
    Der Track-Indikator (0=Peak, 1=Loudness) wird immer gesetzt.
    """
    if output_ext.lower() == ".wav" and rekordbox:
        base = ["-map_metadata", "-1"]
    else:
        base = ["-map_metadata", "0"]
    return base + ["-metadata", f"track={track_num}"]


# --------------------------------------------------------------------------- #
# Datei-Verarbeitung (I/O, atomar, abbrechbar)
# --------------------------------------------------------------------------- #
def _run_ffmpeg(cmd: List[str], cancel: Optional[threading.Event]) -> str:
    """Führt FFmpeg aus, abbrechbar via ``cancel``-Event. Gibt stderr zurück."""
    rc, _out, stderr = run_cancellable(cmd, cancel)
    if rc != 0:
        raise RuntimeError(
            f"FFmpeg-Fehler (Exit {rc}):\n{(stderr or '').strip()[-2000:]}"
        )
    return stderr


# Marker der atomaren Temp-Dateien. Sie MÜSSEN die echte Endung tragen (sonst
# erkennt FFmpeg das Output-Format nicht) – dadurch sähen sie nach einem
# Absturz aber wie normale Audiodateien aus und würden beim nächsten Lauf
# erneut normalisiert. Der führende Punkt hält sie aus der Sammlung heraus
# (siehe ``batch.collect_audio_files``).
TEMP_MARKER = ".part"


def build_temp_path(output_path: str) -> str:
    """Pfad der atomaren Temp-Datei im Zielordner (versteckt + eindeutig)."""
    out_dir = os.path.dirname(output_path) or os.path.dirname(os.path.abspath(output_path))
    base = os.path.basename(output_path)
    ext = os.path.splitext(output_path)[1].lower()
    return os.path.join(out_dir, f".{base}.{uuid.uuid4().hex[:8]}{TEMP_MARKER}{ext}")


def normalize_file(
    file_path: str,
    output_path: str,
    params: NormalizeParams,
    tools: FFmpegTools,
    measurement: Optional[Measurement] = None,
    cancel: Optional[threading.Event] = None,
    backup_path: Optional[str] = None,
) -> FileResult:
    """Normalisiert eine Datei und schreibt das Ergebnis atomar nach ``output_path``.

    Ist ``backup_path`` gesetzt (Überschreiben-Modus), wird die Originaldatei
    vor der Verarbeitung dorthin kopiert. Da ``output_path`` dann == ``file_path``
    ist, schützt das atomare Temp+Replace die Originaldatei während des Laufs.
    """
    result = FileResult(input_path=file_path, output_path=output_path)

    if cancel is not None and cancel.is_set():
        raise CancelledError()

    # Backup VOR jeglicher Verarbeitung anlegen – aber ein bereits vorhandenes
    # NIE überschreiben: bei einem zweiten Lauf über dieselben Dateien ist die
    # Quelle schon normalisiert. Ein Überschreiben würde das echte Original
    # durch dessen bearbeitete Fassung ersetzen und wäre unwiederbringlich.
    if backup_path and not os.path.exists(backup_path):
        bdir = os.path.dirname(backup_path)
        if bdir:
            os.makedirs(bdir, exist_ok=True)
        shutil.copy2(file_path, backup_path)

    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    info = probe(file_path, tools)
    ext = os.path.splitext(output_path)[1].lower()
    codec_args = build_codec_args(ext, info, params.dither, params.rekordbox)

    actual_mode = decide_actual_mode(params, measurement.lufs if measurement else None)
    result.mode_used = actual_mode
    track_num = "0" if actual_mode == "Peak" else "1"

    if actual_mode == "Peak":
        sample_peak = _measure.measure_sample_peak(file_path, tools, cancel)
        result.measurement = Measurement(sample_peak=sample_peak)
        gain = compute_peak_gain(params, sample_peak)
    else:
        m = measurement
        if m is None or m.lufs is None or m.true_peak is None:
            m = _measure.measure_loudness(file_path, tools, cancel)
        result.measurement = m
        gain = compute_loudness_gain(params, m)

    result.applied_gain_db = gain

    # Atomar schreiben: erst in Temp-Datei im Zielordner, dann umbenennen.
    tmp_path = build_temp_path(output_path)
    map_args = build_map_args(ext)
    metadata_args = build_metadata_args(ext, track_num, params.rekordbox)
    cmd = [
        tools.ffmpeg, "-y", "-hide_banner", "-nostdin", "-i", file_path,
        "-af", f"volume={gain}dB",
    ] + map_args + codec_args + metadata_args + [tmp_path]
    try:
        if cancel is not None and cancel.is_set():
            raise CancelledError()
        _run_ffmpeg(cmd, cancel)
        os.replace(tmp_path, output_path)
    except BaseException:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise

    result.success = True
    return result
