"""Local user authentication, opaque sessions, CSRF helpers, and login throttling."""

from collections import defaultdict
from datetime import datetime, timedelta
import hashlib
import secrets
import time
from typing import Optional

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from argon2.low_level import Type
from fastapi import Request
from sqlmodel import Session, select

from app.models import AppSession, CampaignMembership, User
from app.utils.time import utc_now

SESSION_COOKIE = "campaign_console_session"
SESSION_DAYS = 7
LOGIN_WINDOW_SECONDS = 300
LOGIN_MAX_FAILURES = 5

_password_hasher = PasswordHasher(type=Type.ID)
_login_failures = defaultdict(list)


def normalize_username(username: str) -> str:
    return username.strip().casefold()


def hash_password(password: str) -> str:
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters.")
    return _password_hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def csrf_token_for_session(token: str) -> str:
    return hashlib.sha256(("csrf:" + token).encode("utf-8")).hexdigest()


def create_app_session(db: Session, user_id: int) -> tuple[AppSession, str]:
    raw_token = secrets.token_urlsafe(48)
    now = utc_now()
    record = AppSession(
        token_hash=hash_session_token(raw_token),
        user_id=user_id,
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(days=SESSION_DAYS),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record, raw_token


def _expired(expires_at: datetime) -> bool:
    now = utc_now()
    if expires_at.tzinfo is None:
        now = now.replace(tzinfo=None)
    return expires_at <= now


def resolve_session(db: Session, raw_token: Optional[str]) -> tuple[Optional[AppSession], Optional[User]]:
    if not raw_token:
        return None, None
    record = db.exec(select(AppSession).where(AppSession.token_hash == hash_session_token(raw_token))).first()
    if not record:
        return None, None
    if _expired(record.expires_at):
        db.delete(record)
        db.commit()
        return None, None
    user = db.get(User, record.user_id)
    if not user or not user.is_active:
        db.delete(record)
        db.commit()
        return None, None
    record.last_seen_at = utc_now()
    db.add(record)
    db.commit()
    return record, user


def invalidate_user_sessions(db: Session, user_id: int, except_session_id: Optional[int] = None) -> None:
    records = db.exec(select(AppSession).where(AppSession.user_id == user_id)).all()
    for record in records:
        if except_session_id is None or record.id != except_session_id:
            db.delete(record)
    db.commit()


def delete_session_for_token(db: Session, raw_token: Optional[str]) -> None:
    if not raw_token:
        return
    record = db.exec(select(AppSession).where(AppSession.token_hash == hash_session_token(raw_token))).first()
    if record:
        db.delete(record)
        db.commit()


def get_campaign_membership(db: Session, user_id: int, campaign_id: int) -> Optional[CampaignMembership]:
    return db.exec(select(CampaignMembership).where(
        CampaignMembership.user_id == user_id,
        CampaignMembership.campaign_id == campaign_id,
    )).first()


GM_CAMPAIGN_ROLES = {"owner", "gm"}


def user_can_manage_campaign(db: Session, user_id: int, campaign_id: int) -> bool:
    membership = get_campaign_membership(db, user_id, campaign_id)
    return bool(membership and membership.role in GM_CAMPAIGN_ROLES)


def user_can_create_campaign(db: Session, user: User) -> bool:
    if user.is_admin:
        return True
    membership = db.exec(
        select(CampaignMembership).where(
            CampaignMembership.user_id == user.id,
            CampaignMembership.role.in_(GM_CAMPAIGN_ROLES),
        )
    ).first()
    return membership is not None


def cookie_is_secure(request: Request) -> bool:
    forwarded = request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip().lower()
    return request.url.scheme == "https" or forwarded == "https"


def set_session_cookie(response, request: Request, raw_token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE, raw_token, max_age=SESSION_DAYS * 86400,
        httponly=True, secure=cookie_is_secure(request), samesite="lax", path="/",
    )


def clear_session_cookie(response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="lax")


def throttle_key(request: Request, username: str) -> str:
    host = request.client.host if request.client else "unknown"
    return f"{host}:{normalize_username(username)}"


def login_is_throttled(request: Request, username: str) -> bool:
    key = throttle_key(request, username)
    cutoff = time.monotonic() - LOGIN_WINDOW_SECONDS
    recent = [stamp for stamp in _login_failures[key] if stamp >= cutoff]
    _login_failures[key] = recent
    return len(recent) >= LOGIN_MAX_FAILURES


def record_login_failure(request: Request, username: str) -> None:
    _login_failures[throttle_key(request, username)].append(time.monotonic())


def clear_login_failures(request: Request, username: str) -> None:
    _login_failures.pop(throttle_key(request, username), None)


def clear_login_throttle_for_tests() -> None:
    _login_failures.clear()
