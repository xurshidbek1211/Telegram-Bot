import random
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional


class Role(Enum):
    # Mafia tomonı
    DON = "Don"
    MAFIA = "Mafia"
    YOLLANMA_QOTIL = "Yollanma Qotil"
    ADVOKAT = "Advokat"
    JURNALIST = "Jurnalist"
    # Fuqarolar tomonı
    KOMISSAR = "Komissar Katani"
    DOCTOR = "Doktor"
    SERZHANT = "Serjant"
    JANOB = "Janob"
    CITIZEN = "Tinch Axoli"
    DAYDI = "Daydi"
    KEZUVCHI = "Kezuvchi"
    OMADLI = "Omadli"
    ADMIRAL = "Admiral"
    SOTQIN = "Sotqin"
    # Mustaqil
    QOTIL = "Qotil"
    SUIDSID = "Suidsid"
    BO_RI = "Bo'ri"
    AFSUNGAR = "Afsungar"
    AFERIST = "Aferist"
    SEHRGAR = "Sehrgar"
    GAZABKOR = "G'azabkor"
    JOKER = "Joker"
    KIMYOGAR = "Kimyogar"
    MINIOR = "Minior"


MAFIA_TEAM = {Role.DON, Role.MAFIA, Role.YOLLANMA_QOTIL, Role.ADVOKAT, Role.JURNALIST}
CITIZEN_TEAM = {Role.KOMISSAR, Role.DOCTOR, Role.SERZHANT, Role.JANOB, Role.CITIZEN,
                Role.DAYDI, Role.KEZUVCHI, Role.OMADLI, Role.ADMIRAL, Role.SOTQIN}

ROLE_EMOJIS = {
    Role.DON: "🤵🏻",
    Role.MAFIA: "🤵🏼",
    Role.YOLLANMA_QOTIL: "🥷",
    Role.ADVOKAT: "👨🏼‍💼",
    Role.JURNALIST: "👩🏼‍💻",
    Role.KOMISSAR: "🕵🏼",
    Role.DOCTOR: "👨🏼‍⚕️",
    Role.SERZHANT: "👮🏼",
    Role.JANOB: "🎖",
    Role.CITIZEN: "👨🏼",
    Role.DAYDI: "🧙‍♂️",
    Role.KEZUVCHI: "💃",
    Role.OMADLI: "🤞🏼",
    Role.ADMIRAL: "🧑🏻‍✈️",
    Role.SOTQIN: "🤓",
    Role.QOTIL: "🔪",
    Role.SUIDSID: "🤦🏼",
    Role.BO_RI: "🐺",
    Role.AFSUNGAR: "💣",
    Role.AFERIST: "🤹🏻",
    Role.SEHRGAR: "🧙‍",
    Role.GAZABKOR: "🧟",
    Role.JOKER: "🤡",
    Role.KIMYOGAR: "👨‍🔬",
    Role.MINIOR: "☠️",
}

ROLE_DESCRIPTIONS_UZ = {
    Role.DON: (
        "Siz Donsiz — Mafiyaning sardori.\n"
        "Bu tunda kim o'lishini *siz* hal qilasiz.\n"
        "Guruhingizni boshqaring va fuqarolarni aldang."
    ),
    Role.MAFIA: (
        "Siz Mafiyasiz. Donga bo'ysunasiz va u bilan birgalikda o'ldirasiz.\n"
        "Don o'lsa, siz yangi Don bo'lishingiz mumkin."
    ),
    Role.YOLLANMA_QOTIL: (
        "Siz Yollanma Qotilsiz — Mafiya tomonida o'ynaysiz!\n"
        "Har tun kimnidir yashirincha ovlaysiz.\n"
        "⚠️ Agar Komissar Katanini nishonga olsangiz, u *sizni* o'ldiradi!"
    ),
    Role.ADVOKAT: (
        "Siz Advokatsiz — Mafiya tomonida!\n"
        "Har tun bir Mafiya a'zosini himoya qilasiz: Komissar uni tekshirsa, u fuqaro ko'rinadi.\n"
        "Mafiya g'alaba qilsa siz ham g'olib bo'lasiz."
    ),
    Role.JURNALIST: (
        "Siz Jurnalistsiz — Mafiyaning agentisiz!\n"
        "Har tun kimnikiga intervyu olishga borasiz va o'sha uyga kelgan *barcha* o'yinchilarni ko'rasiz.\n"
        "Bu ma'lumotni Mafiyaga yetkazasiz."
    ),
    Role.KOMISSAR: (
        "Siz Komissar Katanisiz — shaharning asosiy himoyachisi!\n"
        "Har tun bir o'yinchini tekshirasiz. Agar u Mafiya bo'lsa (va himoyalanmagan bo'lsa), *u o'ldiriladi*."
    ),
    Role.DOCTOR: (
        "Siz Doktorsiz.\n"
        "Har tun bir o'yinchini yo'q qilinishdan himoya qilasiz. O'zingizni ham himoya qila olasiz."
    ),
    Role.SERZHANT: (
        "Siz Serjant — Komissar Katanining yordamchisisiz.\n"
        "Komissar har kecha kimni tekshirgani va nima topgani haqida sizga xabar beradi.\n"
        "⚠️ Komissar o'lsa, *siz uning o'rnini egallaysiz.*"
    ),
    Role.JANOB: (
        "Siz Janobsiz.\n"
        "Kunduzgi ovoz berishda sizning ovozingiz *ikkitaga teng* bo'ladi.\n"
        "Ovoz berish vaqtida shaxsingiz oshkor bo'lmaydi."
    ),
    Role.CITIZEN: (
        "Siz Tinch Axolisiz.\n"
        "Vazifangiz — Mafiyani topish va ovoz berish orqali ularni osish."
    ),
    Role.DAYDI: (
        "Siz Daydisiz.\n"
        "Har tun xohlagan odamning uyiga borasiz va o'sha kechasi *kimlar kelganini* ko'rasiz.\n"
        "Qotillikning guvohi bo'lib qolishingiz mumkin!"
    ),
    Role.KEZUVCHI: (
        "Siz Kezuvchisiz.\n"
        "Har tun biror o'yinchiga uyqu dori berasiz — u bir tunni *harakatsiz* o'tkazadi.\n"
        "Bloklangan o'yinchining kecha harakati bekor qilinadi."
    ),
    Role.OMADLI: (
        "Siz Omadli Fuqarosiz.\n"
        "Kechasi o'ldirilsangiz, *50% ehtimol bilan* omon qolishingiz mumkin — omad kulib boqqan hollarda!"
    ),
    Role.ADMIRAL: (
        "Siz Admiralsiz.\n"
        "Agar o'yinda Komissar Katani *va* Serjant tirik bo'lsa, sizi hech kim o'ldira olmaydi.\n"
        "⚠️ Ikkovi o'lsa, siz *Komissar Katani* roliga o'tasiz!"
    ),
    Role.SOTQIN: (
        "Siz Sotqinsiz — fuqarolar tomonida o'ynaysiz.\n"
        "Har tun bir o'yinchini tanlaysiz. Agar u Don, Mafia yoki Qotil bo'lsa, uni *shaxsingizni ochiqlamasdan* guruhga fosh eta olasiz.\n"
        "Tirik qolsangiz g'alaba qozonasiz!"
    ),
    Role.QOTIL: (
        "Siz Qotilsiz — shahardagi hamma o'lishi kerak, sizdan tashqari!\n"
        "Har tun bir o'yinchini o'ldirasiz. Yolg'iz qolsangiz g'alaba qozonasiz."
    ),
    Role.SUIDSID: (
        "Siz Suidsidsiz.\n"
        "Seni kunduz ovozda *osib o'ldirishsa — sen yutasan!* 🎉\n"
        "Kechasi o'ldirilsang, oddiy o'lasan."
    ),
    Role.BO_RI: (
        "Siz Bo'risiz.\n"
        "🔴 Mafiya o'ldirsa → kelgusi tun Mafiaga aylanasiz.\n"
        "🔵 Komissar o'ldirsa → Serjantga aylanasiz.\n"
        "🔪 Qotil o'ldirsa → shu zahoti o'lasiz."
    ),
    Role.AFSUNGAR: (
        "Siz Afsungarsiz — fuqarolarga yordam berish maqsadingiz.\n"
        "⚠️ Agar kechasi *o'ldirilsangiz*, sizni o'ldirgan ham halok bo'ladi!\n"
        "Kunduz osisangiz, biror o'yinchini o'zingiz bilan birga olib keta olasiz."
    ),
    Role.AFERIST: (
        "Siz Aferistsiz.\n"
        "Har tun biror o'yinchiga tashrif buyurasiz va uni keyingi *kunduzgi ovozda* boshqa ismi bilan ko'rsatasiz."
    ),
    Role.SEHRGAR: (
        "Siz Sehrgarsiz — o'z qonunlaringiz bilan yashaysiz!\n"
        "Don, Qotil yoki Komissar sizni o'ldirmoqchi bo'lsa, urinish *behuda* bo'ladi va sizga tanlov beriladi: rahm qilish yoki o'ldirish.\n"
        "Maqsad: omon qolish va dushmanlarga jazo berish.\n"
        "⚠️ Kunduz osisangiz yoki Afsungar/G'azabkor o'ldirsa — o'lasiz."
    ),
    Role.GAZABKOR: (
        "Siz G'azabkorsiz.\n"
        "Har tun 1 ta o'yinchini tanlaysiz (ro'yxat to'planib boradi).\n"
        "Agar *o'zingizni* tanlasangiz, ro'yxatdagi barcha o'yinchilar bilan birga o'lasiz.\n"
        "Kamida *3 kishini* tanlab, so'ng o'zingizni tanlasangiz — *g'alaba qozonasiz!*"
    ),
    Role.JOKER: (
        "Siz Jokersiz.\n"
        "Har tun biror o'yinchiga 4 ta yashirin karta yuborasiz — biri o'lim kartasi.\n"
        "U kartalardan birini tanlashi kerak. Agar o'lim kartasini tanlasa, u o'ladi — siz g'alaba qozonasiz!"
    ),
    Role.KIMYOGAR: (
        "Siz Kimyogarsiz — erkinsiz!\n"
        "Har tun biror o'yinchini *davolashingiz* yoki *o'ldirishingiz* mumkin.\n"
        "G'alaba qilish uchun shunchaki tirik qolsangiz bas!"
    ),
    Role.MINIOR: (
        "Siz Miniorsiz.\n"
        "Har tun tanlagan o'yinchingizning eshigi oldiga *mina* qo'yasiz.\n"
        "O'sha kechasi o'sha uyga kelgan barcha o'yinchilar (Miniordan tashqari) halok bo'ladi."
    ),
}

MIN_PLAYERS = 4
MAX_PLAYERS = 25

ROLE_DISTRIBUTION = {
    4:  [Role.DON, Role.KOMISSAR, Role.DOCTOR, Role.CITIZEN],
    5:  [Role.DON, Role.MAFIA, Role.KOMISSAR, Role.DOCTOR, Role.CITIZEN],
    6:  [Role.DON, Role.MAFIA, Role.KOMISSAR, Role.DOCTOR, Role.SERZHANT, Role.CITIZEN],
    7:  [Role.DON, Role.MAFIA, Role.KOMISSAR, Role.DOCTOR, Role.SERZHANT, Role.CITIZEN, Role.CITIZEN],
    8:  [Role.DON, Role.MAFIA, Role.KOMISSAR, Role.DOCTOR, Role.SERZHANT, Role.JANOB, Role.CITIZEN, Role.CITIZEN],
    9:  [Role.DON, Role.MAFIA, Role.ADVOKAT, Role.KOMISSAR, Role.DOCTOR, Role.SERZHANT, Role.DAYDI, Role.CITIZEN, Role.CITIZEN],
    10: [Role.DON, Role.MAFIA, Role.MAFIA, Role.KOMISSAR, Role.DOCTOR, Role.SERZHANT, Role.JANOB, Role.DAYDI, Role.CITIZEN, Role.CITIZEN],
    11: [Role.DON, Role.MAFIA, Role.MAFIA, Role.ADVOKAT, Role.KOMISSAR, Role.DOCTOR, Role.SERZHANT, Role.JANOB, Role.KEZUVCHI, Role.CITIZEN, Role.CITIZEN],
    12: [Role.DON, Role.MAFIA, Role.MAFIA, Role.ADVOKAT, Role.KOMISSAR, Role.DOCTOR, Role.SERZHANT, Role.JANOB, Role.KEZUVCHI, Role.OMADLI, Role.CITIZEN, Role.CITIZEN],
    13: [Role.DON, Role.MAFIA, Role.MAFIA, Role.ADVOKAT, Role.JURNALIST, Role.KOMISSAR, Role.DOCTOR, Role.SERZHANT, Role.JANOB, Role.KEZUVCHI, Role.OMADLI, Role.SUIDSID, Role.CITIZEN],
    14: [Role.DON, Role.MAFIA, Role.MAFIA, Role.YOLLANMA_QOTIL, Role.ADVOKAT, Role.KOMISSAR, Role.DOCTOR, Role.SERZHANT, Role.JANOB, Role.KEZUVCHI, Role.OMADLI, Role.SUIDSID, Role.ADMIRAL, Role.CITIZEN],
    15: [Role.DON, Role.MAFIA, Role.MAFIA, Role.YOLLANMA_QOTIL, Role.ADVOKAT, Role.JURNALIST, Role.KOMISSAR, Role.DOCTOR, Role.SERZHANT, Role.JANOB, Role.KEZUVCHI, Role.OMADLI, Role.SUIDSID, Role.ADMIRAL, Role.CITIZEN],
    16: [Role.DON, Role.MAFIA, Role.MAFIA, Role.YOLLANMA_QOTIL, Role.ADVOKAT, Role.JURNALIST, Role.KOMISSAR, Role.DOCTOR, Role.SERZHANT, Role.JANOB, Role.KEZUVCHI, Role.OMADLI, Role.QOTIL, Role.SUIDSID, Role.ADMIRAL, Role.CITIZEN],
    17: [Role.DON, Role.MAFIA, Role.MAFIA, Role.YOLLANMA_QOTIL, Role.ADVOKAT, Role.JURNALIST, Role.KOMISSAR, Role.DOCTOR, Role.SERZHANT, Role.JANOB, Role.KEZUVCHI, Role.OMADLI, Role.QOTIL, Role.SUIDSID, Role.ADMIRAL, Role.BO_RI, Role.CITIZEN],
    18: [Role.DON, Role.MAFIA, Role.MAFIA, Role.YOLLANMA_QOTIL, Role.ADVOKAT, Role.JURNALIST, Role.KOMISSAR, Role.DOCTOR, Role.SERZHANT, Role.JANOB, Role.KEZUVCHI, Role.OMADLI, Role.QOTIL, Role.SUIDSID, Role.ADMIRAL, Role.BO_RI, Role.AFSUNGAR, Role.CITIZEN],
    19: [Role.DON, Role.MAFIA, Role.MAFIA, Role.YOLLANMA_QOTIL, Role.ADVOKAT, Role.JURNALIST, Role.KOMISSAR, Role.DOCTOR, Role.SERZHANT, Role.JANOB, Role.KEZUVCHI, Role.OMADLI, Role.QOTIL, Role.SUIDSID, Role.ADMIRAL, Role.BO_RI, Role.AFSUNGAR, Role.AFERIST, Role.CITIZEN],
    20: [Role.DON, Role.MAFIA, Role.MAFIA, Role.YOLLANMA_QOTIL, Role.ADVOKAT, Role.JURNALIST, Role.KOMISSAR, Role.DOCTOR, Role.SERZHANT, Role.JANOB, Role.KEZUVCHI, Role.OMADLI, Role.QOTIL, Role.SUIDSID, Role.ADMIRAL, Role.BO_RI, Role.AFSUNGAR, Role.AFERIST, Role.DAYDI, Role.SOTQIN],
}


def get_role_list(player_count: int) -> list:
    if player_count in ROLE_DISTRIBUTION:
        roles = ROLE_DISTRIBUTION[player_count].copy()
    else:
        roles = ROLE_DISTRIBUTION[20].copy()
        extra = player_count - 20
        roles.extend([Role.CITIZEN] * extra)
    random.shuffle(roles)
    return roles


@dataclass
class Player:
    user_id: int
    username: str
    first_name: str
    role: Optional[Role] = None
    alive: bool = True
    vote_target: Optional[int] = None
    gazabkor_targets: list = field(default_factory=list)
    joker_won: bool = False

    @property
    def display_name(self) -> str:
        if self.username:
            return f"@{self.username}"
        return self.first_name

    @property
    def is_mafia_team(self) -> bool:
        return self.role in MAFIA_TEAM


@dataclass
class Game:
    chat_id: int
    phase: any = None
    players: dict = field(default_factory=dict)
    day_number: int = 0
    winner: Optional[str] = None

    # Night actions keyed by role/player
    night_actions: dict = field(default_factory=dict)

    # Votes keyed by voter_id -> target_id
    votes: dict = field(default_factory=dict)

    # Aferist identity swaps: target_id -> fake_display_name
    aferist_swaps: dict = field(default_factory=dict)

    # Joker pending cards: target_id -> [card_buttons sent]
    joker_pending: dict = field(default_factory=dict)

    # Minior mines set this night: set of mined player_ids
    mines_set: set = field(default_factory=set)

    # Night visitors: target_id -> [visitor_ids]
    night_visitors: dict = field(default_factory=dict)

    # Blocked players this night (by Kezuvchi)
    blocked: set = field(default_factory=set)

    # Advokat protected mafia id
    advokat_protected: Optional[int] = None

    # Sehrgar attacker choice pending: {attacker_id: target_id}
    sehrgar_pending: dict = field(default_factory=dict)

    def __post_init__(self):
        from game import Phase
        if self.phase is None:
            self.phase = Phase.LOBBY

    def add_player(self, user_id: int, username: str, first_name: str) -> bool:
        if user_id in self.players:
            return False
        if len(self.players) >= MAX_PLAYERS:
            return False
        self.players[user_id] = Player(user_id=user_id, username=username, first_name=first_name)
        return True

    def remove_player(self, user_id: int) -> bool:
        from game import Phase
        if user_id in self.players and self.phase == Phase.LOBBY:
            del self.players[user_id]
            return True
        return False

    def alive_players(self) -> list:
        return [p for p in self.players.values() if p.alive]

    def alive_mafia_team(self) -> list:
        return [p for p in self.alive_players() if p.role in MAFIA_TEAM]

    def alive_citizens(self) -> list:
        return [p for p in self.alive_players() if p.role not in MAFIA_TEAM]

    def get_player_by_id(self, user_id: int) -> Optional[Player]:
        return self.players.get(user_id)

    def get_alive_by_role(self, role: Role) -> Optional[Player]:
        for p in self.alive_players():
            if p.role == role:
                return p
        return None

    def eliminate_player(self, user_id: int):
        player = self.players.get(user_id)
        if player:
            player.alive = False

    def assign_roles(self):
        roles = get_role_list(len(self.players))
        for player, role in zip(self.players.values(), roles):
            player.role = role

    def reset_night_state(self):
        self.night_actions = {}
        self.night_visitors = {}
        self.blocked = set()
        self.advokat_protected = None
        self.mines_set = set()
        self.aferist_swaps = {}
        self.joker_pending = {}
        self.sehrgar_pending = {}
        for p in self.players.values():
            p.vote_target = None

    def get_display_name(self, player: Player) -> str:
        if player.user_id in self.aferist_swaps:
            return self.aferist_swaps[player.user_id]
        return player.display_name

    def required_night_actors(self) -> set:
        required = set()
        alive = self.alive_players()
        roles = {p.role for p in alive}

        don = self.get_alive_by_role(Role.DON)
        if don:
            required.add(don.user_id)
        else:
            first_mafia = next((p for p in alive if p.role == Role.MAFIA), None)
            if first_mafia:
                required.add(first_mafia.user_id)

        for role in [Role.KOMISSAR, Role.DOCTOR, Role.QOTIL, Role.KEZUVCHI,
                     Role.YOLLANMA_QOTIL, Role.ADVOKAT, Role.DAYDI,
                     Role.JURNALIST, Role.AFERIST, Role.MINIOR,
                     Role.KIMYOGAR, Role.GAZABKOR, Role.JOKER, Role.SOTQIN]:
            player = self.get_alive_by_role(role)
            if player:
                required.add(player.user_id)

        serzhant = self.get_alive_by_role(Role.SERZHANT)
        komissar = self.get_alive_by_role(Role.KOMISSAR)
        if serzhant and not komissar:
            required.add(serzhant.user_id)

        return required

    def all_night_actions_done(self) -> bool:
        required = self.required_night_actors()
        done = set(self.night_actions.keys())
        return required.issubset(done)

    def tally_votes(self) -> Optional[int]:
        vote_counts: dict = {}
        for voter_id, target_id in self.votes.items():
            voter = self.players.get(voter_id)
            if voter and voter.alive:
                weight = 2 if voter.role == Role.JANOB else 1
                vote_counts[target_id] = vote_counts.get(target_id, 0) + weight

        if not vote_counts:
            return None
        max_votes = max(vote_counts.values())
        candidates = [uid for uid, c in vote_counts.items() if c == max_votes]
        return candidates[0] if len(candidates) == 1 else None

    def check_win_condition(self) -> Optional[str]:
        alive = self.alive_players()
        mafia_count = len([p for p in alive if p.role in MAFIA_TEAM])
        citizen_count = len([p for p in alive if p.role not in MAFIA_TEAM and p.role != Role.QOTIL])
        qotil = self.get_alive_by_role(Role.QOTIL)

        if mafia_count == 0 and (qotil is None):
            return "citizens"
        if mafia_count >= citizen_count and qotil is None:
            return "mafia"
        if qotil and len(alive) == 1:
            return "qotil"
        return None


class Phase(Enum):
    LOBBY = "lobby"
    NIGHT = "night"
    DAY = "day"
    VOTING = "voting"
    ENDED = "ended"
