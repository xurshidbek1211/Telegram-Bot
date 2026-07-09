---
name: Last Words Feature
description: Eliminated players get one chance to send a text that posts to the group as "So'nggi so'z".
---

## Rule
- `game.pending_last_words: set` holds UIDs of recently eliminated players waiting to send their message. Reset is NOT done per night (persists until player sends or game ends).
- `_send_last_words_dm(bot, game, uid)` adds uid to pending_last_words and DMs the player.
- Called from `_do_night_resolution` (for each death in deaths list + afk_kicked) and `_do_vote_resolution` (after game.eliminate_player for Afsungar and normal elimination).
- Handler `_handle_last_words` is the ONLY registered private non-command handler; it checks pending_last_words first, then falls through to `_private_team_relay_inner`.
- Only plain text accepted — media/stickers rejected with error message.
- After one message, uid is discarded from pending_last_words immediately.
- Group format: `🕊 *So'nggi so'z*\n\n☠️ {name}:\n\n{text}`

**Why:** Spec requires dead players to have one last-words text sent to group, text only.

**How to apply:** If adding new elimination paths, call `_send_last_words_dm()` after each `game.eliminate_player()` call.
