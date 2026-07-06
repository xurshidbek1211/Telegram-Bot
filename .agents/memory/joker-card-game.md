---
name: Joker Card Game Flow
description: Joker selects a death card + target at night; the target receives 4 shuffled cards during voting and must pick before the timer ends.
---

The Joker card game is split across night and voting phases.

**Rule:**
1. **Night:** Joker picks a death-card index (0..3) and a target player. Store this in `game.joker_pending` with the original card list.
2. **Night resolution:** Do NOT kill the target. Only persist `joker_pending`.
3. **Voting start:** `_send_joker_cards` shuffles the 4 cards and DMs them to the target with `jokpick` callbacks.
4. **During voting:** If the target picks a card, `_resolve_joker_card` kills them on the death card or announces survival on a safe card. Clear `joker_pending` after use.
5. **Voting timeout:** If `joker_pick` is still `None` when `_do_vote_resolution` runs, auto-resolve as death card and kill the target.

**Why:** The card game must be delayed to voting phase so the target can interact with it; killing at night would skip the intended UX.

**How to apply:**
- Always clear `joker_pending` after resolution (success or auto-timeout) to keep it one-time use.
- Guard `jokpick` callbacks so only the intended target can pick.
- Vote tally must filter dead targets because a Joker kill can happen mid-voting.