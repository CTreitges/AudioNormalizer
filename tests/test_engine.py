import pytest

from audionormalizer import engine
from audionormalizer.models import AudioInfo, Measurement, Mode, NormalizeParams


# --------------------------- Modus-Entscheidung --------------------------- #
def test_decide_mode_peak_and_loudness_are_fixed():
    assert engine.decide_actual_mode(NormalizeParams(mode=Mode.PEAK), -20.0) == "Peak"
    assert engine.decide_actual_mode(NormalizeParams(mode=Mode.LOUDNESS), -20.0) == "Loudness"


def test_decide_mode_hybrid_within_tolerance_is_peak():
    p = NormalizeParams(mode=Mode.HYBRID, target_dev=3.0)
    p.ref_lufs = -12.0
    assert engine.decide_actual_mode(p, -12.0) == "Peak"      # dev 0
    assert engine.decide_actual_mode(p, -13.5) == "Peak"      # dev 1.5 < 3


def test_decide_mode_hybrid_outlier_is_loudness_boundary_inclusive():
    p = NormalizeParams(mode=Mode.HYBRID, target_dev=3.0)
    p.ref_lufs = -12.0
    assert engine.decide_actual_mode(p, -15.0) == "Loudness"  # dev 3 >= 3 (inkl.)
    assert engine.decide_actual_mode(p, -9.0) == "Loudness"   # dev 3 >= 3


def test_decide_mode_hybrid_without_measurement_falls_back_to_loudness():
    p = NormalizeParams(mode=Mode.HYBRID)
    p.ref_lufs = -12.0
    assert engine.decide_actual_mode(p, None) == "Loudness"


# --------------------------- Gain-Berechnung ------------------------------ #
def test_loudness_gain_basic():
    p = NormalizeParams(mode=Mode.LOUDNESS, target_lufs=-11.0, target_tp=-3.0)
    m = Measurement(lufs=-20.0, true_peak=-12.0)
    # gain = -11 - (-20) = 9 ; max_allowed = -3 - (-12) = 9 -> 9
    assert engine.compute_loudness_gain(p, m) == pytest.approx(9.0)


def test_loudness_gain_clamped_by_true_peak():
    p = NormalizeParams(mode=Mode.LOUDNESS, target_lufs=-11.0, target_tp=-3.0)
    m = Measurement(lufs=-20.0, true_peak=-1.0)
    # gain wants 9, aber max_allowed = -3 - (-1) = -2 -> Deckel greift
    assert engine.compute_loudness_gain(p, m) == pytest.approx(-2.0)


def test_hybrid_loudness_gain_uses_ref_and_min_tp_limit():
    p = NormalizeParams(mode=Mode.HYBRID, target_peak=-3.0, target_tp=-1.0)
    p.ref_lufs = -14.0
    m = Measurement(lufs=-24.0, true_peak=-10.0)
    # tp_limit = min(target_tp=-1, target_peak=-3) = -3
    # gain = -14 - (-24) = 10 ; max_allowed = -3 - (-10) = 7 -> 7
    assert engine.compute_loudness_gain(p, m) == pytest.approx(7.0)


def test_loudness_gain_without_lufs_raises():
    with pytest.raises(ValueError):
        engine.compute_loudness_gain(NormalizeParams(mode=Mode.LOUDNESS),
                                     Measurement(lufs=None))


def test_peak_gain():
    p = NormalizeParams(mode=Mode.PEAK, target_peak=-3.0)
    assert engine.compute_peak_gain(p, -9.0) == pytest.approx(6.0)
    assert engine.compute_peak_gain(p, -1.0) == pytest.approx(-2.0)


# --------------------------- Codec-Argumente ------------------------------ #
def test_codec_args_wav_16bit_has_dither():
    info = AudioInfo(channels=2, sample_rate=44100, bits_per_sample=16, sample_fmt="s16")
    args = engine.build_codec_args(".wav", info, dither=True)
    assert "-c:a" in args and "pcm_s16le" in args
    assert "44100" in args and "2" in args
    assert "triangular_hp" in args


def test_codec_args_wav_24bit_no_dither():
    info = AudioInfo(channels=2, sample_rate=48000, bits_per_sample=24, sample_fmt="s32")
    args = engine.build_codec_args(".wav", info, dither=True)
    assert "pcm_s24le" in args
    assert "triangular_hp" not in args


def test_codec_args_flac_24bit_uses_s32():
    info = AudioInfo(channels=2, sample_rate=44100, bits_per_sample=24, sample_fmt="s32")
    args = engine.build_codec_args(".flac", info, dither=True)
    assert "flac" in args
    idx = args.index("-sample_fmt")
    assert args[idx + 1] == "s32"


def test_codec_args_mp3_with_and_without_bitrate():
    with_br = engine.build_codec_args(".mp3", AudioInfo(bit_rate=320000), dither=True)
    assert "libmp3lame" in with_br and "-b:a" in with_br and "320000" in with_br
    no_br = engine.build_codec_args(".mp3", AudioInfo(), dither=True)
    assert "-q:a" in no_br


def test_codec_args_lossy_formats():
    assert "aac" in engine.build_codec_args(".m4a", AudioInfo(), True)
    assert "libopus" in engine.build_codec_args(".opus", AudioInfo(), True)
    assert "libvorbis" in engine.build_codec_args(".ogg", AudioInfo(), True)


def test_codec_args_opus_does_not_force_sample_rate():
    # libopus akzeptiert nur 48/24/16/12/8 kHz -> Quell-SR (44100) darf nicht
    # erzwungen werden, sonst crasht FFmpeg.
    args = engine.build_codec_args(".opus", AudioInfo(sample_rate=44100, channels=2), True)
    assert "-ar" not in args
    assert "libopus" in args and "-ac" in args


# ----------------------------- Stream-Mapping ----------------------------- #
def test_map_args_cover_capable_containers_copy_video():
    for ext in (".mp3", ".flac", ".m4a"):
        args = engine.build_map_args(ext)
        assert args == ["-map", "0:a", "-map", "0:v?", "-c:v", "copy"]


def test_map_args_non_cover_containers_audio_only():
    # WAV/OGG/Opus: kein Video mappen -> kein Crash, kein Theora-Cover.
    for ext in (".wav", ".ogg", ".opus"):
        assert engine.build_map_args(ext) == ["-map", "0:a"]
