"""Sign-up / login endpoints. Email + password, JWT bearer tokens."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import (
    clear_login_failures,
    create_access_token,
    get_current_user,
    hash_password,
    login_is_locked,
    record_login_failure,
    verify_password,
)
from app.config import settings
from app.db import get_db
from app.db_models import User
from app.models import LoginRequest, SignupRequest, TokenResponse
from app.ratelimit import RateLimit

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/signup",
    response_model=TokenResponse,
    status_code=201,
    dependencies=[Depends(RateLimit(settings.rate_limit_signup, "signup"))],
)
def signup(req: SignupRequest, db: Session = Depends(get_db)) -> TokenResponse:
    email = req.email.strip().lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=409, detail="Email is already registered.")
    user = User(email=email, password_hash=hash_password(req.password))
    db.add(user)
    db.commit()
    return TokenResponse(access_token=create_access_token(user.id), email=user.email)


@router.post(
    "/login",
    response_model=TokenResponse,
    dependencies=[Depends(RateLimit(settings.rate_limit_login, "login"))],
)
def login(req: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    email = req.email.strip().lower()
    # Phase 2.1: per-email lockout stops credential stuffing that rotates IPs.
    if login_is_locked(email):
        raise HTTPException(
            status_code=429,
            detail="Too many failed logins for this account; try again later.",
        )
    user = db.scalar(select(User).where(User.email == email))
    # Same error for unknown email vs bad password — don't leak which.
    if user is None or not verify_password(req.password, user.password_hash):
        record_login_failure(email)
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    clear_login_failures(email)
    return TokenResponse(access_token=create_access_token(user.id), email=user.email)


@router.get("/me")
def me(user: User = Depends(get_current_user)) -> dict:
    return {"email": user.email, "created_at": user.created_at.isoformat()}
