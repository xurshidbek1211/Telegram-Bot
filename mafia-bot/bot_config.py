from database import get_pool


async def get_promo_channel() -> str:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT value FROM bot_config WHERE key = 'promo_channel'"
        )
    return row["value"] if row else ""


async def set_promo_channel(channel: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO bot_config (key, value) VALUES ('promo_channel', $1)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            """,
            channel,
        )
