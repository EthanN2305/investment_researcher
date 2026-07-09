"""Recommendation Agent — final synthesis.

Consumes ONLY the merged structured claims from the other agents (their
AgentReports), never free text. If the LLM is unavailable the run still
completes, with a flag and a data-only fallback summary.

Phase 4: the overall confidence is *derived* from the underlying agents'
claim confidences — reasoned over, not flat-averaged:

  1. Each agent's mean claim confidence is weighted by (a) how much evidence
     it produced (sqrt of claim count, capped) and (b) how deterministic its
     source is (SEC filings > LLM-extracted news).
  2. Failed/empty agents subtract a coverage penalty — missing evidence should
     lower conviction even if the surviving agents agree.
  3. Disagreement between agents (spread of their mean confidences) subtracts
     a further penalty — unanimity is worth more than a high average.
  4. The result is blended with the synthesis LLM's own self-estimate, which
     captures qualitative judgement the arithmetic can't.

The derivation is surfaced in `agent_confidences` + `confidence_rationale`
so the UI can show *why* the number is what it is.
"""
from __future__ import annotations

from app.models import AgentReport, Recommendation
from app.tools.base import AgentLLMProvider, ToolError

AGENT_ID = "recommendation"

# Source-reliability weights: deterministic agents (SEC EDGAR math, price-series
# indicators) earn more trust than LLM-extracted news claims.
_AGENT_WEIGHTS = {
    "financials": 1.2,
    "valuation": 1.15,
    "technicals": 1.0,
    "risk": 1.05,   # deterministic beta/correlation math on price series
    "portfolio": 0.9,
    "comps": 0.85,  # deterministic math, but the peer group is LLM-selected
    "news": 0.8,
}
_FAILED_AGENT_PENALTY = 0.07
_DISAGREEMENT_PENALTY = 0.25  # × spread of per-agent means
_LLM_BLEND = 0.4  # weight of the LLM's self-estimate in the final number
_MAX_COUNT_WEIGHT = 5  # claim-count weighting saturates here


def _derive_core(
    agent_reports: list[AgentReport], llm_confidence: float | None
) -> tuple[float, dict[str, float], dict[str, float], str]:
    """Core derivation → (prior_confidence, per_agent, features, rationale).

    `prior_confidence` is the hand-tuned derived score (clamped) BEFORE any
    fitted calibration — it's the feature the Phase 4 calibrator is fitted on,
    so calibration never feeds on its own output.
    """
    per_agent: dict[str, float] = {}
    weighted_sum = weight_total = 0.0
    failed: list[str] = []

    for r in agent_reports:
        if r.agent == AGENT_ID:
            continue
        if r.status != "ok" or not r.claims:
            failed.append(r.agent)
            continue
        mean = sum(c.confidence for c in r.claims) / len(r.claims)
        per_agent[r.agent] = round(mean, 3)
        weight = (
            _AGENT_WEIGHTS.get(r.agent, 1.0)
            * min(len(r.claims), _MAX_COUNT_WEIGHT) ** 0.5
        )
        weighted_sum += weight * mean
        weight_total += weight

    if not per_agent:
        return (
            0.1,
            {},
            {"prior_confidence": 0.1, "coverage_count": 0.0, "failed_count": float(len(failed))},
            "No agent produced usable claims, so confidence is minimal.",
        )

    evidence_conf = weighted_sum / weight_total
    parts = [
        f"Weighted evidence confidence across {len(per_agent)} agents: "
        f"{evidence_conf:.0%} (weighted by claim volume and source reliability)."
    ]

    penalty = 0.0
    if failed:
        penalty += _FAILED_AGENT_PENALTY * len(failed)
        parts.append(
            f"Reduced for missing coverage from: {', '.join(sorted(failed))}."
        )
    spread = 0.0
    if len(per_agent) >= 2:
        spread = max(per_agent.values()) - min(per_agent.values())
        if spread > 0.15:
            penalty += _DISAGREEMENT_PENALTY * spread
            parts.append(
                f"Reduced for disagreement between agents (spread {spread:.0%})."
            )

    overall = evidence_conf - penalty
    if llm_confidence is not None:
        overall = (1 - _LLM_BLEND) * overall + _LLM_BLEND * llm_confidence
        parts.append(
            f"Blended with the synthesis model's own estimate ({llm_confidence:.0%})."
        )
    prior = round(max(0.05, min(0.95, overall)), 3)
    features = {
        "prior_confidence": prior,
        "evidence_conf": round(evidence_conf, 4),
        "coverage_count": float(len(per_agent)),
        "failed_count": float(len(failed)),
        "disagreement_spread": round(spread, 4),
        "llm_self_estimate": (
            round(llm_confidence, 4) if llm_confidence is not None else -1.0
        ),
    }
    return prior, per_agent, features, " ".join(parts)


def confidence_features(
    agent_reports: list[AgentReport], llm_confidence: float | None
) -> dict[str, float]:
    """The raw derivation features, persisted for the Phase 4 calibration loop."""
    return _derive_core(agent_reports, llm_confidence)[2]


def derive_confidence(
    agent_reports: list[AgentReport],
    llm_confidence: float | None,
    calibrator=None,
) -> tuple[float, dict[str, float], str]:
    """Reason over per-agent claim confidences → (overall, per-agent, rationale).

    Phase 4: when a fitted `calibrator` is supplied (and ready), the hand-tuned
    prior score is mapped through empirically-fitted parameters and the
    rationale says so. Without one, the pipeline cold-starts on the hand-tuned
    prior — identical to pre-Phase-4 behavior. The [0.05, 0.95] clamp is always
    enforced: never claim certainty.
    """
    prior, per_agent, features, rationale = _derive_core(agent_reports, llm_confidence)
    if calibrator is not None and getattr(calibrator, "ready", False) and per_agent:
        overall = calibrator.apply(prior, features)
        rationale = (
            f"{rationale} Calibrated on {calibrator.n} resolved reports"
            f"{f' through {calibrator.through}' if calibrator.through else ''}."
        )
    else:
        overall = prior
    overall = max(0.05, min(0.95, overall))
    return round(overall, 3), per_agent, rationale


class RecommendationAgent:
    def __init__(self, llm: AgentLLMProvider, calibrator_provider=None) -> None:
        self._llm = llm
        # Optional zero-arg callable returning the active Calibrator (or None).
        # Injected in build_graph so the agent stays free of DB/session coupling;
        # tests construct without it → cold-start (hand-tuned) behavior.
        self._calibrator_provider = calibrator_provider

    def run(
        self,
        ticker: str,
        agent_reports: list[AgentReport],
        lens: str | None,
        flags: list[str],
    ) -> tuple[Recommendation, list[str]]:
        usable = [r for r in agent_reports if r.claims]
        if not usable:
            return (
                Recommendation(
                    summary=f"No agent produced claims for {ticker}; "
                            "no synthesis is possible.",
                    stance="neutral",
                    confidence=0.1,
                    confidence_rationale="No claims to reason over.",
                ),
                ["no_claims_to_synthesize"],
            )
        try:
            rec = self._llm.recommend(ticker, usable, lens, flags)
            rec_flags: list[str] = []
            llm_conf: float | None = rec.confidence
        except ToolError:
            n = sum(len(r.claims) for r in usable)
            rec = Recommendation(
                summary=f"Synthesis unavailable (LLM error). {n} structured "
                        f"claims from {len(usable)} agents are shown below.",
                stance="neutral",
            )
            rec_flags = ["recommendation_llm_failed"]
            llm_conf = None  # no self-estimate to blend

        calibrator = (
            self._calibrator_provider() if self._calibrator_provider else None
        )
        # Phase 4: derived (and, when fitted, calibrated) confidence.
        overall, per_agent, rationale = derive_confidence(
            agent_reports, llm_conf, calibrator
        )
        rec.confidence = overall
        rec.agent_confidences = per_agent
        rec.confidence_rationale = rationale
        rec.confidence_features = confidence_features(agent_reports, llm_conf)
        return rec, rec_flags
