import json
import os
from dataclasses import dataclass, asdict, field

SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "chat_settings.json")


@dataclass
class ChatSettings:
    chat_id: int
    disabled_roles: list = field(default_factory=list)
    leave_enabled: bool = True
    protection_enabled: bool = True
    night_secs: int = 30
    day_secs: int = 30
    vote_secs: int = 30


_cache: dict[int, ChatSettings] = {}
_loaded = False


def _load_all() -> dict[int, ChatSettings]:
    if not os.path.exists(SETTINGS_FILE):
        return {}
    try:
        with open(SETTINGS_FILE, "r") as f:
            raw = json.load(f)
        known = {f.name for f in ChatSettings.__dataclass_fields__.values()}
        result = {}
        for k, v in raw.items():
            filtered = {key: val for key, val in v.items() if key in known}
            result[int(k)] = ChatSettings(**filtered)
        return result
    except Exception:
        return {}


def _save_all():
    with open(SETTINGS_FILE, "w") as f:
        json.dump({str(k): asdict(v) for k, v in _cache.items()}, f, indent=2)


def _init():
    global _cache, _loaded
    if not _loaded:
        _cache = _load_all()
        _loaded = True


def get_settings(chat_id: int) -> ChatSettings:
    _init()
    if chat_id not in _cache:
        _cache[chat_id] = ChatSettings(chat_id=chat_id)
    return _cache[chat_id]


def save_settings(settings: ChatSettings):
    _init()
    _cache[settings.chat_id] = settings
    _save_all()
