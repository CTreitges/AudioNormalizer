"""Headless-Kommandozeile für den Audio Normalizer.

Beispiele:
    python -m audionormalizer.cli -o out/ --mode hybrid playlist/
    python -m audionormalizer.cli -o out.flac --mode loudness --target-lufs -14 in.flac
    python -m audionormalizer.cli --dry-run --mode peak *.wav -o out/
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from typing import Dict, List, Optional

from . import __version__, ffmpeg_locator
from . import batch as _batch
from . import engine, logwriter, measure
from .models import (
    DEFAULT_TARGET_DEV, DEFAULT_TARGET_LUFS, DEFAULT_TARGET_PEAK,
    DEFAULT_TARGET_TP, LOSSLESS_EXTS, Mode, NormalizeParams, SUPPORTED_EXTS,
)

_MODE_ALIASES = {
    "peak": Mode.PEAK, "loudness": Mode.LOUDNESS, "hybrid": Mode.HYBRID,
}


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="audionormalizer",
        description="Verlustfreie, dynamik-erhaltende Audio-Normalisierung "
                    "(Peak / Loudness / Hybrid) über FFmpeg.",
    )
    p.add_argument("inputs", nargs="+", help="Dateien und/oder Ordner")
    p.add_argument("-o", "--output",
                   help="Zielordner (mehrere Dateien) oder Zieldatei (Einzeldatei). "
                        "Entfällt im --overwrite-Modus.")
    p.add_argument("--overwrite", action="store_true",
                   help="Originaldateien überschreiben (erhält Rekordbox-CuePoints). "
                        "Erfordert --backup-dir.")
    p.add_argument("--backup-dir", default=None,
                   help="Backup-Ordner für die Originale (Pflicht bei --overwrite)")
    p.add_argument("--no-rekordbox", action="store_true",
                   help="Rekordbox-Kompatibilität (WAV/FLAC-Limits) deaktivieren")
    p.add_argument("--mode", choices=list(_MODE_ALIASES), default="peak",
                   help="Normalisierungs-Modus (Standard: peak)")
    p.add_argument("--target-peak", type=float, default=DEFAULT_TARGET_PEAK,
                   help=f"Ziel-Peak in dB (Standard: {DEFAULT_TARGET_PEAK})")
    p.add_argument("--target-lufs", type=float, default=DEFAULT_TARGET_LUFS,
                   help=f"Ziel-Loudness in LUFS (Standard: {DEFAULT_TARGET_LUFS})")
    p.add_argument("--target-tp", type=float, default=DEFAULT_TARGET_TP,
                   help=f"Max. True Peak in dB (Standard: {DEFAULT_TARGET_TP})")
    p.add_argument("--max-dev", type=float, default=DEFAULT_TARGET_DEV,
                   help=f"Max. Abweichung im Hybrid-Modus in dB (Standard: {DEFAULT_TARGET_DEV})")
    p.add_argument("--ref-lufs", type=float, default=None,
                   help="Manuelle Referenz-LUFS (Hybrid). Ohne Angabe: Auto/Mittelwert.")
    p.add_argument("--format", dest="out_format", default=None,
                   choices=[e.lstrip(".") for e in SUPPORTED_EXTS],
                   help="Ausgabeformat erzwingen (sonst wie Quelle)")
    p.add_argument("--suffix", default="",
                   help="Suffix vor der Dateiendung einfügen (z.B. _norm)")
    p.add_argument("--workers", type=int, default=None,
                   help="Anzahl paralleler FFmpeg-Prozesse (Standard: auto)")
    p.add_argument("--no-dither", action="store_true",
                   help="Kein Dither bei Bittiefen-Reduktion")
    p.add_argument("--ffmpeg", default=None, help="Pfad zur ffmpeg-Binary/-Ordner")
    p.add_argument("--no-log", action="store_true", help="Keine Protokolldatei schreiben")
    p.add_argument("--dry-run", action="store_true",
                   help="Nur messen und geplanten Gain anzeigen, nichts schreiben")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def _apply_suffix_and_format(path: str, suffix: str, out_format: Optional[str]) -> str:
    base, ext = os.path.splitext(path)
    if out_format:
        ext = "." + out_format
    return f"{base}{suffix}{ext}"


def _plan_mapping(files: List[str], output: str, suffix: str,
                  out_format: Optional[str]) -> Dict[str, str]:
    """Erzeugt das Quelle->Ziel-Mapping für die CLI."""
    output_is_file = (
        len(files) == 1
        and os.path.splitext(output)[1].lower() in SUPPORTED_EXTS
    )
    if output_is_file:
        out = _apply_suffix_and_format(output, suffix, out_format)
        return {files[0]: out}

    mapping = _batch.build_output_mapping(files, output)
    return {
        src: _apply_suffix_and_format(dst, suffix, out_format)
        for src, dst in mapping.items()
    }


def _warn_overwrite(mapping: Dict[str, str]) -> List[str]:
    """Warnt, wenn Ziel == Quelle (atomic write schützt zwar, aber Hinweis)."""
    clashes = []
    for src, dst in mapping.items():
        if os.path.abspath(src) == os.path.abspath(dst):
            clashes.append(src)
    return clashes


def run(argv: Optional[List[str]] = None) -> int:
    args = _build_parser().parse_args(argv)

    tools = ffmpeg_locator.locate(args.ffmpeg)
    if not tools:
        print("FEHLER: FFmpeg wurde nicht gefunden. Bitte mit --ffmpeg angeben "
              "oder installieren.", file=sys.stderr)
        return 2
    if args.verbose:
        print(ffmpeg_locator.describe(tools))

    files = _batch.collect_audio_files(args.inputs)
    if not files:
        print("FEHLER: Keine unterstützten Audiodateien gefunden.", file=sys.stderr)
        return 1

    mode = _MODE_ALIASES[args.mode]
    if mode is Mode.HYBRID and len(files) < 2:
        print("FEHLER: Hybrid-Modus benötigt mindestens zwei Dateien.", file=sys.stderr)
        return 1

    params = NormalizeParams(
        mode=mode,
        target_peak=args.target_peak,
        target_lufs=args.target_lufs,
        target_tp=args.target_tp,
        target_dev=args.max_dev,
        ref_lufs_override=args.ref_lufs,
        dither=not args.no_dither,
        rekordbox=not args.no_rekordbox,
        max_workers=args.workers,
    )

    backup_mapping = None
    if args.overwrite:
        if not args.backup_dir:
            print("FEHLER: --overwrite erfordert --backup-dir.", file=sys.stderr)
            return 1
        mapping = {f: f for f in files}
        backup_mapping = _batch.build_output_mapping(files, args.backup_dir)
    else:
        if not args.output:
            print("FEHLER: -o/--output ist erforderlich (außer mit --overwrite).",
                  file=sys.stderr)
            return 1
        mapping = _plan_mapping(files, args.output, args.suffix, args.out_format)
        for src in _warn_overwrite(mapping):
            print(f"HINWEIS: Ziel überschreibt Quelle: {src}")

    print(f"{len(files)} Datei(en), Modus: {mode.label}"
          + (" [Überschreiben]" if args.overwrite else ""))

    if args.dry_run:
        return _dry_run(files, params, tools)

    # Ziel- und Backup-Ordner anlegen.
    out_dirs = {os.path.dirname(p) for p in mapping.values() if os.path.dirname(p)}
    for d in out_dirs:
        os.makedirs(d, exist_ok=True)
    if backup_mapping:
        for p in backup_mapping.values():
            bd = os.path.dirname(p)
            if bd:
                os.makedirs(bd, exist_ok=True)

    callbacks = _batch.BatchCallbacks(
        on_phase=lambda name, total: print(f"\n[{name}] {total} Datei(en)"),
        on_progress=lambda done, total: print(f"  {done}/{total}", end="\r", flush=True),
        on_file_done=(lambda r: print(
            f"  OK  {os.path.basename(r.input_path)} "
            f"[{r.mode_used}, {r.applied_gain_db:+.2f} dB]"
        )) if args.verbose else None,
        on_error=lambda msg: print(f"  FEHLER: {msg}", file=sys.stderr),
    )

    result = _batch.run_batch(files, mapping, params, tools, callbacks,
                              backup_mapping=backup_mapping)

    print(f"\nFertig. Erfolgreich: {result.success_count}, "
          f"Fehler: {result.error_count}"
          + (", abgebrochen" if result.cancelled else ""))

    if result.success_count > 0 and not args.no_log:
        target_dir = next(iter(out_dirs), os.path.dirname(next(iter(mapping.values()))))
        log_path = logwriter.write_log_file(
            target_dir, _batch.infer_source_folder(files), params,
            result.success_count, result.error_count, datetime.now(),
        )
        if log_path and args.verbose:
            print(f"Protokoll: {log_path}")

    return 0 if result.error_count == 0 else 1


def _dry_run(files, params, tools) -> int:
    """Misst und zeigt den geplanten Gain, ohne zu schreiben."""
    if params.mode is Mode.HYBRID:
        meas = {}
        for f in files:
            try:
                meas[f] = measure.measure_loudness(f, tools)
            except Exception as exc:
                meas[f] = None
                print(f"  Analyse-Fehler {os.path.basename(f)}: {exc}", file=sys.stderr)
        params.ref_lufs = _batch.compute_reference_lufs(
            meas, params.ref_lufs_override, params.target_lufs)
        print(f"Referenz-LUFS: {params.ref_lufs:.2f}")
    else:
        params.ref_lufs = params.target_lufs

    for f in files:
        try:
            m = meas.get(f) if params.mode is Mode.HYBRID else None
            actual = engine.decide_actual_mode(params, m.lufs if m else None)
            if actual == "Peak":
                sp = measure.measure_sample_peak(f, tools)
                gain = engine.compute_peak_gain(params, sp)
                detail = f"sample_peak={sp:.2f}"
            else:
                if m is None or m.lufs is None:
                    m = measure.measure_loudness(f, tools)
                gain = engine.compute_loudness_gain(params, m)
                detail = f"LUFS={m.lufs:.2f}, TP={m.true_peak}"
            print(f"  {os.path.basename(f)}: {actual}, gain={gain:+.2f} dB ({detail})")
        except Exception as exc:
            print(f"  FEHLER {os.path.basename(f)}: {exc}", file=sys.stderr)
    return 0


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
