from dataclasses import dataclass
from database import get_pool

TOP_N = 20


@dataclass
class ChatRatingEntry:
    user_id: int
    first_name: str = ""
    score: int = 0
    wins: int = 0
    games: int = 0


async def record_game_result(chat_id: int, user_id: int, first_name: str, won: bool, points: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO ratings (chat_id, user_id, first_name, score, wins, games)
            VALUES ($1, $2, $3, $4, $5, 1)
            ON CONFLICT (chat_id, user_id) DO UPDATE SET
                first_name = EXCLUDED.first_name,
                score = ratings.score + EXCLUDED.score,
                wins = ratings.wins + EXCLUDED.wins,
                games = ratings.games + 1
            """,
            chat_id, user_id, first_name or "", points, 1 if won else 0,
        )


async def get_top_ratings(chat_id: int, limit: int = TOP_N) -> list:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT user_id, first_name, score, wins, games
            FROM ratings
            WHERE chat_id = $1
            ORDER BY score DESC
            LIMIT $2
            """,
            chat_id, limit,
        )
    return [
        ChatRatingEntry(
            user_id=r["user_id"],
            first_name=r["first_name"],
            score=r["score"],
            wins=r["wins"],
            games=r["games"],
        )
        for r in rows
    ]
