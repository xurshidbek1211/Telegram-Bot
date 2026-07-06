---
name: Labarant Hidden Mafia Member
description: Labarant is mechanically in MAFIA_TEAM but must be hidden from visible ally lists and from mafia targeting restrictions.
---

Labarant is treated as a member of `MAFIA_TEAM` for win-condition, role-balance, and Tulki/conversion logic, but **Mafia allies must not know they have a Labarant**.

**Rule:** Any code that displays a "Mafia team" list to players must exclude `Role.LABARANT`.

**Why:** The role description says Mafia doesn't know the Labarant; leaking them in startup DMs or night ally lists breaks the role's design and gives Mafia an unfair advantage.

**How to apply:**
- Ally lists: filter with `p.role in MAFIA_TEAM and p.role != Role.LABARANT`.
- Target pickers: keep Labarant targetable by Mafia/YQ because they don't know who they are, so use `p.role not in MAFIA_TEAM or p.role == Role.LABARANT`.
- Advokat protection: exclude Labarant because Advokat doesn't know them either.
- Startup role DM: build a `_visible_mafia_names()` helper that excludes Labarant and give Labarant no team list.
- Check new uses of `MAFIA_TEAM` in ally UI or shared info channels before committing.