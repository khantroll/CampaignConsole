# Campaign Console — Regression Checklist

Manual smoke test before releases or after stabilization changes. Run against a local dev server with a test campaign.

## Core workflow

- [ ] **Create campaign** — `/` → New Campaign → lands on Workspace (or World with session)
- [ ] **Create session** — World → Sessions section → Add Session
- [ ] **Ingest notes** — Ingest Notes → paste notes → extract → review candidates
- [ ] **Approve entities** — Ingest review → link NPCs/locations/threads → save session
- [ ] **Save & analyze session** — Sessions → Session Workflow → save notes → Analyze
- [ ] **Generate prep** — Session Workflow → Generate Prep → prep draft appears
- [ ] **Copy prep to workspace** — Workspace → Copy AI Prep to Workspace → content in editor
- [ ] **Edit workspace** — change notes → Unsaved changes indicator → Save Workspace → Saved
- [ ] **Export markdown** — World → Export Markdown downloads
- [ ] **Backup DB** — World → Backup SQLite downloads
- [ ] **Delete/merge bad locations** — Location Admin → reclassify scene features → merge duplicates → bulk delete

## Navigation & persistence

- [ ] **Back to Workspace** — visible on every campaign page (hub bar); one click returns with session + mode
- [ ] **Session/mode memory** — set Run mode on Session A → Ingest → Back to Workspace → same session + Run mode
- [ ] **Campaign selector** — switches campaign and opens that campaign's last workspace session

## World dashboard widgets

- [ ] **Quick Resume** — shows persisted/current session with Workspace link
- [ ] **Next Session** — shows next session without notes (if any)
- [ ] **Last Analyzed** — shows session with AI metadata after analyze
- [ ] **Active Plot Threads** — lists non-resolved threads
- [ ] **Recently Seen NPCs** — lists NPCs with last session link after ingest/session edit
- [ ] **Needs Attention** — lists incomplete entities with missing fields
- [ ] **Entity Completeness Overview** — progress bars per entity type reflect health scores
- [ ] **Campaign Intelligence strip** — after linking a thread in session 1 only, then advancing 2+ sessions without re-linking, dormant threads appear; with only recent links, strip shows **All clear**
- [ ] **Stale entity signals** — link a location/faction/item/NPC in session 1 only, advance 2+ sessions → Briefing and Intelligence strip list it under Stale …

## World entity lists

- [ ] **Last seen on lists** — link a location/faction/item/NPC to a session → World list row shows “Last seen: [session]”
- [ ] **Last touched (threads)** — linked plot thread shows “Last touched: [session]” on World list

## Brief Me (Campaign Briefing)

- [ ] **Brief Me** — World → Brief Me tile → digest loads all sections (Last Session, Active Plot Threads, Important NPCs, Recent Developments, Unresolved Questions, Dormant Threads, Needs Attention)
- [ ] **Print / Export** — Brief Me → Print / Export → clean print layout opens; Print hides toolbar
- [ ] **Download Markdown** — Brief Me → Download Markdown → `# Brief Me:` text file includes Phase 1 sections
- [ ] **Generate AI Summary** — Brief Me → Generate AI Summary (when LLM configured) → narrative paragraph saved and shown
- [ ] **No AI required** — Brief Me loads with campaign data only (no LLM call on page load)

## Entity detail

- [ ] **Health badge** — edit NPC/location/etc. → score + missing fields shown
- [ ] **History panel** — entity linked to 2+ sessions → First Seen / Last Seen, Appears In list, session links work; related entities and statistics shown
- [ ] **History badges** — entity not seen within intelligence gap → dormant; first seen in last 2 sessions → new
- [ ] **PC History** — party member linked via ingest/session → PC edit page shows session appearances
- [ ] **Relationship History** — link NPC to faction on edit → panel shows Linked; unlink → Unlinked
- [ ] **Ingest relationship log** — approve entity relationship on ingest → Relationship History shows session title on edit form
- [ ] **Entity edit session attribution** — link/unlink from workspace (`return_to`) or with persisted session cookie → Relationship History shows session title (not “via entity edit”)
- [ ] **Co-appearance Timeline** — NPC + linked faction both in same session → edit form shows shared session row

## Workspace ref panel

- [ ] **Session history on cards** — NPC/location/faction/item/thread linked across 2+ sessions → ref card shows “Session history” list
- [ ] **NPC returning flag** — NPC in session 1 and 2 → “returning” badge on session 2 workspace
- [ ] **Location returning flag** — same for linked location
- [ ] **Faction returning flag** — same for linked faction
- [ ] **Item returning flag** — same for linked item (optional smoke)
- [ ] **Thread dormant flag** — active thread last linked 2+ sessions ago → “dormant” on current session workspace (if still linked)
- [ ] **Prep-gap alert** — session with notes but no analysis → “needs analysis” banner; after analyze, no prep → “needs prep” banner

## Location admin

- [ ] **Types** — Major Location, Sub-Location, Scene Feature on create/edit
- [ ] **Ingest defaults** — vague places (chest, side passage) → Scene Feature or skipped in link options
- [ ] **Bulk delete / reclassify / merge** — Location Admin tools work without orphan links
