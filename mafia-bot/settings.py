import json
from dataclasses import dataclass, asdict, field
from database import get_pool

_cache: dict[int, "ChatSettings"] = {}


@dataclass
class ChatSettings:
    chat_id: int
    disabled_roles: list = field(default_factory=list)
    leave_enabled: bool = True
    protection_enabled: bool = True
    night_secs: int = 30
    day_secs: int = 30
    vote_secs: int = 30
    hang_confirm_enabled: bool = True
    hang_confirm_secs: int = 30
    custom_role_configs: dict = field(default_factory=dict)
    auto_delete_dead: bool = False
    night_atmosphere: bool = True


def _from_dict(chat_id: int, d: dict) -> "ChatSettings":
    known = {f for f in ChatSettings.__dataclass_fields__}
    filtered = {k: v for k, v in d.items() if k in known}
    filtered["chat_id"] = chat_id
    return ChatSettings(**filtered)


async def get_settings(chat_id: int) -> ChatSettings:
    if chat_id in _cache:
        return _cache[chat_id]

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT settings FROM chat_settings WHERE chat_id = $1", chat_id
        )

    if row:
        raw = row["settings"]
        if isinstance(raw, str):
            raw = json.loads(raw)
        s = _from_dict(chat_id, raw)
    else:
        s = ChatSettings(chat_id=chat_id)

    _cache[chat_id] = s
    return s


async def save_settings(settings: ChatSettings):
    _cache[settings.chat_id] = settings
    d = asdict(settings)
    d.pop("chat_id", None)
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO chat_settings (chat_id, settings)
            VALUES ($1, $2::jsonb)
            ON CONFLICT (chat_id) DO UPDATE SET settings = EXCLUDED.settings
            """,
            settings.chat_id, json.dumps(d),
        )
