from dataclasses import dataclass
from database import get_pool


@dataclass
class GameStats:
    total_games: int = 0
    mafia_wins: int = 0
    citizen_wins: int = 0
    total_players: int = 0


async def load_stats() -> GameStats:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM game_stats WHERE id = 1")
    if row:
        return GameStats(
            total_games=row["total_games"],
            mafia_wins=row["mafia_wins"],
            citizen_wins=row["citizen_wins"],
            total_players=row["total_players"],
        )
    return GameStats()


async def save_stats(stats: GameStats):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO game_stats (id, total_games, mafia_wins, citizen_wins, total_players)
            VALUES (1, $1, $2, $3, $4)
            ON CONFLICT (id) DO UPDATE SET
                total_games = EXCLUDED.total_games,
                mafia_wins = EXCLUDED.mafia_wins,
                citizen_wins = EXCLUDED.citizen_wins,
                total_players = EXCLUDED.total_players
            """,
            stats.total_games, stats.mafia_wins, stats.citizen_wins, stats.total_players,
        )
