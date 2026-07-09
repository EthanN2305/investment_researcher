"""Phase 4 — confidence calibration tests (no network, no keys).

Covers the pure math (Brier, reliability curve, outcome labeling, Platt fit),
the DB-backed backfill/refit/report, and that `derive_confidence` cold-starts
unchanged but applies a fitted calibrator when one is supplied.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app import calibration as cal
from app import db_models
from app.agents.recommend import derive_confidence
from app.db import Base
from app.db_models import CalibrationFit, ReportOutcome, StoredReport, User
from app.models import (
    AgentReport,
    Claim,
    FinalReport,
    Recommendation,
)


# --- fixtures ----------------------------------------------------------------
@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()


def _claim(text: str, conf: float) -> Claim:
    return Claim(claim=text, evidence="e", source="s", confidence=conf)


class FakePrices:
    """get_history returns a fixed 60-row series; index 0 and +horizon matter."""

    def __init__(self, series: dict[str, list[float]]):
        self._series = series

    def get_history(self, ticker, period="1y"):
        from app.models import PriceHistory
        closes = self._series[ticker.upper()]
        dates = [f"2024-{(1 + i // 28):02d}-{(1 + i % 28):02d}" for i in range(len(closes))]
        return PriceHistory(ticker=ticker, dates=dates, closes=closes)


# --- pure math ---------------------------------------------------------------
def test_brier_score():
    assert cal.brier_score([]) is None
    # perfect predictions → 0; worst → 1
    assert cal.brier_score([(1.0, 1), (0.0, 0)]) == 0.0
    assert cal.brier_score([(0.0, 1), (1.0, 0)]) == 1.0
    assert cal.brier_score([(0.5, 1), (0.5, 0)]) == pytest.approx(0.25)


def test_reliability_curve_buckets():
    pairs = [(0.05, 0), (0.15, 0), (0.55, 1), (0.95, 1)]
    curve = cal.reliability_curve(pairs, n_buckets=10)
    # one bucket per occupied decile; observed hit rate is 0 then 1
    by_lo = {b["lo"]: b for b in curve}
    assert by_lo[0.0]["observed"] == 0.0
    assert by_lo[0.9]["observed"] == 1.0 and by_lo[0.9]["count"] == 1


def test_label_outcome_truth_table():
    band = 0.02
    # bullish correct only when it beats benchmark by > band
    assert cal.label_outcome("bullish", 0.10, 0.02, band) is True
    assert cal.label_outcome("bullish", 0.03, 0.02, band) is False
    # bearish correct when it trails by > band
    assert cal.label_outcome("bearish", -0.05, 0.02, band) is True
    assert cal.label_outcome("bearish", 0.05, 0.02, band) is False
    # neutral correct when within the band
    assert cal.label_outcome("neutral", 0.03, 0.02, band) is True
    assert cal.label_outcome("neutral", 0.10, 0.02, band) is False


def test_fit_platt_recovers_direction_and_calibrator():
    # Synthetic: correctness rises with the prior → positive slope.
    priors, labels = [], []
    for p in [0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]:
        for _ in range(20):
            priors.append(p)
        hits = int(round(p * 20))  # hit rate == prior
        labels.extend([1] * hits + [0] * (20 - hits))
        # pad the per-p block to 20 (already 20)
    params = cal.fit_platt(priors, labels)
    assert params["w1"] > 0  # higher prior → higher realized hit rate
    c = cal.Calibrator(params, n=len(priors), through="2026-06")
    assert c.ready
    # monotonic and clamped
    assert c.apply(0.9) > c.apply(0.2)
    assert 0.0 <= c.apply(0.99) <= 1.0


def test_calibrator_not_ready_on_nonpositive_slope():
    c = cal.Calibrator({"w0": 0.0, "w1": -1.0})
    assert c.ready is False


# --- derive_confidence integration ------------------------------------------
def test_derive_confidence_cold_start_unchanged():
    reports = [AgentReport(agent="financials", claims=[_claim("a", 0.8)])]
    base = derive_confidence(reports, llm_confidence=0.7)  # no calibrator
    with_none = derive_confidence(reports, llm_confidence=0.7, calibrator=None)
    assert base == with_none  # cold start is a no-op


def test_derive_confidence_applies_calibrator_and_notes_it():
    reports = [AgentReport(agent="financials", claims=[_claim("a", 0.8)])]
    prior, _, _ = derive_confidence(reports, 0.7)

    class Fake:
        ready = True
        n = 123
        through = "2026-06"
        def apply(self, p, features=None):
            return 0.42  # force a distinct value

    overall, _, rationale = derive_confidence(reports, 0.7, calibrator=Fake())
    assert overall == 0.42 and overall != prior
    assert "Calibrated on 123 resolved reports through 2026-06" in rationale


def test_calibration_always_clamped():
    reports = [AgentReport(agent="financials", claims=[_claim("a", 0.9)])]

    class Extreme:
        ready = True
        n = 50
        through = None
        def apply(self, p, features=None):
            return 5.0  # absurd — must be clamped

    overall, _, _ = derive_confidence(reports, 0.9, calibrator=Extreme())
    assert overall <= 0.95


# --- DB-backed backfill / refit / report -------------------------------------
def _pending_outcome(db, ticker, stance, prior, pred_date):
    o = ReportOutcome(
        ticker=ticker, stance=stance, predicted_confidence=prior,
        prior_confidence=prior,
        features_json='{"agent_confidences": {"news": %.2f}}' % prior,
        prediction_date=pred_date, horizon_days=5, benchmark="SPY",
        band_pct=2.0, status="pending",
    )
    db.add(o)
    db.commit()
    return o


def test_backfill_resolves_and_labels(db):
    old = datetime(2024, 1, 1, tzinfo=timezone.utc)
    _pending_outcome(db, "NVDA", "bullish", 0.8, old)
    # NVDA +10% by index 5, SPY +2% → excess 8% > band → bullish correct
    prices = FakePrices({
        "NVDA": [100.0] + [0]*4 + [110.0] + [111.0]*54,
        "SPY": [100.0] + [0]*4 + [102.0] + [102.0]*54,
    })
    n = cal.backfill_outcomes(prices, db=db)
    assert n == 1
    o = db.scalar(select(ReportOutcome))
    assert o.status == "resolved" and o.correct is True
    assert o.excess_return == pytest.approx(0.08, abs=1e-6)


def test_backfill_skips_immature(db):
    recent = datetime.now(timezone.utc)  # horizon can't have elapsed
    _pending_outcome(db, "AAPL", "bullish", 0.7, recent)
    prices = FakePrices({"AAPL": [100.0]*60, "SPY": [100.0]*60})
    assert cal.backfill_outcomes(prices, db=db) == 0
    assert db.scalar(select(ReportOutcome)).status == "pending"


def test_refit_cold_start_below_min(db):
    old = datetime(2024, 1, 1, tzinfo=timezone.utc)
    for i in range(5):  # well below calibration_min_samples
        o = _pending_outcome(db, f"T{i}", "bullish", 0.7, old)
        o.status = "resolved"; o.correct = True
    db.commit()
    assert cal.refit(db=db) is None


def test_refit_produces_active_versioned_fit(db):
    old = datetime(2024, 1, 1, tzinfo=timezone.utc)
    # 80 resolved outcomes, correctness correlated with prior → fittable
    for i in range(80):
        prior = 0.5 + 0.4 * (i % 2)  # 0.5 or 0.9
        o = _pending_outcome(db, f"T{i}", "bullish", prior, old)
        o.status = "resolved"
        o.correct = (i % 2 == 1)  # the 0.9 ones are right
        o.resolved_at = old
    db.commit()
    fit = cal.refit(db=db)
    assert fit is not None and fit.active and fit.n_samples == 80
    assert fit.brier is not None
    # exactly one active fit
    actives = db.scalars(
        select(CalibrationFit).where(CalibrationFit.active.is_(True))
    ).all()
    assert len(actives) == 1

    report = cal.calibration_report(db)
    assert report["n_resolved"] == 80
    assert report["fit"]["n_samples"] == 80
    assert report["brier"] is not None
    assert any(a["agent"] == "news" for a in report["per_agent"])
