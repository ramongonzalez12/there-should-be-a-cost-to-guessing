"""The committed pressure result stays paired by seed, dose, and arm."""

import csv
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LEVELS = ROOT / "data" / "processed" / "alignment_pressure_replication.csv"
CONTRASTS = ROOT / "data" / "processed" / "alignment_pressure_contrasts.csv"


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_replication_has_complete_matched_checkpoints():
    levels = read_csv(LEVELS)
    contrasts = read_csv(CONTRASTS)

    assert len(levels) == 10
    assert len(contrasts) == 6
    assert all(float(row["delta_wrong_adoption"]) > 0 for row in contrasts)


def test_step_125_effect_reduces_pressure_discernment():
    levels = read_csv(LEVELS)
    keyed = {(row["reward"], row["step"]): row for row in levels}
    accuracy = keyed[("binary", "125")]
    calibrated = keyed[("quadratic", "125")]

    wrong_delta = (
        float(calibrated["accepts_wrong_pushback"])
        - float(accuracy["accepts_wrong_pushback"])
    )
    discernment_delta = (
        float(calibrated["pressure_discernment"])
        - float(accuracy["pressure_discernment"])
    )
    assert wrong_delta == pytest.approx(0.20726, abs=0.00001)
    assert discernment_delta == pytest.approx(-0.156888, abs=0.00001)
