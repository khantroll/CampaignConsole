"""Default-deny authentication, campaign authorization, and CSRF middleware."""

import re
import secrets
from urllib.parse import parse_qs

from fastapi import Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from sqlmodel import Session, select

import app.database as database
from app.auth import SESSION_COOKIE, csrf_token_for_session, get_campaign_membership, resolve_session
from app.models import User

_CAMPAIGN_RE = re.compile(r"^/campaigns/(\d+)(?:/|$)")
_PUBLIC_EXACT = {"/login", "/bootstrap", "/favicon.ico"}
_ADMIN_PREFIXES = ("/admin/", "/settings/", "/llm/", "/debug/")


async def _read_body(receive):
    chunks = []
    while True:
        message = await receive()
        if message["type"] != "http.request":
            continue
        chunks.append(message.get("body", b""))
        if not message.get("more_body", False):
            break
    return b"".join(chunks)


def _csrf_from_body(body: bytes, content_type: str):
    if not body:
        return None
    if content_type.startswith("application/x-www-form-urlencoded"):
        values = parse_qs(body.decode("utf-8", errors="replace")).get("_csrf")
        return values[0] if values else None
    if content_type.startswith("multipart/form-data"):
        match = re.search(br'name="_csrf"\r\n(?:[^\r\n]*\r\n)*\r\n([^\r\n]+)', body)
        return match.group(1).decode("utf-8", errors="replace") if match else None
    return None


class AuthMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        path = request.url.path
        method = request.method.upper()
        public = path in _PUBLIC_EXACT or path.startswith("/static/")

        with Session(database.engine) as db:
            any_user = db.exec(select(User.id).limit(1)).first()

            if not any_user:
                if path.startswith("/static/") or path == "/bootstrap":
                    await self.app(scope, receive, send)
                    return
                response = (
                    RedirectResponse("/bootstrap", status_code=303)
                    if method in {"GET", "HEAD"}
                    else PlainTextResponse("Initial administrator setup is required.", status_code=403)
                )
                await response(scope, receive, send)
                return

            raw_token = request.cookies.get(SESSION_COOKIE)
            app_session, user = resolve_session(db, raw_token)
            if user:
                request.state.current_user = user
                request.state.app_session = app_session
                request.state.csrf_token = csrf_token_for_session(raw_token)

            if public:
                await self.app(scope, receive, send)
                return

            if not user:
                if method in {"GET", "HEAD"}:
                    next_path = request.url.path + (("?" + request.url.query) if request.url.query else "")
                    response = RedirectResponse(f"/login?next={next_path}", status_code=303)
                else:
                    response = PlainTextResponse("Authentication required.", status_code=401)
                await response(scope, receive, send)
                return

            if user.must_change_password and path not in {"/account/password", "/logout"}:
                response = (
                    RedirectResponse("/account/password", status_code=303)
                    if method in {"GET", "HEAD"}
                    else PlainTextResponse("Password change required.", status_code=403)
                )
                await response(scope, receive, send)
                return

            if path.startswith(_ADMIN_PREFIXES) and not user.is_admin:
                await PlainTextResponse("Administrator access required.", status_code=403)(scope, receive, send)
                return

            match = _CAMPAIGN_RE.match(path)
            if match:
                membership = get_campaign_membership(db, user.id, int(match.group(1)))
                request.state.campaign_membership = membership
                if not membership or membership.role not in {"owner", "gm"}:
                    await PlainTextResponse("Campaign GM access denied.", status_code=403)(scope, receive, send)
                    return

            if method in {"POST", "PUT", "PATCH", "DELETE"}:
                body = await _read_body(receive)
                supplied = request.headers.get("x-csrf-token") or _csrf_from_body(
                    body, request.headers.get("content-type", "")
                )
                if not supplied or not secrets.compare_digest(str(supplied), request.state.csrf_token):
                    await PlainTextResponse("CSRF validation failed.", status_code=403)(scope, receive, send)
                    return
                sent = False
                async def replay_receive():
                    nonlocal sent
                    if sent:
                        return {"type": "http.request", "body": b"", "more_body": False}
                    sent = True
                    return {"type": "http.request", "body": body, "more_body": False}
                receive = replay_receive

        await self.app(scope, receive, send)
