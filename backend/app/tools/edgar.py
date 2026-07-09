"""Fundamentals from SEC EDGAR (companyfacts XBRL API).

Free, keyless, and authoritative — the numbers come straight from filed
10-Ks. SEC fair-access rules require a descriptive User-Agent with a contact
address (see `settings.sec_user_agent`).

Limitations: US filers only; we read annual (10-K) facts, so figures can lag
the latest quarter. Both are acceptable for Phase 2.
"""
from __future__ import annotations

import logging
import time

import httpx

from app.config import settings
from app.models import Financials
from app.tools.base import ToolError, ToolTimeoutError

logger = logging.getLogger("edgar")

_TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"

# XBRL tag preference order per concept (filers vary in which tag they use).
_REVENUE_TAGS = [
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
]
_NET_INCOME_TAGS = ["NetIncomeLoss", "ProfitLoss"]
_DEBT_TAGS = ["LongTermDebt", "LongTermDebtNoncurrent"]
_EQUITY_TAGS = [
    "StockholdersEquity",
    "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
]
# Operating-statistics tags (comps-analysis methodology: margins, FCF).
# Not all filers report every tag (e.g. many omit GrossProfit) — fields stay
# None and the agents degrade gracefully.
_GROSS_PROFIT_TAGS = ["GrossProfit"]
_OPERATING_INCOME_TAGS = ["OperatingIncomeLoss"]
_OCF_TAGS = [
    "NetCashProvidedByUsedInOperatingActivities",
    "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
]
_CAPEX_TAGS = [
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "PaymentsToAcquireProductiveAssets",
]
_CASH_TAGS = [
    "CashAndCashEquivalentsAtCarryingValue",
    "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
]

# Ticker→CIK map cache (the file is ~1 MB and changes rarely).
_MAP_CACHE: dict = {"at": 0.0, "map": {}}
_MAP_TTL = 24 * 3600

# Extracted-financials cache: the valuation agent re-reads the same figures
# right after the financials agent within a single run.
_FIN_CACHE: dict[str, tuple[float, Financials]] = {}
_FIN_TTL = 3600


class SecEdgarFinancials:
    name = "sec-edgar"

    def __init__(self, timeout: float = 20.0) -> None:
        self._timeout = timeout
        self._headers = {"User-Agent": settings.sec_user_agent}

    def get_financials(self, ticker: str) -> Financials:
        ticker = ticker.strip().upper()
        hit = _FIN_CACHE.get(ticker)
        if hit and (time.time() - hit[0]) < _FIN_TTL:
            return hit[1]

        cik = self._lookup_cik(ticker)
        if cik is None:
            raise ToolError(f"{ticker} not found in SEC EDGAR (non-US filer?).")

        facts_url = _FACTS_URL.format(cik=cik)
        data = self._get_json(facts_url)
        gaap = (data.get("facts") or {}).get("us-gaap") or {}
        if not gaap:
            raise ToolError(f"No US-GAAP facts for {ticker} in EDGAR.")

        revenue = _annual_series(gaap, _REVENUE_TAGS)
        net_income = _annual_series(gaap, _NET_INCOME_TAGS)
        debt = _annual_series(gaap, _DEBT_TAGS)
        equity = _annual_series(gaap, _EQUITY_TAGS)
        gross_profit = _annual_series(gaap, _GROSS_PROFIT_TAGS)
        op_income = _annual_series(gaap, _OPERATING_INCOME_TAGS)
        ocf = _annual_series(gaap, _OCF_TAGS)
        capex = _annual_series(gaap, _CAPEX_TAGS)
        cash = _annual_series(gaap, _CASH_TAGS)

        if not revenue and not net_income:
            raise ToolError(f"Could not extract annual figures for {ticker}.")

        fin = Financials(
            ticker=ticker,
            cik=f"{cik:010d}",
            company=data.get("entityName"),
            fiscal_year_end=revenue[-1][0] if revenue else None,
            revenue=revenue[-1][1] if revenue else None,
            revenue_prior=revenue[-2][1] if len(revenue) > 1 else None,
            net_income=net_income[-1][1] if net_income else None,
            net_income_prior=net_income[-2][1] if len(net_income) > 1 else None,
            gross_profit=gross_profit[-1][1] if gross_profit else None,
            operating_income=op_income[-1][1] if op_income else None,
            operating_cash_flow=ocf[-1][1] if ocf else None,
            capex=capex[-1][1] if capex else None,
            cash_and_equivalents=cash[-1][1] if cash else None,
            total_debt=debt[-1][1] if debt else None,
            stockholders_equity=equity[-1][1] if equity else None,
            source=facts_url,
        )
        _FIN_CACHE[ticker] = (time.time(), fin)
        return fin

    # -- internals ----------------------------------------------------------
    def _lookup_cik(self, ticker: str) -> int | None:
        now = time.time()
        if not _MAP_CACHE["map"] or (now - _MAP_CACHE["at"]) > _MAP_TTL:
            raw = self._get_json(_TICKER_MAP_URL)
            _MAP_CACHE["map"] = {
                v["ticker"].upper(): int(v["cik_str"]) for v in raw.values()
            }
            _MAP_CACHE["at"] = now
        return _MAP_CACHE["map"].get(ticker)

    def _get_json(self, url: str) -> dict:
        # Phase 2.3: SEC fair-access requires a real contact address. Refuse
        # rather than hammer EDGAR with the placeholder UA (which they may
        # block anyway); the financials agent turns this into a flag.
        if "set SEC_USER_AGENT" in settings.sec_user_agent:
            raise ToolError(
                "SEC_USER_AGENT is not configured (still the placeholder). "
                "Set it to 'AppName/version (you@example.com)' in .env to "
                "enable SEC EDGAR fundamentals."
            )
        try:
            resp = httpx.get(url, headers=self._headers, timeout=self._timeout)
        except httpx.TimeoutException as exc:
            raise ToolTimeoutError(f"EDGAR request timed out: {exc}") from exc
        except httpx.HTTPError as exc:
            raise ToolError(f"EDGAR request failed: {exc}") from exc
        if resp.status_code == 429:
            raise ToolError("SEC EDGAR is rate-limiting requests; try again shortly.")
        if resp.status_code != 200:
            raise ToolError(f"EDGAR error {resp.status_code} for {url}")
        return resp.json()


def _annual_series(gaap: dict, tags: list[str]) -> list[tuple[str, float]]:
    """Return [(end_date, value), ...] oldest→newest from annual 10-K facts.

    Tries tags in preference order; first tag with usable data wins.
    """
    for tag in tags:
        units = (gaap.get(tag) or {}).get("units") or {}
        rows = units.get("USD") or []
        by_end: dict[str, float] = {}
        for r in rows:
            if r.get("form") != "10-K" or r.get("fp") != "FY":
                continue
            end, val = r.get("end"), r.get("val")
            if end is None or val is None:
                continue
            # Duration facts (revenue/income) must cover a full year, not a quarter.
            start = r.get("start")
            if start is not None:
                try:
                    span = (
                        time.mktime(time.strptime(end, "%Y-%m-%d"))
                        - time.mktime(time.strptime(start, "%Y-%m-%d"))
                    ) / 86400
                    if span < 300:
                        continue
                except ValueError:
                    continue
            by_end[end] = float(val)  # later rows (restatements) overwrite
        if by_end:
            return sorted(by_end.items())
    return []
