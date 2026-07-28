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
@dataclass(frozen=True)
class Selection:
    """Gefundene Dateien plus die Herkunft ihrer Ordnerstruktur.

    ``bases`` merkt sich pro Datei den ausgewählten Ordner, relativ zu dem die
    Unterordner-Struktur im Ziel erhalten bleibt. Für einzeln ausgewählte
    Dateien ist der Eintrag ``""`` – die landen flach im Zielordner.

    Ohne diese Herkunft müsste das Mapping die Basis aus dem ``commonpath``
    der Fundstellen raten. Das kollabiert genau dann, wenn alle Treffer in
    *einem* Unterordner liegen (``Musik/Album/*.mp3`` -> Ziel flach, ``Album``
    verschwindet) oder wenn nur eine einzige Datei tief im Baum liegt.
    """

    files: List[str] = field(default_factory=list)
    bases: Dict[str, str] = field(default_factory=dict)


def _is_supported(name: str) -> bool:
    """Unterstützte Endung und keine versteckte Datei.

    Der Punkt-Filter hält zwei Sorten Müll draußen, die sonst als Track
    durchgehen: liegengebliebene ``.<name>.<hex>.part.<ext>``-Temp-Dateien
    eines abgestürzten Laufs (die würden sonst ein zweites Mal verstärkt) und
    AppleDouble-Reste (``._track.mp3``) von Mac-kopierten Ordnern.
    """
    return not name.startswith(".") and name.lower().endswith(SUPPORTED_EXTS)


def collect_selection(paths: List[str]) -> Selection:
    """Sammelt Audiodateien aus Dateien/Ordnern (rekursiv, dedupe) MIT Herkunft.

    Ein übergebener Ordner wird selbst zur Basis: ``<Ordner>/Album/a.mp3``
    landet später unter ``<Ziel>/Album/a.mp3``. Einzeln übergebene Dateien
    bekommen keine Basis und landen flach.
    """
    found: List[str] = []
    bases: Dict[str, str] = {}
    seen = set()

    def _add(p: str, base: str):
        ap = os.path.abspath(p)
        if ap in seen or not _is_supported(os.path.basename(p)):
            return
        seen.add(ap)
        found.append(p)
        bases[p] = base

    for path in paths:
        if os.path.isdir(path):
            base = os.path.abspath(path)
            for root, dirs, files in os.walk(path):
                # Versteckte Unterordner (.git, .Trashes, …) gar nicht betreten.
                dirs[:] = sorted(d for d in dirs if not d.startswith("."))
                for f in sorted(files):
                    _add(os.path.join(root, f), base)
        elif os.path.isfile(path):
            _add(path, "")
    return Selection(files=found, bases=bases)


def collect_audio_files(paths: List[str]) -> List[str]:
    """Sammelt unterstützte Audiodateien aus Dateien/Ordnern (rekursiv, dedupe)."""
    return collect_selection(paths).files


def _relative_target(f: str, base: str) -> Optional[str]:
    """Zielpfad relativ zur Basis – ``None``, wenn die Basis nicht trägt."""
    if not base:
        return None
    try:
        rel = os.path.relpath(os.path.abspath(f), base)
    except ValueError:      # anderes Laufwerk (Windows)
        return None
    return None if rel.startswith("..") else rel


def build_output_mapping(files: List[str], target_dir: str,
                         bases: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Bildet Quell- auf Zielpfade ab und erhält die Unterordner-Struktur.

    Mit ``bases`` (aus :func:`collect_selection`) wird die Struktur relativ zum
    tatsächlich ausgewählten Ordner erhalten. Ohne ``bases`` – etwa bei einer
    direkt übergebenen Dateiliste – wird die Basis wie bisher aus dem
    ``commonpath`` abgeleitet.

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
        if bases is not None and f in bases:
            rel = _relative_target(f, bases[f])
        else:
            rel = _relative_target(f, common) if common else None
        mapping[f] = os.path.join(target_dir, rel or os.path.basename(f))
    return mapping


def find_target_collisions(mapping: Dict[str, str]) -> Dict[str, List[str]]:
    """Findet Zielpfade, auf die mehr als eine Quelle abgebildet wird.

    Das ist ein Muss vor jedem Lauf: die Dateien werden **parallel** verarbeitet,
    zwei Quellen auf einem Ziel heißt also stillen Datenverlust (wer zuletzt
    schreibt, gewinnt). Zwei Wege führen dorthin: ein erzwungenes Ausgabeformat
    (``x.wav`` + ``x.flac`` -> beide ``x.mp3``) und mehrere ausgewählte
    Quellordner mit gleich benannten Unterordnern.
    """
    by_target: Dict[str, List[str]] = {}
    for src, dst in mapping.items():
        by_target.setdefault(os.path.normcase(os.path.abspath(dst)), []).append(src)
    return {t: sorted(srcs) for t, srcs in by_target.items() if len(srcs) > 1}


def format_collisions(collisions: Dict[str, List[str]], limit: int = 5) -> str:
    """Menschenlesbare Auflistung kollidierender Ziele (für CLI/GUI-Meldung)."""
    lines = []
    for target, sources in sorted(collisions.items())[:limit]:
        lines.append(f"  {os.path.basename(target)} <- "
                     + ", ".join(os.path.basename(s) for s in sources))
    if len(collisions) > limit:
        lines.append(f"  … und {len(collisions) - limit} weitere")
    return "\n".join(lines)


def exclude_under(files: List[str], directory: str) -> List[str]:
    """Entfernt Dateien, die im angegebenen Ordner (oder darunter) liegen.

    Verhindert, dass ein Lauf seinen eigenen Output von vorherigen Läufen als
    Eingabe einsammelt, wenn der Zielordner im Quellordner liegt – sonst würde
    die Verstärkung ein zweites Mal angewandt.
    """
    if not directory:
        return list(files)
    target = os.path.normcase(os.path.abspath(directory)) + os.sep
    return [f for f in files
            if not os.path.normcase(os.path.abspath(f)).startswith(target)]


def infer_source_folder(files: List[str], bases: Optional[Dict[str, str]] = None) -> str:
    """Leitet einen Quellordner-Namen für den Log-Dateinamen ab."""
    if not files:
        return ""
    if bases:
        picked = {b for b in (bases.get(f) for f in files) if b}
        if len(picked) == 1:
            return os.path.basename(next(iter(picked)).rstrip(os.sep)) or ""
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
                # Auch der Fehlschlag ist ein "Datei fertig"-Ereignis, sonst
                # bliebe die Zeile in der UI ohne Rückmeldung stehen.
                cb._file_done(fr)
                cb._err(msg)
            done += 1
            cb._progress(done, total)

    if cancel.is_set():
        result.cancelled = True
    return result
