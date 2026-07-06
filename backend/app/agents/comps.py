"""Peer Comparison Agent — how is this ticker priced relative to its peers?

Modeled on Anthropic's financial-services `comps-analysis` skill: a company's
multiple means little in isolation; the peer group median and range tell you
whether it trades rich or cheap. Quartile/median benchmarking is the skill's
core statistical convention ("median and quartiles reveal more than average").

Division of labor mirrors the rest of the project:
- The LLM does *judgment only* — naming 3-5 comparable public companies
  (peer selection is qualitative; the skill's rule is "better to have 3
  perfect comps than 6 questionable ones").
- All numbers are fetched live from the market-data provider and all math
  (median, premium/discount, range position) is deterministic — the LLM
  never supplies a figure.

Degrades gracefully: an LLM provider without `suggest_peers`, no usable
peers, or too few peer P/Es each produce a flag instead of a failure.
"""
from __future__ import annotations

import re

from app.models import AgentReport, Claim, MarketData
from app.tools.base import MarketDataProvider, ToolError

AGENT_ID = "comps"

MAX_PEERS = 5
MIN_PEERS_FOR_STATS = 2
_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


def _median(values: list[float]) -> float:
    s = sorted(values)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2


class PeerComparisonAgent:
    def __init__(self, market: MarketDataProvider, llm) -> None:
        self._market = market
        self._llm = llm

    def run(self, ticker: str) -> AgentReport:
        claims: list[Claim] = []
        flags: list[str] = []

        md: MarketData = self._market.get_market_data(ticker)

        suggest = getattr(self._llm, "suggest_peers", None)
        if suggest is None:
            return AgentReport(agent=AGENT_ID, flags=["comps_llm_unsupported"])
        try:
            raw = suggest(ticker, md.sector, md.industry)
        except ToolError:
            return AgentReport(agent=AGENT_ID, flags=["comps_peer_selection_failed"])

        peer_symbols = self._clean_peers(ticker, raw)
        if not peer_symbols:
            return AgentReport(agent=AGENT_ID, flags=["comps_no_peers"])

        peers: list[MarketData] = []
        for sym in peer_symbols:
            try:
                peers.append(self._market.get_market_data(sym))
            except ToolError:
                continue  # a bad/unfetchable peer just shrinks the group
        if not peers:
            return AgentReport(agent=AGENT_ID, flags=["comps_no_peer_data"])

        group = ", ".join(p.ticker for p in peers)
        claims.append(Claim(
            claim=f"Peer group for {ticker}: {group} "
                  f"({md.sector or 'sector n/a'} / {md.industry or 'industry n/a'}).",
            evidence=f"peers selected by analyst-LLM for comparability; "
                     f"quotes fetched live for {len(peers)} of "
                     f"{len(peer_symbols)} suggested",
            source=md.source, confidence=0.7,
        ))

        claims += self._pe_benchmark(ticker, md, peers, flags)
        claims += self._size_context(ticker, md, peers)

        if not claims:
            flags.append("no_comps_claims")
        return AgentReport(agent=AGENT_ID, claims=claims, flags=flags)

    # -- internals ---------------------------------------------------------
    @staticmethod
    def _clean_peers(ticker: str, raw) -> list[str]:
        """Validate LLM-suggested symbols: format-check, dedupe, cap count."""
        out: list[str] = []
        for item in raw or []:
            sym = str(item).strip().upper()
            if sym == ticker.upper() or not _TICKER_RE.match(sym):
                continue
            if sym not in out:
                out.append(sym)
        return out[:MAX_PEERS]

    @staticmethod
    def _pe_benchmark(
        ticker: str, md: MarketData, peers: list[MarketData], flags: list[str]
    ) -> list[Claim]:
        peer_pes = [(p.ticker, p.pe_ratio) for p in peers if p.pe_ratio and p.pe_ratio > 0]
        if md.pe_ratio is None or md.pe_ratio <= 0:
            flags.append("comps_target_pe_unavailable")
            return []
        if len(peer_pes) < MIN_PEERS_FOR_STATS:
            flags.append("comps_insufficient_peer_pes")
            return []

        values = [pe for _, pe in peer_pes]
        med = _median(values)
        lo_sym, lo = min(peer_pes, key=lambda t: t[1])
        hi_sym, hi = max(peer_pes, key=lambda t: t[1])
        rel = (md.pe_ratio - med) / med
        stance = (
            f"a {rel:.0%} premium to" if rel > 0.05
            else f"a {abs(rel):.0%} discount to" if rel < -0.05
            else "roughly in line with"
        )
        detail = "; ".join(f"{s}={v:.1f}" for s, v in peer_pes)
        claims = [Claim(
            claim=f"{ticker} trades at {stance} its peer-median trailing P/E "
                  f"({md.pe_ratio:.1f} vs median {med:.1f} across "
                  f"{len(peer_pes)} peers).",
            evidence=f"target_pe={md.pe_ratio:.2f}; peer P/Es: {detail}; "
                     f"median={med:.2f}",
            source=md.source, confidence=0.8,
        )]

        if md.pe_ratio < lo:
            pos = f"below the cheapest peer ({lo_sym} at {lo:.1f})"
        elif md.pe_ratio > hi:
            pos = f"above the richest peer ({hi_sym} at {hi:.1f})"
        else:
            pos = (f"within the peer range ({lo_sym} {lo:.1f} – "
                   f"{hi_sym} {hi:.1f})")
        claims.append(Claim(
            claim=f"{ticker}'s earnings multiple sits {pos}.",
            evidence=f"target_pe={md.pe_ratio:.2f}; "
                     f"peer range [{lo:.2f}, {hi:.2f}]",
            source=md.source, confidence=0.8,
        ))
        return claims

    @staticmethod
    def _size_context(
        ticker: str, md: MarketData, peers: list[MarketData]
    ) -> list[Claim]:
        caps = [(p.ticker, p.market_cap) for p in peers if p.market_cap]
        if md.market_cap is None or len(caps) < MIN_PEERS_FOR_STATS:
            return []
        larger = sum(1 for _, c in caps if c > md.market_cap)
        rank = larger + 1
        return [Claim(
            claim=f"{ticker} ranks #{rank} of {len(caps) + 1} in its peer "
                  f"group by market capitalization.",
            evidence=f"target_cap={md.market_cap:,.0f}; peers: "
                     + "; ".join(f"{s}={c:,.0f}" for s, c in caps),
            source=md.source, confidence=0.85,
        )]
