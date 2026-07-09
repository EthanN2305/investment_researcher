"""Auth: bcrypt password hashing + JWT bearer tokens.

Two FastAPI dependencies:
  get_current_user   — 401 if no/invalid token (protected CRUD endpoints)
  get_optional_user  — None if no token (research endpoint works logged out)
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.db_models import User

_ALGORITHM = "HS256"
_bearer = HTTPBearer(auto_error=False)

# --- Phase 2.1: per-email login brute-force lockout ---------------------------
# In-process (per-worker) record of recent failed-login timestamps per email.
# Complements the per-IP rate limit: an attacker rotating IPs against one
# account still trips this. Fine at single-node scale; move to Redis for HA.
_login_failures: dict[str, list[float]] = defaultdict(list)
_login_lock = threading.Lock()


def _prune(times: list[float], window: float) -> list[float]:
    cutoff = time.time() - window
    return [t for t in times if t >= cutoff]


def login_is_locked(email: str) -> bool:
    if not settings.rate_limit_enabled:
        return False
    window = settings.login_lockout_minutes * 60
    with _login_lock:
        times = _prune(_login_failures.get(email, []), window)
        _login_failures[email] = times
        return len(times) >= settings.login_max_failures


def record_login_failure(email: str) -> None:
    window = settings.login_lockout_minutes * 60
    with _login_lock:
        times = _prune(_login_failures.get(email, []), window)
        times.append(time.time())
        _login_failures[email] = times


def clear_login_failures(email: str) -> None:
    with _login_lock:
        _login_failures.pop(email, None)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


def create_access_token(user_id: int) -> str:
    expires = datetime.now(timezone.utc) + timedelta(
        minutes=settings.jwt_expire_minutes
    )
    payload = {"sub": str(user_id), "exp": expires}
    return jwt.encode(payload, settings.jwt_secret, algorithm=_ALGORITHM)


def _decode_user_id(token: str) -> int | None:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[_ALGORITHM])
        return int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User | None:
    if credentials is None:
        return None
    user_id = _decode_user_id(credentials.credentials)
    if user_id is None:
        return None
    return db.get(User, user_id)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    user_id = _decode_user_id(credentials.credentials)
    user = db.get(User, user_id) if user_id is not None else None
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")
    return user
