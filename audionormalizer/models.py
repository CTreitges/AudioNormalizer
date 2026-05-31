"""Datenmodelle und Konstanten für den Audio Normalizer.

Keine Abhängigkeit zu Qt oder FFmpeg – nur reine Datencontainer, damit die
Engine vollständig ohne UI test- und benutzbar ist.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# Unterstützte Container-Endungen (Ein- und Ausgabe).
LOSSLESS_EXTS = (".wav", ".flac")
LOSSY_EXTS = (".mp3", ".m4a", ".aac", ".ogg", ".opus")
SUPPORTED_EXTS = LOSSLESS_EXTS + LOSSY_EXTS


class Mode(Enum):
    """Normalisierungs-Modus.

    Die ``label``-Werte sind Teil des öffentlichen Vertrags: sie erscheinen in
    der GUI-Combobox UND wortgleich in der Log-Datei. Nicht ändern, sonst
    brechen bestehende Log-Formate.
    """

    PEAK = "Peak-Normalizing"
    LOUDNESS = "Loudness-Normalizing"
    HYBRID = "Hybrid-Normalizing"

    @property
    def label(self) -> str:
        return self.value

    @classmethod
    def from_label(cls, label: str) -> "Mode":
        for m in cls:
            if m.value == label:
                return m
        raise ValueError(f"Unbekannter Modus: {label!r}")


# Sentinel-Wert der "Referenz LUFS (Optional)"-Spinbox für "Auto".
REF_LUFS_AUTO_SENTINEL = -100.01

# Standardwerte (entsprechen den bisherigen GUI-Defaults).
DEFAULT_TARGET_PEAK = -3.0
DEFAULT_TARGET_LUFS = -11.0
DEFAULT_TARGET_TP = -3.0
DEFAULT_TARGET_DEV = 3.0


@dataclass(frozen=True)
class AudioInfo:
    """Quell-Parameter eines Audio-Streams (für formattreue Ausgabe)."""

    codec_name: str = ""
    channels: int = 0
    sample_rate: int = 0
    bits_per_sample: int = 0
    sample_fmt: str = ""
    bit_rate: int = 0
    duration: float = 0.0


@dataclass(frozen=True)
class Measurement:
    """Messergebnis eines Tracks. Felder sind ``None`` wenn nicht gemessen."""

    lufs: Optional[float] = None        # integrierte Lautheit (EBU R128)
    true_peak: Optional[float] = None   # True Peak in dBTP
    sample_peak: Optional[float] = None # Sample Peak (max_volume) in dBFS


@dataclass
class NormalizeParams:
    """Alle Parameter eines Normalisierungs-Laufs."""

    mode: Mode
    target_peak: float = DEFAULT_TARGET_PEAK
    target_lufs: float = DEFAULT_TARGET_LUFS
    target_tp: float = DEFAULT_TARGET_TP
    target_dev: float = DEFAULT_TARGET_DEV
    # Manuell vorgegebene Referenz-Lautheit (None => Auto = Mittelwert der Liste).
    ref_lufs_override: Optional[float] = None
    # Tatsächlich verwendete Referenz (wird vom Batch berechnet/gesetzt).
    ref_lufs: Optional[float] = None
    # Dither beim Reduzieren der Bittiefe (verlustfreie Formate).
    dither: bool = True
    # Maximale Anzahl parallel laufender FFmpeg-Prozesse (None => auto).
    max_workers: Optional[int] = None

    def validate(self) -> None:
        if not isinstance(self.mode, Mode):
            raise ValueError("mode muss ein Mode-Enum sein")
        for name in ("target_peak", "target_lufs", "target_tp", "target_dev"):
            val = getattr(self, name)
            if not isinstance(val, (int, float)):
                raise ValueError(f"{name} muss numerisch sein, ist {val!r}")
        if self.target_dev < 0:
            raise ValueError("target_dev darf nicht negativ sein")


@dataclass
class FileResult:
    """Ergebnis der Verarbeitung einer einzelnen Datei."""

    input_path: str
    output_path: str = ""
    mode_used: str = ""           # "Peak" oder "Loudness"
    applied_gain_db: Optional[float] = None
    measurement: Optional[Measurement] = None
    success: bool = False
    error: Optional[str] = None
