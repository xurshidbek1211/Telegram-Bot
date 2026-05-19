import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from game import Game, Phase, Role, MIN_PLAYERS, ROLE_EMOJIS, ROLE_DESCRIPTIONS_UZ, MAFIA_TEAM
from stats import load_stats, save_stats
from night import resolve_night

logger = logging.getLogger(__name__)

games: dict[int, Game] = {}

ROLE_NAMES_UZ = {
    Role.DON: "Don",
    Role.MAFIA: "Mafia",
    Role.YOLLANMA_QOTIL: "Yollanma Qotil",
    Role.ADVOKAT: "Advokat",
    Role.JURNALIST: "Jurnalist",
    Role.KOMISSAR: "Komissar Katani",
    Role.DOCTOR: "Doktor",
    Role.SERZHANT: "Serjant",
    Role.JANOB: "Janob",
    Role.CITIZEN: "Tinch Axoli",
    Role.DAYDI: "Daydi",
    Role.KEZUVCHI: "Kezuvchi",
    Role.OMADLI: "Omadli",
    Role.ADMIRAL: "Admiral",
    Role.SOTQIN: "Sotqin",
    Role.QOTIL: "Qotil",
    Role.SUIDSID: "Suidsid",
    Role.BO_RI: "Bo'ri",
    Role.AFSUNGAR: "Afsungar",
    Role.AFERIST: "Aferist",
    Role.SEHRGAR: "Sehrgar",
    Role.GAZABKOR: "G'azabkor",
    Role.JOKER: "Joker",
    Role.KIMYOGAR: "Kimyogar",
    Role.MINIOR: "Minior",
}

TEAM_LABELS = {
    "mafia": "🔴 Mafiya jamoasi",
    "citizen": "🔵 Fuqarolar jamoasi",
    "independent": "⚪ Mustaqil",
}

ROLE_TEAMS = {
    Role.DON: "mafia", Role.MAFIA: "mafia", Role.YOLLANMA_QOTIL: "mafia",
    Role.ADVOKAT: "mafia", Role.JURNALIST: "mafia",
    Role.KOMISSAR: "citizen", Role.DOCTOR: "citizen", Role.SERZHANT: "citizen",
    Role.JANOB: "citizen", Role.CITIZEN: "citizen", Role.DAYDI: "citizen",
    Role.KEZUVCHI: "citizen", Role.OMADLI: "citizen", Role.ADMIRAL: "citizen",
    Role.SOTQIN: "citizen",
    Role.QOTIL: "independent", Role.SUIDSID: "independent", Role.BO_RI: "independent",
    Role.AFSUNGAR: "independent", Role.AFERIST: "independent", Role.SEHRGAR: "independent",
    Role.GAZABKOR: "independent", Role.JOKER: "independent", Role.KIMYOGAR: "independent",
    Role.MINIOR: "independent",
}

# Roles that have night actions (not passive)
NIGHT_ACTION_ROLES = {
    Role.DON, Role.MAFIA, Role.KOMISSAR, Role.SERZHANT, Role.DOCTOR,
    Role.KEZUVCHI, Role.DAYDI, Role.JURNALIST, Role.ADVOKAT, Role.AFERIST,
    Role.QOTIL, Role.YOLLANMA_QOTIL, Role.KIMYOGAR, Role.MINIOR,
    Role.GAZABKOR, Role.JOKER, Role.SOTQIN,
}

# Roles with no night action (passive)
PASSIVE_NIGHT_ROLES = {
    Role.CITIZEN, Role.JANOB, Role.SUIDSID, Role.OMADLI, Role.BO_RI,
    Role.AFSUNGAR, Role.SEHRGAR, Role.ADMIRAL,
}

PASSIVE_MESSAGES = {
    Role.CITIZEN: "👨🏼 Siz Tinch Axolisiz. Dam oling — ertaga shahar himoyangizga muhtoj!",
    Role.JANOB: "🎖 Siz Janobsiz. Kunduz ovozda sizning ovozingiz ikkitaga teng bo'ladi. Dam oling!",
    Role.SUIDSID: "🤦🏼 Siz Suidsidsiz. Kunduz ovozda osib o'ldirilsangiz — g'alaba qozonasiz!\nDam oling.",
    Role.OMADLI: "🤞🏼 Siz Omadlisiz. Agar kechasi nishonga olinsangiz, 50% ehtimolda omon qolishingiz mumkin! Dam oling.",
    Role.BO_RI: "🐺 Siz Bo'risiz. Bu kecha siz passiv — dam oling. Esda tutingki, sizi kim o'ldirishi kelajagingizni belgilaydi!",
    Role.AFSUNGAR: "💣 Siz Afsungarsiz. Dam oling — agar kechasi o'ldirilsangiz, o'ldirgan ham halok bo'ladi!",
    Role.SEHRGAR: "🧙‍ Siz Sehrgarsiz. Don, Qotil yoki Komissar sizi o'ldirmoqchi bo'lsa, siz xabar olasiz va tanlov beriladi. Dam oling.",
    Role.ADMIRAL: "🧑🏻‍✈️ Siz Admiralsiz. Komissar va Serjant tirik ekan, siz o'lmas! Ular o'lsa, siz Komissar bo'lasiz. Dam oling.",
}


def build_player_list(game: Game, show_roles: bool = False) -> str:
    lines = []
    for i, player in enumerate(game.players.values(), 1):
        status = "" if player.alive else " ☠️"
        if show_roles and player.role:
            role_name = ROLE_NAMES_UZ.get(player.role, player.role.value)
            role_str = f" ({ROLE_EMOJIS[player.role]} {role_name})"
        else:
            role_str = ""
        lines.append(f"{i}. {player.display_name}{role_str}{status}")
    return "\n".join(lines) if lines else "Hali o'yinchilar yo'q."


def build_target_keyboard(game: Game, action_prefix: str, exclude_ids: list = None, include_self: bool = False, actor_id: int = None) -> InlineKeyboardMarkup:
    exclude_ids = exclude_ids or []
    buttons = []
    for player in game.alive_players():
        if player.user_id in exclude_ids:
            continue
        if not include_self and actor_id and player.user_id == actor_id:
            continue
        buttons.append([InlineKeyboardButton(
            player.display_name,
            callback_data=f"{action_prefix}:{player.user_id}:{game.chat_id}"
        )])
    return InlineKeyboardMarkup(buttons)


def build_vote_keyboard(game: Game, voter_id: int) -> InlineKeyboardMarkup:
    buttons = []
    for player in game.alive_players():
        if player.user_id != voter_id:
            label = game.get_display_name(player)
            if game.votes.get(voter_id) == player.user_id:
                label = f"✅ {label}"
            buttons.append([InlineKeyboardButton(label, callback_data=f"vote:{player.user_id}")])
    return InlineKeyboardMarkup(buttons)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        await update.message.reply_text(
            "👋 Salom! Men *Mafiya O'yin Boti*man.\n\n"
            "Meni guruh chatiga qo'shing va o'yinni boshlash uchun /newgame dan foydalaning!\n\n"
            "*Buyruqlar:*\n"
            "/newgame — Yangi o'yin lobby'si\n"
            "/join — O'yinga qo'shilish\n"
            "/leave — Lobby'dan chiqish\n"
            "/players — O'yinchilar ro'yxati\n"
            "/startgame — O'yinni boshlash (admin)\n"
            "/endgame — O'yinni tugatish (admin)\n"
            "/stats — Statistika\n"
            "/rules — Qoidalar\n"
            "/roles — Barcha rollar haqida",
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await update.message.reply_text("👋 Mafiya o'yinini boshlash uchun /newgame dan foydalaning!")


async def cmd_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🃏 *Mafiya O'yin Qoidalari*\n\n"
        "*Bosqichlar:*\n"
        "🌙 *Kecha* — Maxsus rollar xususiy xabar orqali harakatlarini bajaradi.\n"
        "☀️ *Kunduz* — O'yinchilar muhokama qiladi va shubhalilarga ovoz beradi.\n\n"
        "*G'alaba shartlari:*\n"
        "🔴 Mafiya jamoasi — Fuqarolar soniga teng yoki ko'p bo'lganda g'alaba.\n"
        "🔵 Fuqarolar — Barcha Mafiya yo'q qilinganda g'alaba.\n"
        "⚪ Mustaqil rollar — O'z shartlari bor (Suidsid, Qotil, G'azabkor va h.k.)\n\n"
        "Barcha rollar uchun: /roles\n\n"
        f"*Minimal o'yinchilar:* {MIN_PLAYERS}"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def cmd_roles(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pages = []
    team_roles = {
        "🔴 *Mafiya jamoasi:*": [Role.DON, Role.MAFIA, Role.YOLLANMA_QOTIL, Role.ADVOKAT, Role.JURNALIST],
        "🔵 *Fuqarolar jamoasi:*": [Role.KOMISSAR, Role.DOCTOR, Role.SERZHANT, Role.JANOB, Role.CITIZEN, Role.DAYDI, Role.KEZUVCHI, Role.OMADLI, Role.ADMIRAL, Role.SOTQIN],
        "⚪ *Mustaqil rollar:*": [Role.QOTIL, Role.SUIDSID, Role.BO_RI, Role.AFSUNGAR, Role.AFERIST, Role.SEHRGAR, Role.GAZABKOR, Role.JOKER, Role.KIMYOGAR, Role.MINIOR],
    }
    for team_label, roles in team_roles.items():
        msg = f"{team_label}\n\n"
        for role in roles:
            emoji = ROLE_EMOJIS[role]
            name = ROLE_NAMES_UZ[role]
            desc = ROLE_DESCRIPTIONS_UZ[role].split("\n")[0]
            msg += f"{emoji} *{name}*\n_{desc}_\n\n"
        pages.append(msg)

    for page in pages:
        await update.message.reply_text(page, parse_mode=ParseMode.MARKDOWN)


async def cmd_newgame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if update.effective_chat.type == "private":
        await update.message.reply_text("⚠️ Bu buyruq faqat guruh chatlarda ishlaydi.")
        return

    existing = games.get(chat_id)
    if existing and existing.phase != Phase.ENDED:
        await update.message.reply_text("⚠️ O'yin allaqachon davom etmoqda! Avval /endgame bilan bekor qiling.")
        return

    games[chat_id] = Game(chat_id=chat_id)
    game = games[chat_id]
    user = update.effective_user
    game.add_player(user.id, user.username or "", user.first_name)

    await update.message.reply_text(
        "🎮 *Yangi Mafiya o'yini boshlanmoqda!*\n\n"
        f"👤 {user.first_name} o'yinni yaratdi.\n\n"
        "Qo'shilish uchun /join dan foydalaning.\n"
        "Hammasi tayyor bo'lganda admin /startgame bossin.\n"
        "/roles — barcha rollar haqida.\n\n"
        f"*O'yinchilar ({len(game.players)}/{MIN_PLAYERS} min):*\n"
        f"{build_player_list(game)}",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if update.effective_chat.type == "private":
        await update.message.reply_text("⚠️ Guruh chatida o'yinga qo'shiling.")
        return

    game = games.get(chat_id)
    if not game or game.phase == Phase.ENDED:
        await update.message.reply_text("⚠️ Faol lobby yo'q. /newgame bilan yangisini boshlang.")
        return
    if game.phase != Phase.LOBBY:
        await update.message.reply_text("⚠️ O'yin allaqachon boshlangan. Keyingi o'yinni kuting!")
        return

    user = update.effective_user
    if game.add_player(user.id, user.username or "", user.first_name):
        await update.message.reply_text(
            f"✅ *{user.first_name}* o'yinga qo'shildi!\n\n"
            f"*O'yinchilar ({len(game.players)}/{MIN_PLAYERS} min):*\n"
            f"{build_player_list(game)}",
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        if user.id in game.players:
            await update.message.reply_text("⚠️ Siz allaqachon o'yindasiz!")
        else:
            await update.message.reply_text("⚠️ Lobby to'lgan.")


async def cmd_leave(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    game = games.get(chat_id)
    if not game or game.phase != Phase.LOBBY:
        await update.message.reply_text("⚠️ Faqat lobby bosqichida chiqish mumkin.")
        return

    user = update.effective_user
    if game.remove_player(user.id):
        await update.message.reply_text(
            f"👋 *{user.first_name}* o'yindan chiqdi.\n\n"
            f"*O'yinchilar ({len(game.players)}):*\n{build_player_list(game)}",
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await update.message.reply_text("⚠️ Siz lobby'da emassiz.")


async def cmd_players(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    game = games.get(chat_id)
    if not game or game.phase == Phase.ENDED:
        await update.message.reply_text("⚠️ Bu chatda faol o'yin yo'q.")
        return

    phase_label = {
        Phase.LOBBY: "Lobby",
        Phase.NIGHT: f"{game.day_number}-kecha",
        Phase.DAY: f"{game.day_number}-kun",
        Phase.VOTING: f"Ovoz berish — {game.day_number}-kun",
    }.get(game.phase, "")

    alive = game.alive_players()
    dead = [p for p in game.players.values() if not p.alive]

    text = f"👥 *O'yinchilar — {phase_label}*\n\n*Tirik ({len(alive)}):*\n"
    for i, p in enumerate(alive, 1):
        text += f"{i}. {p.display_name}\n"
    if dead:
        text += f"\n*Chiqarilgan ({len(dead)}):*\n"
        for p in dead:
            role_name = ROLE_NAMES_UZ.get(p.role, "") if p.role else ""
            emoji = ROLE_EMOJIS.get(p.role, "") if p.role else ""
            text += f"☠️ {p.display_name} — {emoji} {role_name}\n"

    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def cmd_startgame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if update.effective_chat.type == "private":
        await update.message.reply_text("⚠️ Bu buyruq faqat guruh chatlarda ishlaydi.")
        return

    game = games.get(chat_id)
    if not game or game.phase == Phase.ENDED:
        await update.message.reply_text("⚠️ Faol lobby yo'q. /newgame dan foydalaning.")
        return
    if game.phase != Phase.LOBBY:
        await update.message.reply_text("⚠️ O'yin allaqachon boshlangan.")
        return

    member = await context.bot.get_chat_member(chat_id, update.effective_user.id)
    is_admin = member.status in ("administrator", "creator")
    if not is_admin and update.effective_user.id not in game.players:
        await update.message.reply_text("⚠️ Faqat admin yoki lobby o'yinchilari boshlashi mumkin.")
        return

    if len(game.players) < MIN_PLAYERS:
        await update.message.reply_text(
            f"⚠️ Kamida *{MIN_PLAYERS}* o'yinchi kerak. Hozir: *{len(game.players)}*",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    await start_game(update, context, game)


async def start_game(update: Update, context: ContextTypes.DEFAULT_TYPE, game: Game):
    game.assign_roles()
    game.phase = Phase.NIGHT
    game.day_number = 1

    role_counts: dict = {}
    for p in game.players.values():
        role_counts[p.role] = role_counts.get(p.role, 0) + 1

    dist_text = "  ".join(
        f"{ROLE_EMOJIS[r]} {ROLE_NAMES_UZ[r]}: {n}"
        for r, n in role_counts.items()
    )

    await update.message.reply_text(
        f"🎮 *Mafiya o'yini boshlandi!*\n\n"
        f"*{len(game.players)} o'yinchi* o'z rollarini oldi.\n"
        f"{dist_text}\n\n"
        "🌙 *1-kecha boshlandi!*\n"
        "Rolingiz va ko'rsatmalar uchun shaxsiy xabarlaringizni tekshiring.\n"
        "⚠️ Agar bot sizga DM yubora olmasa, avval botga /start yozing!",
        parse_mode=ParseMode.MARKDOWN,
    )

    mafia_team = [p for p in game.players.values() if p.role in MAFIA_TEAM]
    mafia_names = ", ".join(p.display_name for p in mafia_team)

    for player in game.players.values():
        emoji = ROLE_EMOJIS[player.role]
        role_name = ROLE_NAMES_UZ[player.role]
        desc = ROLE_DESCRIPTIONS_UZ[player.role]
        team = TEAM_LABELS.get(ROLE_TEAMS.get(player.role, "independent"), "")

        extra = ""
        if player.role in MAFIA_TEAM:
            extra = f"\n\n🤝 *Mafiya jamoangiz:* {mafia_names}"

        try:
            await context.bot.send_message(
                player.user_id,
                f"🎭 *Sizning rolingiz: {emoji} {role_name}*\n"
                f"_{team}_\n\n{desc}{extra}\n\n"
                "O'yin boshlandi. Kecha harakati ko'rsatmalarini kuting.",
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            pass

    await send_night_actions(context, game)


async def send_night_actions(context: ContextTypes.DEFAULT_TYPE, game: Game):
    game.reset_night_state()
    chat_id = game.chat_id
    alive = game.alive_players()
    mafia_team = [p for p in alive if p.role in MAFIA_TEAM and p.role in (Role.DON, Role.MAFIA)]
    mafia_team_names = ", ".join(p.display_name for p in mafia_team)

    for player in alive:
        role = player.role

        if role == Role.DON:
            targets = [p for p in alive if p.role not in MAFIA_TEAM]
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(p.display_name, callback_data=f"night_mafia:{p.user_id}:{chat_id}")]
                for p in targets
            ])
            allies = [p.display_name for p in mafia_team if p.user_id != player.user_id]
            ally_text = f"\n🤝 Mafiya: {', '.join(allies)}" if allies else ""
            await _send_dm(context, player.user_id,
                f"🌙 *{game.day_number}-kecha*{ally_text}\n\n"
                "🤵🏻 *Don sifatida:* bu kecha yo'q qilish uchun o'yinchini tanlang:",
                kb)

        elif role == Role.MAFIA:
            targets = [p for p in alive if p.role not in MAFIA_TEAM]
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(p.display_name, callback_data=f"night_mafia:{p.user_id}:{chat_id}")]
                for p in targets
            ])
            don = game.get_alive_by_role(Role.DON)
            leader = f"Don: {don.display_name}" if don else "Siz lider (Don yo'q)"
            allies = [p.display_name for p in mafia_team if p.user_id != player.user_id]
            ally_text = f"\n🤝 Mafiya: {', '.join(allies)}" if allies else ""
            await _send_dm(context, player.user_id,
                f"🌙 *{game.day_number}-kecha*\n_{leader}_{ally_text}\n\n"
                "🤵🏼 O'ldirish uchun nishon tanlang:",
                kb)

        elif role == Role.YOLLANMA_QOTIL:
            targets = [p for p in alive if p.role not in MAFIA_TEAM]
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(p.display_name, callback_data=f"night_yq:{p.user_id}:{chat_id}")]
                for p in targets
            ])
            allies = [p.display_name for p in alive if p.role in MAFIA_TEAM and p.role != Role.YOLLANMA_QOTIL]
            ally_text = f"\n🤝 Mafiya jamoasi: {', '.join(allies)}" if allies else ""
            await _send_dm(context, player.user_id,
                f"🌙 *{game.day_number}-kecha*{ally_text}\n\n"
                "🥷 Yashirincha ovlash uchun nishon tanlang:\n"
                "⚠️ Komissarni tanlasangiz, u sizni o'ldiradi!",
                kb)

        elif role == Role.ADVOKAT:
            targets = [p for p in alive if p.role in MAFIA_TEAM and p.user_id != player.user_id]
            if not targets:
                game.night_actions[Role.ADVOKAT] = player.user_id
                await _send_dm(context, player.user_id,
                    f"🌙 *{game.day_number}-kecha*\n\n"
                    "👨🏼‍💼 Himoya qilish uchun boshqa Mafiya yo'q. Harakatingiz o'tkazib yuborildi.")
            else:
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton(p.display_name, callback_data=f"night_advokat:{p.user_id}:{chat_id}")]
                    for p in targets
                ])
                await _send_dm(context, player.user_id,
                    f"🌙 *{game.day_number}-kecha*\n\n"
                    "👨🏼‍💼 Kommisardan himoya qilish uchun Mafiya a'zosini tanlang:",
                    kb)

        elif role == Role.JURNALIST:
            kb = build_target_keyboard(game, "night_jurnalist", actor_id=player.user_id)
            await _send_dm(context, player.user_id,
                f"🌙 *{game.day_number}-kecha*\n\n"
                "👩🏼‍💻 Intervyu olish uchun o'yinchini tanlang (uyiga kimlar kelganini ko'rasiz):",
                kb)

        elif role == Role.KOMISSAR:
            kb = build_target_keyboard(game, "night_komissar", actor_id=player.user_id)
            await _send_dm(context, player.user_id,
                f"🌙 *{game.day_number}-kecha*\n\n"
                "🕵🏼 Tekshirish uchun o'yinchini tanlang. Agar u Mafiya bo'lsa (va himoyalanmagan bo'lsa), u o'ldiriladi:",
                kb)

        elif role == Role.SERZHANT and not game.get_alive_by_role(Role.KOMISSAR):
            kb = build_target_keyboard(game, "night_komissar", actor_id=player.user_id)
            await _send_dm(context, player.user_id,
                f"🌙 *{game.day_number}-kecha*\n\n"
                "👮🏼 Siz endi Komissar vazifasini bajaryapsiz.\n"
                "Tekshirish uchun o'yinchini tanlang:",
                kb)

        elif role == Role.DOCTOR:
            kb = build_target_keyboard(game, "night_doctor", include_self=True, actor_id=player.user_id)
            await _send_dm(context, player.user_id,
                f"🌙 *{game.day_number}-kecha*\n\n"
                "💊 Himoya qilish uchun o'yinchini tanlang (o'zingizni ham tanlashingiz mumkin):",
                kb)

        elif role == Role.KEZUVCHI:
            kb = build_target_keyboard(game, "night_kezuvchi", actor_id=player.user_id)
            await _send_dm(context, player.user_id,
                f"🌙 *{game.day_number}-kecha*\n\n"
                "💃 Uyqu dori berish uchun o'yinchini tanlang (u bu kecha harakatsiz bo'ladi):",
                kb)

        elif role == Role.DAYDI:
            kb = build_target_keyboard(game, "night_daydi", actor_id=player.user_id)
            await _send_dm(context, player.user_id,
                f"🌙 *{game.day_number}-kecha*\n\n"
                "🧙‍♂️ Tashrif buyurish uchun o'yinchini tanlang (uning uyiga kimlar kelganini ko'rasiz):",
                kb)

        elif role == Role.QOTIL:
            kb = build_target_keyboard(game, "night_qotil", actor_id=player.user_id)
            await _send_dm(context, player.user_id,
                f"🌙 *{game.day_number}-kecha*\n\n"
                "🔪 O'ldirish uchun nishon tanlang:",
                kb)

        elif role == Role.KIMYOGAR:
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🩺 Davolash", callback_data=f"night_kimyogar_mode:heal:{chat_id}"),
                 InlineKeyboardButton("☠️ O'ldirish", callback_data=f"night_kimyogar_mode:kill:{chat_id}")]
            ])
            await _send_dm(context, player.user_id,
                f"🌙 *{game.day_number}-kecha*\n\n"
                "👨‍🔬 Bu kecha nima qilasiz?",
                kb)

        elif role == Role.MINIOR:
            kb = build_target_keyboard(game, "night_minior", actor_id=player.user_id)
            await _send_dm(context, player.user_id,
                f"🌙 *{game.day_number}-kecha*\n\n"
                "☠️ Mina qo'yish uchun o'yinchini tanlang (uning uyiga bu kecha kelganlar halok bo'ladi):",
                kb)

        elif role == Role.AFERIST:
            kb = build_target_keyboard(game, "night_aferist", actor_id=player.user_id)
            await _send_dm(context, player.user_id,
                f"🌙 *{game.day_number}-kecha*\n\n"
                "🤹🏻 Kimning ovoz berish shaxsini almashtirmoqchisiz?",
                kb)

        elif role == Role.GAZABKOR:
            kb = build_target_keyboard(game, "night_gazabkor", include_self=True, actor_id=player.user_id)
            count = len(player.gazabkor_targets)
            await _send_dm(context, player.user_id,
                f"🌙 *{game.day_number}-kecha*\n\n"
                f"🧟 Ro'yxatga qo'shish uchun o'yinchini tanlang.\n"
                f"Hozirgi ro'yxat: *{count}* kishi\n"
                f"O'zingizni tanlasangiz, barchasi o'ladi (kamida 3 kishi kerak g'alaba uchun):",
                kb)

        elif role == Role.JOKER:
            kb = build_target_keyboard(game, "night_joker", actor_id=player.user_id)
            await _send_dm(context, player.user_id,
                f"🌙 *{game.day_number}-kecha*\n\n"
                "🤡 Kimga 4 ta karta yuborasiz? (biri o'lim kartasi — 25% ehtimol):",
                kb)

        elif role == Role.SOTQIN:
            targets = [p for p in alive if p.role in (Role.DON, Role.MAFIA, Role.QOTIL)]
            if targets:
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton(p.display_name, callback_data=f"night_sotqin:{p.user_id}:{chat_id}")]
                    for p in targets
                ] + [[InlineKeyboardButton("⏭️ O'tkazib yuborish", callback_data=f"night_sotqin:0:{chat_id}")]])
                await _send_dm(context, player.user_id,
                    f"🌙 *{game.day_number}-kecha*\n\n"
                    "🤓 Kimni fosh qilmoqchisiz? (Faqat Don, Mafia yoki Qotilni aniqlashingiz mumkin)\n"
                    "Agar bilmasangiz, o'tkazib yuboring:",
                    kb)
            else:
                game.night_actions[Role.SOTQIN] = 0
                await _send_dm(context, player.user_id,
                    f"🌙 *{game.day_number}-kecha*\n\n"
                    "🤓 Hozircha fosh qilish uchun ma'lum nishon yo'q. Dam oling.")

        elif role in PASSIVE_NIGHT_ROLES:
            msg = PASSIVE_MESSAGES.get(role, "Dam oling.")
            actor_id_key = f"passive_{player.user_id}"
            game.night_actions[actor_id_key] = True
            await _send_dm(context, player.user_id,
                f"🌙 *{game.day_number}-kecha*\n\n{msg}")

    _auto_register_passive_actions(game)


def _auto_register_passive_actions(game: Game):
    for player in game.alive_players():
        if player.role in PASSIVE_NIGHT_ROLES:
            key = f"passive_{player.user_id}"
            if key not in game.night_actions:
                game.night_actions[key] = True

    required = game.required_night_actors()
    for uid in required:
        p = game.get_player_by_id(uid)
        if p and p.role == Role.SERZHANT and game.get_alive_by_role(Role.KOMISSAR):
            game.night_actions[Role.SERZHANT] = 0


async def _send_dm(context, user_id: int, text: str, keyboard=None):
    try:
        await context.bot.send_message(user_id, text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.warning(f"DM yuborishda xato (user {user_id}): {e}")


async def handle_night_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    parts = data.split(":")
    action = parts[0]
    raw_target = parts[1]
    chat_id = int(parts[2])

    game = games.get(chat_id)
    if not game or game.phase != Phase.NIGHT:
        await query.edit_message_text("⚠️ Bu harakat endi amal qilmaydi.")
        return

    actor_id = query.from_user.id
    actor = game.get_player_by_id(actor_id)
    if not actor or not actor.alive:
        await query.edit_message_text("⚠️ Siz faol o'yinchi emassiz.")
        return

    target_id = int(raw_target) if raw_target != "0" else 0

    if action == "night_mafia":
        target = game.get_player_by_id(target_id)
        if not target or not target.alive:
            await query.edit_message_text("⚠️ Bu o'yinchi mavjud emas.")
            return
        game.night_actions["mafia_kill"] = target_id
        game.night_actions[actor_id] = target_id
        await query.edit_message_text(
            f"🔪 Nishon tanlandi: *{target.display_name}*",
            parse_mode=ParseMode.MARKDOWN,
        )

    elif action == "night_yq":
        target = game.get_player_by_id(target_id)
        if not target or not target.alive:
            await query.edit_message_text("⚠️ Bu o'yinchi mavjud emas.")
            return
        game.night_actions[Role.YOLLANMA_QOTIL] = target_id
        await query.edit_message_text(
            f"🥷 Nishon tanlandi: *{target.display_name}*",
            parse_mode=ParseMode.MARKDOWN,
        )

    elif action == "night_advokat":
        target = game.get_player_by_id(target_id)
        if not target or not target.alive:
            await query.edit_message_text("⚠️ Bu o'yinchi mavjud emas.")
            return
        game.night_actions[Role.ADVOKAT] = target_id
        await query.edit_message_text(
            f"👨🏼‍💼 Himoya qilindi: *{target.display_name}*",
            parse_mode=ParseMode.MARKDOWN,
        )

    elif action == "night_jurnalist":
        target = game.get_player_by_id(target_id)
        if not target or not target.alive:
            await query.edit_message_text("⚠️ Bu o'yinchi mavjud emas.")
            return
        game.night_actions[Role.JURNALIST] = target_id
        await query.edit_message_text(
            f"👩🏼‍💻 Intervyu manzili: *{target.display_name}*",
            parse_mode=ParseMode.MARKDOWN,
        )

    elif action == "night_komissar":
        target = game.get_player_by_id(target_id)
        if not target or not target.alive:
            await query.edit_message_text("⚠️ Bu o'yinchi mavjud emas.")
            return
        komissar = game.get_alive_by_role(Role.KOMISSAR)
        key = Role.KOMISSAR if komissar else Role.SERZHANT
        game.night_actions[key] = target_id
        await query.edit_message_text(
            f"🕵🏼 Tekshirilmoqda: *{target.display_name}*",
            parse_mode=ParseMode.MARKDOWN,
        )

    elif action == "night_doctor":
        target = game.get_player_by_id(target_id)
        if not target or not target.alive:
            await query.edit_message_text("⚠️ Bu o'yinchi mavjud emas.")
            return
        game.night_actions[Role.DOCTOR] = target_id
        await query.edit_message_text(
            f"💊 Himoyaga olindi: *{target.display_name}*",
            parse_mode=ParseMode.MARKDOWN,
        )

    elif action == "night_kezuvchi":
        target = game.get_player_by_id(target_id)
        if not target or not target.alive:
            await query.edit_message_text("⚠️ Bu o'yinchi mavjud emas.")
            return
        game.night_actions[Role.KEZUVCHI] = target_id
        await query.edit_message_text(
            f"💃 Uyqu dori berildi: *{target.display_name}*",
            parse_mode=ParseMode.MARKDOWN,
        )

    elif action == "night_daydi":
        target = game.get_player_by_id(target_id)
        if not target or not target.alive:
            await query.edit_message_text("⚠️ Bu o'yinchi mavjud emas.")
            return
        game.night_actions[Role.DAYDI] = target_id
        await query.edit_message_text(
            f"🧙‍♂️ Tashrif manzili: *{target.display_name}*",
            parse_mode=ParseMode.MARKDOWN,
        )

    elif action == "night_qotil":
        target = game.get_player_by_id(target_id)
        if not target or not target.alive:
            await query.edit_message_text("⚠️ Bu o'yinchi mavjud emas.")
            return
        game.night_actions[Role.QOTIL] = target_id
        await query.edit_message_text(
            f"🔪 Nishon: *{target.display_name}*",
            parse_mode=ParseMode.MARKDOWN,
        )

    elif action == "night_kimyogar_mode":
        mode = parts[1]
        game.night_actions["kimyogar_mode"] = mode
        label = "davolash 🩺" if mode == "heal" else "o'ldirish ☠️"
        kb = build_target_keyboard(game, "night_kimyogar", include_self=(mode == "heal"), actor_id=actor_id)
        await query.edit_message_text(
            f"👨‍🔬 *{label.capitalize()}* uchun o'yinchini tanlang:",
            reply_markup=kb,
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    elif action == "night_kimyogar":
        target = game.get_player_by_id(target_id)
        if not target or not target.alive:
            await query.edit_message_text("⚠️ Bu o'yinchi mavjud emas.")
            return
        game.night_actions[Role.KIMYOGAR] = target_id
        mode = game.night_actions.get("kimyogar_mode", "heal")
        label = "davolash" if mode == "heal" else "o'ldirish"
        await query.edit_message_text(
            f"👨‍🔬 *{target.display_name}* — {label} tanlandi.",
            parse_mode=ParseMode.MARKDOWN,
        )

    elif action == "night_minior":
        target = game.get_player_by_id(target_id)
        if not target or not target.alive:
            await query.edit_message_text("⚠️ Bu o'yinchi mavjud emas.")
            return
        game.night_actions[Role.MINIOR] = target_id
        await query.edit_message_text(
            f"☠️ Mina qo'yildi: *{target.display_name}* eshigi oldiga.",
            parse_mode=ParseMode.MARKDOWN,
        )

    elif action == "night_aferist":
        target = game.get_player_by_id(target_id)
        if not target or not target.alive:
            await query.edit_message_text("⚠️ Bu o'yinchi mavjud emas.")
            return
        game.night_actions[Role.AFERIST] = target_id
        await query.edit_message_text(
            f"🤹🏻 Shaxs almashtirildi: *{target.display_name}*",
            parse_mode=ParseMode.MARKDOWN,
        )

    elif action == "night_gazabkor":
        actor = game.get_player_by_id(actor_id)
        if not actor:
            await query.edit_message_text("⚠️ Siz faol o'yinchi emassiz.")
            return
        game.night_actions[Role.GAZABKOR] = target_id
        if target_id == actor_id:
            await query.edit_message_text(
                "🧟 O'zingizni tanladingiz — natija tunda aniqlanadi!",
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            target = game.get_player_by_id(target_id)
            t_name = target.display_name if target else str(target_id)
            await query.edit_message_text(
                f"🧟 *{t_name}* ro'yxatga qo'shildi.",
                parse_mode=ParseMode.MARKDOWN,
            )

    elif action == "night_joker":
        target = game.get_player_by_id(target_id)
        if not target or not target.alive:
            await query.edit_message_text("⚠️ Bu o'yinchi mavjud emas.")
            return
        game.night_actions[Role.JOKER] = target_id
        await query.edit_message_text(
            f"🤡 4 ta karta yuborildi: *{target.display_name}*",
            parse_mode=ParseMode.MARKDOWN,
        )

    elif action == "night_sotqin":
        game.night_actions[Role.SOTQIN] = target_id
        if target_id == 0:
            await query.edit_message_text("🤓 Bu kecha o'tkazib yubordingiz.")
        else:
            target = game.get_player_by_id(target_id)
            t_name = target.display_name if target else str(target_id)
            await query.edit_message_text(
                f"🤓 Nishon tanlandi: *{t_name}*",
                parse_mode=ParseMode.MARKDOWN,
            )

    else:
        await query.edit_message_text("⚠️ Noma'lum harakat.")
        return

    if game.all_night_actions_done():
        await do_night_resolution(context, game)


async def handle_sehrgar_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":")
    choice = parts[1]
    chat_id = int(parts[2])

    game = games.get(chat_id)
    if not game or game.phase != Phase.NIGHT:
        await query.edit_message_text("⚠️ Bu harakat endi amal qilmaydi.")
        return

    sehrgar = game.get_alive_by_role(Role.SEHRGAR)
    if not sehrgar or sehrgar.user_id != query.from_user.id:
        await query.edit_message_text("⚠️ Bu sizning harakatingiz emas.")
        return

    if choice == "kill":
        for cause in list(game.sehrgar_pending.keys()):
            attacker_role_map = {"mafia": [Role.DON, Role.MAFIA], "komissar": [Role.KOMISSAR, Role.SERZHANT], "qotil": [Role.QOTIL]}
            for r in attacker_role_map.get(cause, []):
                attacker = game.get_alive_by_role(r)
                if attacker:
                    game.eliminate_player(attacker.user_id)
        await query.edit_message_text("⚡ Siz dushmanni o'ldirdingiz! Natija tunda e'lon qilinadi.")
    else:
        await query.edit_message_text("🕊️ Rahm qildingiz. Kech bo'lsa ham yaxshilik qaytadi...")

    game.sehrgar_pending = {}

    if game.all_night_actions_done():
        await do_night_resolution(context, game)


async def do_night_resolution(context: ContextTypes.DEFAULT_TYPE, game: Game):
    events = await resolve_night(game, context)
    game.phase = Phase.DAY

    winner = game.check_win_condition()
    if winner:
        summary = "\n".join(f"• {e}" for e in events)
        await context.bot.send_message(
            game.chat_id,
            f"🌙 *{game.day_number}-kecha yakunlandi:*\n\n{summary}",
            parse_mode=ParseMode.MARKDOWN,
        )
        await end_game(context, game, winner, game.chat_id)
        return

    summary = "\n".join(f"• {e}" for e in events)
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🗳️ Ovoz berishni boshlash", callback_data=f"open_voting:{game.chat_id}")
    ]])
    await context.bot.send_message(
        game.chat_id,
        f"☀️ *{game.day_number}-kun boshlandi!*\n\n"
        f"*Kecha nima bo'ldi:*\n{summary}\n\n"
        "Muhokama qiling va shubhalilarga ovoz bering!",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard,
    )


async def cmd_vote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    game = games.get(chat_id)
    if not game or game.phase not in (Phase.DAY, Phase.VOTING):
        await update.message.reply_text("⚠️ Hozir ovoz berish faol emas.")
        return

    game.phase = Phase.VOTING
    game.votes = {}
    await update.message.reply_text(
        "🗳️ *Ovoz berish boshlandi!* Har bir o'yinchiga shaxsiy xabar yuboriladi.",
        parse_mode=ParseMode.MARKDOWN,
    )
    await send_voting_to_players(context, game)


async def handle_open_voting_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":")
    chat_id = int(parts[1])
    game = games.get(chat_id)

    if not game or game.phase not in (Phase.DAY, Phase.VOTING):
        await query.edit_message_text("⚠️ Ovoz berish endi faol emas.")
        return

    game.phase = Phase.VOTING
    game.votes = {}
    await query.edit_message_text(
        "🗳️ *Ovoz berish boshlandi!*\nHar bir o'yinchiga shaxsiy xabar yuboriladi.",
        parse_mode=ParseMode.MARKDOWN,
    )
    await send_voting_to_players(context, game)


async def send_voting_to_players(context: ContextTypes.DEFAULT_TYPE, game: Game):
    for player in game.alive_players():
        kb = build_vote_keyboard(game, player.user_id)
        await _send_dm(context, player.user_id,
            f"🗳️ *{game.day_number}-kun — Ovoz bering!*\n\n"
            "Sizningcha kim Mafiya?\n"
            "Bosing = ovoz. Qayta bosing = bekor.\n\n"
            "Hammasi ovoz bergach guruhda /endvote bosing.",
            kb)


async def handle_vote_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":")
    target_id = int(parts[1])
    voter_id = query.from_user.id

    chat_id = None
    for cid, g in games.items():
        if voter_id in g.players and g.phase == Phase.VOTING:
            chat_id = cid
            break

    if not chat_id:
        await query.edit_message_text("⚠️ Faol ovoz berish topilmadi.")
        return

    game = games[chat_id]
    voter = game.get_player_by_id(voter_id)
    target = game.get_player_by_id(target_id)

    if not voter or not voter.alive:
        await query.edit_message_text("⚠️ Siz faol o'yinchi emassiz.")
        return
    if not target or not target.alive:
        await query.edit_message_text("⚠️ Bu o'yinchi mavjud emas.")
        return

    target_display = game.get_display_name(target)

    if game.votes.get(voter_id) == target_id:
        del game.votes[voter_id]
        await query.edit_message_text(
            f"🗳️ *{game.day_number}-kun — Ovoz bering!*\n\n"
            f"*{target_display}*ga ovozingiz bekor qilindi.\n\nBoshqa nomga bosing.",
            reply_markup=build_vote_keyboard(game, voter_id),
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        game.votes[voter_id] = target_id
        await query.edit_message_text(
            f"🗳️ *{game.day_number}-kun — Ovoz bering!*\n\n"
            f"✅ *{target_display}*ga ovoz berdingiz.\n\nBekor qilish uchun qayta bosing.",
            reply_markup=build_vote_keyboard(game, voter_id),
            parse_mode=ParseMode.MARKDOWN,
        )


async def cmd_endvote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    game = games.get(chat_id)

    if not game or game.phase != Phase.VOTING:
        await update.message.reply_text("⚠️ Tugatish uchun faol ovoz berish yo'q.")
        return

    voted_count = sum(1 for vid in game.votes if game.get_player_by_id(vid) and game.get_player_by_id(vid).alive)
    alive_count = len(game.alive_players())

    if voted_count < alive_count:
        not_voted = [p.display_name for p in game.alive_players() if p.user_id not in game.votes]
        await update.message.reply_text(
            f"⏳ *Ovozlar kutilmoqda...*\n"
            f"{voted_count}/{alive_count} ovoz berildi.\n\n"
            f"*Hali bermagan:* {', '.join(not_voted)}",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    await resolve_vote(update, context, game)


async def resolve_vote(update, context: ContextTypes.DEFAULT_TYPE, game: Game):
    eliminated_id = game.tally_votes()

    vote_counts: dict = {}
    for vid, tid in game.votes.items():
        voter = game.get_player_by_id(vid)
        if voter:
            weight = 2 if voter.role == Role.JANOB else 1
            vote_counts[tid] = vote_counts.get(tid, 0) + weight

    lines = []
    for tid, c in sorted(vote_counts.items(), key=lambda x: -x[1]):
        p = game.get_player_by_id(tid)
        if p:
            name = game.get_display_name(p)
            lines.append(f"  {name}: {c} ovoz")
    summary = "\n".join(lines) or "Hech kim ovoz bermadi."

    if eliminated_id is None:
        msg = (
            f"🗳️ *Ovoz natijalari — {game.day_number}-kun:*\n{summary}\n\n"
            "⚖️ *Tenglashdi!* Bugun hech kim chiqarilmadi.\n\n🌙 Kecha tushdi..."
        )
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
    else:
        eliminated = game.get_player_by_id(eliminated_id)

        if eliminated.role == Role.SUIDSID:
            role_name = ROLE_NAMES_UZ[eliminated.role]
            emoji = ROLE_EMOJIS[eliminated.role]
            game.eliminate_player(eliminated_id)
            await update.message.reply_text(
                f"🗳️ *Ovoz natijalari — {game.day_number}-kun:*\n{summary}\n\n"
                f"🎉 *{eliminated.display_name}* osib o'ldirildi!\n"
                f"Roli: {emoji} *{role_name}*\n\n"
                f"*{eliminated.display_name} — G'ALABA QOZONDI!* 🤦🏼 (Suidsid o'z maqsadiga erishdi!)",
                parse_mode=ParseMode.MARKDOWN,
            )
            winner = game.check_win_condition()
            if winner:
                await end_game(context, game, winner, update.effective_chat.id)
                return
        else:
            game.eliminate_player(eliminated_id)
            role_name = ROLE_NAMES_UZ.get(eliminated.role, "")
            emoji = ROLE_EMOJIS.get(eliminated.role, "")

            if eliminated.role == Role.AFSUNGAR:
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton(p.display_name, callback_data=f"afsungar_revenge:{p.user_id}:{game.chat_id}")]
                    for p in game.alive_players()
                ])
                await update.message.reply_text(
                    f"🗳️ *Ovoz natijalari — {game.day_number}-kun:*\n{summary}\n\n"
                    f"💣 *{eliminated.display_name}* osib o'ldirildi! Roli: {emoji} *{role_name}*\n\n"
                    f"*{eliminated.display_name} (Afsungar) — biror o'yinchini o'zi bilan olib ketishi mumkin!*",
                    reply_markup=kb,
                    parse_mode=ParseMode.MARKDOWN,
                )
                return

            msg = (
                f"🗳️ *Ovoz natijalari — {game.day_number}-kun:*\n{summary}\n\n"
                f"☠️ *{eliminated.display_name}* chiqarildi! Roli: {emoji} *{role_name}*\n\n"
            )
            winner = game.check_win_condition()
            if winner:
                await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
                await end_game(context, game, winner, update.effective_chat.id)
                return

            msg += "🌙 Kecha tushdi..."
            await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

    game.day_number += 1
    game.phase = Phase.NIGHT
    await send_night_actions(context, game)


async def handle_afsungar_revenge_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":")
    target_id = int(parts[1])
    chat_id = int(parts[2])

    game = games.get(chat_id)
    if not game:
        return

    target = game.get_player_by_id(target_id)
    if target and target.alive:
        game.eliminate_player(target_id)
        role_name = ROLE_NAMES_UZ.get(target.role, "")
        emoji = ROLE_EMOJIS.get(target.role, "")
        await query.edit_message_text(
            f"💣 *Afsungar* jahannamga ketayotib *{target.display_name}*ni ham olib ketdi!\n"
            f"Roli: {emoji} *{role_name}*",
            parse_mode=ParseMode.MARKDOWN,
        )

        winner = game.check_win_condition()
        if winner:
            await end_game(context, game, winner, chat_id)
            return

    game.day_number += 1
    game.phase = Phase.NIGHT
    await send_night_actions(context, game)


async def cmd_endgame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    game = games.get(chat_id)
    if not game or game.phase == Phase.ENDED:
        await update.message.reply_text("⚠️ Tugatish uchun faol o'yin yo'q.")
        return

    member = await context.bot.get_chat_member(chat_id, update.effective_user.id)
    if member.status not in ("administrator", "creator"):
        await update.message.reply_text("⚠️ Faqat admin o'yinni majburiy tugatishi mumkin.")
        return

    game.phase = Phase.ENDED
    role_list = "\n".join(
        f"  {'☠️' if not p.alive else '✅'} {p.display_name} — {ROLE_EMOJIS.get(p.role,'')} {ROLE_NAMES_UZ.get(p.role, '')}"
        for p in game.players.values() if p.role
    )
    await update.message.reply_text(
        f"🛑 *O'yin admin tomonidan tugatildi.*\n\n*Rollar:*\n{role_list}",
        parse_mode=ParseMode.MARKDOWN,
    )


async def end_game(context: ContextTypes.DEFAULT_TYPE, game: Game, winner: str, chat_id: int = None):
    game.phase = Phase.ENDED
    game.winner = winner
    cid = chat_id or game.chat_id

    win_messages = {
        "citizens": ("🏆", "🎉 *Fuqarolar g'alaba qozondi!* Barcha Mafiya yo'q qilindi!"),
        "mafia": ("🔪", "💀 *Mafiya g'alaba qozondi!* Ular shaharga egalik qildi!"),
        "qotil": ("🔪", "🔪 *Qotil g'alaba qozondi!* Shahar uning qo'liga o'tdi!"),
    }
    emoji, result_text = win_messages.get(winner, ("🏆", "O'yin tugadi."))

    role_list = "\n".join(
        f"  {'☠️' if not p.alive else '✅'} {p.display_name} — {ROLE_EMOJIS.get(p.role,'')} {ROLE_NAMES_UZ.get(p.role, '')}"
        for p in game.players.values() if p.role
    )

    await context.bot.send_message(
        cid,
        f"{emoji} *O'yin tugadi!*\n\n{result_text}\n\n"
        f"*Yakuniy rollar:*\n{role_list}\n\n"
        "Yana o'ynash uchun /newgame!",
        parse_mode=ParseMode.MARKDOWN,
    )

    stats = load_stats()
    stats.total_games += 1
    stats.total_players += len(game.players)
    if winner == "mafia":
        stats.mafia_wins += 1
    elif winner == "citizens":
        stats.citizen_wins += 1
    save_stats(stats)


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats = load_stats()
    total = stats.total_games
    if total == 0:
        await update.message.reply_text("📊 Hali hech qanday o'yin o'ynalmagan!")
        return

    citizen_pct = round(stats.citizen_wins / total * 100)
    mafia_pct = round(stats.mafia_wins / total * 100)
    avg_players = round(stats.total_players / total, 1)

    await update.message.reply_text(
        "📊 *O'yin Statistikasi*\n\n"
        f"🎮 Jami o'yinlar: *{total}*\n"
        f"👥 O'rtacha o'yinchilar: *{avg_players}*\n\n"
        f"🏆 Fuqarolar g'alabasi: *{stats.citizen_wins}* ({citizen_pct}%)\n"
        f"🔪 Mafiya g'alabasi: *{stats.mafia_wins}* ({mafia_pct}%)\n",
        parse_mode=ParseMode.MARKDOWN,
    )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data

    night_prefixes = (
        "night_mafia:", "night_yq:", "night_advokat:", "night_jurnalist:",
        "night_komissar:", "night_doctor:", "night_kezuvchi:", "night_daydi:",
        "night_qotil:", "night_kimyogar_mode:", "night_kimyogar:", "night_minior:",
        "night_aferist:", "night_gazabkor:", "night_joker:", "night_sotqin:",
    )

    if any(data.startswith(p) for p in night_prefixes):
        await handle_night_callback(update, context)
    elif data.startswith("sehrgar:"):
        await handle_sehrgar_callback(update, context)
    elif data.startswith("vote:"):
        await handle_vote_callback(update, context)
    elif data.startswith("open_voting:"):
        await handle_open_voting_callback(update, context)
    elif data.startswith("afsungar_revenge:"):
        await handle_afsungar_revenge_callback(update, context)
    else:
        await query.answer("Noma'lum harakat.")
