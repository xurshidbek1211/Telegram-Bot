---
name: VS Mode Separate Registry
description: vs_game.py uses own vs_games dict for lobby; on start moves into handlers.games.
---

## Rule
- `vs_games: dict[int, Game]` is module-level in `vs_game.py` — used for lobby phase only.
- `/vsgame` command creates Game(vs_mode=True) in `vs_games`, NOT in `handlers.games`.
- `_launch_vs_game` moves the game into `regular_games[chat_id]` (handlers.games) so night/day logic (`run_night` etc.) can find it.
- `end_vs_game` removes from both `regular_games` and `vs_games`.
- `/game` (`_open_lobby`) only sees `handlers.games` — so VS lobbies don't block regular game creation.
- All cross-module references use lazy imports inside function bodies to avoid circular imports.

**Why:** Sharing one registry caused VS lobby to be picked up by regular game logic. Separate dict isolates lobby; shared dict during play reuses existing night logic.

**How to apply:** VS lobby state → vs_games; VS active game → also in handlers.games (night loop); cleanup must remove from both.
