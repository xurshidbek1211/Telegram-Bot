import json
import os

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "bot_config.json")

_cache: dict = {}
_loaded = False


def _load():
    if not os.path.exists(CONFIG_FILE):
        return {}
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def _save():
    with open(CONFIG_FILE, "w") as f:
        json.dump(_cache, f, indent=2)


def _init():
    global _cache, _loaded
    if not _loaded:
        _cache = _load()
        _loaded = True


def get_promo_channel() -> str:
    _init()
    return _cache.get("promo_channel", "")


def set_promo_channel(channel: str):
    _init()
    _cache["promo_channel"] = channel
    _save()
