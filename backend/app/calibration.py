"""Phase 4 — confidence calibration (close the loop).

Turns the hand-tuned derived confidence into an empirically grounded number by
scoring past recommendations against realized outcomes:

  1. When a report is stored, a *pending* `report_outcomes` row is created,
     snapshotting the derivation features at prediction time.
  2. A scheduled backfill resolves pending rows once the horizon has elapsed:
     it compares the ticker's forward return to a benchmark (SPY) over H
     trading days and labels the stance correct/incorrect.
  3. Calibration metrics (Brier score, reliability curve, per-agent hit rates)
     are computed from the resolved pairs.
  4. A Platt scaling is fitted from (prior_confidence → correctness) and stored
     as a versioned `calibration_fits` row; the active fit is applied inside
     `derive_confidence`. With no fit (cold start) the pipeline uses the
     hand-tuned prior unchanged.

Guardrails: fitting always uses `prior_confidence` (the UNcalibrated derived
score), never the calibrated output — no feedback loop. The [0.05, 0.95] clamp
is enforced downstream in `derive_confidence`: never claim certainty.

Math is numpy-only (no sklearn/scipy dependency).
"""
from __future__ import annotations

import json
import logging
import math
import time
from datetime import datetime, timezone

import numpy as np
from sqlalchemy import select

from app.config import settings
from app.db_models import CalibrationFit, ReportOutcome, StoredReport
from app.models import FinalReport
from app.tools.base import PriceHistoryProvider

logger = logging.getLogger("calibration")

_STANCES = ("bullish", "neutral", "bearish")


# --------------------------------------------------------------------------- #
# Pure math                                                                   #
# --------------------------------------------------------------------------- #
def _sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def brier_score(pairs: list[tuple[float, int]]) -> float | None:
    """Mean squared error of predicted probabilities vs {0,1} outcomes."""
    if not pairs:
        return None
    return sum((p - y) ** 2 for p, y in pairs) / len(pairs)


def reliability_curve(
    pairs: list[tuple[float, int]], n_buckets: int = 10
) -> list[dict]:
    """Bucket predictions and compare predicted vs observed hit rate.

    Perfect calibration lies on the diagonal (predicted == observed).
    """
    buckets: list[dict] = []
    for b in range(n_buckets):
        lo, hi = b / n_buckets, (b + 1) / n_buckets
        # Last bucket is closed on the right so p == 1.0 lands somewhere.
        in_b = [
            (p, y) for p, y in pairs
            if (lo <= p < hi) or (b == n_buckets - 1 and p == hi)
        ]
        if not in_b:
            continue
        buckets.append({
            "lo": round(lo, 2),
            "hi": round(hi, 2),
            "predicted": round(sum(p for p, _ in in_b) / len(in_b), 4),
            "observed": round(sum(y for _, y in in_b) / len(in_b), 4),
            "count": len(in_b),
        })
    return buckets


def label_outcome(
    stance: str, ticker_return: float, benchmark_return: float, band_frac: float
) -> bool:
    """Was the stance right? Excess = ticker − benchmark, over the horizon.

    bullish → beat the benchmark by more than the band; bearish → trailed by
    more than the band; neutral → stayed within ±band.
    """
    excess = ticker_return - benchmark_return
    if stance == "bullish":
        return excess > band_frac
    if stance == "bearish":
        return excess < -band_frac
    return abs(excess) <= band_frac


def fit_platt(
    priors: list[float], labels: list[int], *, l2: float = 1e-2, iters: int = 2000,
    lr: float = 0.5,
) -> dict:
    """Fit P(correct) = sigmoid(w0 + w1·(prior − 0.5)) by gradient descent.

    Platt scaling (1-D logistic on the prior confidence) — stable at the small
    N this project produces, unlike a many-feature logistic that would overfit.
    Returns {"w0", "w1"}; `w1 > 0` means higher prior → higher realized hit rate.
    """
    x = np.asarray(priors, dtype=float) - 0.5
    y = np.asarray(labels, dtype=float)
    w0, w1 = 0.0, 0.0
    n = len(y)
    for _ in range(iters):
        z = w0 + w1 * x
        p = 1.0 / (1.0 + np.exp(-z))
        err = p - y
        g0 = err.mean()
        g1 = (err * x).mean() + l2 * w1
        w0 -= lr * g0
        w1 -= lr * g1
    return {"w0": float(w0), "w1": float(w1)}


class Calibrator:
    """Applies a fitted Platt scaling to a prior confidence."""

    def __init__(self, params: dict, n: int = 0, through: str | None = None) -> None:
        self._w0 = float(params.get("w0", 0.0))
        self._w1 = float(params.get("w1", 0.0))
        self.n = n
        self.through = through
        # Guard: a non-positive slope would invert the mapping (perverse tiny-N
        # fit) — treat as not-ready so we fall back to the prior.
        self.ready = self._w1 > 0.0

    def apply(self, prior: float, features: dict | None = None) -> float:
        return _sigmoid(self._w0 + self._w1 * (prior - 0.5))


# --------------------------------------------------------------------------- #
# Outcome creation + resolution                                               #
# --------------------------------------------------------------------------- #
def create_pending_outcome(
    db, stored: StoredReport, report: FinalReport
) -> ReportOutcome | None:
    """Snapshot a stored report as a pending outcome for later resolution."""
    rec = report.recommendation
    if rec is None or rec.stance not in _STANCES:
        return None
    features = dict(rec.confidence_features or {})
    features["agent_confidences"] = rec.agent_confidences or {}
    prior = float(features.get("prior_confidence", rec.confidence))
    outcome = ReportOutcome(
        stored_report_id=stored.id,
        ticker=report.ticker,
        stance=rec.stance,
        predicted_confidence=rec.confidence,
        prior_confidence=prior,
        features_json=json.dumps(features, default=str),
        prediction_date=stored.created_at or datetime.now(timezone.utc),
        horizon_days=settings.calibration_horizon_days,
        benchmark=settings.calibration_benchmark,
        band_pct=settings.calibration_band_pct,
        status="pending",
    )
    db.add(outcome)
    db.commit()
    return outcome


def _period_covering(days: int) -> str:
    for limit, period in ((25, "1mo"), (80, "3mo"), (170, "6mo"),
                          (350, "1y"), (700, "2y"), (1800, "5y")):
        if days <= limit:
            return period
    return "max"


def _forward_return(
    prices: PriceHistoryProvider, ticker: str, start: datetime, horizon: int,
    cache: dict,
) -> float | None:
    """Total return from the first trading day on/after `start` to +horizon rows.

    Returns None when the forward window isn't complete yet (stay pending) or
    the price feed is unavailable. No lookahead: the window is strictly after
    the prediction date.
    """
    start_str = start.date().isoformat()
    span_days = (datetime.now(timezone.utc) - start).days + 5
    period = _period_covering(span_days)
    key = (ticker.upper(), period)
    if key not in cache:
        try:
            cache[key] = prices.get_history(ticker, period=period)
        except Exception as exc:  # noqa: BLE001 — price feed best-effort
            logger.info("calibration: history for %s unavailable: %s", ticker, exc)
            cache[key] = None
    hist = cache[key]
    if hist is None or not hist.closes:
        return None
    dates, closes = hist.dates, hist.closes
    i0 = next((i for i, d in enumerate(dates) if d >= start_str), None)
    if i0 is None or i0 + horizon >= len(closes):
        return None  # forward window not complete yet
    start_px, end_px = closes[i0], closes[i0 + horizon]
    if not start_px:
        return None
    return end_px / start_px - 1.0


def backfill_outcomes(prices: PriceHistoryProvider, *, db=None) -> int:
    """Resolve pending outcomes whose horizon has elapsed. Returns count resolved."""
    from app.db import SessionLocal

    own = db is None
    db = db or SessionLocal()
    resolved = 0
    cache: dict = {}
    try:
        pending = db.scalars(
            select(ReportOutcome).where(ReportOutcome.status == "pending")
        ).all()
        now = datetime.now(timezone.utc)
        for o in pending:
            pred = o.prediction_date
            if pred.tzinfo is None:
                pred = pred.replace(tzinfo=timezone.utc)
            # Cheap gate: H trading days span at least ~1.4× that in calendar days.
            if (now - pred).days < int(o.horizon_days * 1.4) + 1:
                continue
            tr = _forward_return(prices, o.ticker, pred, o.horizon_days, cache)
            br = _forward_return(prices, o.benchmark, pred, o.horizon_days, cache)
            if tr is None or br is None:
                continue
            o.ticker_return = round(tr, 6)
            o.benchmark_return = round(br, 6)
            o.excess_return = round(tr - br, 6)
            o.correct = label_outcome(o.stance, tr, br, o.band_pct / 100.0)
            o.status = "resolved"
            o.resolved_at = now
            resolved += 1
        db.commit()
    finally:
        if own:
            db.close()
    if resolved:
        logger.info("calibration: resolved %d outcome(s)", resolved)
    return resolved


# --------------------------------------------------------------------------- #
# Fitting + reporting                                                         #
# --------------------------------------------------------------------------- #
def _resolved(db) -> list[ReportOutcome]:
    return list(db.scalars(
        select(ReportOutcome).where(
            ReportOutcome.status == "resolved",
            ReportOutcome.correct.is_not(None),
        )
    ))


def refit(*, db=None) -> CalibrationFit | None:
    """Fit a new Platt calibration from resolved outcomes; store it active.

    No-op (returns None) below `calibration_min_samples` — cold start keeps the
    hand-tuned prior. Deactivates any previous fit.
    """
    from app.db import SessionLocal

    own = db is None
    db = db or SessionLocal()
    try:
        rows = _resolved(db)
        if len(rows) < settings.calibration_min_samples:
            return None
        priors = [r.prior_confidence for r in rows]
        labels = [1 if r.correct else 0 for r in rows]
        params = fit_platt(priors, labels)
        cal = Calibrator(params, n=len(rows))
        brier = brier_score(
            [(cal.apply(p), y) for p, y in zip(priors, labels)]
        )
        through = max(
            (r.resolved_at for r in rows if r.resolved_at), default=None
        )
        db.execute(
            CalibrationFit.__table__.update()
            .where(CalibrationFit.active.is_(True))
            .values(active=False)
        )
        fit = CalibrationFit(
            method="platt",
            params_json=json.dumps(params),
            n_samples=len(rows),
            brier=brier,
            through_date=through.date().isoformat() if through else None,
            active=True,
        )
        db.add(fit)
        db.commit()
        logger.info(
            "calibration: refit on %d outcomes (brier=%.4f, w1=%.3f)",
            len(rows), brier or 0.0, params["w1"],
        )
        _CACHE["at"] = 0.0  # invalidate the process cache
        return fit
    finally:
        if own:
            db.close()


# Process-wide cache of the active calibrator (refreshed on a TTL / after refit).
_CACHE: dict = {"at": 0.0, "cal": None}
_CACHE_TTL = 300.0


def get_active_calibrator() -> Calibrator | None:
    """Cached load of the active fit. Returns None on cold start / any error."""
    now = time.time()
    if now - _CACHE["at"] < _CACHE_TTL:
        return _CACHE["cal"]
    cal: Calibrator | None = None
    try:
        from app.db import SessionLocal

        db = SessionLocal()
        try:
            fit = db.scalar(
                select(CalibrationFit).where(CalibrationFit.active.is_(True))
                .order_by(CalibrationFit.created_at.desc())
            )
            if fit is not None:
                cal = Calibrator(
                    json.loads(fit.params_json), n=fit.n_samples,
                    through=fit.through_date,
                )
                if not cal.ready:
                    cal = None
        finally:
            db.close()
    except Exception as exc:  # noqa: BLE001 — never break a run over calibration
        logger.info("calibration: could not load active fit: %s", exc)
        cal = None
    _CACHE["at"] = now
    _CACHE["cal"] = cal
    return cal


def calibration_report(db) -> dict:
    """Aggregate calibration metrics for the API / UI."""
    from sqlalchemy import func

    rows = _resolved(db)
    n_pending = db.scalar(
        select(func.count(ReportOutcome.id)).where(ReportOutcome.status == "pending")
    ) or 0

    pairs = [(r.predicted_confidence, 1 if r.correct else 0) for r in rows]
    prior_pairs = [(r.prior_confidence, 1 if r.correct else 0) for r in rows]

    # Per-agent slice: for each agent that contributed, mean stated confidence
    # vs observed hit rate — "news at 0.80 is right 55% of the time".
    per_agent: dict[str, list[tuple[float, int]]] = {}
    for r in rows:
        try:
            feats = json.loads(r.features_json)
            confs = feats.get("agent_confidences", {})
        except (ValueError, TypeError):
            confs = {}
        y = 1 if r.correct else 0
        for agent, conf in confs.items():
            per_agent.setdefault(agent, []).append((float(conf), y))
    per_agent_out = [
        {
            "agent": a,
            "mean_confidence": round(sum(c for c, _ in v) / len(v), 4),
            "hit_rate": round(sum(y for _, y in v) / len(v), 4),
            "count": len(v),
        }
        for a, v in sorted(per_agent.items())
    ]

    active = db.scalar(
        select(CalibrationFit).where(CalibrationFit.active.is_(True))
        .order_by(CalibrationFit.created_at.desc())
    )
    return {
        "n_resolved": len(rows),
        "n_pending": int(n_pending),
        "horizon_days": settings.calibration_horizon_days,
        "benchmark": settings.calibration_benchmark,
        "band_pct": settings.calibration_band_pct,
        "brier": brier_score(pairs),
        "brier_prior": brier_score(prior_pairs),
        "reliability": reliability_curve(pairs),
        "per_agent": per_agent_out,
        "fit": None if active is None else {
            "method": active.method,
            "n_samples": active.n_samples,
            "brier": active.brier,
            "through_date": active.through_date,
            "created_at": active.created_at.isoformat() if active.created_at else None,
        },
    }
