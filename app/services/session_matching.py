"""Match ingest sessions to existing campaign sessions by title and date."""

from __future__ import annotations

from typing import Optional

from sqlmodel import Session, select

from app.deps import parse_session_date
from app.models import SessionModel
from app.services.text_similarity import normalize_text


def session_titles_match(left: Optional[str], right: Optional[str]) -> bool:
    return normalize_text(left or "") == normalize_text(right or "")


def session_dates_match(left: Optional[str], right: Optional[str]) -> bool:
    left_parsed = parse_session_date(left)
    right_parsed = parse_session_date(right)
    if left_parsed and right_parsed:
        return left_parsed == right_parsed
    return normalize_text(left or "") == normalize_text(right or "")


def find_matching_session(
    db: Session,
    campaign_id: int,
    title: str,
    session_date: str,
) -> Optional[SessionModel]:
    title = (title or "").strip()
    if not title:
        return None
    sessions = db.exec(select(SessionModel).where(SessionModel.campaign_id == campaign_id)).all()
    for session in sessions:
        if session_titles_match(session.title, title) and session_dates_match(session.date, session_date):
            return session
    return None
