import json
import os
from dataclasses import dataclass, field

from database import get_pool

OWNER_ID = int(os.environ.get("OWNER_ID", "0"))

_FIELDS = [
    "user_id", "first_name", "dollar", "diamond", "wins", "games",
    "infinite_diamond", "infinite_dollar", "shield", "documents",
    "hang_protect", "killer_protect", "gun", "drug_protect", "mask",
    "slip_protect", "hero_protect", "mines", "active_roles",
    "oltin_sandiq_date", "oltin_sandiq_count",
]


@dataclass
class Profile:
    user_id: int
    first_name: str = ""
    dollar: int = 0
    diamond: int = 0
    wins: int = 0
    games: int = 0
    infinite_diamond: bool = False
    infinite_dollar: bool = False
    shield: int = 0
    documents: int = 0
    hang_protect: int = 0
    killer_protect: int = 0
    gun: int = 0
    drug_protect: int = 0
    mask: int = 0
    slip_protect: int = 0
    hero_protect: int = 0
    mines: int = 0
    active_roles: list = field(default_factory=list)
    oltin_sandiq_date: str = ""
    oltin_sandiq_count: int = 0


_cache: dict[int, Profile] = {}


def _row_to_profile(row) -> Profile:
    d = dict(row)
    ar = d.get("active_roles", [])
    if isinstance(ar, str):
        ar = json.loads(ar)
    return Profile(
        user_id=d["user_id"],
        first_name=d.get("first_name", ""),
        dollar=d.get("dollar", 0),
        diamond=d.get("diamond", 0),
        wins=d.get("wins", 0),
        games=d.get("games", 0),
        infinite_diamond=bool(d.get("infinite_diamond", False)),
        infinite_dollar=bool(d.get("infinite_dollar", False)),
        shield=d.get("shield", 0),
        documents=d.get("documents", 0),
        hang_protect=d.get("hang_protect", 0),
        killer_protect=d.get("killer_protect", 0),
        gun=d.get("gun", 0),
        drug_protect=d.get("drug_protect", 0),
        mask=d.get("mask", 0),
        slip_protect=d.get("slip_protect", 0),
        hero_protect=d.get("hero_protect", 0),
        mines=d.get("mines", 0),
        active_roles=ar or [],
        oltin_sandiq_date=d.get("oltin_sandiq_date", ""),
        oltin_sandiq_count=int(d.get("oltin_sandiq_count", 0)),
    )


def _apply_owner(p: Profile) -> Profile:
    if OWNER_ID and p.user_id == OWNER_ID:
        p.infinite_diamond = True
        p.infinite_dollar = True
    return p


async def get_profile(user_id: int, first_name: str = "") -> Profile:
    if user_id in _cache:
        p = _cache[user_id]
        if first_name:
            p.first_name = first_name
        return _apply_owner(p)

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM profiles WHERE user_id = $1", user_id
        )
    if row:
        p = _row_to_profile(row)
        if first_name:
            p.first_name = first_name
    else:
        p = Profile(user_id=user_id, first_name=first_name)

    _apply_owner(p)
    _cache[user_id] = p
    return p


async def save_profile(profile: Profile):
    _apply_owner(profile)
    _cache[profile.user_id] = profile
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO profiles (
                user_id, first_name, dollar, diamond, wins, games,
                infinite_diamond, infinite_dollar, shield, documents,
                hang_protect, killer_protect, gun, drug_protect, mask,
                slip_protect, hero_protect, mines, active_roles,
                oltin_sandiq_date, oltin_sandiq_count
            ) VALUES (
                $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21
            )
            ON CONFLICT (user_id) DO UPDATE SET
                first_name = EXCLUDED.first_name,
                dollar = EXCLUDED.dollar,
                diamond = EXCLUDED.diamond,
                wins = EXCLUDED.wins,
                games = EXCLUDED.games,
                infinite_diamond = EXCLUDED.infinite_diamond,
                infinite_dollar = EXCLUDED.infinite_dollar,
                shield = EXCLUDED.shield,
                documents = EXCLUDED.documents,
                hang_protect = EXCLUDED.hang_protect,
                killer_protect = EXCLUDED.killer_protect,
                gun = EXCLUDED.gun,
                drug_protect = EXCLUDED.drug_protect,
                mask = EXCLUDED.mask,
                slip_protect = EXCLUDED.slip_protect,
                hero_protect = EXCLUDED.hero_protect,
                mines = EXCLUDED.mines,
                active_roles = EXCLUDED.active_roles,
                oltin_sandiq_date = EXCLUDED.oltin_sandiq_date,
                oltin_sandiq_count = EXCLUDED.oltin_sandiq_count
            """,
            profile.user_id, profile.first_name, profile.dollar, profile.diamond,
            profile.wins, profile.games, profile.infinite_diamond, profile.infinite_dollar,
            profile.shield, profile.documents, profile.hang_protect, profile.killer_protect,
            profile.gun, profile.drug_protect, profile.mask, profile.slip_protect,
            profile.hero_protect, profile.mines, json.dumps(profile.active_roles),
            profile.oltin_sandiq_date, profile.oltin_sandiq_count,
        )


async def add_dollar(user_id: int, amount: int):
    p = await get_profile(user_id)
    if not p.infinite_dollar:
        p.dollar += amount
        await save_profile(p)


async def spend_dollar(user_id: int, amount: int) -> bool:
    p = await get_profile(user_id)
    if p.infinite_dollar:
        return True
    if p.dollar < amount:
        return False
    p.dollar -= amount
    await save_profile(p)
    return True


async def add_diamond(user_id: int, amount: int):
    p = await get_profile(user_id)
    if not p.infinite_diamond:
        p.diamond += amount
        await save_profile(p)


async def spend_diamond(user_id: int, amount: int) -> bool:
    p = await get_profile(user_id)
    if p.infinite_diamond:
        return True
    if p.diamond < amount:
        return False
    p.diamond -= amount
    await save_profile(p)
    return True


async def transfer_diamond(giver_id: int, target_id: int, amount: int) -> bool:
    giver = await get_profile(giver_id)
    target = await get_profile(target_id)
    if not giver.infinite_diamond and giver.diamond < amount:
        return False
    if not giver.infinite_diamond:
        giver.diamond -= amount
    target.diamond += amount
    await save_profile(giver)
    await save_profile(target)
    return True


async def transfer_dollar(giver_id: int, target_id: int, amount: int) -> bool:
    giver = await get_profile(giver_id)
    target = await get_profile(target_id)
    if not giver.infinite_dollar and giver.dollar < amount:
        return False
    if not giver.infinite_dollar:
        giver.dollar -= amount
    target.dollar += amount
    await save_profile(giver)
    await save_profile(target)
    return True


async def record_game_start(user_id: int, first_name: str = ""):
    p = await get_profile(user_id, first_name)
    p.games += 1
    await save_profile(p)


async def record_win(user_id: int, dollar_reward: int = 40):
    p = await get_profile(user_id)
    p.wins += 1
    if not p.infinite_dollar:
        p.dollar += dollar_reward
    await save_profile(p)
