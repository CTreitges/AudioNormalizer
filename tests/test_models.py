import pytest

from audionormalizer.models import Mode, NormalizeParams


def test_mode_label_roundtrip():
    for m in Mode:
        assert Mode.from_label(m.label) is m


def test_mode_labels_are_stable_contract():
    # Diese Strings landen wortgleich in der Log-Datei – dürfen nicht ändern.
    assert Mode.PEAK.label == "Peak-Normalizing"
    assert Mode.LOUDNESS.label == "Loudness-Normalizing"
    assert Mode.HYBRID.label == "Hybrid-Normalizing"


def test_from_label_unknown_raises():
    with pytest.raises(ValueError):
        Mode.from_label("Quatsch")


def test_params_validate_ok():
    NormalizeParams(mode=Mode.PEAK).validate()


def test_params_validate_negative_dev():
    with pytest.raises(ValueError):
        NormalizeParams(mode=Mode.HYBRID, target_dev=-1).validate()
