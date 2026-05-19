import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from game import Game, Phase, Role, MIN_PLAYERS, ROLE_EMOJIS, ROLE_DESCRIPTIONS, get_role_distribution
from stats import load_stats, save_stats

logger = logging.getLogger(__name__)

games: dict[int, Game] = {}

ROLE_NAMES_UZ = {
    Role.MAFIA: "Mafiya",
    Role.DOCTOR: "Shifokor",
    Role.DETECTIVE: "Detektiv",
    Role.CITIZEN: "Fuqaro",
}

ROLE_DESCRIPTIONS_UZ = {
    Role.MAFIA: (
        "Siz Mafiyasiz. Har kecha bir o'yinchini yo'q qilishingiz mumkin. "
        "Kunduz vaqtida shubha uyg'otmasdan yashirin yuring."
    ),
    Role.DOCTOR: (
        "Siz Shifokorсиз. Har kecha bir o'yinchini yo'q qilinishdan himoya qilishingiz mumkin. "
        "O'zingizni ham himoya qilishingiz mumkin."
    ),
    Role.DETECTIVE: (
        "Siz Detektivsiz. Har kecha bir o'yinchini tekshirib, "
        "u Mafiya ekanligini bilib olishingiz mumkin."
    ),
    Role.CITIZEN: (
        "Siz Fuqarosiz. Kunduz vaqtida Mafiyani aniqlab, ovoz berish orqali ularni chiqarib yuboring."
    ),
}


def get_or_create_game(chat_id: int) -> Game:
    if chat_id not in games:
        games[chat_id] = Game(chat_id=chat_id)
    return games[chat_id]


def build_player_list(game: Game, show_roles: bool = False) -> str:
    lines = []
    for i, player in enumerate(game.players.values(), 1):
        status = "" if player.alive else " ☠️"
        role_name = ROLE_NAMES_UZ.get(player.role, player.role.value) if player.role else ""
        role_str = f" ({ROLE_EMOJIS[player.role]} {role_name})" if show_roles and player.role else ""
        lines.append(f"{i}. {player.display_name}{role_str}{status}")
    return "\n".join(lines) if lines else "Hali o'yinchilar yo'q."


def build_vote_keyboard(game: Game, voter_id: int) -> InlineKeyboardMarkup:
    buttons = []
    for player in game.alive_players():
        if player.user_id != voter_id:
            current_vote = game.votes.get(voter_id)
            label = player.display_name
            if current_vote == player.user_id:
                label = f"✅ {label}"
            buttons.append([InlineKeyboardButton(label, callback_data=f"vote:{player.user_id}")])
    return InlineKeyboardMarkup(buttons)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        await update.message.reply_text(
            "👋 Salom! Men *Mafiya O'yin Boti*man.\n\n"
            "Meni guruh chatiga qo'shing va o'yinni boshlash uchun /newgame dan foydalaning!\n\n"
            "*Mavjud buyruqlar:*\n"
            "/newgame — Yangi o'yin lobby'si boshlash\n"
            "/join — Joriy o'yinga qo'shilish\n"
            "/leave — Lobby'dan chiqish\n"
            "/players — Joriy o'yinchilarni ko'rish\n"
            "/startgame — O'yinni boshlash (admin)\n"
            "/endgame — O'yinni majburiy tugatish (admin)\n"
            "/stats — O'yin statistikasini ko'rish\n"
            "/rules — O'yin qoidalarini ko'rish",
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await update.message.reply_text(
            "👋 Mafiya o'yinini boshlash uchun /newgame dan foydalaning!"
        )


async def cmd_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🃏 *Mafiya O'yin Qoidalari*\n\n"
        "*Rollar:*\n"
        "🔪 *Mafiya* — Har kecha bir o'yinchini yo'q qiladi. Fuqarolardan ko'p bo'lganda g'alaba qozonadi.\n"
        "💊 *Shifokor* — Har kecha bir o'yinchini yo'q qilinishdan himoya qiladi.\n"
        "🔍 *Detektiv* — Har kecha bir o'yinchini tekshiradi (Mafiyami yoki yo'q).\n"
        "👤 *Fuqaro* — Kunduz vaqtida Mafiyani aniqlab, ovoz berish orqali chiqarib yuboradi.\n\n"
        "*Bosqichlar:*\n"
        "🌙 *Kecha* — Maxsus rollar xususiy xabar orqali harakatlarini bajaradi.\n"
        "☀️ *Kunduz* — O'yinchilar muhokama qiladi va shubhali kishiga ovoz beradi.\n\n"
        "*G'alaba shartlari:*\n"
        "🏆 Barcha Mafiya yo'q qilinsa — Fuqarolar g'alaba qozonadi.\n"
        "💀 Mafiya soni fuqarolar soniga teng yoki ko'p bo'lsa — Mafiya g'alaba qozonadi.\n\n"
        f"*Minimal o'yinchilar soni:* {MIN_PLAYERS}"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def cmd_newgame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if update.effective_chat.type == "private":
        await update.message.reply_text("⚠️ Bu buyruq faqat guruh chatlarda ishlaydi.")
        return

    existing = games.get(chat_id)
    if existing and existing.phase != Phase.ENDED:
        await update.message.reply_text(
            "⚠️ O'yin allaqachon davom etmoqda! Avval /endgame bilan bekor qiling."
        )
        return

    games[chat_id] = Game(chat_id=chat_id)
    game = games[chat_id]

    user = update.effective_user
    game.add_player(user.id, user.username or "", user.first_name)

    await update.message.reply_text(
        "🎮 *Yangi Mafiya o'yini boshlanmoqda!*\n\n"
        f"👤 {user.first_name} o'yinni yaratdi.\n\n"
        "Qo'shilish uchun /join dan foydalaning.\n"
        "Hammasi tayyor bo'lganda admin /startgame bossin.\n\n"
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

    text = f"👥 *O'yinchilar — {phase_label}*\n\n"
    text += f"*Tirik ({len(alive)}):*\n"
    for i, p in enumerate(alive, 1):
        text += f"{i}. {p.display_name}\n"
    if dead:
        text += f"\n*Chiqarilgan ({len(dead)}):*\n"
        for p in dead:
            role_name = ROLE_NAMES_UZ.get(p.role, p.role.value) if p.role else ""
            role_str = f" — {ROLE_EMOJIS[p.role]} {role_name}" if p.role else ""
            text += f"☠️ {p.display_name}{role_str}\n"

    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def cmd_startgame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if update.effective_chat.type == "private":
        await update.message.reply_text("⚠️ Bu buyruq faqat guruh chatlarda ishlaydi.")
        return

    game = games.get(chat_id)
    if not game or game.phase == Phase.ENDED:
        await update.message.reply_text("⚠️ Faol lobby yo'q. Avval /newgame dan foydalaning.")
        return

    if game.phase != Phase.LOBBY:
        await update.message.reply_text("⚠️ O'yin allaqachon boshlangan.")
        return

    member = await context.bot.get_chat_member(chat_id, update.effective_user.id)
    is_admin = member.status in ("administrator", "creator")
    if not is_admin and update.effective_user.id not in game.players:
        await update.message.reply_text("⚠️ Faqat admin yoki lobby'dagi o'yinchilar o'yinni boshlashi mumkin.")
        return

    if len(game.players) < MIN_PLAYERS:
        await update.message.reply_text(
            f"⚠️ O'yinni boshlash uchun kamida *{MIN_PLAYERS}* o'yinchi kerak. Hozir: *{len(game.players)}*",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    await start_game(update, context, game)


async def start_game(update: Update, context: ContextTypes.DEFAULT_TYPE, game: Game):
    game.assign_roles()
    game.phase = Phase.NIGHT
    game.day_number = 1

    dist = get_role_distribution(len(game.players))
    dist_text = "  ".join(
        f"{ROLE_EMOJIS[r]} {ROLE_NAMES_UZ[r]}: {n}"
        for r, n in dist.items() if n > 0
    )

    await update.message.reply_text(
        f"🎮 *Mafiya o'yini boshlandi!*\n\n"
        f"*{len(game.players)} o'yinchi* o'z rollarini oldi.\n"
        f"{dist_text}\n\n"
        "🌙 *1-kecha boshlandi!*\nRolingiz va ko'rsatmalar uchun shaxsiy xabarlaringizni tekshiring.",
        parse_mode=ParseMode.MARKDOWN,
    )

    for player in game.players.values():
        try:
            role_emoji = ROLE_EMOJIS[player.role]
            role_name = ROLE_NAMES_UZ[player.role]
            desc = ROLE_DESCRIPTIONS_UZ[player.role]
            await context.bot.send_message(
                player.user_id,
                f"🎭 *Sizning rolingiz: {role_emoji} {role_name}*\n\n{desc}\n\n"
                "O'yin boshlandi. Kecha harakati ko'rsatmalarini kuting.",
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            pass

    await send_night_actions(context, game)


async def send_night_actions(context: ContextTypes.DEFAULT_TYPE, game: Game):
    game.reset_night_state()
    chat_id = game.chat_id

    mafia_players = game.alive_mafia()
    alive = game.alive_players()

    for mafia in mafia_players:
        targets = [p for p in alive if p.role != Role.MAFIA]
        if targets:
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton(p.display_name, callback_data=f"night_kill:{p.user_id}:{chat_id}")]
                for p in targets
            ])
            mafia_allies = [p.display_name for p in mafia_players if p.user_id != mafia.user_id]
            ally_text = f"\n🤝 Mafiya hamkorlaringiz: {', '.join(mafia_allies)}" if mafia_allies else ""
            try:
                await context.bot.send_message(
                    mafia.user_id,
                    f"🌙 *{game.day_number}-kecha*{ally_text}\n\n"
                    "🔪 Bu kecha *yo'q qilish* uchun o'yinchini tanlang:",
                    reply_markup=keyboard,
                    parse_mode=ParseMode.MARKDOWN,
                )
            except Exception:
                pass

    for player in alive:
        if player.role == Role.DOCTOR:
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton(p.display_name, callback_data=f"night_protect:{p.user_id}:{chat_id}")]
                for p in alive
            ])
            try:
                await context.bot.send_message(
                    player.user_id,
                    f"🌙 *{game.day_number}-kecha*\n\n💊 Bu kecha *himoya qilish* uchun o'yinchini tanlang:",
                    reply_markup=keyboard,
                    parse_mode=ParseMode.MARKDOWN,
                )
            except Exception:
                pass

        elif player.role == Role.DETECTIVE:
            targets = [p for p in alive if p.user_id != player.user_id]
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton(p.display_name, callback_data=f"night_investigate:{p.user_id}:{chat_id}")]
                for p in targets
            ])
            try:
                await context.bot.send_message(
                    player.user_id,
                    f"🌙 *{game.day_number}-kecha*\n\n🔍 Bu kecha *tekshirish* uchun o'yinchini tanlang:",
                    reply_markup=keyboard,
                    parse_mode=ParseMode.MARKDOWN,
                )
            except Exception:
                pass

        elif player.role == Role.CITIZEN:
            try:
                await context.bot.send_message(
                    player.user_id,
                    f"🌙 *{game.day_number}-kecha*\n\n"
                    "👤 Siz Fuqarosiz. Dam oling...\n"
                    "Kunduz vaqtida shaharga yordam kerak bo'ladi!",
                    parse_mode=ParseMode.MARKDOWN,
                )
            except Exception:
                pass


async def handle_night_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    parts = data.split(":")
    action = parts[0]
    target_id = int(parts[1])
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

    target = game.get_player_by_id(target_id)
    if not target or not target.alive:
        await query.edit_message_text("⚠️ Bu o'yinchi mavjud emas.")
        return

    if action == "night_kill" and actor.role == Role.MAFIA:
        game.night_actions[f"kill_{actor_id}"] = target_id
        await query.edit_message_text(
            f"🔪 Siz bu kecha *{target.display_name}*ni yo'q qilishni tanladingiz.",
            parse_mode=ParseMode.MARKDOWN,
        )
    elif action == "night_protect" and actor.role == Role.DOCTOR:
        game.night_actions["protect"] = target_id
        await query.edit_message_text(
            f"💊 Siz bu kecha *{target.display_name}*ni himoya qilishni tanladingiz.",
            parse_mode=ParseMode.MARKDOWN,
        )
    elif action == "night_investigate" and actor.role == Role.DETECTIVE:
        is_mafia = target.role == Role.MAFIA
        result_text = "🔴 *MAFIYA*" if is_mafia else "🟢 *Mafiya emas*"
        game.night_actions[f"investigate_{actor_id}"] = target_id
        await query.edit_message_text(
            f"🔍 *{target.display_name}* tekshiruv natijasi:\n{result_text}",
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await query.edit_message_text("⚠️ Noto'g'ri harakat.")
        return

    await check_night_complete(context, game)


async def check_night_complete(context: ContextTypes.DEFAULT_TYPE, game: Game):
    alive = game.alive_players()
    mafia = game.alive_mafia()

    kill_actions = [k for k in game.night_actions if k.startswith("kill_")]
    has_doctor = any(p.role == Role.DOCTOR for p in alive)
    has_detective = any(p.role == Role.DETECTIVE for p in alive)

    if len(kill_actions) < len(mafia):
        return
    if has_doctor and "protect" not in game.night_actions:
        return
    if has_detective and not any(k.startswith("investigate_") for k in game.night_actions):
        return

    await resolve_night(context, game)


async def resolve_night(context: ContextTypes.DEFAULT_TYPE, game: Game):
    kill_votes: dict = {}
    for key, target_id in game.night_actions.items():
        if key.startswith("kill_"):
            kill_votes[target_id] = kill_votes.get(target_id, 0) + 1

    kill_target = max(kill_votes, key=kill_votes.get) if kill_votes else None
    protected_id = game.night_actions.get("protect")

    eliminated = None
    if kill_target and kill_target != protected_id:
        game.eliminate_player(kill_target)
        eliminated = game.get_player_by_id(kill_target)

    winner = game.check_win_condition()
    if winner:
        await end_game(context, game, winner)
        return

    game.phase = Phase.DAY
    chat_id = game.chat_id

    if eliminated:
        role_name = ROLE_NAMES_UZ.get(eliminated.role, eliminated.role.value)
        role_reveal = f"Uning roli: {ROLE_EMOJIS[eliminated.role]} *{role_name}*"
        msg = (
            f"☀️ *{game.day_number}-kun boshlandi!*\n\n"
            f"☠️ *{eliminated.display_name}* kecha yo'q qilindi.\n"
            f"{role_reveal}\n\n"
            "Muhokama qiling va shubhaliga ovoz bering!\n"
            "/vote buyrug'i yoki quyidagi tugma orqali ovoz bering."
        )
    else:
        msg = (
            f"☀️ *{game.day_number}-kun boshlandi!*\n\n"
            "🛡️ Shifokor kimnidir himoya qildi — kecha hech kim yo'q qilinmadi!\n\n"
            "Muhokama qiling va shubhaliga ovoz bering!\n"
            "/vote buyrug'i yoki quyidagi tugma orqali ovoz bering."
        )

    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🗳️ Ovoz berishni boshlash", callback_data=f"open_voting:{chat_id}")]])
    await context.bot.send_message(chat_id, msg, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)


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
        keyboard = build_vote_keyboard(game, player.user_id)
        try:
            await context.bot.send_message(
                player.user_id,
                f"🗳️ *{game.day_number}-kun — Ovoz bering!*\n\n"
                "Sizningcha kim Mafiya?\n"
                "Ovoz berish uchun ismga bosing. Ovozni o'zgartirish uchun qayta bosing.\n\n"
                "Tayyor bo'lgach, guruh chatida /endvote bosing.",
                reply_markup=keyboard,
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            pass


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

    if game.votes.get(voter_id) == target_id:
        del game.votes[voter_id]
        await query.edit_message_text(
            f"🗳️ *{game.day_number}-kun — Ovoz bering!*\n\n"
            f"*{target.display_name}*ga ovozingiz bekor qilindi.\n\n"
            "Ovoz berish uchun ismga bosing.",
            reply_markup=build_vote_keyboard(game, voter_id),
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        game.votes[voter_id] = target_id
        await query.edit_message_text(
            f"🗳️ *{game.day_number}-kun — Ovoz bering!*\n\n"
            f"✅ *{target.display_name}*ga ovoz berdingiz.\n\n"
            "Bekor qilish uchun qayta bosing yoki boshqa nomga bosib ovozni o'zgartiring.",
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
            f"{voted_count}/{alive_count} o'yinchi ovoz berdi.\n\n"
            f"*Hali ovoz bermagan:* {', '.join(not_voted)}",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    await resolve_vote(update, context, game)


async def resolve_vote(update, context: ContextTypes.DEFAULT_TYPE, game: Game):
    eliminated_id = game.tally_votes()

    vote_summary = {}
    for vid, tid in game.votes.items():
        vote_summary[tid] = vote_summary.get(tid, 0) + 1

    summary_lines = []
    for tid, count in sorted(vote_summary.items(), key=lambda x: -x[1]):
        player = game.get_player_by_id(tid)
        if player:
            summary_lines.append(f"  {player.display_name}: {count} ovoz")

    summary_text = "\n".join(summary_lines) or "Hech kim ovoz bermadi."

    if eliminated_id is None:
        msg = (
            f"🗳️ *Ovoz natijalari — {game.day_number}-kun:*\n{summary_text}\n\n"
            "⚖️ *Tenglashdi!* Bugun hech kim chiqarilmadi.\n\n"
            "🌙 Kecha tushdi..."
        )
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
    else:
        eliminated = game.get_player_by_id(eliminated_id)
        game.eliminate_player(eliminated_id)
        role_name = ROLE_NAMES_UZ.get(eliminated.role, eliminated.role.value)
        role_reveal = f"Uning roli: {ROLE_EMOJIS[eliminated.role]} *{role_name}*"
        msg = (
            f"🗳️ *Ovoz natijalari — {game.day_number}-kun:*\n{summary_text}\n\n"
            f"☠️ *{eliminated.display_name}* chiqarildi!\n"
            f"{role_reveal}\n\n"
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


async def cmd_endgame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    game = games.get(chat_id)

    if not game or game.phase == Phase.ENDED:
        await update.message.reply_text("⚠️ Tugatish uchun faol o'yin yo'q.")
        return

    member = await context.bot.get_chat_member(chat_id, update.effective_user.id)
    is_admin = member.status in ("administrator", "creator")
    if not is_admin:
        await update.message.reply_text("⚠️ Faqat admin o'yinni majburiy tugatishi mumkin.")
        return

    game.phase = Phase.ENDED
    role_list = "\n".join(
        f"  {p.display_name} — {ROLE_EMOJIS[p.role]} {ROLE_NAMES_UZ.get(p.role, p.role.value)}"
        for p in game.players.values()
        if p.role
    )
    await update.message.reply_text(
        "🛑 *O'yin admin tomonidan tugatildi.*\n\n"
        f"*Rollar:*\n{role_list}",
        parse_mode=ParseMode.MARKDOWN,
    )


async def end_game(context: ContextTypes.DEFAULT_TYPE, game: Game, winner: str, chat_id: int = None):
    game.phase = Phase.ENDED
    game.winner = winner
    cid = chat_id or game.chat_id

    if winner == "citizens":
        result_text = "🎉 *Fuqarolar g'alaba qozondi!* Barcha Mafiya yo'q qilindi!"
        emoji = "🏆"
    else:
        result_text = "💀 *Mafiya g'alaba qozondi!* Ular shaharga egalik qildi!"
        emoji = "🔪"

    role_list = "\n".join(
        f"  {'☠️' if not p.alive else '✅'} {p.display_name} — {ROLE_EMOJIS[p.role]} {ROLE_NAMES_UZ.get(p.role, p.role.value)}"
        for p in game.players.values()
        if p.role
    )

    await context.bot.send_message(
        cid,
        f"{emoji} *O'yin tugadi!*\n\n{result_text}\n\n"
        f"*Yakuniy rollar:*\n{role_list}\n\n"
        "Yana o'ynash uchun /newgame dan foydalaning!",
        parse_mode=ParseMode.MARKDOWN,
    )

    stats = load_stats()
    stats.total_games += 1
    stats.total_players += len(game.players)
    if winner == "mafia":
        stats.mafia_wins += 1
    else:
        stats.citizen_wins += 1
    save_stats(stats)


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats = load_stats()
    total = stats.total_games
    if total == 0:
        await update.message.reply_text("📊 Hali hech qanday o'yin o'ynalmagan!")
        return

    citizen_pct = round(stats.citizen_wins / total * 100) if total else 0
    mafia_pct = round(stats.mafia_wins / total * 100) if total else 0
    avg_players = round(stats.total_players / total, 1) if total else 0

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

    if data.startswith("night_kill:") or data.startswith("night_protect:") or data.startswith("night_investigate:"):
        await handle_night_callback(update, context)
    elif data.startswith("vote:"):
        await handle_vote_callback(update, context)
    elif data.startswith("open_voting:"):
        await handle_open_voting_callback(update, context)
    else:
        await query.answer("Noma'lum harakat.")
