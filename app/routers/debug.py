import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlmodel import Session

from app.database import get_session
from app.deps import templates
from app.services.mission_control_ui import mc_settings_context
from app.services.provider_router import (
    SMOKE_TEST_PROMPT,
    generate_raw,
    get_active_provider_or_none,
    list_provider_diagnostics,
    run_provider_smoke_test,
)

router = APIRouter()


@router.get("/debug/providers", response_class=HTMLResponse)
def debug_providers(request: Request, db: Session = Depends(get_session)):
    return templates.TemplateResponse(
        "debug_providers.html",
        mc_settings_context(
            db,
            {
                "request": request,
                "providers": list_provider_diagnostics(),
                "active_provider": get_active_provider_or_none(),
            },
        ),
    )


@router.post("/debug/provider-test")
async def debug_provider_test(request: Request, db: Session = Depends(get_session)):
    form = await request.form()
    want_html = form.get("format") != "json"
    result = run_provider_smoke_test(SMOKE_TEST_PROMPT, max_tokens=20)
    if not want_html and request.headers.get("accept") == "application/json":
        return JSONResponse(result)
    if form.get("format") == "json":
        return JSONResponse(result)
    return templates.TemplateResponse(
        "debug_provider_test.html",
        mc_settings_context(
            db,
            {
                "request": request,
                "prompt": SMOKE_TEST_PROMPT,
                "result": result,
                "raw_body": json.dumps(result.get("body"), indent=2, default=str),
            },
        ),
    )


@router.get("/debug/provider-test", response_class=HTMLResponse)
def debug_provider_test_form(request: Request, db: Session = Depends(get_session)):
    provider = get_active_provider_or_none() or "not set"
    model_info = next(
        (row for row in list_provider_diagnostics() if row["provider"] == provider),
        None,
    )
    return templates.TemplateResponse(
        "debug_provider_test_form.html",
        mc_settings_context(
            db,
            {
                "request": request,
                "provider": provider,
                "model_info": model_info,
                "prompt": SMOKE_TEST_PROMPT,
            },
        ),
    )
