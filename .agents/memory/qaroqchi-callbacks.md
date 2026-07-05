---
name: Qaroqchi Multi-step Night Callbacks
description: 4-step callback flow for Qaroqchi independent role with HP damage system.
---

# Qaroqchi Callback Flow

Step 1: `qar_mode1:{steal|attack}:{cid}` → stores `night_actions["qaroqchi_step1_mode"]`
Step 2: `qar_t1:{tid}:{cid}` → stores `night_actions["qaroqchi_action1"] = (mode, tid)`, shows step 2 choice
Step 3: `qar_mode2:{steal|attack}:{cid}` → stores `night_actions["qaroqchi_step2_mode"]`
Step 4: `qar_t2:{tid}:{cid}` → stores `night_actions["qaroqchi_action2"] = (mode, tid)`, marks done

Completion marker: `game.night_actions[Role.QAROQCHI] = True` AND `game.night_actions[actor.user_id] = True`

# HP System
- `Player.hp = 100` (only used by Qaroqchi)
- Each Qaroqchi attack: -50 HP
- Steal from broke target: -50 HP instead of money
- HP invariant enforced in night.py after Qaroqchi section: any alive player at hp<=0 added to pending
- No other roles use HP — safe to ignore hp field elsewhere
