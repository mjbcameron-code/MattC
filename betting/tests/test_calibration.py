"""Correcting the model against its own record, without fooling ourselves."""

import random

import pytest

from vb.calibrate import Fit, apply, fit, gap, inverse_logit, logit


def _biased(n: int, shift: float, seed: int = 1) -> list[tuple[float, bool]]:
    """Bets from a model that is `shift` too confident in log-odds."""
    rng = random.Random(seed)
    rows = []
    for _ in range(n):
        claimed = rng.uniform(0.08, 0.75)
        true = inverse_logit(logit(claimed) + shift)
        rows.append((claimed, rng.random() < true))
    return rows


def test_the_fit_recovers_a_distortion_it_was_never_told_about():
    fitted = fit(_biased(4000, -0.30))
    assert fitted.slope == pytest.approx(1.0, abs=0.12)
    assert fitted.intercept == pytest.approx(-0.30, abs=0.10)


def test_a_well_calibrated_model_gets_left_alone():
    fitted = fit(_biased(4000, 0.0))
    assert fitted.slope == pytest.approx(1.0, abs=0.12)
    assert fitted.intercept == pytest.approx(0.0, abs=0.10)


def test_the_correction_closes_the_gap_on_bets_it_never_saw():
    """The only test that matters: does it work out of sample?"""
    rows = _biased(4000, -0.30, seed=7)
    train, holdout = rows[:2000], rows[2000:]
    fitted = fit(train)

    _, _, before = gap(holdout)
    corrected = [(apply(p, fitted.slope, fitted.intercept), won)
                 for p, won in holdout]
    _, _, after = gap(corrected)
    assert abs(before) > 3.0, "the holdout should show the fault plainly"
    assert abs(after) < abs(before) / 2


def test_the_identity_changes_nothing():
    for p in (0.01, 0.2, 0.5, 0.99):
        assert apply(p, 1.0, 0.0) == p


def test_too_few_bets_yields_no_correction():
    assert fit(_biased(12, -0.5)).is_identity
    assert fit([]).is_identity


def test_a_bucket_nobody_won_does_not_break_the_fit():
    """Zero winners has no finite log-odds, and long-shot bands hit that."""
    rows = [(0.02, False)] * 60 + _biased(400, -0.3)
    fitted = fit(rows)
    assert fitted.slope == fitted.slope        # not NaN
    assert -3 < fitted.intercept < 3


def test_the_gap_measures_what_it_claims():
    expected, actual, z = gap([(0.5, True), (0.5, False)] * 50)
    assert expected == pytest.approx(50.0)
    assert actual == 50.0
    assert z == pytest.approx(0.0, abs=1e-9)


def test_an_over_confident_record_shows_a_positive_z():
    expected, actual, z = gap(_biased(1000, -0.40))
    assert expected > actual
    assert z > 3


def test_the_engine_applies_the_correction_before_taking_an_edge(conn):
    """An inflated probability inflates the edge at every price, so the
    correction has to land before the thresholds, not on the stake after."""
    from vb.config import load_settings
    from vb.sample import generate_all
    from vb.tips.select import gather

    generate_all(conn, season="2026/27", leagues=["E2"], seed=9)
    settings = load_settings()
    model = settings.raw["model"]
    before = dict(model.get("calibration", {}))
    try:
        model["calibration"] = {"slope": 1.0, "intercept": 0.0}
        plain, _, _ = gather(conn, days=7)
        model["calibration"] = {"slope": 1.0, "intercept": -0.40}
        shaded, _, _ = gather(conn, days=7)
    finally:
        model["calibration"] = before

    assert plain, "no candidates to compare"
    assert len(shaded) < len(plain), (
        f"shading every probability must cost candidates, "
        f"got {len(shaded)} against {len(plain)}")
    for candidate in shaded:
        assert candidate.blended_prob < 1.0


def test_a_local_override_is_merged_over_the_shipped_settings(tmp_path, monkeypatch):
    """A calibration is a fact about one database, not about the code.

    Put this database's fitted numbers in settings.yaml and the demo — whose
    generator is honest by construction — is corrected for a fault it does not
    have and advises nothing at all. So the fit lives beside the settings.
    """
    import yaml

    import vb.config as config

    (tmp_path / "settings.yaml").write_text(yaml.safe_dump({
        "model": {"calibration": {"slope": 1.0, "intercept": 0.0},
                  "half_life_days": 180},
        "selection": {"min_edge": 0.04},
    }))
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)
    config.load_settings.cache_clear()

    plain = config.load_settings()
    assert plain.get("model.calibration.intercept") == 0.0

    (tmp_path / "settings.local.yaml").write_text(yaml.safe_dump({
        "model": {"calibration": {"slope": 0.819, "intercept": -0.281}}}))

    config.load_settings.cache_clear()
    merged = config.load_settings()
    assert merged.get("model.calibration.slope") == 0.819
    assert merged.get("model.calibration.intercept") == -0.281
    # Merged leaf by leaf: neighbours in the same branch must survive.
    assert merged.get("model.half_life_days") == 180
    assert merged.get("selection.min_edge") == 0.04


def test_the_shipped_settings_carry_no_fitted_correction():
    """Shipping one database's fit as a default silently corrupts every other."""
    import vb.config as config

    config.load_settings.cache_clear()
    settings = config.load_settings()
    assert settings.get("model.calibration.slope", 1.0) == 1.0
    assert settings.get("model.calibration.intercept", 0.0) == 0.0


def test_applying_a_fit_writes_a_file_the_loader_can_read(tmp_path, monkeypatch):
    """The round trip: what --apply writes must be what load_settings reads."""
    import yaml

    import vb.config as config
    from vb.calibrate import Fit
    from vb.cli import _write_local_calibration

    (tmp_path / "settings.yaml").write_text(yaml.safe_dump({
        "model": {"calibration": {"slope": 1.0, "intercept": 0.0},
                  "half_life_days": 180}}))
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)

    _write_local_calibration(Fit(slope=0.819, intercept=-0.281, bets=444))

    config.load_settings.cache_clear()
    settings = config.load_settings()
    assert settings.get("model.calibration.slope") == 0.819
    assert settings.get("model.calibration.intercept") == -0.281
    assert settings.get("model.half_life_days") == 180
    config.load_settings.cache_clear()

    written = (tmp_path / "settings.local.yaml").read_text()
    assert written.startswith("#"), "it has to explain itself to whoever opens it"
    assert "Git-ignored" in written


def test_applying_twice_does_not_stack_up(tmp_path, monkeypatch):
    import yaml

    import vb.config as config
    from vb.calibrate import Fit
    from vb.cli import _write_local_calibration

    (tmp_path / "settings.yaml").write_text(yaml.safe_dump({"model": {}}))
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)

    _write_local_calibration(Fit(slope=0.9, intercept=-0.2))
    _write_local_calibration(Fit(slope=0.819, intercept=-0.281))

    data = yaml.safe_load((tmp_path / "settings.local.yaml").read_text())
    assert data["model"]["calibration"] == {"slope": 0.819, "intercept": -0.281}
    config.load_settings.cache_clear()
