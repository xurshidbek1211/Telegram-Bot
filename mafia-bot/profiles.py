import json
import os
from dataclasses import dataclass, asdict, field

PROFILES_FILE = os.path.join(os.path.dirname(__file__), "profiles.json")

OWNER_ID = int(os.environ.get("OWNER_ID", "0"))


@dataclass
class Profile:
    user_id: int
    first_name: str = ""
    dollar: int = 0
    diamond: int = 0
    wins: int = 0
    games: int = 0
    infinite_diamond: bool = False
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


_cache: dict[int, Profile] = {}


def _load_all() -> dict[int, Profile]:
    if not os.path.exists(PROFILES_FILE):
        return {}
    try:
        with open(PROFILES_FILE, "r") as f:
            raw = json.load(f)
        return {int(k): Profile(**v) for k, v in raw.items()}
    except Exception:
        return {}


def _save_all():
    with open(PROFILES_FILE, "w") as f:
        json.dump({str(k): asdict(v) for k, v in _cache.items()}, f, indent=2)


def _init_cache():
    global _cache
    if not _cache:
        _cache = _load_all()
        if OWNER_ID and OWNER_ID not in _cache:
            _cache[OWNER_ID] = Profile(user_id=OWNER_ID, infinite_diamond=True)
        elif OWNER_ID and OWNER_ID in _cache:
            _cache[OWNER_ID].infinite_diamond = True


def get_profile(user_id: int, first_name: str = "") -> Profile:
    _init_cache()
    if user_id not in _cache:
        _cache[user_id] = Profile(user_id=user_id, first_name=first_name)
    elif first_name:
        _cache[user_id].first_name = first_name
    return _cache[user_id]


def save_profile(profile: Profile):
    _init_cache()
    _cache[profile.user_id] = profile
    _save_all()


def add_dollar(user_id: int, amount: int):
    p = get_profile(user_id)
    p.dollar += amount
    save_profile(p)


def add_diamond(user_id: int, amount: int):
    p = get_profile(user_id)
    p.diamond += amount
    save_profile(p)


def transfer_diamond(giver_id: int, target_id: int, amount: int) -> bool:
    giver = get_profile(giver_id)
    target = get_profile(target_id)
    if not giver.infinite_diamond and giver.diamond < amount:
        return False
    if not giver.infinite_diamond:
        giver.diamond -= amount
    target.diamond += amount
    save_profile(giver)
    save_profile(target)
    return True


def record_game_start(user_id: int, first_name: str = ""):
    p = get_profile(user_id, first_name)
    p.games += 1
    save_profile(p)


def record_win(user_id: int, dollar_reward: int = 40):
    p = get_profile(user_id)
    p.wins += 1
    p.dollar += dollar_reward
    save_profile(p)
