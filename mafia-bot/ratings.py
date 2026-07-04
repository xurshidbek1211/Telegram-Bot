import json
import os
from dataclasses import dataclass, asdict, field

RATINGS_FILE = os.path.join(os.path.dirname(__file__), "ratings.json")

TOP_N = 20


@dataclass
class ChatRatingEntry:
    user_id: int
    first_name: str = ""
    score: int = 0
    wins: int = 0
    games: int = 0


_cache: dict = {}
_loaded = False


def _load_all() -> dict:
    if not os.path.exists(RATINGS_FILE):
        return {}
    try:
        with open(RATINGS_FILE, "r") as f:
            raw = json.load(f)
        known = {f.name for f in ChatRatingEntry.__dataclass_fields__.values()}
        result = {}
        for chat_id, entries in raw.items():
            result[int(chat_id)] = {}
            for uid, v in entries.items():
                filtered = {key: val for key, val in v.items() if key in known}
                result[int(chat_id)][int(uid)] = ChatRatingEntry(**filtered)
        return result
    except Exception:
        return {}


def _save_all():
    with open(RATINGS_FILE, "w") as f:
        json.dump(
            {
                str(chat_id): {str(uid): asdict(e) for uid, e in entries.items()}
                for chat_id, entries in _cache.items()
            },
            f, indent=2,
        )


def _init():
    global _cache, _loaded
    if not _loaded:
        _cache = _load_all()
        _loaded = True


def record_game_result(chat_id: int, user_id: int, first_name: str, won: bool, points: int):
    """Update a player's per-chat rating after a finished game."""
    _init()
    chat = _cache.setdefault(chat_id, {})
    entry = chat.get(user_id)
    if not entry:
        entry = ChatRatingEntry(user_id=user_id, first_name=first_name)
        chat[user_id] = entry
    entry.first_name = first_name or entry.first_name
    entry.games += 1
    entry.score += points
    if won:
        entry.wins += 1
    _save_all()


def get_top_ratings(chat_id: int, limit: int = TOP_N) -> list:
    _init()
    entries = list(_cache.get(chat_id, {}).values())
    entries.sort(key=lambda e: e.score, reverse=True)
    return entries[:limit]
