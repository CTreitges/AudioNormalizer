"""Qt-freie Stapel-Orchestrierung.

Trennt die Ablauflogik (Datei-Sammlung, Output-Mapping, Analyse-/
Verarbeitungs-Phase, Parallelität, Abbruch) vollständig vom UI. Fortschritt
wird über Callbacks gemeldet; die GUI mappt diese auf Qt-Signale, die CLI auf
Konsolen-Ausgaben.
"""
from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from .ffmpeg_locator import FFmpegTools
from .models import FileResult, Measurement, Mode, NormalizeParams, SUPPORTED_EXTS
from . import engine
from . import measure as _measure


# --------------------------------------------------------------------------- #
# Datei-Sammlung & Output-Mapping (reine Funktionen)
# --------------------------------------------------------------------------- #
def collect_audio_files(paths: List[str]) -> List[str]:
    """Sammelt unterstützte Audiodateien aus Dateien/Ordnern (rekursiv, dedupe)."""
    found: List[str] = []
    seen = set()

    def _add(p: str):
        ap = os.path.abspath(p)
        if ap not in seen and p.lower().endswith(SUPPORTED_EXTS):
            seen.add(ap)
            found.append(p)

    for path in paths:
        if os.path.isdir(path):
            for root, _dirs, files in os.walk(path):
                for f in sorted(files):
                    _add(os.path.join(root, f))
        elif os.path.isfile(path):
            _add(path)
    return found


def build_output_mapping(files: List[str], target_dir: str) -> Dict[str, str]:
    """Bildet Quell- auf Zielpfade ab und erhält die Unterordner-Struktur.

    Robust gegen unterschiedliche Laufwerke (Windows): dort wird auf den
    Dateinamen zurückgefallen statt zu crashen (``commonpath``-ValueError).
    """
    mapping: Dict[str, str] = {}
    if not files:
        return mapping

    common: Optional[str] = None
    if len(files) > 1:
        try:
            common = os.path.commonpath([os.path.abspath(f) for f in files])
        except ValueError:
            common = None
    else:
        common = os.path.dirname(os.path.abspath(files[0]))
    if common and os.path.isfile(common):
        common = os.path.dirname(common)

    for f in files:
        rel: Optional[str] = None
        if common:
            try:
                rel = os.path.relpath(os.path.abspath(f), common)
            except ValueError:
                rel = None
        if not rel or rel.startswith(".."):
            rel = os.path.basename(f)
        mapping[f] = os.path.join(target_dir, rel)
    return mapping


def infer_source_folder(files: List[str]) -> str:
    """Leitet einen Quellordner-Namen für den Log-Dateinamen ab."""
    if not files:
        return ""
    if len(files) == 1:
        return os.path.basename(os.path.dirname(os.path.abspath(files[0])))
    try:
        common = os.path.commonpath([os.path.abspath(f) for f in files])
        return os.path.basename(common.rstrip(os.sep)) or ""
    except ValueError:
        return os.path.basename(os.path.dirname(os.path.abspath(files[0])))


def compute_reference_lufs(
    measurements: Dict[str, Optional[Measurement]],
    override: Optional[float],
    fallback: float,
) -> float:
    """Referenz-LUFS für den Hybrid-Modus: manueller Wert oder Mittelwert."""
    if override is not None:
        return override
    values = [m.lufs for m in measurements.values() if m and m.lufs is not None]
    if values:
        return sum(values) / len(values)
    return fallback


# --------------------------------------------------------------------------- #
# Callbacks & Ergebnis
# --------------------------------------------------------------------------- #
@dataclass
class BatchCallbacks:
    on_phase: Optional[Callable[[str, int], None]] = None        # (phase_name, total)
    on_progress: Optional[Callable[[int, int], None]] = None     # (done, total)
    on_file_done: Optional[Callable[[FileResult], None]] = None
    on_error: Optional[Callable[[str], None]] = None

    def _phase(self, name, total):
        if self.on_phase:
            self.on_phase(name, total)

    def _progress(self, done, total):
        if self.on_progress:
            self.on_progress(done, total)

    def _file_done(self, res):
        if self.on_file_done:
            self.on_file_done(res)

    def _err(self, msg):
        if self.on_error:
            self.on_error(msg)


@dataclass
class BatchResult:
    results: List[FileResult] = field(default_factory=list)
    success_count: int = 0
    error_count: int = 0
    cancelled: bool = False
    ffmpeg_error: bool = False
    ref_lufs: Optional[float] = None


def default_max_workers(params: NormalizeParams) -> int:
    if params.max_workers and params.max_workers > 0:
        return params.max_workers
    # FFmpeg ist selbst multithreaded -> nicht über-subscriben.
    return max(1, min(4, os.cpu_count() or 2))


# --------------------------------------------------------------------------- #
# Hauptablauf
# --------------------------------------------------------------------------- #
def run_batch(
    files: List[str],
    output_mapping: Dict[str, str],
    params: NormalizeParams,
    tools: FFmpegTools,
    callbacks: Optional[BatchCallbacks] = None,
    cancel: Optional[threading.Event] = None,
    backup_mapping: Optional[Dict[str, str]] = None,
) -> BatchResult:
    """Führt einen kompletten Normalisierungs-Lauf aus.

    Ablauf:
    1. (Nur Hybrid) Analyse-Phase: misst LUFS aller Dateien parallel und
       berechnet die Referenz-Lautheit (Mittelwert oder manueller Override).
       *Wichtig:* Die Analyse läuft im Hybrid-Modus IMMER – auch bei manuellem
       Referenzwert –, damit pro Track korrekt zwischen Peak/Loudness
       entschieden werden kann (Bugfix ggü. v1).
    2. Verarbeitungs-Phase: normalisiert alle Dateien parallel.
    """
    params.validate()
    cb = callbacks or BatchCallbacks()
    cancel = cancel or threading.Event()
    result = BatchResult()
    workers = default_max_workers(params)

    measurements: Dict[str, Optional[Measurement]] = {}

    # ---- Phase 1: Analyse (nur Hybrid) ----
    if params.mode is Mode.HYBRID:
        total = len(files)
        cb._phase("Analysiere Playlist", total)
        done = 0

        def _analyze(f: str) -> Measurement:
            # Bereits eingereihte Tasks brechen sofort ab; der laufende Decode
            # wird über das Cancel-Event terminiert (kein Hängen bei Abbruch).
            if cancel.is_set():
                raise engine.CancelledError()
            return _measure.measure_loudness(f, tools, cancel)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_analyze, f): f for f in files}
            for fut in as_completed(futures):
                f = futures[fut]
                try:
                    measurements[f] = fut.result()
                except engine.CancelledError:
                    measurements[f] = None
                except Exception as exc:  # Messfehler -> kein Hard-Stop
                    measurements[f] = None
                    msg = f"Analyse-Fehler bei {os.path.basename(f)}: {exc}"
                    if "ffmpeg" in str(exc).lower() or "ffprobe" in str(exc).lower():
                        result.ffmpeg_error = True
                    cb._err(msg)
                done += 1
                cb._progress(done, total)
        if cancel.is_set():
            result.cancelled = True
            return result
        params.ref_lufs = compute_reference_lufs(
            measurements, params.ref_lufs_override, params.target_lufs
        )
        result.ref_lufs = params.ref_lufs
    else:
        # Referenz für Nicht-Hybrid-Modi (wird dort nicht zur Entscheidung genutzt).
        params.ref_lufs = (
            params.ref_lufs_override
            if params.ref_lufs_override is not None
            else params.target_lufs
        )
        result.ref_lufs = params.ref_lufs

    # ---- Phase 2: Verarbeitung ----
    total = len(files)
    cb._phase("Verarbeite", total)
    done = 0

    def _work(f: str) -> FileResult:
        if cancel.is_set():
            raise engine.CancelledError()
        return engine.normalize_file(
            f, output_mapping[f], params, tools,
            measurement=measurements.get(f), cancel=cancel,
            backup_path=(backup_mapping.get(f) if backup_mapping else None),
        )

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_work, f): f for f in files}
        for fut in as_completed(futures):
            f = futures[fut]
            try:
                res = fut.result()
                result.results.append(res)
                result.success_count += 1
                cb._file_done(res)
            except engine.CancelledError:
                result.cancelled = True
            except Exception as exc:
                result.error_count += 1
                msg = f"Fehler bei {os.path.basename(f)}: {exc}"
                if "ffmpeg" in str(exc).lower() or "ffprobe" in str(exc).lower():
                    result.ffmpeg_error = True
                fr = FileResult(input_path=f, output_path=output_mapping.get(f, ""),
                                success=False, error=str(exc))
                result.results.append(fr)
                cb._err(msg)
            done += 1
            cb._progress(done, total)

    if cancel.is_set():
        result.cancelled = True
    return result
