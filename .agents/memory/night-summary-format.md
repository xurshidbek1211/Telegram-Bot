---
name: Night summary & role-swap privacy
description: How death attribution and role-swap announcements are separated between group chat and DMs in the night-resolution flow.
---

# Design decision

`resolve_night()` in `night.py` returns `(deaths, events)`, not a flat event list.

- `deaths`: structured per-victim dicts (name/role/attackers) built at the very end from every kill source (main pending kills, afsungar counter-kill, mine explosions, gazabkor victims/suicide). Rendered by `_format_night_summary()` in handlers.py as the "📋 Kecha natijalari" block, showing each victim's role and who killed them ("Mehmoni"/"Mehmonlari", in arrival order).
- `events`: everything else that isn't a death (protection-survived notices, sotqin leak, gazabkor win suffix, konchi report) — shown as a separate block appended after the death summary, never mixed into it.

**Why:** the group message must show ONLY death info (per explicit product requirement); non-death informational lines still have value but must not pollute or be confused with the death list, and protected/saved players must never appear as dead.

**How to apply:** Automatic role-swap promotions (Serzhant→Komissar, Hamshira→Doktor, Admiral→Komissar, Tulki/Bo'ri transformations) are DM-only — never announce them in group chat. If adding a new auto-promotion or new kill-capable role, only send a DM to the affected player, and if it's a kill, add a matching `_tag(uid, Role)` call into `pending_attackers` alongside the `pending[uid] = cause` assignment so it shows up correctly in the death summary.
