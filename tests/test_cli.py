import os

from audionormalizer import cli
from audionormalizer.ffmpeg_locator import FFmpegTools


def test_apply_suffix_and_format():
    # Reine String-Operation auf splitext – Eingabe-Separator bleibt erhalten.
    assert cli._apply_suffix_and_format("a/b.wav", "_norm", None) == "a/b_norm.wav"
    assert cli._apply_suffix_and_format("a/b.wav", "", "flac") == "a/b.flac"
    assert cli._apply_suffix_and_format("a/b.wav", "_n", "mp3") == "a/b_n.mp3"


def test_plan_mapping_single_output_file(tmp_path):
    f = str(tmp_path / "song.flac")
    open(f, "w").close()
    mapping = cli._plan_mapping([f], "out.wav", "", None)
    assert mapping[f] == "out.wav"


def test_plan_mapping_directory(tmp_path):
    f1 = str(tmp_path / "1.wav")
    f2 = str(tmp_path / "2.wav")
    open(f1, "w").close()
    open(f2, "w").close()
    mapping = cli._plan_mapping([f1, f2], "outdir", "_norm", "flac")
    assert mapping[f1] == os.path.join("outdir", "1_norm.flac")
    assert mapping[f2] == os.path.join("outdir", "2_norm.flac")


def test_parser_defaults():
    args = cli._build_parser().parse_args(["x.wav", "-o", "out"])
    assert args.mode == "peak"
    assert args.target_lufs == -11.0
    assert args.output == "out"


def test_parser_max_dev_default_is_one():
    args = cli._build_parser().parse_args(["x.wav", "-o", "out"])
    assert args.max_dev == 1.0           # V4-Default


def test_run_overwrite_requires_backup_dir(monkeypatch):
    monkeypatch.setattr(cli.ffmpeg_locator, "locate",
                        lambda *_a, **_k: FFmpegTools(ffmpeg="ffmpeg"))
    monkeypatch.setattr(cli._batch, "collect_audio_files", lambda paths: ["a.wav"])
    rc = cli.run(["a.wav", "--overwrite"])
    assert rc == 1


def test_run_requires_output_without_overwrite(monkeypatch):
    monkeypatch.setattr(cli.ffmpeg_locator, "locate",
                        lambda *_a, **_k: FFmpegTools(ffmpeg="ffmpeg"))
    monkeypatch.setattr(cli._batch, "collect_audio_files", lambda paths: ["a.wav"])
    rc = cli.run(["a.wav"])
    assert rc == 1


def test_warn_overwrite_detects_clash(tmp_path):
    f = str(tmp_path / "x.wav")
    assert cli._warn_overwrite({f: f}) == [f]
    assert cli._warn_overwrite({f: f + ".out"}) == []


def test_run_returns_2_when_no_ffmpeg(monkeypatch, capsys):
    monkeypatch.setattr(cli.ffmpeg_locator, "locate", lambda *_a, **_k: None)
    rc = cli.run(["x.wav", "-o", "out"])
    assert rc == 2
    assert "FFmpeg" in capsys.readouterr().err


def test_run_returns_1_when_no_files(monkeypatch, tmp_path):
    monkeypatch.setattr(cli.ffmpeg_locator, "locate",
                        lambda *_a, **_k: FFmpegTools(ffmpeg="ffmpeg"))
    monkeypatch.setattr(cli._batch, "collect_audio_files", lambda paths: [])
    rc = cli.run([str(tmp_path), "-o", "out"])
    assert rc == 1


def _fake_ffmpeg(monkeypatch):
    monkeypatch.setattr(cli.ffmpeg_locator, "locate",
                        lambda *_a, **_k: FFmpegTools(ffmpeg="ffmpeg"))


def test_run_aborts_on_format_collision(monkeypatch, tmp_path, capsys):
    """``x.wav`` + ``x.flac`` mit --format mp3 -> Abbruch statt stillem Verlust."""
    _fake_ffmpeg(monkeypatch)
    for name in ("x.wav", "x.flac"):
        (tmp_path / name).write_bytes(b"x")
    rc = cli.run([str(tmp_path), "-o", str(tmp_path / "out"), "--format", "mp3"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "mehreren Quellen" in err and "x.mp3" in err


def test_run_aborts_on_backup_collision(monkeypatch, tmp_path, capsys):
    """Kollidierende Backups wären fatal: Original nicht wiederherstellbar."""
    _fake_ffmpeg(monkeypatch)
    for root in ("R1", "R2"):
        d = tmp_path / root / "Album"
        d.mkdir(parents=True)
        (d / "a.mp3").write_bytes(b"x")
    rc = cli.run([str(tmp_path / "R1"), str(tmp_path / "R2"),
                  "--overwrite", "--backup-dir", str(tmp_path / "bak")])
    assert rc == 1
    assert "Backup-Pfade" in capsys.readouterr().err


def test_run_skips_files_inside_output_dir(monkeypatch, tmp_path, capsys):
    """Zielordner im Quellordner: früherer Output darf nicht erneut ran."""
    _fake_ffmpeg(monkeypatch)
    (tmp_path / "song.mp3").write_bytes(b"x")
    out = tmp_path / "out"
    out.mkdir()
    (out / "song.mp3").write_bytes(b"x")

    captured = {}

    def fake_batch(files, mapping, *a, **k):
        captured["files"] = list(files)
        return cli._batch.BatchResult()

    monkeypatch.setattr(cli._batch, "run_batch", fake_batch)
    cli.run([str(tmp_path), "-o", str(out), "--no-log"])
    assert [os.path.basename(f) for f in captured["files"]] == ["song.mp3"]
    assert os.path.dirname(captured["files"][0]) == str(tmp_path)
    assert "übersprungen" in capsys.readouterr().out


def test_run_writes_log_into_selected_output_dir(monkeypatch, tmp_path):
    """Regression: das Protokoll landete in einem beliebigen Unterordner.

    ``next(iter(set))`` über die Zielordner ist nicht deterministisch, sobald
    Unterordner-Struktur erhalten bleibt.
    """
    _fake_ffmpeg(monkeypatch)
    for sub in ("A", "B"):
        d = tmp_path / "src" / sub
        d.mkdir(parents=True)
        (d / f"{sub}.mp3").write_bytes(b"x")
    out = tmp_path / "out"

    monkeypatch.setattr(cli._batch, "run_batch",
                        lambda *a, **k: cli._batch.BatchResult(success_count=2))
    seen = {}
    monkeypatch.setattr(cli.logwriter, "write_log_file",
                        lambda target_dir, *a, **k: seen.setdefault("dir", target_dir))
    cli.run([str(tmp_path / "src"), "-o", str(out)])
    assert seen["dir"] == str(out)


def test_run_hybrid_needs_two_files(monkeypatch):
    monkeypatch.setattr(cli.ffmpeg_locator, "locate",
                        lambda *_a, **_k: FFmpegTools(ffmpeg="ffmpeg"))
    monkeypatch.setattr(cli._batch, "collect_audio_files", lambda paths: ["only.wav"])
    rc = cli.run(["only.wav", "-o", "out", "--mode", "hybrid"])
    assert rc == 1
