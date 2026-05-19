import json
import os
from dataclasses import dataclass, asdict

STATS_FILE = os.path.join(os.path.dirname(__file__), "stats.json")


@dataclass
class GameStats:
    total_games: int = 0
    mafia_wins: int = 0
    citizen_wins: int = 0
    total_players: int = 0


def load_stats() -> GameStats:
    if not os.path.exists(STATS_FILE):
        return GameStats()
    try:
        with open(STATS_FILE, "r") as f:
            data = json.load(f)
        return GameStats(**data)
    except Exception:
        return GameStats()


def save_stats(stats: GameStats):
    with open(STATS_FILE, "w") as f:
        json.dump(asdict(stats), f, indent=2)
