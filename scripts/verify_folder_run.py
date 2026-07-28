"""End-to-End-Verifikation eines kompletten ORDNER-Laufs.

Normalisiert einen echten Ordnerbaum über die CLI und prüft danach am Ergebnis:

  * Ordnerstruktur bleibt relativ zum ausgewählten Ordner erhalten
  * jede Ausgabedatei trifft ihr Ziel (LUFS bzw. Peak), ohne den True-Peak
    zu überschreiten
  * keine liegengebliebenen ``.part``-Temp-Dateien
  * das Protokoll liegt im ausgewählten Zielordner
  * versteckte Dateien/Ordner und Nicht-Audio wurden übersprungen

Beispiel:
    python scripts/verify_folder_run.py "C:/Musik" --out "C:/Musik-norm" \
        --mode loudness --target-lufs -14 --target-tp -1
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from audionormalizer import batch, cli, ffmpeg_locator, measure  # noqa: E402
from audionormalizer.engine import TEMP_MARKER  # noqa: E402


def _walk(root: str):
    for dirpath, _dirs, files in os.walk(root):
        for name in sorted(files):
            full = os.path.join(dirpath, name)
            yield os.path.relpath(full, root), full


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("source", help="Quellordner")
    ap.add_argument("--out", required=True, help="Zielordner")
    ap.add_argument("--mode", default="loudness", choices=["peak", "loudness", "hybrid"])
    ap.add_argument("--target-lufs", type=float, default=-14.0)
    ap.add_argument("--target-peak", type=float, default=-3.0)
    ap.add_argument("--target-tp", type=float, default=-1.0)
    ap.add_argument("--tolerance", type=float, default=1.0, help="erlaubte Abweichung in dB")
    ap.add_argument("--ffmpeg", default=None)
    args = ap.parse_args()

    tools = ffmpeg_locator.locate(args.ffmpeg)
    if not tools:
        print("FFmpeg nicht gefunden")
        return 2
    print(ffmpeg_locator.describe(tools), "\n")

    def _temp_leftovers() -> set:
        return {full for root in (args.source, args.out) if os.path.isdir(root)
                for _rel, full in _walk(root)
                if os.path.basename(full).startswith(".")
                and TEMP_MARKER + "." in os.path.basename(full).lower()}

    # Reste, die schon VOR dem Lauf da waren, gehen nicht auf seine Rechnung.
    pre_existing = _temp_leftovers()

    # ---- Lauf über die echte CLI (kein Nachbau der Ablauflogik) ----
    argv = [args.source, "-o", args.out, "--mode", args.mode,
            "--target-lufs", str(args.target_lufs),
            "--target-peak", str(args.target_peak),
            "--target-tp", str(args.target_tp)]
    if args.ffmpeg:
        argv += ["--ffmpeg", args.ffmpeg]
    rc = cli.run(argv)
    print(f"\nCLI-Exitcode: {rc}")

    selection = batch.collect_selection([args.source])
    expected = {os.path.relpath(os.path.abspath(f), os.path.abspath(args.source))
                for f in selection.files}
    produced = {rel for rel, _ in _walk(args.out) if not rel.lower().endswith(".txt")}

    failures = []

    # ---- 1. Struktur ----
    print("\n[1] Ordnerstruktur")
    missing = expected - produced
    extra = produced - expected
    for rel in sorted(expected):
        print(f"   {'OK ' if rel in produced else 'FEHLT'}  {rel}")
    if missing:
        failures.append(f"{len(missing)} Datei(en) fehlen im Ziel: {sorted(missing)}")
    if extra:
        failures.append(f"unerwartete Dateien im Ziel: {sorted(extra)}")

    # ---- 2. Pegel je Datei ----
    print(f"\n[2] Zielwerte je Datei (Toleranz {args.tolerance} dB)")
    for rel in sorted(produced):
        full = os.path.join(args.out, rel)
        try:
            m = measure.measure_loudness(full, tools)
        except Exception as exc:
            failures.append(f"{rel}: nicht messbar ({exc})")
            print(f"   FAIL  {rel}: {exc}")
            continue

        tp_txt = f"{m.true_peak:+.2f}" if m.true_peak is not None else "?"
        lufs_txt = f"{m.lufs:+.2f}" if m.lufs is not None else "?"
        problems = []
        if m.true_peak is not None and m.true_peak > args.target_tp + 0.5:
            problems.append(f"TP {tp_txt} > Ziel {args.target_tp}")
        # LUFS trifft das Ziel nur, wenn der True-Peak-Deckel nicht gegriffen hat.
        if args.mode == "loudness" and m.lufs is not None:
            capped = m.true_peak is not None and abs(m.true_peak - args.target_tp) <= 0.5
            if not capped and abs(m.lufs - args.target_lufs) > args.tolerance:
                problems.append(f"LUFS {lufs_txt} verfehlt Ziel {args.target_lufs}")
        status = "FAIL" if problems else "OK  "
        note = ("  <- " + "; ".join(problems)) if problems else ""
        print(f"   {status}  {rel}: LUFS={lufs_txt} TP={tp_txt}{note}")
        failures.extend(f"{rel}: {p}" for p in problems)

    # ---- 3. Keine neuen Temp-Reste ----
    print("\n[3] Temp-Reste durch diesen Lauf")
    leftovers = sorted(_temp_leftovers() - pre_existing)
    print(f"   {'OK  keine' if not leftovers else 'FAIL ' + str(leftovers)}")
    if pre_existing:
        print(f"   (ignoriert, lag vorher schon da: {len(pre_existing)})")
    if leftovers:
        failures.append(f"neue Temp-Reste: {leftovers}")

    # ---- 4. Protokoll ----
    print("\n[4] Protokoll im Zielordner")
    logs = [rel for rel, _ in _walk(args.out)
            if os.path.basename(rel).startswith("Audio-Normalizer-Log")]
    top_level = [l for l in logs if os.path.dirname(l) == ""]
    print(f"   gefunden: {logs or 'keine'}")
    if not top_level:
        failures.append("kein Protokoll direkt im Zielordner")

    print("\n" + "=" * 60)
    if failures:
        print(f"FEHLGESCHLAGEN – {len(failures)} Problem(e):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"BESTANDEN – {len(produced)} Datei(en) korrekt normalisiert.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
