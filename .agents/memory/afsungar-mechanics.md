---
name: Afsungar mechanics
description: Afsungar night counter-kill, special victory, and daytime revenge resolution rules.
---

# Rule

Afsungar's night death records every actual attacker who visited the target. Don or Qotil attacking Afsungar sets the special Afsungar victory; every other attacker is counter-killed except Yollanma Qotil. During daytime revenge, the eliminated Afsungar gets one authenticated target choice; selecting Mafia grants the special victory, while selecting a non-Mafia target loses. The timeout continuation must not start a second night after a callback resolves the revenge.

**Why:** Afsungar can die before its win condition resolves, and Mafia attacks may have multiple participants even though they share one target.

**How to apply:** Preserve the special winner state after Afsungar dies, track attacker roles independently from the single pending kill cause, and guard the 30-second revenge continuation whenever changing the callback or vote-resolution flow.