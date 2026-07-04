import random
import asyncio
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, Any

from mdutil import escape_md


class Role(Enum):
    DON = "Don"
    MAFIA = "Mafia"
    YOLLANMA_QOTIL = "Yollanma Qotil"
    ADVOKAT = "Advokat"
    JURNALIST = "Jurnalist"
    KOMISSAR = "Komissar Katani"
    DOCTOR = "Doktor"
    SERZHANT = "Serjant"
    CITIZEN = "Tinch Axoli"
    DAYDI = "Daydi"
    KEZUVCHI = "Kezuvchi"
    OMADLI = "Omadli"
    ADMIRAL = "Admiral"
    SOTQIN = "Sotqin"
    QOTIL = "Qotil"
    BO_RI = "Bo'ri"
    AFSUNGAR = "Afsungar"
    AFERIST = "Aferist"
    SEHRGAR = "Sehrgar"
    GAZABKOR = "G'azabkor"
    JOKER = "Joker"
    KIMYOGAR = "Kimyogar"
    MINIOR = "Minior"
    KONCHI = "Konchi"
    TULKI = "Tulki"
    LABARANT = "Labarant"


class Phase(Enum):
    LOBBY = "lobby"
    NIGHT = "night"
    DAY = "day"
    VOTING = "voting"
    ENDED = "ended"


MAFIA_TEAM = {Role.DON, Role.MAFIA, Role.YOLLANMA_QOTIL, Role.ADVOKAT, Role.JURNALIST}
CITIZEN_TEAM = {Role.KOMISSAR, Role.DOCTOR, Role.SERZHANT, Role.CITIZEN,
                Role.DAYDI, Role.KEZUVCHI, Role.OMADLI, Role.ADMIRAL, Role.SOTQIN}

ROLE_EMOJIS = {
    Role.DON: "🤵🏻", Role.MAFIA: "🤵🏼", Role.YOLLANMA_QOTIL: "🥷",
    Role.ADVOKAT: "👨🏼‍💼", Role.JURNALIST: "👩🏼‍💻",
    Role.KOMISSAR: "🕵🏼", Role.DOCTOR: "👨🏼‍⚕️", Role.SERZHANT: "👮🏼",
    Role.CITIZEN: "👨🏼", Role.DAYDI: "🧙‍♂️",
    Role.KEZUVCHI: "💃", Role.OMADLI: "🤞🏼", Role.ADMIRAL: "🧑🏻‍✈️",
    Role.SOTQIN: "🤓", Role.QOTIL: "🔪",
    Role.BO_RI: "🐺", Role.AFSUNGAR: "💣", Role.AFERIST: "🤹🏻",
    Role.SEHRGAR: "🧙‍", Role.GAZABKOR: "🧟", Role.JOKER: "🤡",
    Role.KIMYOGAR: "👨‍🔬", Role.MINIOR: "☠️", Role.KONCHI: "⛏️", Role.TULKI: "🦊",
    Role.LABARANT: "🧪",
}

ROLE_DESCRIPTIONS_UZ = {
    Role.DON: "Bu tunda kim o'lishini *siz* hal qilasiz. Siz Mafiya sardorisiz.",
    Role.MAFIA: "Donga bo'ysunasiz va u bilan birgalikda o'ldirasiz. Don o'lsa, siz yangi Don bo'lishingiz mumkin.",
    Role.YOLLANMA_QOTIL: "Mafiya tomonida o'ynaysiz! Har tun kimnidir yashirincha ovlaysiz.\n⚠️ Komissarni nishonga olsangiz, u *sizni* o'ldiradi!",
    Role.ADVOKAT: "Har tun bir Mafiya a'zosini himoya qilasiz: Komissar uni tekshirsa, u fuqaro ko'rinadi.",
    Role.JURNALIST: "Har tun kimnikiga intervyu olishga borasiz va o'sha uyga kelgan *barcha* o'yinchilarni ko'rasiz.",
    Role.KOMISSAR: "Har tun bir o'yinchini tekshirasiz. Agar u Mafiya bo'lsa (va himoyalanmagan bo'lsa), *u o'ldiriladi*.",
    Role.DOCTOR: "Har tun bir o'yinchini yo'q qilinishdan himoya qilasiz. O'zingizni ham himoya qila olasiz.",
    Role.SERZHANT: "Komissar har kecha kimni tekshirgani haqida sizga xabar beradi.\n⚠️ Komissar o'lsa, *siz uning o'rnini egallaysiz.*",
    Role.CITIZEN: "Vazifangiz — Mafiyani topish va ovoz berish orqali ularni osish.",
    Role.DAYDI: "Har tun xohlagan odamning uyiga borasiz va o'sha kechasi *kimlar kelganini* ko'rasiz.",
    Role.KEZUVCHI: "Har tun biror o'yinchiga uyqu dori berasiz — u bir tunni *harakatsiz* o'tkazadi.",
    Role.OMADLI: "Kechasi o'ldirilsangiz, *50% ehtimol bilan* omon qolishingiz mumkin!",
    Role.ADMIRAL: "Komissar va Serjant tirik ekan, sizi hech kim o'ldira olmaydi. Ikkovi o'lsa, siz *Komissar* bo'lasiz.",
    Role.SOTQIN: "Har tun bir o'yinchini tanlaysiz. Agar u Don, Mafia yoki Qotil bo'lsa, shaxsingizni ochiqlamasdan fosh qila olasiz!",
    Role.QOTIL: "Shahardagi hamma o'lishi kerak, sizdan tashqari! Har tun bir o'yinchini o'ldirasiz.",
    Role.BO_RI: "🔴 Mafiya o'ldirsa → Mafiaga aylanasiz.\n🔵 Komissar o'ldirsa → Serjantga aylanasiz.\n🔪 Qotil o'ldirsa → shu zahoti o'lasiz.",
    Role.AFSUNGAR: "Kechasi o'ldirilsangiz, o'ldirgan ham halok bo'ladi!\nKunduz osisangiz, birorini o'zingiz bilan olib keta olasiz.",
    Role.AFERIST: "Har tun biror o'yinchining kunduzgi ovoz berish shaxsini almashtiradi.",
    Role.SEHRGAR: "Don, Qotil yoki Komissar sizni o'ldirmoqchi bo'lsa — urinish behuda. Rahm qilish yoki o'ldirish tanlovingiz bor.\n⚠️ Kunduz osisangiz yoki Afsungar/G'azabkor o'ldirsa — o'lasiz.",
    Role.GAZABKOR: "Har tun 1 ta o'yinchini tanlaysiz. Kamida *3 kishini* tanlab, o'zingizni tanlasangiz — *g'alaba qozonasiz!*",
    Role.JOKER: "Har tun biror o'yinchiga 4 ta karta yuborasiz — biri o'lim kartasi (25% ehtimol). O'lsa — siz g'alaba qozonasiz!",
    Role.KIMYOGAR: "Har tun biror o'yinchini *davolashingiz* yoki *o'ldirishingiz* mumkin. Tirik qolsangiz g'alaba!",
    Role.MINIOR: "Har tun tanlagan o'yinchingizning eshigi oldiga *mina* qo'yasiz. O'sha kechasi kelgan barcha o'yinchilar halok bo'ladi.",
    Role.KONCHI: "Har tun 1 ta raqam tanlaysiz: 💎 olmos, 💵 pul yoki 💣 mina topishingiz mumkin. Minaga tushsangiz — halok bo'lasiz!",
    Role.TULKI: "Har tun 1 o'yinchini tanlaysiz. Tinch aholi bo'lsa → *Serjant*ga, Mafiya bo'lsa → *Mafiya*ga, mustaqil bo'lsa → *Qotil*ga aylanasiz!",
    Role.LABARANT: "Mafiya tomonida o'ynaysiz, lekin Mafiya sizni tanimaydi! Har tun birini tanlaysiz: Mafiya a'zosi bo'lsa — himoya qilasiz, tinch aholi yoki mustaqil bo'lsa — o'ldirasiz.\n⚠️ Mafiya sizni otsa — omon qolasiz, lekin Komissar yoki Kimyogar otsa — o'lasiz.",
}

MIN_PLAYERS = 4
MAX_PLAYERS = 25

ROLE_DISTRIBUTION = {
    4:  [Role.DON, Role.KOMISSAR, Role.DOCTOR, Role.CITIZEN],
    5:  [Role.DON, Role.MAFIA, Role.KOMISSAR, Role.DOCTOR, Role.CITIZEN],
    6:  [Role.DON, Role.MAFIA, Role.KOMISSAR, Role.DOCTOR, Role.SERZHANT, Role.CITIZEN],
    7:  [Role.DON, Role.MAFIA, Role.KOMISSAR, Role.DOCTOR, Role.SERZHANT, Role.CITIZEN, Role.CITIZEN],
    8:  [Role.DON, Role.MAFIA, Role.KOMISSAR, Role.DOCTOR, Role.SERZHANT, Role.CITIZEN, Role.CITIZEN, Role.CITIZEN],
    9:  [Role.DON, Role.MAFIA, Role.ADVOKAT, Role.KOMISSAR, Role.DOCTOR, Role.SERZHANT, Role.DAYDI, Role.CITIZEN, Role.CITIZEN],
    10: [Role.DON, Role.MAFIA, Role.MAFIA, Role.KOMISSAR, Role.DOCTOR, Role.SERZHANT, Role.DAYDI, Role.CITIZEN, Role.CITIZEN, Role.CITIZEN],
    11: [Role.DON, Role.MAFIA, Role.MAFIA, Role.ADVOKAT, Role.KOMISSAR, Role.DOCTOR, Role.SERZHANT, Role.KEZUVCHI, Role.TULKI, Role.CITIZEN, Role.CITIZEN],
    12: [Role.DON, Role.MAFIA, Role.MAFIA, Role.ADVOKAT, Role.KOMISSAR, Role.DOCTOR, Role.SERZHANT, Role.KEZUVCHI, Role.OMADLI, Role.TULKI, Role.CITIZEN, Role.CITIZEN],
    13: [Role.DON, Role.MAFIA, Role.MAFIA, Role.ADVOKAT, Role.JURNALIST, Role.KOMISSAR, Role.DOCTOR, Role.SERZHANT, Role.KEZUVCHI, Role.OMADLI, Role.TULKI, Role.CITIZEN, Role.CITIZEN],
    14: [Role.DON, Role.MAFIA, Role.MAFIA, Role.YOLLANMA_QOTIL, Role.ADVOKAT, Role.KOMISSAR, Role.DOCTOR, Role.SERZHANT, Role.KEZUVCHI, Role.OMADLI, Role.ADMIRAL, Role.TULKI, Role.KONCHI, Role.CITIZEN],
    15: [Role.DON, Role.MAFIA, Role.MAFIA, Role.YOLLANMA_QOTIL, Role.ADVOKAT, Role.JURNALIST, Role.KOMISSAR, Role.DOCTOR, Role.SERZHANT, Role.KEZUVCHI, Role.OMADLI, Role.ADMIRAL, Role.TULKI, Role.KONCHI, Role.CITIZEN],
    16: [Role.DON, Role.MAFIA, Role.MAFIA, Role.YOLLANMA_QOTIL, Role.ADVOKAT, Role.JURNALIST, Role.KOMISSAR, Role.DOCTOR, Role.SERZHANT, Role.KEZUVCHI, Role.OMADLI, Role.QOTIL, Role.ADMIRAL, Role.TULKI, Role.KONCHI, Role.CITIZEN],
    17: [Role.DON, Role.MAFIA, Role.MAFIA, Role.YOLLANMA_QOTIL, Role.ADVOKAT, Role.JURNALIST, Role.KOMISSAR, Role.DOCTOR, Role.SERZHANT, Role.KEZUVCHI, Role.OMADLI, Role.QOTIL, Role.ADMIRAL, Role.BO_RI, Role.TULKI, Role.KONCHI, Role.CITIZEN],
    18: [Role.DON, Role.MAFIA, Role.MAFIA, Role.YOLLANMA_QOTIL, Role.ADVOKAT, Role.JURNALIST, Role.KOMISSAR, Role.DOCTOR, Role.SERZHANT, Role.KEZUVCHI, Role.OMADLI, Role.QOTIL, Role.ADMIRAL, Role.BO_RI, Role.AFSUNGAR, Role.TULKI, Role.KONCHI, Role.CITIZEN],
    19: [Role.DON, Role.MAFIA, Role.MAFIA, Role.YOLLANMA_QOTIL, Role.ADVOKAT, Role.JURNALIST, Role.KOMISSAR, Role.DOCTOR, Role.SERZHANT, Role.KEZUVCHI, Role.OMADLI, Role.QOTIL, Role.ADMIRAL, Role.BO_RI, Role.AFSUNGAR, Role.AFERIST, Role.TULKI, Role.KONCHI, Role.CITIZEN],
    20: [Role.DON, Role.MAFIA, Role.MAFIA, Role.YOLLANMA_QOTIL, Role.ADVOKAT, Role.JURNALIST, Role.KOMISSAR, Role.DOCTOR, Role.SERZHANT, Role.KEZUVCHI, Role.OMADLI, Role.QOTIL, Role.ADMIRAL, Role.BO_RI, Role.AFSUNGAR, Role.AFERIST, Role.DAYDI, Role.SOTQIN, Role.TULKI, Role.KONCHI],
    21: [Role.DON, Role.MAFIA, Role.MAFIA, Role.YOLLANMA_QOTIL, Role.ADVOKAT, Role.JURNALIST, Role.KOMISSAR, Role.DOCTOR, Role.SERZHANT, Role.KEZUVCHI, Role.OMADLI, Role.QOTIL, Role.ADMIRAL, Role.BO_RI, Role.AFSUNGAR, Role.AFERIST, Role.DAYDI, Role.SOTQIN, Role.TULKI, Role.KONCHI, Role.LABARANT],
}


def get_role_list(player_count: int, disabled_roles: Optional[set] = None) -> list:
    if player_count in ROLE_DISTRIBUTION:
        roles = ROLE_DISTRIBUTION[player_count].copy()
    else:
        base = max(k for k in ROLE_DISTRIBUTION if k <= player_count)
        roles = ROLE_DISTRIBUTION[base].copy()
        roles.extend([Role.CITIZEN] * (player_count - base))
    if disabled_roles:
        roles = [Role.CITIZEN if r.name in disabled_roles and r != Role.CITIZEN else r for r in roles]
    random.shuffle(roles)
    return roles


@dataclass
class Player:
    user_id: int
    username: str
    first_name: str
    last_name: str = ""
    role: Optional[Role] = None
    alive: bool = True
    gazabkor_targets: list = field(default_factory=list)
    joker_won: bool = False

    @property
    def display_name(self) -> str:
        raw = f"{self.first_name} {self.last_name}".strip() if self.last_name else self.first_name
        return escape_md(raw)


@dataclass
class Game:
    chat_id: int
    phase: Phase = Phase.LOBBY
    players: dict = field(default_factory=dict)
    day_number: int = 0
    winner: Optional[str] = None
    night_actions: dict = field(default_factory=dict)
    votes: dict = field(default_factory=dict)
    aferist_swaps: dict = field(default_factory=dict)
    mines_set: set = field(default_factory=set)
    night_visitors: dict = field(default_factory=dict)
    blocked: set = field(default_factory=set)
    advokat_protected: Optional[int] = None
    sehrgar_pending: dict = field(default_factory=dict)
    konchi_rewards: dict = field(default_factory=dict)
    hang_confirm_votes: dict = field(default_factory=dict)
    hang_confirm_msg_id: Optional[int] = None
    komissar_found_mafia: Optional[str] = None
    phase_task: Any = None
    group_link: Optional[str] = None
    vote_msg_id: Optional[int] = None
    give_drops: dict = field(default_factory=dict)
    money_drops: dict = field(default_factory=dict)
    lobby_msg_id: Optional[int] = None
    komissar_investigations: dict = field(default_factory=dict)

    def add_player(self, user_id: int, username: str, first_name: str, last_name: str = "") -> bool:
        if user_id in self.players or len(self.players) >= MAX_PLAYERS:
            return False
        self.players[user_id] = Player(user_id=user_id, username=username, first_name=first_name, last_name=last_name)
        return True

    def remove_player(self, user_id: int) -> bool:
        if user_id in self.players and self.phase == Phase.LOBBY:
            del self.players[user_id]
            return True
        return False

    def alive_players(self) -> list:
        return [p for p in self.players.values() if p.alive]

    def alive_mafia_team(self) -> list:
        return [p for p in self.alive_players() if p.role in MAFIA_TEAM]

    def get_player_by_id(self, uid: int) -> Optional[Player]:
        return self.players.get(uid)

    def get_alive_by_role(self, role: Role) -> Optional[Player]:
        return next((p for p in self.alive_players() if p.role == role), None)

    def eliminate_player(self, uid: int):
        p = self.players.get(uid)
        if p:
            p.alive = False

    def assign_roles(self, disabled_roles: Optional[set] = None):
        roles = get_role_list(len(self.players), disabled_roles)
        for player, role in zip(self.players.values(), roles):
            player.role = role

    def reset_night_state(self):
        self.night_actions = {}
        self.night_visitors = {}
        self.blocked = set()
        self.advokat_protected = None
        self.mines_set = set()
        self.aferist_swaps = {}
        self.sehrgar_pending = {}
        self.konchi_rewards = {}
        self.hang_confirm_votes = {}
        self.komissar_found_mafia = None

    def get_display_name(self, player: Player) -> str:
        return self.aferist_swaps.get(player.user_id, player.display_name)

    def required_night_actors(self) -> set:
        required = set()
        alive = self.alive_players()
        don = self.get_alive_by_role(Role.DON)
        if don:
            required.add(don.user_id)
        else:
            first_mafia = next((p for p in alive if p.role == Role.MAFIA), None)
            if first_mafia:
                required.add(first_mafia.user_id)
        for role in [Role.KOMISSAR, Role.DOCTOR, Role.QOTIL, Role.KEZUVCHI,
                     Role.YOLLANMA_QOTIL, Role.ADVOKAT, Role.DAYDI, Role.JURNALIST,
                     Role.AFERIST, Role.MINIOR, Role.KIMYOGAR, Role.GAZABKOR,
                     Role.JOKER, Role.SOTQIN, Role.TULKI, Role.LABARANT]:
            p = self.get_alive_by_role(role)
            if p:
                required.add(p.user_id)
        serzhant = self.get_alive_by_role(Role.SERZHANT)
        if serzhant and not self.get_alive_by_role(Role.KOMISSAR):
            required.add(serzhant.user_id)
        return required

    def all_night_actions_done(self) -> bool:
        return self.required_night_actors().issubset(set(self.night_actions.keys()))

    def tally_votes(self) -> Optional[int]:
        counts: dict = {}
        for vid, tid in self.votes.items():
            voter = self.players.get(vid)
            if voter and voter.alive:
                counts[tid] = counts.get(tid, 0) + 1
        if not counts:
            return None
        mx = max(counts.values())
        candidates = [uid for uid, c in counts.items() if c == mx]
        return candidates[0] if len(candidates) == 1 else None

    def check_win_condition(self) -> Optional[str]:
        alive = self.alive_players()
        mafia_count = sum(1 for p in alive if p.role in MAFIA_TEAM or p.role == Role.LABARANT)
        citizen_count = sum(1 for p in alive if p.role not in MAFIA_TEAM and p.role not in (Role.QOTIL, Role.LABARANT))
        qotil = self.get_alive_by_role(Role.QOTIL)
        if mafia_count == 0 and qotil is None:
            return "citizens"
        if mafia_count >= citizen_count and qotil is None:
            return "mafia"
        if qotil and len(alive) == 1:
            return "qotil"
        return None

    def cancel_phase_task(self):
        if self.phase_task and not self.phase_task.done():
            self.phase_task.cancel()
        self.phase_task = None
