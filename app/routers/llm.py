from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlmodel import Session, select

from app.database import get_session
from app.deps import templates
from app.llm import (
    generate,
    get_active_provider_or_none,
    get_configured_model,
    get_provider,
    llm_available,
    provider_available,
)
from app.services.env_config import MANAGED_KEYS, apply_env_to_process, get_llm_settings_for_form, update_env_file
from app.models import Campaign, SessionModel
from app.services.ai_workflow import run_future_prep_generation
from app.services.analysis import prep_overwrite_requires_confirmation
from app.services.mission_control_ui import mc_settings_context, with_mc
from app.services.provider_router import (
    PROVIDER_DISPLAY_NAMES,
    SMOKE_TEST_PROMPT,
    gemini_is_disabled,
    list_provider_diagnostics,
)

router = APIRouter()


def _parse_optional_session_id(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    cleaned = str(value).strip()
    if not cleaned:
        return None
    try:
        return int(cleaned)
    except ValueError:
        return None

OTHER_PROVIDER_FIELDS = [
    ("mistral", "MISTRAL_API_URL", "MISTRAL_API_KEY"),
    ("copilot", "COPILOT_API_URL", "COPILOT_API_KEY"),
    ("groq", "GROQ_API_URL", "GROQ_API_KEY"),
    ("deepseek", "DEEPSEEK_API_URL", "DEEPSEEK_API_KEY"),
]
EMBEDDING_PROVIDER_OPTIONS = ["local_fallback", "openai", "ollama"]

PROVIDER_TOGGLE_ORDER = [
    "openai",
    "gemini",
    "mistral",
    "groq",
    "deepseek",
    "claude",
    "ollama",
    "copilot",
]

PROVIDER_DESCRIPTIONS = {
    "openai": "OpenAI chat completions API.",
    "gemini": "Google Gemini generateContent API.",
    "mistral": "Mistral chat completions API.",
    "groq": "Fast Groq-hosted open models.",
    "deepseek": "DeepSeek chat completions API.",
    "claude": "Anthropic Claude messages API.",
    "ollama": "Local Ollama generate endpoint.",
    "copilot": "Custom OpenAI-compatible HTTP endpoint.",
}


def _provider_toggle_options(active_provider: Optional[str]) -> list:
    diagnostics = {row["provider"]: row for row in list_provider_diagnostics()}
    options = []
    for provider_id in PROVIDER_TOGGLE_ORDER:
        row = diagnostics.get(provider_id, {})
        configured = bool(row.get("api_key_present"))
        if provider_id == "ollama":
            configured = True
        if provider_id == "gemini" and gemini_is_disabled():
            configured = False
        options.append(
            {
                "id": provider_id,
                "label": PROVIDER_DISPLAY_NAMES.get(provider_id, provider_id),
                "description": PROVIDER_DESCRIPTIONS.get(provider_id, ""),
                "model": row.get("model") or "",
                "configured": configured,
                "active": provider_id == active_provider,
                "disabled": provider_id == "gemini" and gemini_is_disabled(),
            }
        )
    return options


def _settings_context(request: Request, message: str = None, message_type: str = "info"):
    active_provider = None
    try:
        active_provider = get_provider()
    except Exception:
        active_provider = None
    return {
        "request": request,
        "settings": get_llm_settings_for_form(),
        "providers": sorted(PROVIDER_DISPLAY_NAMES.keys()),
        "provider_toggle_options": _provider_toggle_options(active_provider),
        "other_providers": OTHER_PROVIDER_FIELDS,
        "embedding_providers": EMBEDDING_PROVIDER_OPTIONS,
        "llm_available": llm_available(),
        "active_provider": active_provider,
        "message": message,
        "message_type": message_type,
    }


def _ai_review_context(
    db: Session,
    request: Request,
    campaign: Campaign,
    *,
    sessions,
    session_model=None,
    notes: str = "",
    message=None,
    result=None,
    overwrite_confirmation=None,
):
    return with_mc(
        db,
        {
            "request": request,
            "campaign": campaign,
            "sessions": sessions,
            "session": session_model,
            "notes": notes,
            "message": message,
            "llm_available": llm_available(),
            "result": result,
            "overwrite_confirmation": overwrite_confirmation,
        },
        campaign=campaign,
        session=session_model,
        active_nav="ai_review",
        layout="dashboard",
        request=request,
    )


def _render_settings(request: Request, db: Session, **kwargs):
    return templates.TemplateResponse(
        "llm_settings.html",
        mc_settings_context(db, _settings_context(request, **kwargs)),
    )


def _render_llm_test(request: Request, db: Session, *, result=None):
    return templates.TemplateResponse(
        "llm_test.html",
        with_mc(db, _llm_test_context(request, result=result), active_nav="settings", layout="minimal"),
    )


@router.get("/settings/llm", response_class=HTMLResponse)
def llm_settings_form(request: Request, db: Session = Depends(get_session)):
    return _render_settings(request, db)


@router.post("/settings/llm/provider")
async def llm_settings_set_provider(
    request: Request,
    provider: str = Form(...),
    db: Session = Depends(get_session),
):
    selected = provider.strip().lower()
    if selected not in PROVIDER_DISPLAY_NAMES:
        if request.headers.get("accept") == "application/json":
            return JSONResponse(
                {"ok": False, "error": f"Unsupported provider: {selected}"},
                status_code=400,
            )
        return _render_settings(
            request,
            db,
            message=f"Unsupported provider: {selected}",
            message_type="danger",
        )
    try:
        update_env_file({"CAMPAIGN_CONSOLE_LLM_PROVIDER": selected})
        apply_env_to_process()
        message = f"Active provider set to {PROVIDER_DISPLAY_NAMES.get(selected, selected)}."
        message_type = "success"
    except Exception as exc:
        message = f"Could not switch provider: {exc}"
        message_type = "danger"
        if request.headers.get("accept") == "application/json":
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)
        return _render_settings(request, db, message=message, message_type=message_type)
    if request.headers.get("accept") == "application/json":
        return JSONResponse({"ok": True, "provider": selected, "message": message})
    return _render_settings(request, db, message=message, message_type=message_type)


@router.post("/settings/llm", response_class=HTMLResponse)
async def llm_settings_save(request: Request, db: Session = Depends(get_session)):
    form = await request.form()
    updates = {key: form.get(key) for key in MANAGED_KEYS}
    try:
        update_env_file(updates)
        apply_env_to_process()
        message = "Settings saved. The active LLM configuration has been reloaded."
        message_type = "success"
    except Exception as exc:
        message = f"Could not save settings: {exc}"
        message_type = "danger"
    return _render_settings(request, db, message=message, message_type=message_type)


def _llm_test_context(
    request: Request,
    *,
    result: Optional[dict] = None,
):
    active_provider = get_active_provider_or_none()
    configured_model = get_configured_model(active_provider) if active_provider else ""
    return {
        "request": request,
        "provider": active_provider,
        "provider_label": PROVIDER_DISPLAY_NAMES.get(active_provider or "", active_provider or ""),
        "model": configured_model,
        "llm_available": llm_available(),
        "result": result,
    }


@router.get("/llm/test", response_class=HTMLResponse)
def llm_test_form(request: Request, db: Session = Depends(get_session)):
    return _render_llm_test(request, db)


@router.post("/llm/test", response_class=HTMLResponse)
def llm_test(request: Request, db: Session = Depends(get_session)):
    active_provider = get_active_provider_or_none()
    if not active_provider or not provider_available(active_provider):
        result = {
            "success": False,
            "message": None,
            "error": f"Provider '{active_provider or 'unknown'}' is not configured.",
        }
        return _render_llm_test(request, db, result=result)
    try:
        output = generate(SMOKE_TEST_PROMPT, max_tokens=20, task_name="llm/test")
        success = output.strip().lower() == "ok"
        result = {
            "success": success,
            "message": output,
            "error": None if success else "Expected response OK.",
        }
    except Exception as exc:
        result = {"success": False, "message": None, "error": str(exc)}
    return _render_llm_test(request, db, result=result)


@router.get("/campaigns/{campaign_id}/ai/review", response_class=HTMLResponse)
def ai_review_form(request: Request, campaign_id: int, db: Session = Depends(get_session)):
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        return RedirectResponse(url="/", status_code=303)

    sessions = db.exec(
        select(SessionModel).where(SessionModel.campaign_id == campaign_id).order_by(SessionModel.id)
    ).all()
    return templates.TemplateResponse(
        "ai_review.html",
        _ai_review_context(
            db,
            request,
            campaign,
            sessions=sessions,
            session_model=None,
        ),
    )


@router.post("/campaigns/{campaign_id}/ai/review", response_class=HTMLResponse)
def ai_review(
    request: Request,
    campaign_id: int,
    session_id: Optional[str] = Form(None),
    notes: str = Form(""),
    confirm_overwrite: Optional[str] = Form(None),
    db: Session = Depends(get_session),
):
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        return RedirectResponse(url="/", status_code=303)

    sessions = db.exec(
        select(SessionModel).where(SessionModel.campaign_id == campaign_id).order_by(SessionModel.id)
    ).all()
    selected_session_id = _parse_optional_session_id(session_id)
    session_model = None
    if selected_session_id is not None:
        session_model = db.get(SessionModel, selected_session_id)
        if not session_model or session_model.campaign_id != campaign_id:
            return RedirectResponse(url=f"/campaigns/{campaign_id}/ai/review", status_code=303)

    if session_model is None:
        message = (
            "Create at least one session before generating future prep."
            if not sessions
            else "Select a session to save prep to."
        )
        return templates.TemplateResponse(
            "ai_review.html",
            _ai_review_context(
                db,
                request,
                campaign,
                sessions=sessions,
                session_model=None,
                notes=notes,
                message=message,
            ),
        )

    if not notes:
        notes = session_model.notes or ""

    if not notes.strip():
        return templates.TemplateResponse(
            "ai_review.html",
            _ai_review_context(
                db,
                request,
                campaign,
                sessions=sessions,
                session_model=session_model,
                notes=notes,
                message="Choose a session with notes or paste notes to generate future prep.",
            ),
        )

    overwrite_confirmation = None
    if prep_overwrite_requires_confirmation(session_model) and confirm_overwrite != "1":
        overwrite_confirmation = {
            "session_id": session_model.id,
            "notes": notes,
            "existing_prep_preview": (session_model.next_session_prep or "")[:500],
        }
        return templates.TemplateResponse(
            "ai_review.html",
            _ai_review_context(
                db,
                request,
                campaign,
                sessions=sessions,
                session_model=session_model,
                notes=notes,
                overwrite_confirmation=overwrite_confirmation,
            ),
        )

    try:
        message, result, _prep_text = run_future_prep_generation(
            db,
            campaign_id,
            session_model,
            notes,
            save_to_session=True,
            task_name="ai/review",
            save_raw_on_failure=False,
        )
        db.commit()
        db.refresh(session_model)
    except Exception as exc:
        return templates.TemplateResponse(
            "ai_review.html",
            _ai_review_context(
                db,
                request,
                campaign,
                sessions=sessions,
                session_model=session_model,
                notes=notes,
                message=str(exc),
            ),
        )

    if not message and "next_session_prep" in result.get("updated_fields", []):
        message = f"Future prep saved to {session_model.title}."

    return templates.TemplateResponse(
        "ai_review.html",
        _ai_review_context(
            db,
            request,
            campaign,
            sessions=sessions,
            session_model=session_model,
            notes=notes,
            message=message,
            result=result,
        ),
    )
