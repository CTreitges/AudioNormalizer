import pytest

from audionormalizer.measure import parse_loudnorm_json, parse_volumedetect


LOUDNORM_STDERR = """
[Parsed_loudnorm_0 @ 0000]
{
	"input_i" : "-18.52",
	"input_tp" : "-2.10",
	"input_lra" : "7.30",
	"input_thresh" : "-28.90",
	"output_i" : "-24.00",
	"target_offset" : "0.00"
}
"""

VOLUMEDETECT_STDERR = """
[Parsed_volumedetect_0 @ 0000] n_samples: 123456
[Parsed_volumedetect_0 @ 0000] mean_volume: -21.3 dB
[Parsed_volumedetect_0 @ 0000] max_volume: -4.7 dB
[Parsed_volumedetect_0 @ 0000] histogram_0db: 1
"""


def test_parse_loudnorm_json_ok():
    m = parse_loudnorm_json(LOUDNORM_STDERR)
    assert m.lufs == pytest.approx(-18.52)
    assert m.true_peak == pytest.approx(-2.10)


def test_parse_loudnorm_json_missing_block_raises():
    with pytest.raises(ValueError):
        parse_loudnorm_json("kein json hier")


def test_parse_loudnorm_silence_sentinel_becomes_none():
    silent = '{ "input_i" : "-120.00", "input_tp" : "-120.00" }'
    with pytest.raises(ValueError):
        parse_loudnorm_json(silent)


def test_parse_volumedetect_ok():
    assert parse_volumedetect(VOLUMEDETECT_STDERR) == pytest.approx(-4.7)


def test_parse_volumedetect_positive_value():
    assert parse_volumedetect("max_volume: 0.0 dB") == pytest.approx(0.0)


def test_parse_volumedetect_missing_raises():
    with pytest.raises(ValueError):
        parse_volumedetect("nichts")
