"""Geroy (Hero) tizimi — Mafia Bot."""
from __future__ import annotations
import json
import random
from dataclasses import dataclass, field
from typing import Optional
from database import get_pool

# ── Narxlar & limitlar ──────────────────────────────────────
MAX_HP              = 80
MAX_CHARGES         = 10
HP_RESTORE_COST     = 1200   # dollar
CHARGE_RESTORE_COST = 1300   # dollar
NAME_CHANGE_COST    = 2500   # dollar
HERO_BUY_COST       = 90     # diamond
XP_BUY_COST         = 500    # dollar
XP_BUY_AMOUNT       = 100    # ball
XP_PER_ATTACK       = 5


# ── Daraja hisoblash ─────────────────────────────────────────

def hero_level_threshold(level: int) -> int:
    """Ushbu darajaga yetish uchun kerakli umumiy XP (1-darajadan).
    2→1000, 3→2100, 4→3300 (har bir daraja 100 ball ko'proq talab qiladi)."""
    if level <= 1:
        return 0
    total, step = 0, 1000
    for _ in range(2, level + 1):
        total += step
        step += 100
    return total


def hero_level_from_xp(xp: int) -> int:
    """Umumiy XP bo'yicha joriy darajani hisoblaydi."""
    level = 1
    while level < 100 and xp >= hero_level_threshold(level + 1):
        level += 1
    return level


def hero_upgrade_cost(level: int) -> int:
    """Ushbu darajadan keyingisiga oshirish narxi (olmos). N→N+1 = (N+2)×10."""
    return (level + 2) * 10


def hero_damage(level: int) -> int:
    """Ushbu darajada Geroy bera oladigan tasodifiy zarar (HP)."""
    min_d = 40 + (level - 1) * 15
    max_d = 50 + (level - 1) * 15
    return random.randint(min_d, max_d)


def hero_next_xp(hero: "Hero") -> int:
    """Keyingi darajaga yetish uchun qolgan XP."""
    return max(0, hero_level_threshold(hero.level + 1) - hero.xp)


# ── Dataclass ────────────────────────────────────────────────

@dataclass
class Hero:
    user_id: int
    name: str = "Geroy"
    level: int = 1
    xp: int = 0
    hp: int = MAX_HP
    charges: int = MAX_CHARGES
    total_attacks: int = 0
    kills: int = 0
    completed_missions: dict = field(
        default_factory=lambda: {"kills": [], "levels": [], "activity": []}
    )


# ── DB ───────────────────────────────────────────────────────

def _parse_cm(raw) -> dict:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            raw = {}
    if not isinstance(raw, dict):
        raw = {}
    raw.setdefault("kills", [])
    raw.setdefault("levels", [])
    raw.setdefault("activity", [])
    return raw


async def get_hero(user_id: int) -> Optional[Hero]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM heroes WHERE user_id = $1", user_id
        )
    if not row:
        return None
    d = dict(row)
    return Hero(
        user_id=d["user_id"],
        name=d.get("name", "Geroy"),
        level=d.get("level", 1),
        xp=d.get("xp", 0),
        hp=d.get("hp", MAX_HP),
        charges=d.get("charges", MAX_CHARGES),
        total_attacks=d.get("total_attacks", 0),
        kills=d.get("kills", 0),
        completed_missions=_parse_cm(d.get("completed_missions")),
    )


async def save_hero(hero: Hero):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO heroes (
                user_id, name, level, xp, hp, charges,
                total_attacks, kills, completed_missions
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
            ON CONFLICT (user_id) DO UPDATE SET
                name               = EXCLUDED.name,
                level              = EXCLUDED.level,
                xp                 = EXCLUDED.xp,
                hp                 = EXCLUDED.hp,
                charges            = EXCLUDED.charges,
                total_attacks      = EXCLUDED.total_attacks,
                kills              = EXCLUDED.kills,
                completed_missions = EXCLUDED.completed_missions
        """,
        hero.user_id, hero.name, hero.level, hero.xp, hero.hp,
        hero.charges, hero.total_attacks, hero.kills,
        json.dumps(hero.completed_missions))


async def delete_hero(user_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM heroes WHERE user_id = $1", user_id)


# ── Missiyalar ───────────────────────────────────────────────

KILL_MISSIONS: list[tuple[int, dict]] = [
    (10,  {"diamond": 5,  "dollar": 1000}),
    (20,  {"diamond": 8,  "dollar": 1500}),
    (30,  {"diamond": 10, "dollar": 2000}),
    (40,  {"diamond": 13, "dollar": 2500}),
    (50,  {"diamond": 15, "dollar": 3000}),
    (60,  {"diamond": 18, "dollar": 3500}),
    (70,  {"diamond": 20, "dollar": 4000}),
    (80,  {"diamond": 23, "dollar": 4500}),
    (90,  {"diamond": 25, "dollar": 5000}),
    (100, {"diamond": 30, "dollar": 6000}),
]

LEVEL_MISSIONS: list[tuple[int, dict]] = [
    (5,  {"diamond": 10}),
    (10, {"diamond": 20}),
    (15, {"diamond": 30}),
    (20, {"diamond": 50}),
]

ACTIVITY_MISSIONS: list[tuple[int, dict]] = [
    (20,  {"dollar": 1000,  "charges": 1}),
    (40,  {"dollar": 1500,  "charges": 2}),
    (60,  {"dollar": 2000,  "charges": 3}),
    (80,  {"dollar": 2500,  "charges": 4}),
    (100, {"dollar": 3000,  "diamond": 10, "charges": 5}),
    (150, {"dollar": 4000,  "diamond": 15, "charges": 6}),
    (200, {"dollar": 5000,  "diamond": 20, "charges": 8}),
    (300, {"dollar": 7000,  "diamond": 30, "charges": 10}),
    (500, {"dollar": 10000, "diamond": 50, "charges": 15}),
]


async def check_and_award_missions(hero: Hero) -> list[str]:
    """Yangi bajarilgan missiyalarni tekshirib mukofot beradi. Mukofot matnlari qaytariladi."""
    from profiles import add_dollar, add_diamond
    awards: list[str] = []
    cm = hero.completed_missions

    for threshold, rewards in KILL_MISSIONS:
        if threshold not in cm["kills"] and hero.kills >= threshold:
            cm["kills"].append(threshold)
            parts: list[str] = []
            if "dollar" in rewards:
                await add_dollar(hero.user_id, rewards["dollar"])
                parts.append(f"💶 {rewards['dollar']}")
            if "diamond" in rewards:
                await add_diamond(hero.user_id, rewards["diamond"])
                parts.append(f"💎 {rewards['diamond']}")
            awards.append(f"☠️ {threshold} ta o'ldirish: {' + '.join(parts)}")

    for threshold, rewards in LEVEL_MISSIONS:
        if threshold not in cm["levels"] and hero.level >= threshold:
            cm["levels"].append(threshold)
            parts = []
            if "diamond" in rewards:
                await add_diamond(hero.user_id, rewards["diamond"])
                parts.append(f"💎 {rewards['diamond']}")
            awards.append(f"⭐ {threshold}-daraja: {' + '.join(parts)}")

    for threshold, rewards in ACTIVITY_MISSIONS:
        if threshold not in cm["activity"] and hero.total_attacks >= threshold:
            cm["activity"].append(threshold)
            parts = []
            if "dollar" in rewards:
                await add_dollar(hero.user_id, rewards["dollar"])
                parts.append(f"💶 {rewards['dollar']}")
            if "diamond" in rewards:
                await add_diamond(hero.user_id, rewards["diamond"])
                parts.append(f"💎 {rewards['diamond']}")
            if "charges" in rewards:
                hero.charges = min(hero.charges + rewards["charges"], MAX_CHARGES)
                parts.append(f"🩸 +{rewards['charges']} zaryad")
            awards.append(f"⚔️ {threshold} ta hujum: {' + '.join(parts)}")

    if awards:
        await save_hero(hero)

    return awards
