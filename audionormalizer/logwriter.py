"""Erzeugt die Lauf-Protokolldatei.

Das Textformat ist bewusst byte-genau zur bisherigen Version – es existieren
bereits Logs in genau diesem Layout. Die reine Textgenerierung ist von der
Datei-I/O getrennt (testbar).
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Optional

from .models import Mode, NormalizeParams


def build_log_text(
    params: NormalizeParams,
    success_count: int,
    error_count: int,
    when: datetime,
) -> str:
    """Baut den Protokoll-Text (identisches Layout wie v1)."""
    lines = [
        "Audio Normalizer Log",
        "====================",
        "",
        f"Datum/Zeit: {when.strftime('%d.%m.%Y %H:%M:%S')}",
        f"Modus: {params.mode.label}",
    ]

    if params.mode is Mode.PEAK:
        lines.append(f"Ziel Peak: {params.target_peak} dB")
    elif params.mode is Mode.LOUDNESS:
        lines.append(f"Ziel Loudness: {params.target_lufs} LUFS")
        lines.append(f"Max True Peak: {params.target_tp} dB")
    elif params.mode is Mode.HYBRID:
        lines.append(f"Ziel Peak: {params.target_peak} dB")
        lines.append(f"Max True Peak: {params.target_tp} dB")
        lines.append(f"Max. Abweichung: {params.target_dev} dB")
        ref_lufs = params.ref_lufs if params.ref_lufs is not None else 0.0
        lines.append(f"Verwendete Referenz LUFS: {ref_lufs:.2f} LUFS")
        if params.ref_lufs_override is not None:
            lines.append(f"(Manuelle Referenz: {params.ref_lufs_override} LUFS)")

    lines += [
        "",
        "Statistik:",
        f"Erfolgreich verarbeitet: {success_count}",
        f"Fehler: {error_count}",
        "",
    ]
    return "\n".join(lines)


def write_log_file(
    target_dir: str,
    source_folder_name: str,
    params: NormalizeParams,
    success_count: int,
    error_count: int,
    when: Optional[datetime] = None,
) -> Optional[str]:
    """Schreibt das Protokoll in den Zielordner. Gibt den Pfad zurück."""
    when = when or datetime.now()
    timestamp = when.strftime("%Y-%m-%d_%H-%M")
    folder_name = source_folder_name or "Audio-Files"
    log_filename = f"Audio-Normalizer-Log-{timestamp}-{folder_name}.txt"
    log_path = os.path.join(target_dir, log_filename)
    try:
        with open(log_path, "w", encoding="utf-8") as fh:
            fh.write(build_log_text(params, success_count, error_count, when))
        return log_path
    except OSError as exc:
        print(f"Fehler beim Erstellen der Log-Datei: {exc}")
        return None
