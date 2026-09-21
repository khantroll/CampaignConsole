"""One-off patch for entities.py dual-hub return_to support."""
from pathlib import Path

p = Path("app/routers/entities.py")
text = p.read_text(encoding="utf-8")

text = text.replace(
    "from app.services.mission_control_ui import entity_form_context, redirect_after_entity_save, with_mc",
    "from app.services.mission_control_ui import confirm_delete_context, entity_form_context, redirect_after_entity_save",
)

old_form = '''        with_mc(
            db,
            {
            "request": request,'''

new_form = '''        entity_form_context(
            db,
            request,
            campaign,
            {'''

text = text.replace(old_form, new_form)

text = text.replace(
    '''            "cancel_url": f"/campaigns/{campaign_id}",
            },
            campaign=campaign,
            layout="dashboard",
        ),
    )''',
    '''            },
        ),
    )''',
)

old_del = '''        with_mc(
            db,
            {
            "request": request,
            "title": "Delete'''

new_del = '''        confirm_delete_context(
            db,
            request,
            campaign,
            {
            "title": "Delete'''

text = text.replace(old_del, new_del)

text = text.replace(
    '''            "action": f"/campaigns/{campaign_id}/npcs/{npc_id}/delete",
            "cancel_url": f"/campaigns/{campaign_id}",
            },
            campaign=campaign,
            layout="dashboard",
        ),
    )''',
    '''            "action": f"/campaigns/{campaign_id}/npcs/{npc_id}/delete",
            },
        ),
    )''',
)

for entity in ("locations", "factions", "items", "threads"):
    text = text.replace(
        f'''            "action": f"/campaigns/{{campaign_id}}/{entity}/'''
        + ("{location_id}" if entity == "locations" else "{faction_id}" if entity == "factions" else "{item_id}" if entity == "items" else "{thread_id}")
        + '''/delete",
            "cancel_url": f"/campaigns/{campaign_id}",
            },
            campaign=campaign,
            layout="dashboard",
        ),
    )''',
        f'''            "action": f"/campaigns/{{campaign_id}}/{entity}/'''
        + ("{location_id}" if entity == "locations" else "{faction_id}" if entity == "factions" else "{item_id}" if entity == "items" else "{thread_id}")
        + '''/delete",
            },
        ),
    )''',
    )

replacements = [
    (
        "    selected_plot_threads: Optional[List[str]] = Form(None),\n    db: Session = Depends(get_session),\n):\n    location =",
        "    selected_plot_threads: Optional[List[str]] = Form(None),\n    return_to: Optional[str] = Form(None),\n    db: Session = Depends(get_session),\n):\n    location =",
    ),
    (
        "    summary: str = Form(\"\"),\n    db: Session = Depends(get_session),\n):\n    faction =",
        "    summary: str = Form(\"\"),\n    return_to: Optional[str] = Form(None),\n    db: Session = Depends(get_session),\n):\n    faction =",
    ),
    (
        "    selected_plot_threads: Optional[List[str]] = Form(None),\n    db: Session = Depends(get_session),\n):\n    item =",
        "    selected_plot_threads: Optional[List[str]] = Form(None),\n    return_to: Optional[str] = Form(None),\n    db: Session = Depends(get_session),\n):\n    item =",
    ),
    (
        "    resolution_notes: str = Form(\"\"),\n    db: Session = Depends(get_session),\n):\n    thread =",
        "    resolution_notes: str = Form(\"\"),\n    return_to: Optional[str] = Form(None),\n    db: Session = Depends(get_session),\n):\n    thread =",
    ),
]
for old, new in replacements:
    text = text.replace(old, new, 1)

# update_* redirects after commit (location, faction, item, thread)
for marker in [
    "    db.add(location)\n    db.commit()\n    return RedirectResponse(url=f\"/campaigns/{campaign_id}\", status_code=303)",
    "    db.add(faction)\n    db.commit()\n    return RedirectResponse(url=f\"/campaigns/{campaign_id}\", status_code=303)",
    "    db.add(item)\n    db.commit()\n    return RedirectResponse(url=f\"/campaigns/{campaign_id}\", status_code=303)",
    "    db.add(thread)\n    db.commit()\n    return RedirectResponse(url=f\"/campaigns/{campaign_id}\", status_code=303)",
]:
    text = text.replace(marker, marker.replace(
        "return RedirectResponse(url=f\"/campaigns/{campaign_id}\", status_code=303)",
        "return _entity_save_redirect(campaign_id, return_to)",
    ), 1)

p.write_text(text, encoding="utf-8")
print("patched entities.py")
