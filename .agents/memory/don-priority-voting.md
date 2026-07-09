---
name: Don Priority Mafia Voting
description: How mafia night kills are resolved — Don's vote overrides, member votes tallied on tie/no-Don.
---

## Rule
- `game.mafia_votes: dict` stores each mafia member's individual vote (uid → target_uid), reset each night.
- `game.night_actions["mafia_don_voted"] = True` is set when Don votes — used in resolve_night.
- When Don votes in `cb_nk`: mafia_kill is set, `mafia_don_voted` is True, ALL Don/MAFIA uids are added to `night_acted_uids` so night resolves immediately.
- When a non-Don Mafia member votes: only that voter is marked acted. Night waits for all other Mafia (required_night_actors returns ALL alive MAFIA when Don absent).
- In `resolve_night`: if `mafia_don_voted` → use `mafia_kill`. Else tally `game.mafia_votes`: majority wins, tie → events append "kelisha olishmadi" and mafia_target = None.
- Mafia vote notifications go to all visible Mafia members via DM only — no group atmosphere message.

**Why:** Spec requires Don's choice to be final and override members; ties should result in no kill.

**How to apply:** Any change to cb_nk or resolve_night night-kill section must respect this three-way branch: don_voted / no-don-tally / fallback.
