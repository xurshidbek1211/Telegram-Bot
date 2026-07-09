---
name: Mafia Night Target Badges
description: 🤵/👮 badges shown in night action keyboards so team members can identify each other.
---

## Rule
- `_mafia_target_kb(game, prefix, actor_id, exclude_mafia=False)` — shows `🤵 ` before MAFIA_TEAM member names in the keyboard. Used by: ADVOKAT (nadv), JURNALIST (njurn), LABARANT (nlab), AYGOQCHI (naygoychi).
- `_komissar_target_kb(game, prefix, actor_id)` — shows `👮 ` before KOMISSAR/SERZHANT member names. Used in `cb_nkommode` after mode selection (for "nkom" prefix).
- DON/MAFIA/YQ target lists already exclude MAFIA_TEAM for kill selection — no badge needed there (allies shown in text above keyboard).
- Badges are ONLY in private DM keyboards. Never in group messages.

**Why:** Spec requires team members to see each other labeled when selecting night action targets.

**How to apply:** Any new role that's on the mafia side and can target any player should use `_mafia_target_kb`. Komissar-side roles use `_komissar_target_kb`.
