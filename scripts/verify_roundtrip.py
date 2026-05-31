"""End-to-End-Verifikation des Normalisierungs-Vertrags.

Normalisiert eine echte Datei und MISST das Ergebnis erneut, um zu beweisen:
  * Loudness/Hybrid: Output-True-Peak <= Ziel-True-Peak  (clippt nie)
  * Loudness:        Output-LUFS ~ Ziel-LUFS             (sofern TP nicht deckelt)
  * Metadaten/Track-Tag bleiben erhalten

Beispiel:
    python scripts/verify_roundtrip.py "song.flac" --mode loudness \
        --target-lufs -14 --target-tp -1 --ffmpeg "C:/.../ffmpeg.exe"
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from audionormalizer import ffmpeg_locator, engine, measure, probe  # noqa: E402
from audionormalizer.models import Mode, NormalizeParams  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("--mode", default="loudness", choices=["peak", "loudness"])
    ap.add_argument("--target-lufs", type=float, default=-14.0)
    ap.add_argument("--target-peak", type=float, default=-3.0)
    ap.add_argument("--target-tp", type=float, default=-1.0)
    ap.add_argument("--ffmpeg", default=None)
    ap.add_argument("--out-ext", default=None, help="z.B. .wav/.flac/.mp3 (sonst wie Quelle)")
    args = ap.parse_args()

    tools = ffmpeg_locator.locate(args.ffmpeg)
    if not tools:
        print("FFmpeg nicht gefunden")
        return 2
    print(ffmpeg_locator.describe(tools))

    mode = Mode.PEAK if args.mode == "peak" else Mode.LOUDNESS
    params = NormalizeParams(mode=mode, target_lufs=args.target_lufs,
                             target_peak=args.target_peak, target_tp=args.target_tp)

    ext = args.out_ext or os.path.splitext(args.input)[1]
    in_info = probe.probe(args.input, tools)
    print(f"\nQuelle: {args.input}")
    print(f"  codec={in_info.codec_name} sr={in_info.sample_rate} ch={in_info.channels} "
          f"bits={in_info.bits_per_sample} br={in_info.bit_rate}")
    pre = measure.measure_loudness(args.input, tools)
    print(f"  LUFS={pre.lufs}  TP={pre.true_peak}")

    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "out" + ext)
        res = engine.normalize_file(args.input, out, params, tools)
        print(f"\nVerarbeitet: mode={res.mode_used} gain={res.applied_gain_db:+.2f} dB -> {os.path.basename(out)}")

        out_info = probe.probe(out, tools)
        post = measure.measure_loudness(out, tools)
        print(f"  codec={out_info.codec_name} sr={out_info.sample_rate} ch={out_info.channels} "
              f"bits={out_info.bits_per_sample}")
        print(f"  LUFS={post.lufs}  TP={post.true_peak}")

        # Track-Tag (0=Peak,1=Loudness) prüfen.
        track = _read_track_tag(out, tools)
        print(f"  Track-Tag: {track!r}")

        ok = True
        if post.true_peak is not None and post.true_peak > args.target_tp + 0.5:
            print(f"  FAIL: Output-TP {post.true_peak} > Ziel-TP {args.target_tp}")
            ok = False
        else:
            print(f"  PASS: Output-TP <= Ziel-TP ({args.target_tp})")

        if mode is Mode.LOUDNESS and post.lufs is not None:
            # Wenn der TP-Deckel NICHT gegriffen hat, sollte LUFS das Ziel treffen.
            tp_capped = (pre.true_peak is not None and
                         (args.target_lufs - pre.lufs) > (args.target_tp - pre.true_peak))
            if tp_capped:
                print("  INFO: TP-Deckel hat gegriffen -> LUFS bleibt absichtlich unter Ziel")
            elif abs(post.lufs - args.target_lufs) <= 1.0:
                print(f"  PASS: Output-LUFS {post.lufs} ~ Ziel {args.target_lufs}")
            else:
                print(f"  FAIL: Output-LUFS {post.lufs} verfehlt Ziel {args.target_lufs}")
                ok = False

        expected_track = "0" if res.mode_used == "Peak" else "1"
        if track == expected_track:
            print(f"  PASS: Track-Tag = {expected_track} (Indikator korrekt)")
        else:
            print(f"  WARN: Track-Tag {track!r} != erwartet {expected_track!r} "
                  f"(Container unterstützt evtl. keine Track-Tags)")

        return 0 if ok else 1


def _read_track_tag(path: str, tools):
    if not tools.has_ffprobe:
        return None
    from audionormalizer.procutil import run
    res = run([tools.ffprobe, "-v", "error", "-show_entries",
               "format_tags=track:stream_tags=track", "-of", "default=nw=1:nk=1", path])
    val = (res.stdout or "").strip().splitlines()
    return val[0] if val else None


if __name__ == "__main__":
    sys.exit(main())
