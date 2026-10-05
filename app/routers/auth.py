from typing import Optional

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from sqlmodel import Session, select

from app.auth import (
    SESSION_COOKIE,
    clear_login_failures,
    clear_session_cookie,
    create_app_session,
    delete_session_for_token,
    hash_password,
    invalidate_user_sessions,
    login_is_throttled,
    normalize_username,
    record_login_failure,
    set_session_cookie,
    verify_password,
)
from app.database import get_session
from app.deps import templates
from app.models import Campaign, CampaignMembership, PlayerCharacterNote, User
from app.utils.time import utc_now

router = APIRouter()
VALID_ROLES = {"owner", "gm", "player"}


def _safe_next(value: Optional[str]) -> str:
    if not value or not value.startswith("/") or value.startswith("//") or "://" in value:
        return "/"
    return value


def _default_landing_path(db: Session, user: User) -> str:
    if user.is_admin:
        return "/"
    roles = set(
        db.exec(
            select(CampaignMembership.role).where(CampaignMembership.user_id == user.id)
        ).all()
    )
    if roles and roles.issubset({"player"}):
        return "/player"
    return "/"


def _user_by_name(db: Session, username: str):
    return db.exec(select(User).where(User.username == normalize_username(username))).first()


@router.get("/bootstrap", response_class=HTMLResponse)
def bootstrap_form(request: Request, db: Session = Depends(get_session)):
    if db.exec(select(User.id).limit(1)).first():
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse("bootstrap.html", {"request": request, "message": None})


@router.post("/bootstrap")
def bootstrap(
    request: Request,
    username: str = Form(...),
    display_name: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_session),
):
    if db.exec(select(User.id).limit(1)).first():
        return PlainTextResponse("Bootstrap is no longer available.", status_code=403)
    normalized = normalize_username(username)
    if not normalized:
        return templates.TemplateResponse(
            "bootstrap.html", {"request": request, "message": "Username is required."}, status_code=400
        )
    try:
        password_hash = hash_password(password)
    except ValueError as exc:
        return templates.TemplateResponse(
            "bootstrap.html", {"request": request, "message": str(exc)}, status_code=400
        )

    user = User(
        username=normalized,
        display_name=display_name.strip() or normalized,
        password_hash=password_hash,
        is_admin=True,
        is_active=True,
        must_change_password=False,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    for campaign in db.exec(select(Campaign)).all():
        db.add(CampaignMembership(campaign_id=campaign.id, user_id=user.id, role="owner"))
    db.commit()

    _, raw_token = create_app_session(db, user.id)
    response = RedirectResponse(_default_landing_path(db, user), status_code=303)
    set_session_cookie(response, request, raw_token)
    return response


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request, next: str = Query("/"), db: Session = Depends(get_session)):
    if not db.exec(select(User.id).limit(1)).first():
        return RedirectResponse("/bootstrap", status_code=303)
    if getattr(request.state, "current_user", None):
        return RedirectResponse(_safe_next(next), status_code=303)
    return templates.TemplateResponse(
        "login.html", {"request": request, "message": None, "next_url": _safe_next(next)}
    )


@router.post("/login")
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form("/"),
    db: Session = Depends(get_session),
):
    if login_is_throttled(request, username):
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "message": "Too many failed login attempts. Try again later.",
                "next_url": _safe_next(next),
            },
            status_code=429,
        )
    user = _user_by_name(db, username)
    if not user or not user.is_active or not verify_password(user.password_hash, password):
        record_login_failure(request, username)
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "message": "Invalid username or password.",
                "next_url": _safe_next(next),
            },
            status_code=401,
        )

    clear_login_failures(request, username)
    user.last_login_at = utc_now()
    db.add(user)
    db.commit()
    _, raw_token = create_app_session(db, user.id)
    safe_next = _safe_next(next)
    target = (
        "/account/password"
        if user.must_change_password
        else (_default_landing_path(db, user) if safe_next == "/" else safe_next)
    )
    response = RedirectResponse(target, status_code=303)
    set_session_cookie(response, request, raw_token)
    return response


@router.post("/logout")
def logout(request: Request, db: Session = Depends(get_session)):
    delete_session_for_token(db, request.cookies.get(SESSION_COOKIE))
    response = RedirectResponse("/login", status_code=303)
    clear_session_cookie(response)
    return response


@router.get("/account/password", response_class=HTMLResponse)
def password_form(request: Request):
    return templates.TemplateResponse("change_password.html", {"request": request, "message": None})


@router.post("/account/password")
def change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    db: Session = Depends(get_session),
):
    user = db.get(User, request.state.current_user.id)
    if not user or not verify_password(user.password_hash, current_password):
        return templates.TemplateResponse(
            "change_password.html",
            {"request": request, "message": "Current password is incorrect."},
            status_code=400,
        )
    try:
        user.password_hash = hash_password(new_password)
    except ValueError as exc:
        return templates.TemplateResponse(
            "change_password.html", {"request": request, "message": str(exc)}, status_code=400
        )
    user.must_change_password = False
    user.updated_at = utc_now()
    db.add(user)
    db.commit()
    invalidate_user_sessions(db, user.id)
    _, raw_token = create_app_session(db, user.id)
    response = RedirectResponse(_default_landing_path(db, user), status_code=303)
    set_session_cookie(response, request, raw_token)
    return response


@router.get("/admin/users", response_class=HTMLResponse)
def admin_users(request: Request, db: Session = Depends(get_session)):
    users = db.exec(select(User).order_by(User.username)).all()
    return templates.TemplateResponse("admin_users.html", {"request": request, "users": users})


@router.post("/admin/users")
def admin_create_user(
    request: Request,
    username: str = Form(...),
    display_name: str = Form(...),
    email: str = Form(""),
    temporary_password: str = Form(...),
    is_admin: Optional[str] = Form(None),
    db: Session = Depends(get_session),
):
    normalized = normalize_username(username)
    if not normalized or _user_by_name(db, normalized):
        return PlainTextResponse("Username already exists or is invalid.", status_code=409)
    try:
        password_hash = hash_password(temporary_password)
    except ValueError as exc:
        return PlainTextResponse(str(exc), status_code=400)
    user = User(
        username=normalized,
        display_name=display_name.strip() or normalized,
        email=email.strip() or None,
        password_hash=password_hash,
        is_admin=bool(is_admin),
        is_active=True,
        must_change_password=True,
    )
    db.add(user)
    db.commit()
    return RedirectResponse("/admin/users", status_code=303)


@router.get("/admin/users/{user_id}", response_class=HTMLResponse)
def admin_user_edit(request: Request, user_id: int, db: Session = Depends(get_session)):
    user = db.get(User, user_id)
    if not user:
        return PlainTextResponse("User not found.", status_code=404)
    memberships = db.exec(
        select(CampaignMembership).where(CampaignMembership.user_id == user_id)
    ).all()
    campaigns = db.exec(select(Campaign).order_by(Campaign.name)).all()
    pcs = db.exec(select(PlayerCharacterNote).order_by(PlayerCharacterNote.character_name)).all()
    return templates.TemplateResponse(
        "admin_user_edit.html",
        {
            "request": request,
            "managed_user": user,
            "memberships": memberships,
            "campaigns": campaigns,
            "campaign_lookup": {c.id: c for c in campaigns},
            "pcs": pcs,
        },
    )


@router.post("/admin/users/{user_id}/status")
def admin_user_status(
    request: Request,
    user_id: int,
    active: Optional[str] = Form(None),
    db: Session = Depends(get_session),
):
    user = db.get(User, user_id)
    if not user:
        return PlainTextResponse("User not found.", status_code=404)
    user.is_active = bool(active)
    user.updated_at = utc_now()
    db.add(user)
    db.commit()
    if not user.is_active:
        invalidate_user_sessions(db, user.id)
    return RedirectResponse(f"/admin/users/{user_id}", status_code=303)


@router.post("/admin/users/{user_id}/reset-password")
def admin_reset_password(
    request: Request,
    user_id: int,
    temporary_password: str = Form(...),
    db: Session = Depends(get_session),
):
    user = db.get(User, user_id)
    if not user:
        return PlainTextResponse("User not found.", status_code=404)
    try:
        user.password_hash = hash_password(temporary_password)
    except ValueError as exc:
        return PlainTextResponse(str(exc), status_code=400)
    user.must_change_password = True
    user.updated_at = utc_now()
    db.add(user)
    db.commit()
    invalidate_user_sessions(db, user.id)
    return RedirectResponse(f"/admin/users/{user_id}", status_code=303)


@router.post("/admin/users/{user_id}/memberships")
def admin_membership(
    request: Request,
    user_id: int,
    campaign_id: int = Form(...),
    role: str = Form(...),
    player_character_id: str = Form(""),
    db: Session = Depends(get_session),
):
    user = db.get(User, user_id)
    campaign = db.get(Campaign, campaign_id)
    if not user or not campaign or role not in VALID_ROLES:
        return PlainTextResponse("Invalid membership.", status_code=400)

    pc_id = int(player_character_id) if player_character_id.isdigit() else None
    if pc_id is not None:
        pc = db.get(PlayerCharacterNote, pc_id)
        if not pc or pc.campaign_id != campaign_id:
            return PlainTextResponse(
                "Player character must belong to the selected campaign.", status_code=400
            )
    if role != "player":
        pc_id = None

    membership = db.exec(
        select(CampaignMembership).where(
            CampaignMembership.user_id == user_id,
            CampaignMembership.campaign_id == campaign_id,
        )
    ).first()
    if not membership:
        membership = CampaignMembership(campaign_id=campaign_id, user_id=user_id, role=role)
    membership.role = role
    membership.player_character_id = pc_id
    membership.updated_at = utc_now()
    db.add(membership)
    db.commit()
    return RedirectResponse(f"/admin/users/{user_id}", status_code=303)


@router.post("/admin/users/{user_id}/memberships/{membership_id}/delete")
def admin_membership_delete(
    request: Request,
    user_id: int,
    membership_id: int,
    db: Session = Depends(get_session),
):
    membership = db.get(CampaignMembership, membership_id)
    if membership and membership.user_id == user_id:
        db.delete(membership)
        db.commit()
    return RedirectResponse(f"/admin/users/{user_id}", status_code=303)
