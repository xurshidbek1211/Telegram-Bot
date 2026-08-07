---
name: Journalist Interview Privacy
description: Visibility rules for the Journalist's night interview report.
---

## Rule
The Journalist's report must be sent only to the Journalist. Visitors whose role is in `MAFIA_TEAM` are omitted entirely, including both their name and role. Non-Mafia civilian and independent visitors are shown with their name and role.

**Why:** The Mafia team must not leak through an interview result, while the Journalist's intended information is limited to peaceful and independent roles.

**How to apply:** Any future visitor-report path for the Journalist must filter by `role not in MAFIA_TEAM` before formatting names or role labels.