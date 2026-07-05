---
name: Mafia Bot Architecture
description: Key design decisions about night action key storage and action completion detection.
---

# Night Action Key Storage Convention

Most callbacks store actions under **Role enum keys** (e.g. `game.night_actions[Role.DOCTOR] = target_id`), NOT user IDs.

Exceptions that store UID keys:
- Mafia/Don: stores `game.night_actions[actor.user_id] = tid` AND `game.night_actions["mafia_kill"] = tid`
- Qaroqchi: stores `game.night_actions[actor.user_id] = True` when both steps done

**Why:** `all_night_actions_done()` checks if `required_night_actors()` (a set of UIDs) is subset of `night_actions.keys()`. This only works for roles that explicitly store their UID as a key.

**How to apply:** When adding new active-night roles, you MUST store the actor's user_id in night_actions to allow early completion. Also add `game.night_acted_uids.add(uid)` for AFK tracking.

# AFK System
- `night_required_snapshot` = copy of required_night_actors() at night start
- `night_acted_uids` = set of UIDs who submitted any night action
- 2 consecutive missed nights → auto-kick
- Auto-skipped actions (e.g. Advokat with no valid targets) MUST add to `night_acted_uids` to avoid false AFK penalties
