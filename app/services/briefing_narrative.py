"""Campaign briefing narrative: local digest summary and optional AI paragraph."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

from app.llm import generate, get_active_provider_or_none, get_configured_model, provider_available
from app.models import Campaign

logger = logging.getLogger(__name__)


def build_local_briefing_narrative(campaign: Campaign, briefing: Dict[str, Any]) -> str:
    parts: list[str] = []
    current = briefing.get("current_session")
    if current:
        date_suffix = f" ({current.date})" if current.date else ""
        parts.append(f"Current focus is {current.title}{date_suffix}.")

    returning = briefing.get("returning_npcs") or []
    if returning:
        names = ", ".join(row["npc"].name for row in returning[:5])
        parts.append(f"Returning this session: {names}.")

    signals = briefing.get("signals") or {}
    dormant_count = signals.get("dormant_count") or 0
    stale_count = signals.get("stale_count") or 0
    if dormant_count or stale_count:
        attention: list[str] = []
        if dormant_count:
            attention.append(f"{dormant_count} dormant thread{'s' if dormant_count != 1 else ''}")
        if stale_count:
            attention.append(f"{stale_count} stale entit{'ies' if stale_count != 1 else 'y'}")
        parts.append(f"Needs attention: {' and '.join(attention)}.")
    elif current:
        parts.append("No dormant threads or stale entities in the current intelligence window.")

    next_session = briefing.get("next_session")
    if next_session:
        parts.append(f"Next session queued: {next_session.title}.")

    threads = briefing.get("briefing_threads") or []
    if threads:
        titles = ", ".join(row["thread"].title for row in threads[:4])
        parts.append(f"Active plot threads include {titles}.")

    dashboard = briefing.get("dashboard_summary") or {}
    needs = dashboard.get("needs_attention") or []
    if needs:
        parts.append(f"{len(needs)} incomplete entit{'ies' if len(needs) != 1 else 'y'} need profile work.")

    if not parts:
        if (dashboard.get("session_count") or 0) == 0:
            return "No sessions yet. Add a session and link entities to build a briefing."
        return f"{campaign.name} is ready for more session links and analysis to populate this briefing."

    return " ".join(parts)


def _briefing_prompt(campaign: Campaign, briefing: Dict[str, Any]) -> str:
    local = build_local_briefing_narrative(campaign, briefing)
    lines = [
        "Write a concise GM-facing campaign briefing paragraph (3–5 sentences).",
        "Use only the facts below. Do not invent plot details.",
        "Tone: practical prep notes for the Dungeon Master.",
        "",
        f"Campaign: {campaign.name}",
    ]
    if campaign.system:
        lines.append(f"System: {campaign.system}")
    lines.append("")
    lines.append("Structured digest:")
    lines.append(local)

    signals = briefing.get("signals") or {}
    for label, key in [
        ("Dormant threads", "dormant_threads"),
        ("Stale NPCs", "stale_npcs"),
        ("Stale locations", "stale_locations"),
    ]:
        rows = signals.get(key) or []
        if rows:
            names = []
            for row in rows[:6]:
                if key == "dormant_threads":
                    names.append(getattr(row.get("thread"), "title", "") or "?")
                else:
                    names.append(row.get("name") or "?")
            lines.append(f"{label}: {', '.join(names)}")

    last = briefing.get("last_analyzed")
    if last and last.get("session"):
        lines.append(f"Last analyzed session: {last['session'].title}")

    lines.append("")
    lines.append("Return plain prose only — no markdown headers or bullet lists.")
    return "\n".join(lines)


def generate_ai_briefing_narrative(
    campaign: Campaign,
    briefing: Dict[str, Any],
) -> Tuple[Optional[str], Optional[str]]:
    """Returns (narrative_text, error_message)."""
    if not provider_available():
        return None, "LLM provider not configured."

    prompt = _briefing_prompt(campaign, briefing)
    try:
        output = generate(prompt, max_tokens=500, task_name="briefing/narrative")
    except Exception as exc:
        logger.exception("AI briefing narrative failed for campaign %s", campaign.id)
        return None, str(exc)

    text = (output or "").strip()
    if not text:
        return None, "AI returned an empty summary."
    return text, None


def build_briefing_narrative_context(campaign: Campaign, briefing: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "local": build_local_briefing_narrative(campaign, briefing),
        "ai": (campaign.briefing_narrative or "").strip() or None,
        "ai_generated_at": campaign.briefing_narrative_generated_at,
        "ai_provider": campaign.briefing_narrative_provider,
        "ai_model": campaign.briefing_narrative_model,
        "llm_available": provider_available(),
    }


def save_ai_briefing_narrative(db, campaign: Campaign, text: str) -> None:
    from app.utils.time import utc_now

    provider = get_active_provider_or_none()
    model = get_configured_model(provider) if provider else None
    campaign.briefing_narrative = text
    campaign.briefing_narrative_generated_at = utc_now()
    campaign.briefing_narrative_provider = provider
    campaign.briefing_narrative_model = model
    db.add(campaign)
