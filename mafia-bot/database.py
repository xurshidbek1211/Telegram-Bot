import asyncpg
import os
import logging

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        url = os.getenv("DATABASE_URL")
        if not url:
            raise RuntimeError("DATABASE_URL o'rnatilmagan.")
        _pool = await asyncpg.create_pool(url, min_size=2, max_size=10)
    return _pool


async def init_db():
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS profiles (
                user_id BIGINT PRIMARY KEY,
                first_name TEXT DEFAULT '',
                dollar INTEGER DEFAULT 0,
                diamond INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                games INTEGER DEFAULT 0,
                infinite_diamond BOOLEAN DEFAULT FALSE,
                infinite_dollar BOOLEAN DEFAULT FALSE,
                shield INTEGER DEFAULT 0,
                documents INTEGER DEFAULT 0,
                hang_protect INTEGER DEFAULT 0,
                killer_protect INTEGER DEFAULT 0,
                gun INTEGER DEFAULT 0,
                drug_protect INTEGER DEFAULT 0,
                mask INTEGER DEFAULT 0,
                slip_protect INTEGER DEFAULT 0,
                hero_protect INTEGER DEFAULT 0,
                mines INTEGER DEFAULT 0,
                active_roles JSONB DEFAULT '[]'::jsonb
            )
        """)
        # Migrate: add oltin_sandiq columns if absent
        await conn.execute("""
            ALTER TABLE profiles ADD COLUMN IF NOT EXISTS oltin_sandiq_date TEXT DEFAULT '';
        """)
        await conn.execute("""
            ALTER TABLE profiles ADD COLUMN IF NOT EXISTS oltin_sandiq_count INTEGER DEFAULT 0;
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS game_stats (
                id INTEGER PRIMARY KEY DEFAULT 1,
                total_games INTEGER DEFAULT 0,
                mafia_wins INTEGER DEFAULT 0,
                citizen_wins INTEGER DEFAULT 0,
                total_players INTEGER DEFAULT 0
            )
        """)
        await conn.execute(
            "INSERT INTO game_stats (id) VALUES (1) ON CONFLICT (id) DO NOTHING"
        )
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS ratings (
                chat_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                first_name TEXT DEFAULT '',
                score INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                games INTEGER DEFAULT 0,
                PRIMARY KEY (chat_id, user_id)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_settings (
                chat_id BIGINT PRIMARY KEY,
                settings JSONB NOT NULL DEFAULT '{}'::jsonb
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS heroes (
                user_id       BIGINT PRIMARY KEY,
                name          TEXT    DEFAULT 'Geroy',
                level         INTEGER DEFAULT 1,
                xp            INTEGER DEFAULT 0,
                hp            INTEGER DEFAULT 80,
                charges       INTEGER DEFAULT 10,
                total_attacks INTEGER DEFAULT 0,
                kills         INTEGER DEFAULT 0,
                completed_missions JSONB DEFAULT
                    '{"kills":[],"levels":[],"activity":[]}'::jsonb
            )
        """)
    logger.info("Barcha jadvallar tayyor.")


async def close_db():
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        logger.info("Database pool yopildi.")
