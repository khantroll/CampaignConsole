import io
import re
import zipfile
from typing import List

def wrap_link(text: str) -> str:
    safe = text.replace("[[", "").replace("]]", "")
    return f"[[{safe}]]"


def linkify_text(text: str, references: List[str]) -> str:
    if not text or not references:
        return text or ""
    replaced = text
    for ref in sorted(set(references), key=len, reverse=True):
        if not ref:
            continue
        replaced = re.sub(rf"\b{re.escape(ref)}\b", wrap_link(ref), replaced)
    return replaced


def format_entity_links(entries):
    return [wrap_link(getattr(entry, "name", None) or getattr(entry, "title", "")) for entry in entries if getattr(entry, "name", None) or getattr(entry, "title", None)]


def render_campaign_markdown(
    campaign,
    sessions,
    npcs,
    locations,
    factions,
    items,
    threads,
    pc_notes,
    *,
    location_related_names: dict | None = None,
    thread_related_names: dict | None = None,
    include_gm_secrets: bool = True,
):
    lines = [f"# {campaign.name}", f"_System: {campaign.system or 'Unknown'}_", "", campaign.description or ""]
    all_names = [npc.name for npc in npcs] + [location.name for location in locations] + [faction.name for faction in factions] + [item.name for item in items] + [thread.title for thread in threads]
    lines.append("\n## Sessions")
    for session in sessions:
        note_body = linkify_text(session.notes or "No notes yet.", all_names)
        lines.append(f"\n### {session.title}")
        lines.append(f"- Date: {session.date or 'TBD'}")
        lines.append(note_body)
        if session.npcs:
            lines.append(f"- NPCs: {', '.join(format_entity_links(session.npcs))}")
        if session.locations:
            lines.append(f"- Locations: {', '.join(format_entity_links(session.locations))}")
        if session.factions:
            lines.append(f"- Factions: {', '.join(format_entity_links(session.factions))}")
        if session.items:
            lines.append(f"- Items: {', '.join(format_entity_links(session.items))}")
        if session.plot_threads:
            lines.append(f"- Plot Threads: {', '.join(format_entity_links(session.plot_threads))}")
        if session.player_recap:
            lines.append(f"\n**Player Recap:** {session.player_recap}")
        if session.recap:
            lines.append(f"\n**GM Recap:** {session.recap}")
        if session.next_session_prep:
            lines.append(f"\n**Next Session Prep:**\n{session.next_session_prep}")
    if npcs:
        lines.append("\n## NPCs")
        for npc in npcs:
            status_bits = []
            if getattr(npc, "world_status", None):
                status_bits.append(f"Status: {npc.world_status}")
            if getattr(npc, "state_notes", None):
                status_bits.append(f"State Notes: {npc.state_notes}")
            status_suffix = f" [{' · '.join(status_bits)}]" if status_bits else ""
            lines.append(f"- **{wrap_link(npc.name)}** ({npc.role or 'Unknown'}){status_suffix} — {npc.description or ''}")
            related = []
            if npc.factions:
                related.append("Factions: " + ", ".join(format_entity_links(npc.factions)))
            if npc.locations:
                related.append("Locations: " + ", ".join(format_entity_links(npc.locations)))
            if npc.plot_threads:
                related.append("Plot Threads: " + ", ".join(format_entity_links(npc.plot_threads)))
            if npc.sessions:
                related.append("Sessions: " + ", ".join(format_entity_links(npc.sessions)))
            if related:
                lines.append("  - " + " | ".join(related))
    if locations:
        lines.append("\n## Locations")
        for location in locations:
            desc = location.description or ""
            if location.notes:
                desc = f"{desc} — Notes: {location.notes}" if desc else f"Notes: {location.notes}"
            if getattr(location, "world_status", None):
                desc = (desc + f" — Status: {location.world_status}") if desc else f"Status: {location.world_status}"
            if getattr(location, "state_notes", None):
                desc = (desc + f" — State Notes: {location.state_notes}") if desc else f"State Notes: {location.state_notes}"
            lines.append(f"- **{wrap_link(location.name)}** — {desc}")
            related = []
            if location.factions:
                related.append("Factions: " + ", ".join(format_entity_links(location.factions)))
            if location_related_names and location.id in location_related_names:
                names = location_related_names[location.id]
                if names:
                    related.append("Related Locations: " + ", ".join(wrap_link(name) for name in names))
            if location.npcs:
                related.append("NPCs: " + ", ".join(format_entity_links(location.npcs)))
            if location.plot_threads:
                related.append("Plot Threads: " + ", ".join(format_entity_links(location.plot_threads)))
            if location.items:
                related.append("Items: " + ", ".join(format_entity_links(location.items)))
            if location.sessions:
                related.append("Sessions: " + ", ".join(format_entity_links(location.sessions)))
            if related:
                lines.append("  - " + " | ".join(related))
    if factions:
        lines.append("\n## Factions")
        for faction in factions:
            desc = faction.summary or ""
            if getattr(faction, "world_status", None):
                desc = (desc + f" — Status: {faction.world_status}") if desc else f"Status: {faction.world_status}"
            if getattr(faction, "state_notes", None):
                desc = (desc + f" — State Notes: {faction.state_notes}") if desc else f"State Notes: {faction.state_notes}"
            related = []
            if getattr(faction, "npcs", None):
                related.append("NPCs: " + ", ".join(format_entity_links(faction.npcs)))
            if getattr(faction, "pcs", None):
                related.append("Party: " + ", ".join(
                    wrap_link(getattr(pc, "character_name", "") or "PC") for pc in faction.pcs
                ))
            line = f"- **{wrap_link(faction.name)}** — {desc}"
            if related:
                line += " (" + "; ".join(related) + ")"
            lines.append(line)
    if items:
        lines.append("\n## Items")
        for item in items:
            desc = item.description or ""
            if getattr(item, "world_status", None):
                desc = (desc + f" — Status: {item.world_status}") if desc else f"Status: {item.world_status}"
            if getattr(item, "state_notes", None):
                desc = (desc + f" — State Notes: {item.state_notes}") if desc else f"State Notes: {item.state_notes}"
            related = []
            if getattr(item, "factions", None):
                related.append("Factions: " + ", ".join(format_entity_links(item.factions)))
            if getattr(item, "locations", None):
                related.append("Locations: " + ", ".join(format_entity_links(item.locations)))
            if getattr(item, "plot_threads", None):
                related.append("Plot Threads: " + ", ".join(format_entity_links(item.plot_threads)))
            if item.sessions:
                related.append("Sessions: " + ", ".join(format_entity_links(item.sessions)))
            line = f"- **{wrap_link(item.name)}** — {desc}"
            if related:
                line += " (" + "; ".join(related) + ")"
            lines.append(line)
    if threads:
        lines.append("\n## Plot Threads")
        for thread in threads:
            lines.append(f"- **{wrap_link(thread.title)}** ({thread.status or 'Unknown'})")
            if getattr(thread, "mystery_status", None):
                lines.append(f"  - Mystery Status: {thread.mystery_status}")
            if getattr(thread, "state_notes", None):
                lines.append(f"  - State Notes: {thread.state_notes}")
            if include_gm_secrets and getattr(thread, "open_clues", None):
                lines.append(f"  - Open Clues:\n" + "\n".join(f"    - {c}" for c in thread.open_clues.splitlines() if c.strip()))
            if getattr(thread, "revealed_clues", None):
                lines.append(f"  - Revealed Clues:\n" + "\n".join(f"    - {c}" for c in thread.revealed_clues.splitlines() if c.strip()))
            if include_gm_secrets and getattr(thread, "secret_notes", None):
                lines.append(f"  - Secret Notes (GM): {thread.secret_notes}")
            if thread.thread_type:
                lines.append(f"  - Thread Type: {thread.thread_type}")
            if thread.details:
                lines.append(f"  - Description: {thread.details}")
            if getattr(thread, "npcs", None) or getattr(thread, "pcs", None):
                actors = []
                if getattr(thread, "npcs", None):
                    actors.extend(format_entity_links(thread.npcs))
                if getattr(thread, "pcs", None):
                    actors.extend(format_entity_links(thread.pcs))
                if actors:
                    lines.append("  - Key Actors: " + ", ".join(actors))
            if getattr(thread, "locations", None):
                lines.append("  - Key Locations: " + ", ".join(format_entity_links(thread.locations)))
            if getattr(thread, "factions", None):
                lines.append("  - Related Factions: " + ", ".join(format_entity_links(thread.factions)))
            if getattr(thread, "creatures", None):
                lines.append("  - Related Creatures: " + ", ".join(format_entity_links(thread.creatures)))
            if thread_related_names and thread.id in thread_related_names:
                names = thread_related_names[thread.id]
                if names:
                    lines.append("  - Related Plot Threads: " + ", ".join(wrap_link(name) for name in names))
            if thread.plot_significance_notes:
                lines.append(f"  - Plot Significance: {thread.plot_significance_notes}")
    if pc_notes:
        lines.append("\n## Party Members")
        for note in pc_notes:
            lines.append(f"- **{note.character_name}**")
            if note.character_archetype:
                lines.append(f"  - Archetype: {note.character_archetype}")
            if note.description:
                lines.append(f"  - Description: {note.description}")
            if note.signature_gear:
                lines.append(f"  - Signature Gear: {note.signature_gear}")
            if note.key_ties_history:
                lines.append(f"  - Key Ties & History: {note.key_ties_history}")
            if note.campaign_role_plot_notes:
                lines.append(f"  - Campaign Role & Plot Notes: {note.campaign_role_plot_notes}")
            if note.notes:
                lines.append(f"  - Additional Notes: {note.notes}")
            if getattr(note, "locations", None):
                lines.append(
                    "  - Locations: " + ", ".join(format_entity_links(note.locations))
                )
            if getattr(note, "plot_threads", None):
                lines.append(
                    "  - Plot Threads: " + ", ".join(format_entity_links(note.plot_threads))
                )
    return "\n".join(lines)


def render_session_markdown(
    campaign,
    session,
    references: List[str],
    *,
    scenes=None,
    encounters=None,
    objectives=None,
    include_gm_notes: bool = True,
):
    lines = [f"# {campaign.name} — {session.title}", f"_Date: {session.date or 'TBD'}_", "", linkify_text(session.notes or "No notes yet.", references)]

    if scenes:
        lines.append("\n## Scenes")
        for scene in scenes:
            lines.append(f"\n### {scene.title} ({scene.status})")
            if scene.narrative_goal:
                lines.append(f"- Narrative Goal: {scene.narrative_goal}")
            if scene.summary:
                lines.append(f"- Summary: {scene.summary}")
            if include_gm_notes and scene.gm_only_notes:
                lines.append(f"- GM Notes: {scene.gm_only_notes}")

    if encounters:
        lines.append("\n## Encounters")
        for enc in encounters:
            lines.append(f"\n### {enc.title} ({enc.encounter_type}, {enc.status})")
            if enc.objective:
                lines.append(f"- Objective: {enc.objective}")
            if enc.stakes:
                lines.append(f"- Stakes: {enc.stakes}")
            if enc.outcome:
                lines.append(f"- Outcome: {enc.outcome}")
            if include_gm_notes and enc.gm_only_notes:
                lines.append(f"- GM Notes: {enc.gm_only_notes}")

    if objectives:
        lines.append("\n## Objectives")
        for obj in objectives:
            lines.append(f"\n### {obj.title} ({obj.objective_type}, {obj.priority}, {obj.status})")
            if obj.description:
                lines.append(f"- {obj.description}")
            if include_gm_notes and obj.gm_only_notes:
                lines.append(f"- GM Notes: {obj.gm_only_notes}")

    if session.npcs:
        lines.append("\n## NPCs")
        lines.extend(f"- {wrap_link(npc.name)}" for npc in session.npcs)
    if session.locations:
        lines.append("\n## Locations")
        lines.extend(f"- {wrap_link(location.name)}" for location in session.locations)
    if session.factions:
        lines.append("\n## Factions")
        lines.extend(f"- {wrap_link(faction.name)}" for faction in session.factions)
    if session.items:
        lines.append("\n## Items")
        lines.extend(f"- {wrap_link(item.name)}" for item in session.items)
    if session.plot_threads:
        lines.append("\n## Plot Threads")
        lines.extend(f"- {wrap_link(thread.title)}" for thread in session.plot_threads)
    if session.player_recap:
        lines.append(f"\n## Player Recap\n{session.player_recap}")
    if session.recap:
        lines.append(f"\n## GM Recap\n{session.recap}")
    if session.next_session_prep:
        lines.append(f"\n## Next Session Prep\n{session.next_session_prep}")
    return "\n".join(lines)


def render_briefing_markdown(campaign, briefing: dict) -> str:
    lines = [f"# Brief Me: {campaign.name}"]
    if campaign.system:
        lines.append(f"_System: {campaign.system}_")
    lines.append("")

    narrative = briefing.get("narrative") or {}
    summary = narrative.get("ai") or narrative.get("local")
    if summary:
        lines.append("## Summary")
        lines.append(summary)
        lines.append("")

    sections = briefing.get("sections") or {}
    health = sections.get("campaign_health") or {}
    if health.get("average") is not None:
        lines.append("## Campaign Health")
        lines.append(f"- Campaign Health: {health.get('average', 0)}%")
        lines.append(
            f"- NPC Coverage: {health.get('npc_coverage', 0)}%"
            f" · Location Coverage: {health.get('location_coverage', 0)}%"
            f" · Thread Coverage: {health.get('thread_coverage', 0)}%"
        )
        lines.append("")

    last = sections.get("last_session")
    if last and last.get("session"):
        session = last["session"]
        lines.append("## Last Session")
        lines.append(f"- **{session.title}** · {session.date or 'No date'}")
        if last.get("recap_preview"):
            lines.append(f"  {last['recap_preview']}")
        lines.append("")

    active_threads = sections.get("active_threads") or []
    if active_threads:
        lines.append("## Active Plot Threads")
        for row in active_threads:
            thread = row["thread"]
            parts = [thread.title]
            if thread.status:
                parts.append(thread.status)
            if thread.importance:
                parts.append(thread.importance)
            if row.get("last_session"):
                parts.append(f"last: {row['last_session'].title}")
            lines.append(f"- {' · '.join(parts)}")
        lines.append("")

    important_npcs = sections.get("important_npcs") or []
    if important_npcs:
        lines.append("## Important NPCs")
        for row in important_npcs:
            npc = row["npc"]
            parts = [npc.name]
            if row.get("status"):
                parts.append(row["status"])
            if row.get("last_seen_title"):
                parts.append(f"last seen: {row['last_seen_title']}")
            if row.get("thread_link_count"):
                parts.append(f"{row['thread_link_count']} active thread link(s)")
            lines.append(f"- {' · '.join(parts)}")
        lines.append("")

    developments = sections.get("recent_developments") or []
    if developments:
        lines.append("## Recent Developments")
        for row in developments:
            session_title = row["session"].title if row.get("session") else "Session"
            lines.append(f"- **{row.get('label', 'Update')}** ({session_title}): {row.get('text', '')}")
        lines.append("")

    questions = sections.get("unresolved_questions") or []
    if questions:
        lines.append("## Unresolved Questions")
        for row in questions:
            lines.append(f"- {row['text']} · _{row.get('source', '')}_")
        lines.append("")

    dormant = sections.get("dormant_threads") or []
    if dormant:
        lines.append("## Dormant Threads")
        for row in dormant:
            thread = row["thread"]
            if row.get("never_linked"):
                lines.append(f"- {thread.title} · never linked to a session")
            elif row.get("last_session"):
                suffix = f" · dormant: {row['sessions_since']} session(s)" if row.get("sessions_since") is not None else ""
                lines.append(f"- {thread.title} · last advanced: {row['last_session'].title}{suffix}")
            else:
                lines.append(f"- {thread.title}")
        lines.append("")

    needs = sections.get("needs_attention") or {}
    if needs.get("lines") or needs.get("needs_attention_items") or needs.get("unanalyzed_sessions"):
        lines.append("## Needs Attention")
        for line in needs.get("lines") or []:
            lines.append(f"- {line['text']}")
        for item in needs.get("needs_attention_items") or []:
            lines.append(f"- [{item['type_badge']}] {item['name']} · {item['score']}% complete")
        for session in needs.get("unanalyzed_sessions") or []:
            lines.append(f"- Unanalyzed: {session.title}")
        lines.append("")

    signals = briefing.get("signals") or {}
    stale_sections = [
        ("Stale NPCs", signals.get("stale_npcs") or []),
        ("Stale Locations", signals.get("stale_locations") or []),
        ("Stale Factions", signals.get("stale_factions") or []),
        ("Stale Items", signals.get("stale_items") or []),
    ]
    stale_rows = [(heading, rows) for heading, rows in stale_sections if rows]
    if stale_rows:
        lines.append("## Stale Entities")
        for heading, rows in stale_rows:
            lines.append(f"\n### {heading}")
            for row in rows:
                name = row.get("name") or getattr(row.get("entity"), "name", "") or "Unknown"
                suffix = f" · last in {row['last_session'].title}" if row.get("last_session") else ""
                lines.append(f"- {name}{suffix}")
        lines.append("")

    if len(lines) <= 3:
        lines.append("_No briefing signals yet. Link entities to sessions and run analysis to populate this digest._")

    return "\n".join(lines).strip() + "\n"


def safe_filename(name: str) -> str:
    return "".join(c if c.isalnum() or c in " _-" else "_" for c in name).strip()


def create_obsidian_export(
    campaign,
    sessions,
    npcs,
    locations,
    factions,
    items,
    threads,
    pc_notes,
    *,
    location_related_names: dict | None = None,
    thread_related_names: dict | None = None,
) -> bytes:
    buffer = io.BytesIO()
    base_folder = safe_filename(campaign.name) or "campaign"
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        root = f"{base_folder}/"
        zf.writestr(
            root + "Campaign.md",
            render_campaign_markdown(
                campaign,
                sessions,
                npcs,
                locations,
                factions,
                items,
                threads,
                pc_notes,
                location_related_names=location_related_names,
                thread_related_names=thread_related_names,
            ),
        )
        for session in sessions:
            references = [npc.name for npc in npcs] + [location.name for location in locations] + [faction.name for faction in factions] + [item.name for item in items] + [thread.title for thread in threads]
            content = render_session_markdown(campaign, session, references)
            zf.writestr(root + f"Sessions/{safe_filename(session.title)}.md", content)
        for npc in npcs:
            linked_factions = ", ".join(wrap_link(f.name) for f in getattr(npc, "factions", []))
            linked_locations = ", ".join(wrap_link(l.name) for l in getattr(npc, "locations", []))
            linked_threads = ", ".join(wrap_link(t.title) for t in getattr(npc, "plot_threads", []))
            linked_sessions = ", ".join(wrap_link(s.title) for s in getattr(npc, "sessions", []))
            content = f"# {npc.name}\n\n{npc.description or ''}\n"
            if linked_factions:
                content += f"\n## Related Factions\n{linked_factions}\n"
            if linked_locations:
                content += f"\n## Related Locations\n{linked_locations}\n"
            if linked_threads:
                content += f"\n## Related Plot Threads\n{linked_threads}\n"
            if linked_sessions:
                content += f"\n## Sessions\n{linked_sessions}\n"
            zf.writestr(root + f"NPCs/{safe_filename(npc.name)}.md", content)
        for location in locations:
            linked_factions = ", ".join(wrap_link(f.name) for f in getattr(location, "factions", []))
            linked_npcs = ", ".join(wrap_link(n.name) for n in getattr(location, "npcs", []))
            linked_threads = ", ".join(wrap_link(t.title) for t in getattr(location, "plot_threads", []))
            linked_items = ", ".join(wrap_link(i.name) for i in getattr(location, "items", []))
            linked_sessions = ", ".join(wrap_link(s.title) for s in getattr(location, "sessions", []))
            content = f"# {location.name}\n\n{location.description or ''}\n"
            if location.notes:
                content += f"\n## Notes\n{location.notes}\n"
            if linked_factions:
                content += f"\n## Related Factions\n{linked_factions}\n"
            if linked_npcs:
                content += f"\n## Related NPCs\n{linked_npcs}\n"
            if linked_threads:
                content += f"\n## Related Plot Threads\n{linked_threads}\n"
            if linked_items:
                content += f"\n## Related Items\n{linked_items}\n"
            if linked_sessions:
                content += f"\n## Sessions\n{linked_sessions}\n"
            zf.writestr(root + f"Locations/{safe_filename(location.name)}.md", content)
        for faction in factions:
            linked_npcs = ", ".join(wrap_link(n.name) for n in getattr(faction, "npcs", []))
            linked_pcs = ", ".join(
                wrap_link(getattr(pc, "character_name", "") or "PC") for pc in getattr(faction, "pcs", [])
            )
            linked_locations = ", ".join(wrap_link(loc.name) for loc in getattr(faction, "locations", []))
            linked_threads = ", ".join(wrap_link(t.title) for t in getattr(faction, "plot_threads", []))
            hq_name = ""
            if faction.hq_location_id:
                hq_match = next((loc for loc in locations if loc.id == faction.hq_location_id), None)
                if hq_match:
                    hq_name = wrap_link(hq_match.name)
            content = f"# {faction.name}\n\n"
            if faction.faction_type:
                from app.services.faction_classification import faction_type_label

                content += f"**Type:** {faction_type_label(faction.faction_type)}\n\n"
            content += f"{faction.summary or ''}\n"
            if hq_name:
                content += f"\n## HQ / Base of Operations\n{hq_name}\n"
            if faction.plot_notes:
                content += f"\n## Plot Significance / Notes\n{faction.plot_notes}\n"
            if linked_npcs:
                content += f"\n## Key Figures\n{linked_npcs}\n"
            if linked_pcs:
                content += f"\n## Related Party Members\n{linked_pcs}\n"
            if linked_locations:
                content += f"\n## Related Locations\n{linked_locations}\n"
            if linked_threads:
                content += f"\n## Related Plot Threads\n{linked_threads}\n"
            zf.writestr(root + f"Factions/{safe_filename(faction.name)}.md", content)
        for item in items:
            linked_factions = ", ".join(wrap_link(f.name) for f in getattr(item, "factions", []))
            linked_locations = ", ".join(wrap_link(l.name) for l in getattr(item, "locations", []))
            linked_threads = ", ".join(wrap_link(t.title) for t in getattr(item, "plot_threads", []))
            linked_sessions = ", ".join(wrap_link(s.title) for s in getattr(item, "sessions", []))
            owner_label = ""
            if item.owner_npc_id:
                owner = next((n for n in npcs if n.id == item.owner_npc_id), None)
                if owner:
                    owner_label = wrap_link(owner.name)
            elif item.owner_pc_id:
                owner = next((pc for pc in pc_notes if pc.id == item.owner_pc_id), None)
                if owner:
                    owner_label = wrap_link(getattr(owner, "character_name", "") or "PC")
            content = f"# {item.name}\n\n"
            if item.item_type:
                from app.services.item_classification import item_type_label

                content += f"**Type:** {item_type_label(item.item_type)}\n\n"
            content += f"{item.description or ''}\n"
            if owner_label:
                content += f"\n## Current Owner / Carrier\n{owner_label}\n"
            if item.origin:
                content += f"\n## Origin / Where Found\n{item.origin}\n"
            if item.plot_notes:
                content += f"\n## Plot Significance / Notes\n{item.plot_notes}\n"
            if linked_factions:
                content += f"\n## Related Factions\n{linked_factions}\n"
            if linked_locations:
                content += f"\n## Related Locations\n{linked_locations}\n"
            if linked_threads:
                content += f"\n## Related Plot Threads\n{linked_threads}\n"
            if linked_sessions:
                content += f"\n## Sessions\n{linked_sessions}\n"
            zf.writestr(root + f"Items/{safe_filename(item.name)}.md", content)
        for thread in threads:
            linked_npcs = ", ".join(wrap_link(n.name) for n in getattr(thread, "npcs", []))
            linked_pcs = ", ".join(wrap_link(p.character_name) for p in getattr(thread, "pcs", []))
            linked_locations = ", ".join(wrap_link(l.name) for l in getattr(thread, "locations", []))
            linked_factions = ", ".join(wrap_link(f.name) for f in getattr(thread, "factions", []))
            linked_creatures = ", ".join(wrap_link(c.name) for c in getattr(thread, "creatures", []))
            linked_items = ", ".join(wrap_link(i.name) for i in getattr(thread, "items", []))
            linked_sessions = ", ".join(wrap_link(s.title) for s in getattr(thread, "sessions", []))
            content = f"# {thread.title}\n\n"
            if thread.thread_type:
                content += f"**Thread Type:** {thread.thread_type}\n\n"
            if thread.status:
                content += f"**Status:** {thread.status}\n\n"
            content += f"{thread.details or ''}\n"
            if thread.plot_significance_notes:
                content += f"\n## Plot Significance / Notes\n{thread.plot_significance_notes}\n"
            if linked_npcs or linked_pcs:
                content += "\n## Key Actors\n"
                if linked_npcs:
                    content += f"NPCs: {linked_npcs}\n"
                if linked_pcs:
                    content += f"Party Members: {linked_pcs}\n"
            if linked_locations:
                content += f"\n## Key Locations\n{linked_locations}\n"
            if linked_factions:
                content += f"\n## Related Factions\n{linked_factions}\n"
            if linked_creatures:
                content += f"\n## Related Creatures\n{linked_creatures}\n"
            if thread_related_names and thread.id in thread_related_names:
                linked_related_threads = ", ".join(
                    wrap_link(title) for title in thread_related_names[thread.id]
                )
                if linked_related_threads:
                    content += f"\n## Related Plot Threads\n{linked_related_threads}\n"
            if linked_items:
                content += f"\n## Related Items\n{linked_items}\n"
            if linked_sessions:
                content += f"\n## Sessions\n{linked_sessions}\n"
            zf.writestr(root + f"PlotThreads/{safe_filename(thread.title)}.md", content)
    return buffer.getvalue()


