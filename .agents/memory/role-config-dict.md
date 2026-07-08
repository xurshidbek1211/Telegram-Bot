---
name: Role Config Dict Migration
description: roles in rcfg session changed from set to dict[str,int]; countable roles need ➕/➖ UI
---

**Rule:** `session["roles"]` is now `dict[role_name: str, count: int]`. Everywhere that used to call `.discard()` or `.add()` on a set must now do `roles[name] = 0` / `roles[name] = count+1`.

**Countable roles** (COUNTABLE_RCFG_ROLES list): Serzhant, Tulki, Qotil, Afsungar, Citizen — rendered with ➕/➖ rows; all others are toggle (0 or 1).

**MAFIA field:** Stored as integer "extra Mafias" count (0 = Don only). Always cast `int(raw_mafia)` when loading from DB since old saves may have been True/1.

**Why:** Multiple copies of countable roles are game-balanced and user-requested. dict unifies counting and toggling in one data structure.

**How to apply:** In rcfgo, normalize legacy values. In rcfgr (toggle), set 0 or 1. In rcfgcr (countable), inc/dec. In rcfgs, serialize only entries with count > 0.
