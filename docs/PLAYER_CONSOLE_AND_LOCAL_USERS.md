# Campaign Console — Local Users & Player Console

Status: approved for implementation

## Goal

Add a deliberately player-facing companion experience to Campaign Console without turning the application into a VTT, character-sheet platform, chat server, or generic campaign wiki.

The feature has two coupled parts:

1. **Application-local users and campaign membership** that do not depend on YunoHost/server accounts.
2. **Player Console**, a player-safe field journal over the same campaign data used by GM Mission Control.

The GM experience remains authoritative. Player data represents what a player knows, remembers, suspects, or writes down.

---

## Design principles

### Separate surfaces, shared campaign

The Player Console is not the GM Console with buttons hidden. It uses dedicated routes, templates, services, and safe projections.

Suggested route families:

- `/login`, `/logout`, `/account/...`
- `/admin/users/...`
- `/campaigns/{campaign_id}/members/...`
- `/player/`
- `/player/campaigns/{campaign_id}/...`

### Default-deny player data access

GM-only fields must never be placed into player-facing query/view models and then hidden in templates.

Examples that remain GM-only unless deliberately copied into a reveal:

- NPC secrets
- Plot-thread secret notes and unrevealed clues
- campaign/plot significance notes
- GM workspace notes
- analyses and raw model output
- next-session prep
- AI prep/reasoning
- entity health/intelligence metadata
- internal relationship/history metadata that reveals undisclosed facts

### Keep permissions simple

Initial campaign roles:

- `owner`
- `gm`
- `player`

Do not build arbitrary RBAC or per-field ACL configuration in this phase.

### Preserve current self-hosted architecture

Continue using FastAPI, SQLModel, Jinja, SQLite, and local static assets. No React/Vue requirement and no external identity provider requirement.

---

# Part A — Local users and campaign membership

## User model

Add an application-local identity model approximately equivalent to:

```text
User
----
id
username
display_name
email?                  optional
password_hash
is_admin
is_active
must_change_password
created_at
updated_at
last_login_at?
```

Requirements:

- usernames are unique and case-normalized
- passwords are never stored or logged in plaintext
- use Argon2id through an established password-hashing library
- changing a password invalidates existing sessions if practical
- account disablement immediately blocks new authenticated requests

## Campaign membership

```text
CampaignMembership
------------------
id
campaign_id
user_id
role                    owner | gm | player
player_character_id?    optional PlayerCharacterNote
created_at
updated_at
```

Constraints:

- unique campaign/user membership
- a player membership may be linked to a `PlayerCharacterNote`
- owner/gm may open Player Console for testing but retain GM capabilities elsewhere
- a user can belong to multiple campaigns

## Application sessions

Use opaque server-side sessions rather than JWTs.

Suggested data:

```text
AppSession
----------
id/token_hash
user_id
created_at
last_seen_at
expires_at
```

Cookie requirements:

- HttpOnly
- SameSite=Lax or stricter where compatible
- Secure when served over HTTPS
- no user authorization state stored solely in a client-controlled cookie

Add:

- login
- logout
- session expiration
- current-user dependency/helper
- campaign-role authorization helpers
- CSRF protection for authenticated state-changing form requests
- basic login throttling

## Bootstrap behavior

A fresh install needs a deterministic path to its first administrator.

Preferred approach:

- if no users exist, expose a one-time local setup page or documented CLI/bootstrap command
- once the first admin exists, bootstrap setup cannot create additional admins
- the admin can create further local users from the UI

Do not require creating a Unix/YunoHost account for a player.

## User administration

GM/admin UI should support:

- create user
- activate/deactivate
- set/reset temporary password
- require password change
- add/remove campaign membership
- choose role
- associate player membership with an existing `PlayerCharacterNote`

Avoid email-reset infrastructure in this phase.

---

# Part B — Player-safe campaign information

## Existing PlayerCharacterNote

`PlayerCharacterNote` remains the canonical campaign PC record.

Do not create a duplicate player-character model.

Its existing relationships to sessions, locations, factions, and plot threads should be reused by the player experience where those related records have been revealed.

GM-only fields on the PC record must still be separated from player-safe fields.

## Reveal model

Use explicit player-safe records instead of exposing the GM entity wholesale.

Suggested base model:

```text
PlayerReveal
------------
id
campaign_id
entity_kind
entity_id
title?
public_summary
revealed_at
revealed_session_id?
created_by_user_id?
updated_at
```

Audience can be modeled either on the reveal or with a link table:

```text
RevealAudience
--------------
reveal_id
user_id? / membership_id?
```

Supported semantics:

- whole campaign / all players
- selected player memberships

A reveal should preserve when information became available so future features can answer: “What did this player know after Session N?”

A reveal is a safe projection, not permission to read the underlying GM record.

## Reveal workflow

From GM entity pages, provide a clear action such as **Player Info / Reveal**.

The GM should be able to:

- preview current player-facing text
- edit the safe summary independently of GM notes
- reveal to all players or selected PCs/members
- associate the reveal with a session
- update/correct revealed text
- revoke a reveal

A reveal update must not overwrite canonical GM fields.

---

# Part C — Player Console

## Player shell

Use a separate player-oriented shell and navigation. Reuse visual tokens where helpful, but optimize for readable reference and note taking rather than dense GM mission control.

Primary navigation:

- Home
- Journal
- Lore
- Sessions
- Character

## Player home

Show:

- campaign title/system
- linked character identity
- latest player recap
- recent reveals/discoveries
- pinned journal notes
- unresolved player-authored clues/theories
- recent sessions

Do not show GM intelligence, completeness scores, prep gaps, secret/unrevealed counts, or hidden entity existence.

## Lore

Player-facing categories may include:

- NPCs
- Locations
- Factions
- Items
- Creatures
- Plot Threads / Quests

Only revealed records are discoverable.

Player lore pages display the safe reveal content plus player-authored notes linked to that entity where appropriate.

Search must operate on player-visible material only. Do not call the existing GM campaign search and filter the result afterward if that risks hidden result leakage.

## Sessions

Players may read:

- session title/date
- `player_recap`
- player-safe/revealed lore associated with that session
- their own journal entries associated with that session

They must not receive:

- GM notes
- recap variants intended only for the GM
- analysis/raw analysis
- next-session prep
- workspace notes

## Character

Show player-safe portions of the linked `PlayerCharacterNote` and relationships that have been revealed.

This is not a rules-system character sheet.

No stat block, spell manager, inventory rules engine, dice roller, leveling engine, or rules automation is required.

---

# Part D — Journal

## Journal entry

Suggested model:

```text
PlayerJournalEntry
------------------
id
campaign_id
author_user_id
player_character_id?
session_id?
title
body
visibility              private | gm | party
is_pinned
created_at
updated_at
```

Add optional tags and entity links.

Entity links should support the campaign entity types already modeled by Campaign Console.

## Visibility

### private
Visible only to the author.

### gm
Visible to the author and campaign owner/gm memberships.

### party
Visible to campaign members.

The GM must not silently edit a player's journal entry. If moderation/removal is eventually required, record that separately; it is not necessary for the first implementation.

## Clues and theories

Do not create a separate complex subsystem initially.

Support clue/theory behavior through journal metadata/tags or a small entry type/status:

- note
- clue
- theory
- question

Optional status:

- open
- resolved

This allows the Home page to show unresolved questions without creating a second note database.

---

# Authorization contract

Authorization must be enforced server-side.

Minimum rules:

1. Anonymous users may access only login/bootstrap/static endpoints.
2. Admin can manage users.
3. Owner/GM can use the existing GM application for campaigns in which they have that role.
4. Player cannot enter GM routes for a campaign.
5. Player may enter Player Console only for campaigns where they have membership.
6. A player may only read reveals whose audience includes them or the campaign.
7. A player may mutate only their own journal entries.
8. GM may read entries shared with `gm` or `party`, but not `private`.
9. Search/export endpoints must respect the same authorization boundaries.
10. IDs from another campaign must never succeed merely because the object exists.

Do not treat UI hiding as authorization.

---

# Migration and compatibility

Campaign Console already contains usable campaigns with no users.

Migration must not lock the existing owner out.

On upgrade:

- existing campaign/world data remains intact
- no `PlayerCharacterNote` duplication
- admin bootstrap is available when the user table is empty
- existing GM routes continue working after authentication is established
- backup/export behavior is reviewed for the new tables and secrets

Passwords and live session tokens should not be exposed in campaign exports.

---

# Testing requirements

At minimum add tests for:

## Authentication

- bootstrap first admin
- duplicate username rejection
- successful/failed login
- logout/session invalidation
- disabled user rejection
- password hash is not plaintext
- unauthenticated redirect/401 behavior as appropriate
- CSRF rejection for protected mutation

## Authorization

- player denied GM campaign routes
- player denied another campaign
- player cannot enumerate hidden lore by direct ID
- GM can access authorized campaign
- cross-campaign IDs fail safely

## Reveals

- unrevealed entity absent from Player Console and player search
- campaign-wide reveal visible to players
- selected-player reveal visible only to selected memberships
- GM secret fields never appear in player responses/templates
- revoked reveal disappears

## Journal

- private entry author-only
- gm-shared entry visible to author + GM
- party entry visible to campaign members
- another player cannot edit/delete author's entry
- links to unrevealed entities do not leak underlying data

## Regression

Run the existing test suite and preserve the current GM workflows.

---

# Explicit non-goals

Do not add in this phase:

- VTT/map/token system
- dice roller
- initiative tracker
- rules-system character sheets
- spell/feat/inventory engine
- campaign chat
- voice/video
- external OAuth/SSO requirement
- arbitrary RBAC designer
- JWT-based SPA authentication
- player-facing AI chatbot
- device/mobile app
- public campaign publishing

---

# Recommended implementation order

1. Local user/session foundation
2. Campaign memberships and route authorization
3. Player-safe reveal model/service
4. Player Console read-only shell and lore/session views
5. Journal and visibility
6. GM reveal-management UI
7. Player-safe search and polish
8. Security/regression pass

Authentication/authorization is intentionally first. Do not build the Player Console on unauthenticated routes and retrofit security later.

## Phase 2 implementation clarification

The Phase 2 implementation uses membership-oriented selected audiences. `PlayerReveal.audience_mode` is explicitly `campaign` or `selected`; selected reveals use `RevealAudience.membership_id` links. This explicit mode is intentionally fail-closed: a selected reveal with no resolvable audience rows is visible to nobody rather than becoming campaign-wide.

For campaign backup, reveal rows and audience-link rows are preserved while application users and session credentials remain excluded. Membership IDs are installation-local references; a restore into a different identity database may require audience reassociation before selected reveals become visible.
