"""Lightweight recommendation log (Phase 1 guardrail).

Appends each generated report to a JSONL file so recommendations can be
checked against outcomes later. Deliberately simple — no DB yet.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from app.models import ResearchReport

logger = logging.getLogger("logstore")
_LOG_PATH = Path(__file__).resolve().parent.parent / "recommendations_log.jsonl"


def log_report(report: ResearchReport) -> None:
    try:
        with _LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(report.model_dump_json() + "\n")
    except OSError as exc:
        logger.warning("could not write recommendation log: %s", exc)
