"""📦 Sandiq (Chest) tizimi — Mafia Bot."""
from __future__ import annotations
import random
from datetime import date
from typing import Optional

from profiles import get_profile, save_profile, spend_dollar, spend_diamond, add_dollar, add_diamond

# ── Narxlar ──────────────────────────────────────────────────
ODDIY_COST   = 500    # dollar
NOYOB_COST   = 2000   # dollar
OLTIN_COST   = 10     # diamond
OLTIN_LIMIT  = 2      # per day per user

# ── Himoya turlari ───────────────────────────────────────────
PROTECTION_TYPES = [
    ("shield",       "🛡 Himoya"),
    ("hang_protect", "⚖️ Osishdan himoya"),
    ("killer_protect","⛑️ Qotildan himoya"),
    ("drug_protect", "💊 Doridan himoya"),
    ("mask",         "🎭 Maska"),
    ("slip_protect", "🟨 Sirpanishdan himoya"),
    ("hero_protect", "🟩 Geroydan himoya"),
]

# Active sessions: user_id → {type, boxes, picks_left, picked}
_chest_sessions: dict[int, dict] = {}


def _rand_protections(count: int) -> list[tuple[str, str]]:
    return random.sample(PROTECTION_TYPES, min(count, len(PROTECTION_TYPES)))


def _make_boxes(chest_type: str) -> list[dict]:
    """6 ta tasodifiy sandiq tarkibini yaratadi."""
    items: list[dict] = []

    if chest_type == "oddiy":
        # 2 bo'sh, 1 himoya, 3 pul (400-800$)
        items.append({"kind": "empty"})
        items.append({"kind": "empty"})
        items.append({"kind": "protect", "protos": _rand_protections(1)})
        for _ in range(3):
            items.append({"kind": "dollar", "amount": random.randint(400, 800)})

    elif chest_type == "noyob":
        # 1 bo'sh, 1 himoya, 2 olmos (1-3💎), 2 pul (500-2500$)
        items.append({"kind": "empty"})
        items.append({"kind": "protect", "protos": _rand_protections(2)})
        for _ in range(2):
            items.append({"kind": "diamond", "amount": random.randint(1, 3)})
        for _ in range(2):
            items.append({"kind": "dollar", "amount": random.randint(500, 2500)})

    elif chest_type == "oltin":
        # 1 bo'sh, 1 himoya, 2 olmos (3-8💎), 2 pul (3000-7000$)
        items.append({"kind": "empty"})
        items.append({"kind": "protect", "protos": _rand_protections(3)})
        for _ in range(2):
            items.append({"kind": "diamond", "amount": random.randint(3, 8)})
        for _ in range(2):
            items.append({"kind": "dollar", "amount": random.randint(3000, 7000)})

    random.shuffle(items)
    return items


def box_emoji(box: dict, revealed: bool = False) -> str:
    if not revealed:
        return "📦"
    kind = box["kind"]
    if kind == "empty":
        return "❌"
    if kind == "dollar":
        return f"💵 {box['amount']}$"
    if kind == "diamond":
        return f"💎 {box['amount']}"
    if kind == "protect":
        labels = [p[1] for p in box.get("protos", [])]
        return "🛡 " + " + ".join(labels) if labels else "🛡"
    return "❓"


async def apply_box_reward(user_id: int, box: dict) -> str:
    """Tanlangan sandiq mukofotini profil balansiga qo'shadi. Natija matni qaytariladi."""
    kind = box["kind"]
    if kind == "empty":
        return "❌ Bo'sh sandiq"
    if kind == "dollar":
        await add_dollar(user_id, box["amount"])
        return f"💵 {box['amount']}$ qo'shildi!"
    if kind == "diamond":
        await add_diamond(user_id, box["amount"])
        return f"💎 {box['amount']} olmos qo'shildi!"
    if kind == "protect":
        p = await get_profile(user_id)
        labels = []
        for field, label in box.get("protos", []):
            cur = getattr(p, field, 0)
            setattr(p, field, cur + 1)
            labels.append(label)
        await save_profile(p)
        return "🛡 Himoya qo'shildi: " + ", ".join(labels) if labels else "🛡"
    return "❓"


async def can_open_oltin(user_id: int) -> tuple[bool, int]:
    """Oltin sandiq ochish mumkinmi? (mumkin, qolgan_son) qaytaradi."""
    p = await get_profile(user_id)
    today = str(date.today())
    if p.oltin_sandiq_date != today:
        return True, OLTIN_LIMIT
    remaining = OLTIN_LIMIT - p.oltin_sandiq_count
    return remaining > 0, remaining


async def record_oltin_open(user_id: int):
    """Oltin sandiq ochilganini qayd qiladi."""
    p = await get_profile(user_id)
    today = str(date.today())
    if p.oltin_sandiq_date != today:
        p.oltin_sandiq_date = today
        p.oltin_sandiq_count = 1
    else:
        p.oltin_sandiq_count += 1
    await save_profile(p)


def start_session(user_id: int, chest_type: str) -> dict:
    picks = 2 if chest_type == "oltin" else 1
    session = {
        "type": chest_type,
        "boxes": _make_boxes(chest_type),
        "picks_left": picks,
        "picked": [],   # list of picked indices
    }
    _chest_sessions[user_id] = session
    return session


def get_session(user_id: int) -> Optional[dict]:
    return _chest_sessions.get(user_id)


def clear_session(user_id: int):
    _chest_sessions.pop(user_id, None)
