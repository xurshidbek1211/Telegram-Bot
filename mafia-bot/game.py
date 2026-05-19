import random
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional


class Role(Enum):
    MAFIA = "Mafia"
    DOCTOR = "Doctor"
    DETECTIVE = "Detective"
    CITIZEN = "Citizen"


class Phase(Enum):
    LOBBY = "lobby"
    NIGHT = "night"
    DAY = "day"
    VOTING = "voting"
    ENDED = "ended"


ROLE_DESCRIPTIONS = {
    Role.MAFIA: (
        "You are Mafia. Each night, you may eliminate one player. "
        "Stay hidden and avoid suspicion during the day."
    ),
    Role.DOCTOR: (
        "You are the Doctor. Each night, you may protect one player from elimination. "
        "You can protect yourself."
    ),
    Role.DETECTIVE: (
        "You are the Detective. Each night, you may investigate one player "
        "to learn if they are Mafia or not."
    ),
    Role.CITIZEN: (
        "You are a Citizen. Help identify and vote out the Mafia during the day phase."
    ),
}

ROLE_EMOJIS = {
    Role.MAFIA: "🔪",
    Role.DOCTOR: "💊",
    Role.DETECTIVE: "🔍",
    Role.CITIZEN: "👤",
}

MIN_PLAYERS = 4
MAX_PLAYERS = 20

ROLE_DISTRIBUTION = {
    4: {Role.MAFIA: 1, Role.DOCTOR: 1, Role.DETECTIVE: 0, Role.CITIZEN: 2},
    5: {Role.MAFIA: 1, Role.DOCTOR: 1, Role.DETECTIVE: 1, Role.CITIZEN: 2},
    6: {Role.MAFIA: 1, Role.DOCTOR: 1, Role.DETECTIVE: 1, Role.CITIZEN: 3},
    7: {Role.MAFIA: 2, Role.DOCTOR: 1, Role.DETECTIVE: 1, Role.CITIZEN: 3},
    8: {Role.MAFIA: 2, Role.DOCTOR: 1, Role.DETECTIVE: 1, Role.CITIZEN: 4},
    9: {Role.MAFIA: 2, Role.DOCTOR: 1, Role.DETECTIVE: 1, Role.CITIZEN: 5},
    10: {Role.MAFIA: 3, Role.DOCTOR: 1, Role.DETECTIVE: 1, Role.CITIZEN: 5},
}


def get_role_distribution(player_count: int) -> dict:
    if player_count <= 4:
        return ROLE_DISTRIBUTION[4]
    elif player_count in ROLE_DISTRIBUTION:
        return ROLE_DISTRIBUTION[player_count]
    else:
        mafia_count = max(2, player_count // 4)
        remaining = player_count - mafia_count - 2
        return {
            Role.MAFIA: mafia_count,
            Role.DOCTOR: 1,
            Role.DETECTIVE: 1,
            Role.CITIZEN: remaining,
        }


@dataclass
class Player:
    user_id: int
    username: str
    first_name: str
    role: Optional[Role] = None
    alive: bool = True
    protected: bool = False
    vote_target: Optional[int] = None

    @property
    def display_name(self) -> str:
        if self.username:
            return f"@{self.username}"
        return self.first_name


@dataclass
class GameStats:
    total_games: int = 0
    mafia_wins: int = 0
    citizen_wins: int = 0
    total_players: int = 0


@dataclass
class Game:
    chat_id: int
    phase: Phase = Phase.LOBBY
    players: dict = field(default_factory=dict)
    day_number: int = 0
    night_actions: dict = field(default_factory=dict)
    votes: dict = field(default_factory=dict)
    eliminated_this_round: Optional[int] = None
    winner: Optional[str] = None
    action_timeout_job: any = None

    def add_player(self, user_id: int, username: str, first_name: str) -> bool:
        if user_id in self.players:
            return False
        if len(self.players) >= MAX_PLAYERS:
            return False
        self.players[user_id] = Player(user_id=user_id, username=username, first_name=first_name)
        return True

    def remove_player(self, user_id: int) -> bool:
        if user_id in self.players and self.phase == Phase.LOBBY:
            del self.players[user_id]
            return True
        return False

    def alive_players(self) -> list:
        return [p for p in self.players.values() if p.alive]

    def alive_mafia(self) -> list:
        return [p for p in self.alive_players() if p.role == Role.MAFIA]

    def alive_citizens(self) -> list:
        return [p for p in self.alive_players() if p.role != Role.MAFIA]

    def assign_roles(self):
        count = len(self.players)
        distribution = get_role_distribution(count)
        roles = []
        for role, num in distribution.items():
            roles.extend([role] * num)
        while len(roles) < count:
            roles.append(Role.CITIZEN)
        random.shuffle(roles)
        for player, role in zip(self.players.values(), roles):
            player.role = role

    def check_win_condition(self) -> Optional[str]:
        alive = self.alive_players()
        mafia_count = len([p for p in alive if p.role == Role.MAFIA])
        citizen_count = len([p for p in alive if p.role != Role.MAFIA])

        if mafia_count == 0:
            return "citizens"
        if mafia_count >= citizen_count:
            return "mafia"
        return None

    def get_player_by_id(self, user_id: int) -> Optional[Player]:
        return self.players.get(user_id)

    def eliminate_player(self, user_id: int):
        player = self.players.get(user_id)
        if player:
            player.alive = False

    def reset_night_state(self):
        self.night_actions = {}
        for p in self.players.values():
            p.protected = False
            p.vote_target = None

    def tally_votes(self) -> Optional[int]:
        vote_counts: dict = {}
        for voter_id, target_id in self.votes.items():
            voter = self.players.get(voter_id)
            if voter and voter.alive:
                vote_counts[target_id] = vote_counts.get(target_id, 0) + 1

        if not vote_counts:
            return None

        max_votes = max(vote_counts.values())
        candidates = [uid for uid, count in vote_counts.items() if count == max_votes]

        if len(candidates) == 1:
            return candidates[0]
        return None
