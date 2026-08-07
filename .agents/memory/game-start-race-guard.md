---
name: Game Start Race Guard
description: Rules that prevent late joins and duplicate starts while roles are being assigned.
---

## Rule
- A game claims `Phase.STARTING` before its first awaited operation when regular or VS startup begins.
- `Game.add_player()` accepts players only while the game is in `Phase.LOBBY`, so every join path is protected even if a phase check happened before an await.
- The roster is snapshotted before role assignment. After assignment, startup validates that the player IDs are unchanged and every player has a non-None role. A failed validation ends the broken game and logs the cause.

**Why:** Telegram can deliver join links and duplicate start actions while profile/settings/database awaits are in progress; mutating the roster then can produce duplicate or missing role assignments.

**How to apply:** Any new start or join path must use the same LOBBY-only mutation rule and must never bypass the STARTING claim.