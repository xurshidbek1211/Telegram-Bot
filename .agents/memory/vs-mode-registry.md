---
name: VS Mode Single Registry
description: VS games share the same `games` dict as regular games; vs_mode=True distinguishes them
---

**Rule:** Both regular Mafia games and VS Mode games are stored in `handlers.games[chat_id]`. `vs_game.py` accesses it via `_get_games()` (lazy import to avoid circular). There is no separate `vs_games` dict.

**Why:** Separate registries allowed simultaneous regular+VS lobbies in one chat, creating race conditions and stale state. Single registry enforces mutual exclusion at the chat level.

**How to apply:**
- `/vsgame` checks `games.get(chat_id)` and blocks if any non-ENDED game exists (regular or VS).
- `_launch_vs_game` does NOT re-register the game; it was already stored in the lobby phase.
- `end_vs_game` pops the entry from `games` after announcing results.
- `cb_vs_newgame` checks the registry before creating a fresh VS lobby.
- VS game identification: `game.vs_mode == True`.
