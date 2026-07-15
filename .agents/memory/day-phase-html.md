---
name: Day Phase HTML Redesign
description: Group messages use HTML with clickable mentions; flood-control helpers prevent game freeze on TelegramRetryAfter.
---

# Day Phase HTML Redesign

## The rule
All group-chat messages that name players use `parse_mode="HTML"` with `<a href="tg://user?id=…">name</a>` mentions built by `_player_mention_html(game, p)`. DMs and other messages keep `parse_mode="Markdown"`.

**Why:** Markdown @mentions don't work reliably for users without usernames; HTML tg:// links always work.

## How to apply
- Use `_player_mention_html(game, p)` wherever a player name goes in a group message.
- Use `_safe_send` / `_safe_edit_text` / `_safe_edit_markup` instead of `bot.send_message` / `bot.edit_message_text` in game-flow code paths.
- Use `_safe_task(coro)` instead of `asyncio.create_task(coro)` for all fire-and-forget tasks — it logs exceptions instead of swallowing them.

## Flood-control fix
`TelegramRetryAfter` used to crash `_run_hang_confirmation` and leave the game frozen in VOTING phase. Fix:
1. `_do_vote_resolution` sets `game.phase = Phase.DAY` at the very top (before any awaits) so stale vote callbacks are rejected immediately.
2. All group sends in the voting/day path use `_safe_send` / `_safe_edit_text` which retry up to 4 times, sleeping `retry_after + 1` seconds each time.

## Sheriklari DM
At game start, each mafia member (and Komissar/Serzhant pair) receives a separate "Sheriklaringizni eslab qoling!" HTML DM with clickable ally mentions, sent via the inner `_sheriklari_dm` helper in `_launch_game`.

## labarant_show setting
`ChatSettings.labarant_show` (default True) controls whether Labarant appears in ally lists for DON, MAFIA, YOLLANMA_QOTIL, JURNALIST, AYGOQCHI, and whether Labarant sees their own allies. Toggle via /sozlash → 🧪 Labarantni ko'rish button.
