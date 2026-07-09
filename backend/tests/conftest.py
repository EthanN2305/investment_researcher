"""Test-suite environment setup.

Runs before any test module is imported, so it must set env vars that the
app reads at import time (settings are instantiated when app.config loads):

- RATE_LIMIT_ENABLED=false  — the suite hammers /auth and /research far past
  the production per-IP limits; throttling here would cause spurious failures.
- SCHEDULER_ENABLED=false    — no background APScheduler jobs during tests.

Only applies to pytest runs. The module-style tests (`python -m tests.foo`)
don't load conftest, but they don't spam rate-limited endpoints either.
"""
from __future__ import annotations

import os

os.environ.setdefault("RATE_LIMIT_ENABLED", "false")
os.environ.setdefault("SCHEDULER_ENABLED", "false")
