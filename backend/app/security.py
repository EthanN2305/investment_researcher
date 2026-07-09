"""Startup security checks (Phase 2.2).

Called once at import time from `main.py`. In a non-dev environment the app
refuses to boot with the shipped default JWT secret (or any secret shorter
than 32 bytes), so a public deployment can't mint forgeable tokens with a
secret that's readable in the repo.
"""
from __future__ import annotations

import logging

from app.config import settings

logger = logging.getLogger("security")

# The value shipped in config.py's default. Must match exactly.
DEFAULT_JWT_SECRET = "dev-only-secret-change-me-via-dotenv-0123456789"
_MIN_SECRET_BYTES = 32


class InsecureConfigError(RuntimeError):
    """Raised at startup when a non-dev deployment is misconfigured."""


def check_startup_security() -> None:
    is_default = settings.jwt_secret == DEFAULT_JWT_SECRET
    too_short = len(settings.jwt_secret.encode()) < _MIN_SECRET_BYTES

    if settings.env != "dev":
        if is_default:
            raise InsecureConfigError(
                "Refusing to boot: ENV is not 'dev' but JWT_SECRET is still the "
                "shipped default. Set a strong JWT_SECRET (>=32 bytes) in .env."
            )
        if too_short:
            raise InsecureConfigError(
                "Refusing to boot: JWT_SECRET is shorter than 32 bytes. "
                "Generate one with `python -c \"import secrets; "
                "print(secrets.token_urlsafe(48))\"`."
            )
        return

    # dev: warn loudly but keep working so local setup stays frictionless.
    if is_default:
        logger.warning(
            "Using the DEFAULT JWT secret. Fine for local dev; set JWT_SECRET "
            "and ENV=prod before deploying (tokens are forgeable otherwise)."
        )
