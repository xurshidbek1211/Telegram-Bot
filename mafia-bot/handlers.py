import asyncio
import logging
import random
from aiogram import Router, Bot, F
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
)

from game import Game, Phase, Role, MIN_PLAYERS, ROLE_EMOJIS, ROLE_DESCRIPTIONS_UZ, MAFIA_TEAM
from stats import load_stats, save_stats
from night import resolve_night
from profiles import get_profile, save_profile, transfer_diamond, record_game_start, record_win, add_dollar, add_diamond

logger = logging.getLogger(__name__)
router = Router()

games: dict[int, Game] = {}
mine_sessions: dict[int, dict] = {}

NIGHT_SECS = 30
DAY_SECS   = 30
VOTE_SECS  = 30

ROLE_NAMES_UZ = {
    Role.DON: "Don", Role.MAFIA: "Mafia",
    Role.YOLLANMA_QOTIL: "Yollanma Qotil", Role.ADVOKAT: "Advokat",
    Role.JURNALIST: "Jurnalist", Role.KOMISSAR: "Komissar Katani",
    Role.DOCTOR: "Doktor", Role.SERZHANT: "Serjant",
    Role.JANOB: "Janob", Role.CITIZEN: "Tinch Axoli",
    Role.DAYDI: "Daydi", Role.KEZUVCHI: "Kezuvchi",
    Role.OMADLI: "Omadli", Role.ADMIRAL: "Admiral",
    Role.SOTQIN: "Sotqin", Role.QOTIL: "Qotil",
    Role.SUIDSID: "Suidsid", Role.BO_RI: "Bo'ri",
    Role.AFSUNGAR: "Afsungar", Role.AFERIST: "Aferist",
    Role.SEHRGAR: "Sehrgar", Role.GAZABKOR: "G'azabkor",
    Role.JOKER: "Joker", Role.KIMYOGAR: "Kimyogar",
    Role.MINIOR: "Minior",
}

PASSIVE_NIGHT_ROLES = {
    Role.CITIZEN, Role.JANOB, Role.SUIDSID, Role.OMADLI,
    Role.BO_RI, Role.AFSUNGAR, Role.SEHRGAR, Role.ADMIRAL,
}

PASSIVE_MESSAGES = {
    Role.CITIZEN:  "👨🏼 Siz *Tinch Axoli*siz. Dam oling — ertaga shahar himoyangizga muhtoj!",
    Role.JANOB:    "🎖 Siz *Janob*siz. Kunduz ovozda sizning ovozingiz ikkitaga teng. Dam oling!",
    Role.SUIDSID:  "🤦🏼 Siz *Suidsid*siz. Kunduz ovozda osib o'ldirilsangiz — g'alaba qozonasiz! 🎉",
    Role.OMADLI:   "🤞🏼 Siz *Omadli*siz. Kechasi nishonga olinsangiz 50% ehtimolda omon qolasiz!",
    Role.BO_RI:    "🐺 Siz *Bo'ri*siz. Dam oling — kimning qo'lidan o'lishingiz kelajagingizni belgilaydi!",
    Role.AFSUNGAR: "💣 Siz *Afsungar*siz. Kechasi o'ldirilsangiz, o'ldirgan ham halok bo'ladi!",
    Role.SEHRGAR:  "🧙‍ Siz *Sehrgar*siz. Don/Qotil/Komissar hujumida siz xabar olasiz va tanlov berasiz.",
    Role.ADMIRAL:  "🧑🏻‍✈️ Siz *Admiral*siz. Komissar+Serjant tirik ekan — o'lmasсиз. Ikkovi o'lsa Komissar bo'lasiz.",
}

# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

async def _dm(bot: Bot, uid: int, text: str, kb=None):
    try:
        await bot.send_message(uid, text, reply_markup=kb, parse_mode="Markdown")
    except Exception as e:
        logger.debug(f"DM xatosi {uid}: {e}")


def _lobby_kb(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎮 Qo'shilish",   callback_data=f"join:{chat_id}")],
        [InlineKeyboardButton(text="👥 O'yinchilar", callback_data=f"show_players:{chat_id}")],
    ])


def _player_list(game: Game, show_roles: bool = False) -> str:
    lines = []
    for i, p in enumerate(game.players.values(), 1):
        dead = " ☠️" if not p.alive else ""
        role_str = ""
        if show_roles and p.role:
            role_str = f" ({ROLE_EMOJIS[p.role]} {ROLE_NAMES_UZ[p.role]})"
        lines.append(f"{i}. {p.display_name}{role_str}{dead}")
    return "\n".join(lines) or "Hali o'yinchilar yo'q."


def _target_kb(game: Game, prefix: str, actor_id: int = None,
               include_self: bool = False, only_mafia: bool = False) -> InlineKeyboardMarkup:
    rows = []
    for p in game.alive_players():
        if not include_self and actor_id and p.user_id == actor_id:
            continue
        if only_mafia and p.role not in MAFIA_TEAM:
            continue
        rows.append([InlineKeyboardButton(
            text=p.display_name,
            callback_data=f"{prefix}:{p.user_id}:{game.chat_id}"
        )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _vote_kb(game: Game, voter_id: int) -> InlineKeyboardMarkup:
    rows = []
    for p in game.alive_players():
        if p.user_id == voter_id:
            continue
        label = game.get_display_name(p)
        if game.votes.get(voter_id) == p.user_id:
            label = f"✅ {label}"
        rows.append([InlineKeyboardButton(text=label, callback_data=f"vote:{p.user_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _group_vote_kb(game: Game) -> InlineKeyboardMarkup:
    rows = []
    for p in game.alive_players():
        rows.append([InlineKeyboardButton(
            text=f"👤 {game.get_display_name(p)}",
            callback_data=f"gvote:{p.user_id}:{game.chat_id}"
        )])
    return InlineKeyboardMarkup(inline_keyboard=rows)

# ──────────────────────────────────────────────
# Phase runners
# ──────────────────────────────────────────────

async def run_night(bot: Bot, chat_id: int):
    game = games.get(chat_id)
    if not game:
        return

    game.reset_night_state()
    game.phase = Phase.NIGHT
    _auto_passive(game)

    await bot.send_message(
        chat_id,
        f"🌙 *{game.day_number}-KECHA BOSHLANDI!*\n"
        f"⏳ Vaqt: *{NIGHT_SECS} soniya*\n\n"
        "Har bir o'yinchi shaxsiy xabarda harakat tanlashini kutmoqda...\n"
        "⚠️ Agar DM kelmasa — botga /start yozing!",
    )

    await _send_night_actions(bot, game)

    try:
        await asyncio.wait_for(
            _wait_for_night_done(game),
            timeout=NIGHT_SECS
        )
    except asyncio.TimeoutError:
        pass

    await _do_night_resolution(bot, game)


async def _wait_for_night_done(game: Game):
    while not game.all_night_actions_done():
        await asyncio.sleep(1)


async def _do_night_resolution(bot: Bot, game: Game):
    if game.phase != Phase.NIGHT:
        return
    events = await resolve_night(game, bot)
    game.phase = Phase.DAY

    winner = game.check_win_condition()
    summary = "\n".join(f"• {e}" for e in events)

    if winner:
        await bot.send_message(
            game.chat_id,
            f"🌙 *{game.day_number}-kecha yakunlandi:*\n\n{summary}",
        )
        await _end_game(bot, game, winner)
        return

    await bot.send_message(
        game.chat_id,
        f"🌙 *{game.day_number}-kecha yakunlandi:*\n\n{summary}\n\n"
        f"☀️ *KUN MUHOKAMASI BOSHLANDI!*\n"
        f"⏳ Muhokama vaqti: *{DAY_SECS} soniya*\n\n"
        "Kim Mafiya ekanini aniqlashga harakat qiling!",
    )

    await asyncio.sleep(DAY_SECS)
    await run_vote(bot, game.chat_id)


async def run_vote(bot: Bot, chat_id: int):
    game = games.get(chat_id)
    if not game or game.phase == Phase.ENDED:
        return

    game.phase = Phase.VOTING
    game.votes = {}

    await bot.send_message(
        chat_id,
        f"🗳️ *OVOZ BERISH BOSHLANDI!*\n"
        f"⏳ Vaqt: *{VOTE_SECS} soniya*\n\n"
        "Kim Mafiya? Quyidagi tugmalardan birini bosing!\n"
        "Bir marta bosing = ovoz. Qayta bosing = bekor.",
        reply_markup=_group_vote_kb(game),
    )

    await asyncio.sleep(VOTE_SECS)
    await _do_vote_resolution(bot, game)


async def _do_vote_resolution(bot: Bot, game: Game):
    if game.phase != Phase.VOTING:
        return

    eliminated_id = game.tally_votes()
    counts: dict = {}
    for vid, tid in game.votes.items():
        voter = game.get_player_by_id(vid)
        if voter:
            w = 2 if voter.role == Role.JANOB else 1
            counts[tid] = counts.get(tid, 0) + w

    lines = [
        f"  {game.get_display_name(game.get_player_by_id(tid))}: {c} ovoz"
        for tid, c in sorted(counts.items(), key=lambda x: -x[1])
        if game.get_player_by_id(tid)
    ]
    summary = "\n".join(lines) or "Hech kim ovoz bermadi."

    if eliminated_id is None:
        await bot.send_message(
            game.chat_id,
            f"🗳️ *Ovoz natijalari — {game.day_number}-kun:*\n{summary}\n\n"
            "⚖️ *Tenglashdi!* Bugun hech kim chiqarilmadi.\n\n🌙 Kecha tushdi...",
        )
        game.day_number += 1
        await run_night(bot, game.chat_id)
        return

    eliminated = game.get_player_by_id(eliminated_id)
    role_name = ROLE_NAMES_UZ.get(eliminated.role, "")
    emoji = ROLE_EMOJIS.get(eliminated.role, "")

    # hang_protect item cancels the elimination
    from profiles import get_profile, save_profile as _sp
    ep = get_profile(eliminated_id)
    if ep.hang_protect > 0:
        ep.hang_protect -= 1
        _sp(ep)
        await bot.send_message(
            game.chat_id,
            f"🗳️ *Ovoz natijalari — {game.day_number}-kun:*\n{summary}\n\n"
            f"⚖️ *{eliminated.display_name}* osishdan himoya ishlatdi va omon qoldi! "
            f"(Qolgan himoya: {ep.hang_protect})",
        )
        game.day_number += 1
        await run_night(bot, game.chat_id)
        return

    # Suidsid special win
    if eliminated.role == Role.SUIDSID:
        game.eliminate_player(eliminated_id)
        await bot.send_message(
            game.chat_id,
            f"🗳️ *Ovoz natijalari — {game.day_number}-kun:*\n{summary}\n\n"
            f"🎉 *{eliminated.display_name}* osib o'ldirildi! Roli: {emoji} *{role_name}*\n\n"
            f"*{eliminated.display_name} G'ALABA QOZONDI!* 🤦🏼",
        )
        winner = game.check_win_condition()
        if winner:
            await _end_game(bot, game, winner)
            return
        game.day_number += 1
        await run_night(bot, game.chat_id)
        return

    # Afsungar day revenge
    if eliminated.role == Role.AFSUNGAR:
        game.eliminate_player(eliminated_id)
        await bot.send_message(
            game.chat_id,
            f"🗳️ *Ovoz natijalari — {game.day_number}-kun:*\n{summary}\n\n"
            f"💣 *{eliminated.display_name}* osib o'ldirildi! Roli: {emoji} *{role_name}*\n\n"
            f"*Afsungar* birini o'zi bilan olib ketishi mumkin — 30 soniya ichida tanlang!",
            reply_markup=_target_kb(game, "afsungar_revenge", actor_id=eliminated_id),
        )
        await asyncio.sleep(30)
        winner = game.check_win_condition()
        if winner:
            await _end_game(bot, game, winner)
            return
        game.day_number += 1
        await run_night(bot, game.chat_id)
        return

    game.eliminate_player(eliminated_id)
    msg = (
        f"🗳️ *Ovoz natijalari — {game.day_number}-kun:*\n{summary}\n\n"
        f"☠️ *{eliminated.display_name}* chiqarildi! Roli: {emoji} *{role_name}*\n\n"
    )
    winner = game.check_win_condition()
    if winner:
        await bot.send_message(game.chat_id, msg)
        await _end_game(bot, game, winner)
        return

    await bot.send_message(game.chat_id, msg + "🌙 Kecha tushdi...")
    game.day_number += 1
    await run_night(bot, game.chat_id)


async def _end_game(bot: Bot, game: Game, winner: str):
    game.phase = Phase.ENDED
    game.winner = winner
    game.cancel_phase_task()

    msgs = {
        "citizens": ("🏆", "🎉 *Fuqarolar g'alaba qozondi!* Barcha Mafiya yo'q qilindi!"),
        "mafia":    ("🔪", "💀 *Mafiya g'alaba qozondi!* Ular shaharga egalik qildi!"),
        "qotil":    ("🔪", "🔪 *Qotil g'alaba qozondi!* Shahar uning qo'liga o'tdi!"),
    }
    em, text = msgs.get(winner, ("🏆", "O'yin tugadi."))

    role_list = "\n".join(
        f"  {'☠️' if not p.alive else '✅'} {p.display_name} — "
        f"{ROLE_EMOJIS.get(p.role,'')} {ROLE_NAMES_UZ.get(p.role,'')}"
        for p in game.players.values() if p.role
    )

    reward_lines = []
    if winner == "citizens":
        survivors = [p for p in game.players.values() if p.alive]
        for p in survivors:
            record_win(p.user_id, dollar_reward=40)
        if survivors:
            names = ", ".join(p.display_name for p in survivors)
            reward_lines.append(f"💵 *Tirik qolganlar (+40$):* {names}")
    elif winner == "mafia":
        for p in game.alive_mafia_team():
            record_win(p.user_id, dollar_reward=60)
        mafia_alive = game.alive_mafia_team()
        if mafia_alive:
            names = ", ".join(p.display_name for p in mafia_alive)
            reward_lines.append(f"💵 *Mafiya g'oliblari (+60$):* {names}")
    elif winner == "qotil":
        q = game.get_alive_by_role(Role.QOTIL)
        if q:
            record_win(q.user_id, dollar_reward=80)
            reward_lines.append(f"💵 *Qotil g'olib (+80$):* {q.display_name}")

    reward_text = "\n" + "\n".join(reward_lines) if reward_lines else ""

    await bot.send_message(
        game.chat_id,
        f"{em} *O'YIN TUGADI!*\n\n{text}\n\n*Yakuniy rollar:*\n{role_list}{reward_text}\n\n"
        "Yana o'ynash uchun /newgame!",
    )

    stats = load_stats()
    stats.total_games += 1
    stats.total_players += len(game.players)
    if winner == "mafia":
        stats.mafia_wins += 1
    elif winner == "citizens":
        stats.citizen_wins += 1
    save_stats(stats)

# ──────────────────────────────────────────────
# Night action sender
# ──────────────────────────────────────────────

async def _send_night_actions(bot: Bot, game: Game):
    alive = game.alive_players()
    chat_id = game.chat_id
    mafia_names = ", ".join(
        p.display_name for p in alive if p.role in (Role.DON, Role.MAFIA)
    )

    for player in alive:
        role = player.role
        uid  = player.user_id

        if role == Role.DON:
            targets = [p for p in alive if p.role not in MAFIA_TEAM]
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=p.display_name, callback_data=f"nk:{p.user_id}:{chat_id}")]
                for p in targets
            ])
            allies = [p.display_name for p in alive if p.role == Role.MAFIA]
            ally_txt = f"\n🤝 Mafiya: {', '.join(allies)}" if allies else ""
            await _dm(bot, uid,
                f"🌙 *{game.day_number}-kecha*{ally_txt}\n\n"
                f"🤵🏻 *Don:* o'ldirish uchun o'yinchini tanlang ({NIGHT_SECS}s):", kb)

        elif role == Role.MAFIA:
            targets = [p for p in alive if p.role not in MAFIA_TEAM]
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=p.display_name, callback_data=f"nk:{p.user_id}:{chat_id}")]
                for p in targets
            ])
            don = game.get_alive_by_role(Role.DON)
            leader = f"Don: {don.display_name}" if don else "Siz lider"
            allies = [p.display_name for p in alive if p.role in MAFIA_TEAM and p.user_id != uid]
            ally_txt = f"\n🤝 Jamoa: {', '.join(allies)}" if allies else ""
            await _dm(bot, uid,
                f"🌙 *{game.day_number}-kecha*\n_{leader}_{ally_txt}\n\n"
                f"🤵🏼 Nishon tanlang ({NIGHT_SECS}s):", kb)

        elif role == Role.YOLLANMA_QOTIL:
            targets = [p for p in alive if p.role not in MAFIA_TEAM]
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=p.display_name, callback_data=f"nyq:{p.user_id}:{chat_id}")]
                for p in targets
            ])
            allies = [p.display_name for p in alive if p.role in MAFIA_TEAM]
            ally_txt = f"\n🤝 Mafiya jamoasi: {', '.join(allies)}" if allies else ""
            await _dm(bot, uid,
                f"🌙 *{game.day_number}-kecha*{ally_txt}\n\n"
                f"🥷 Nishon tanlang — ⚠️ Komissarni tanlasangiz, u sizni o'ldiradi! ({NIGHT_SECS}s):", kb)

        elif role == Role.ADVOKAT:
            targets = [p for p in alive if p.role in MAFIA_TEAM and p.user_id != uid]
            if not targets:
                game.night_actions[Role.ADVOKAT] = uid
                await _dm(bot, uid,
                    f"🌙 *{game.day_number}-kecha*\n\n"
                    "👨🏼‍💼 Himoya qilish uchun boshqa Mafiya yo'q. Harakatingiz o'tkazib yuborildi.")
            else:
                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text=p.display_name, callback_data=f"nadv:{p.user_id}:{chat_id}")]
                    for p in targets
                ])
                await _dm(bot, uid,
                    f"🌙 *{game.day_number}-kecha*\n\n"
                    f"👨🏼‍💼 Komissardan himoya qilish uchun Mafiya a'zosini tanlang ({NIGHT_SECS}s):", kb)

        elif role == Role.JURNALIST:
            kb = _target_kb(game, "njurn", actor_id=uid)
            allies = [p.display_name for p in alive if p.role in MAFIA_TEAM]
            ally_txt = f"\n🤝 Mafiya jamoasi: {', '.join(allies)}" if allies else ""
            await _dm(bot, uid,
                f"🌙 *{game.day_number}-kecha*{ally_txt}\n\n"
                f"👩🏼‍💻 Intervyu olish uchun o'yinchini tanlang ({NIGHT_SECS}s):", kb)

        elif role == Role.KOMISSAR:
            kb = _target_kb(game, "nkom", actor_id=uid)
            await _dm(bot, uid,
                f"🌙 *{game.day_number}-kecha*\n\n"
                f"🕵🏼 Tekshirish uchun o'yinchini tanlang. Mafiya bo'lsa — u o'ldiriladi ({NIGHT_SECS}s):", kb)

        elif role == Role.SERZHANT and not game.get_alive_by_role(Role.KOMISSAR):
            kb = _target_kb(game, "nkom", actor_id=uid)
            await _dm(bot, uid,
                f"🌙 *{game.day_number}-kecha*\n\n"
                f"👮🏼 Siz hozir Komissar vazifasini bajaryapsiz. Tekshiring ({NIGHT_SECS}s):", kb)

        elif role == Role.DOCTOR:
            kb = _target_kb(game, "ndoc", actor_id=uid, include_self=True)
            await _dm(bot, uid,
                f"🌙 *{game.day_number}-kecha*\n\n"
                f"💊 Himoya qilish uchun o'yinchini tanlang (o'zingizni ham) ({NIGHT_SECS}s):", kb)

        elif role == Role.KEZUVCHI:
            kb = _target_kb(game, "nkez", actor_id=uid)
            await _dm(bot, uid,
                f"🌙 *{game.day_number}-kecha*\n\n"
                f"💃 Uyqu dori berish uchun o'yinchini tanlang — u bu kecha harakatsiz ({NIGHT_SECS}s):", kb)

        elif role == Role.DAYDI:
            kb = _target_kb(game, "nday", actor_id=uid)
            await _dm(bot, uid,
                f"🌙 *{game.day_number}-kecha*\n\n"
                f"🧙‍♂️ Tashrif buyurish uchun o'yinchini tanlang ({NIGHT_SECS}s):", kb)

        elif role == Role.QOTIL:
            kb = _target_kb(game, "nqot", actor_id=uid)
            await _dm(bot, uid,
                f"🌙 *{game.day_number}-kecha*\n\n"
                f"🔪 O'ldirish uchun nishon tanlang ({NIGHT_SECS}s):", kb)

        elif role == Role.KIMYOGAR:
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="🩺 Davolash", callback_data=f"nkimmode:heal:{chat_id}"),
                InlineKeyboardButton(text="☠️ O'ldirish", callback_data=f"nkimmode:kill:{chat_id}"),
            ]])
            await _dm(bot, uid,
                f"🌙 *{game.day_number}-kecha*\n\n"
                f"👨‍🔬 Bu kecha nima qilasiz ({NIGHT_SECS}s)?", kb)

        elif role == Role.MINIOR:
            kb = _target_kb(game, "nmin", actor_id=uid)
            await _dm(bot, uid,
                f"🌙 *{game.day_number}-kecha*\n\n"
                f"☠️ Mina qo'yish uchun o'yinchini tanlang ({NIGHT_SECS}s):", kb)

        elif role == Role.AFERIST:
            kb = _target_kb(game, "nafer", actor_id=uid)
            await _dm(bot, uid,
                f"🌙 *{game.day_number}-kecha*\n\n"
                f"🤹🏻 Kimning ovoz berish shaxsini almashtirmoqchisiz ({NIGHT_SECS}s)?", kb)

        elif role == Role.GAZABKOR:
            kb = _target_kb(game, "ngaz", actor_id=uid, include_self=True)
            count = len(player.gazabkor_targets)
            await _dm(bot, uid,
                f"🌙 *{game.day_number}-kecha*\n\n"
                f"🧟 Ro'yxatga o'yinchi qo'shing (hozir *{count}* ta). "
                f"O'zingizni tanlasangiz, barchasi o'ladi (g'alaba uchun kamida 3 ta) ({NIGHT_SECS}s):", kb)

        elif role == Role.JOKER:
            kb = _target_kb(game, "njok", actor_id=uid)
            await _dm(bot, uid,
                f"🌙 *{game.day_number}-kecha*\n\n"
                f"🤡 Kimga 4 ta karta yuborasiz? (25% o'lim ehtimoli) ({NIGHT_SECS}s):", kb)

        elif role == Role.SOTQIN:
            suspects = [p for p in alive if p.role in (Role.DON, Role.MAFIA, Role.QOTIL)]
            if suspects:
                rows = [
                    [InlineKeyboardButton(text=p.display_name, callback_data=f"nsot:{p.user_id}:{chat_id}")]
                    for p in suspects
                ] + [[InlineKeyboardButton(text="⏭️ O'tkazib yuborish", callback_data=f"nsot:0:{chat_id}")]]
                await _dm(bot, uid,
                    f"🌙 *{game.day_number}-kecha*\n\n"
                    f"🤓 Kimni fosh qilmoqchisiz ({NIGHT_SECS}s)?",
                    InlineKeyboardMarkup(inline_keyboard=rows))
            else:
                game.night_actions[Role.SOTQIN] = 0
                await _dm(bot, uid,
                    f"🌙 *{game.day_number}-kecha*\n\n🤓 Fosh qilish uchun ma'lum nishon yo'q.")

        elif role in PASSIVE_NIGHT_ROLES:
            await _dm(bot, uid,
                f"🌙 *{game.day_number}-kecha*\n\n{PASSIVE_MESSAGES.get(role, 'Dam oling.')}")


def _auto_passive(game: Game):
    for p in game.alive_players():
        if p.role in PASSIVE_NIGHT_ROLES:
            game.night_actions[f"passive_{p.user_id}"] = True
    serzhant = game.get_alive_by_role(Role.SERZHANT)
    if serzhant and game.get_alive_by_role(Role.KOMISSAR):
        game.night_actions[Role.SERZHANT] = 0

# ──────────────────────────────────────────────
# Commands
# ──────────────────────────────────────────────

@router.message(Command("start", "help"))
async def cmd_start(msg: Message):
    if msg.chat.type == "private":
        await msg.answer(
            "👋 Salom! Men *Mafiya O'yin Boti*man.\n\n"
            "Meni guruh chatiga qo'shing va /newgame bilan o'yinni boshlang!\n\n"
            "*Buyruqlar:*\n"
            "/newgame — Yangi o'yin lobby'si\n"
            "/startgame — O'yinni boshlash (admin)\n"
            "/endgame — O'yinni tugatish (admin)\n"
            "/players — O'yinchilar ro'yxati\n"
            "/stats — Statistika\n"
            "/rules — Qoidalar\n"
            "/roles — Barcha rollar haqida",
        )
    else:
        await msg.answer("👋 /newgame bilan yangi o'yin boshlang!")


@router.message(Command("rules"))
async def cmd_rules(msg: Message):
    await msg.answer(
        "🃏 *Mafiya O'yin Qoidalari*\n\n"
        "🌙 *Kecha* — Maxsus rollar xususiy xabar orqali harakatlarini bajaradi.\n"
        "☀️ *Kunduz* — O'yinchilar muhokama qiladi.\n"
        "🗳️ *Ovoz* — Shubhalini chiqarish uchun ovoz beriladi.\n\n"
        "*Har bosqich avtomatik o'tadi — 30 soniyadan keyin!*\n\n"
        "🔴 Mafiya — fuqarolar soniga yetganda g'alaba.\n"
        "🔵 Fuqarolar — barcha Mafiya yo'q qilinganda g'alaba.\n\n"
        "Barcha rollar: /roles"
    )


@router.message(Command("roles"))
async def cmd_roles(msg: Message):
    teams = {
        "🔴 *Mafiya jamoasi:*": [Role.DON, Role.MAFIA, Role.YOLLANMA_QOTIL, Role.ADVOKAT, Role.JURNALIST],
        "🔵 *Fuqarolar jamoasi:*": [Role.KOMISSAR, Role.DOCTOR, Role.SERZHANT, Role.JANOB, Role.CITIZEN,
                                    Role.DAYDI, Role.KEZUVCHI, Role.OMADLI, Role.ADMIRAL, Role.SOTQIN],
        "⚪ *Mustaqil rollar:*": [Role.QOTIL, Role.SUIDSID, Role.BO_RI, Role.AFSUNGAR, Role.AFERIST,
                                  Role.SEHRGAR, Role.GAZABKOR, Role.JOKER, Role.KIMYOGAR, Role.MINIOR],
    }
    for label, roles in teams.items():
        lines = [label]
        for r in roles:
            desc_short = ROLE_DESCRIPTIONS_UZ[r].split("\n")[0]
            lines.append(f"{ROLE_EMOJIS[r]} *{ROLE_NAMES_UZ[r]}* — _{desc_short}_")
        await msg.answer("\n".join(lines))


@router.message(Command("newgame"))
async def cmd_newgame(msg: Message):
    if msg.chat.type == "private":
        return await msg.answer("⚠️ Bu buyruq faqat guruh chatlarda ishlaydi.")

    chat_id = msg.chat.id
    existing = games.get(chat_id)
    if existing and existing.phase != Phase.ENDED:
        return await msg.answer("⚠️ O'yin allaqachon davom etmoqda! /endgame bilan bekor qiling.")

    games[chat_id] = Game(chat_id=chat_id)
    game = games[chat_id]
    user = msg.from_user
    game.add_player(user.id, user.username or "", user.first_name)

    await msg.answer(
        f"🎮 *YANGI MAFIYA O'YINI!*\n\n"
        f"👤 *{user.first_name}* o'yinni yaratdi.\n\n"
        f"Quyidagi tugmani bosib qo'shiling!\n"
        f"Tayyor bo'lganda admin /startgame bossin.\n\n"
        f"*O'yinchilar ({len(game.players)}/{MIN_PLAYERS} min):*\n"
        f"{_player_list(game)}",
        reply_markup=_lobby_kb(chat_id),
    )


@router.message(Command("players"))
async def cmd_players(msg: Message):
    game = games.get(msg.chat.id)
    if not game or game.phase == Phase.ENDED:
        return await msg.answer("⚠️ Bu chatda faol o'yin yo'q.")

    phase_label = {
        Phase.LOBBY: "Lobby",
        Phase.NIGHT: f"{game.day_number}-kecha",
        Phase.DAY:   f"{game.day_number}-kun",
        Phase.VOTING: f"Ovoz berish — {game.day_number}-kun",
    }.get(game.phase, "")

    alive = game.alive_players()
    dead  = [p for p in game.players.values() if not p.alive]

    text = f"👥 *O'yinchilar — {phase_label}*\n\n*Tirik ({len(alive)}):*\n"
    for i, p in enumerate(alive, 1):
        text += f"{i}. {p.display_name}\n"
    if dead:
        text += f"\n*Chiqarilgan ({len(dead)}):*\n"
        for p in dead:
            rn = ROLE_NAMES_UZ.get(p.role, "") if p.role else ""
            em = ROLE_EMOJIS.get(p.role, "") if p.role else ""
            text += f"☠️ {p.display_name} — {em} {rn}\n"

    await msg.answer(text)


@router.message(Command("startgame"))
async def cmd_startgame(msg: Message, bot: Bot):
    if msg.chat.type == "private":
        return await msg.answer("⚠️ Bu buyruq faqat guruh chatlarda ishlaydi.")

    chat_id = msg.chat.id
    game = games.get(chat_id)
    if not game or game.phase == Phase.ENDED:
        return await msg.answer("⚠️ Faol lobby yo'q. /newgame dan foydalaning.")
    if game.phase != Phase.LOBBY:
        return await msg.answer("⚠️ O'yin allaqachon boshlangan.")

    member = await bot.get_chat_member(chat_id, msg.from_user.id)
    is_admin = member.status in ("administrator", "creator")
    if not is_admin and msg.from_user.id not in game.players:
        return await msg.answer("⚠️ Faqat admin yoki lobby o'yinchilari boshlashi mumkin.")

    if len(game.players) < MIN_PLAYERS:
        return await msg.answer(
            f"⚠️ Kamida *{MIN_PLAYERS}* o'yinchi kerak. Hozir: *{len(game.players)}*"
        )

    game.assign_roles()
    game.day_number = 1

    for player in game.players.values():
        record_game_start(player.user_id, player.first_name)

    counts: dict = {}
    for p in game.players.values():
        counts[p.role] = counts.get(p.role, 0) + 1
    dist = "  ".join(f"{ROLE_EMOJIS[r]} {ROLE_NAMES_UZ[r]}: {n}" for r, n in counts.items())

    await msg.answer(
        f"🟢 *O'YIN BOSHLANDI!*\n\n"
        f"*{len(game.players)} o'yinchi* rollarini oldi.\n{dist}\n\n"
        "🎭 Shaxsiy xabaringizni tekshiring!\n"
        "⚠️ Agar DM kelmasa — botga /start yozing!",
    )

    mafia_names = ", ".join(
        p.display_name for p in game.players.values() if p.role in MAFIA_TEAM
    )
    for player in game.players.values():
        em   = ROLE_EMOJIS[player.role]
        name = ROLE_NAMES_UZ[player.role]
        desc = ROLE_DESCRIPTIONS_UZ[player.role]
        extra = f"\n\n🤝 *Mafiya jamoangiz:* {mafia_names}" if player.role in MAFIA_TEAM else ""
        await _dm(bot, player.user_id,
            f"🎭 *Sizning rolingiz: {em} {name}*\n\n{desc}{extra}\n\nO'yin boshlandi!")

    asyncio.create_task(run_night(bot, chat_id))


@router.message(Command("endgame"))
async def cmd_endgame(msg: Message, bot: Bot):
    chat_id = msg.chat.id
    game = games.get(chat_id)
    if not game or game.phase == Phase.ENDED:
        return await msg.answer("⚠️ Tugatish uchun faol o'yin yo'q.")

    member = await bot.get_chat_member(chat_id, msg.from_user.id)
    if member.status not in ("administrator", "creator"):
        return await msg.answer("⚠️ Faqat admin o'yinni majburiy tugatishi mumkin.")

    game.cancel_phase_task()
    game.phase = Phase.ENDED
    role_list = "\n".join(
        f"  {'☠️' if not p.alive else '✅'} {p.display_name} — "
        f"{ROLE_EMOJIS.get(p.role,'')} {ROLE_NAMES_UZ.get(p.role,'')}"
        for p in game.players.values() if p.role
    )
    await msg.answer(f"🛑 *O'yin admin tomonidan tugatildi.*\n\n*Rollar:*\n{role_list}")


@router.message(Command("stats"))
async def cmd_stats(msg: Message):
    stats = load_stats()
    total = stats.total_games
    if total == 0:
        return await msg.answer("📊 Hali hech qanday o'yin o'ynalmagan!")
    cp = round(stats.citizen_wins / total * 100)
    mp = round(stats.mafia_wins  / total * 100)
    av = round(stats.total_players / total, 1)
    await msg.answer(
        "📊 *O'yin Statistikasi*\n\n"
        f"🎮 Jami o'yinlar: *{total}*\n"
        f"👥 O'rtacha o'yinchilar: *{av}*\n\n"
        f"🏆 Fuqarolar g'alabasi: *{stats.citizen_wins}* ({cp}%)\n"
        f"🔪 Mafiya g'alabasi: *{stats.mafia_wins}* ({mp}%)\n"
    )


@router.message(Command("profile"))
async def cmd_profile(msg: Message):
    user = msg.from_user
    p = get_profile(user.id, user.first_name)
    diamond_str = "♾️" if p.infinite_diamond else str(p.diamond)
    win_rate = f"{round(p.wins / p.games * 100)}%" if p.games > 0 else "—"

    items = []
    if p.shield:       items.append(f"🛡 Himoya: {p.shield}")
    if p.documents:    items.append(f"📁 Hujjat: {p.documents}")
    if p.hang_protect: items.append(f"⚖️ Osishdan himoya: {p.hang_protect}")
    if p.killer_protect: items.append(f"⛑️ Qotildan himoya: {p.killer_protect}")
    if p.gun:          items.append(f"🔫 Miltiq: {p.gun}")
    if p.drug_protect: items.append(f"💊 Doridan himoya: {p.drug_protect}")
    if p.mask:         items.append(f"🎭 Maska: {p.mask}")
    if p.slip_protect: items.append(f"🪤 Sirpanishdan himoya: {p.slip_protect}")
    if p.hero_protect: items.append(f"🔰 Geroydan himoya: {p.hero_protect}")
    if p.mines:        items.append(f"💣 Minalar: {p.mines}")
    items_str = "\n".join(items) if items else "  Hech narsa yo'q"

    roles_str = ", ".join(p.active_roles) if p.active_roles else "Yo'q"

    await msg.answer(
        f"👤 *{user.first_name}*\n\n"
        f"💵 Dollar: *{p.dollar}$*\n"
        f"💎 Olmos: *{diamond_str}*\n\n"
        f"🎯 G'alabalar: *{p.wins}*\n"
        f"🎲 Jami o'yinlar: *{p.games}*\n"
        f"📈 G'alaba foizi: *{win_rate}*\n\n"
        f"🎒 *Inventar:*\n{items_str}\n\n"
        f"🃏 Faol rollar: {roles_str}"
    )


@router.message(Command("give"))
async def cmd_give(msg: Message):
    if not msg.reply_to_message:
        return await msg.answer("❌ Kimga berishni ko'rsating — xabariga reply qiling.")

    giver = msg.from_user
    target_user = msg.reply_to_message.from_user
    if target_user.is_bot:
        return await msg.answer("❌ Botga olmos berish mumkin emas.")
    if giver.id == target_user.id:
        return await msg.answer("❌ O'zingizga bera olmaysiz.")

    parts = msg.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        return await msg.answer("❌ Miqdor kiriting. Masalan: `/give 50` (reply bilan)")

    amount = int(parts[1])
    if amount <= 0:
        return await msg.answer("❌ Miqdor musbat son bo'lishi kerak.")

    get_profile(target_user.id, target_user.first_name)
    ok = transfer_diamond(giver.id, target_user.id, amount)
    if not ok:
        giver_p = get_profile(giver.id)
        return await msg.answer(
            f"❌ Yetarli olmos yo'q. Sizda: *{giver_p.diamond}* 💎"
        )

    await msg.answer(
        f"💎 *{giver.first_name}* → *{target_user.first_name}*\n"
        f"*{amount}* olmos o'tkazildi!"
    )


@router.message(Command("kick"))
async def cmd_kick(msg: Message, bot: Bot):
    if msg.chat.type == "private":
        return await msg.answer("⚠️ Bu buyruq faqat guruhda ishlaydi.")

    chat_id = msg.chat.id
    member = await bot.get_chat_member(chat_id, msg.from_user.id)
    if member.status not in ("administrator", "creator"):
        return await msg.answer("⚠️ Faqat adminlar /kick ishlatishi mumkin.")

    if not msg.reply_to_message:
        return await msg.answer("❌ Kimni chiqarishni ko'rsating — xabariga reply qiling.")

    target = msg.reply_to_message.from_user
    game = games.get(chat_id)
    if not game or game.phase == Phase.ENDED:
        return await msg.answer("⚠️ Faol o'yin yo'q.")

    if target.id not in game.players:
        return await msg.answer(f"⚠️ *{target.first_name}* bu o'yinda emas.")

    if game.phase == Phase.LOBBY:
        game.remove_player(target.id)
        await msg.answer(f"👢 *{target.first_name}* lobbydan chiqarildi.")
    else:
        game.eliminate_player(target.id)
        tp = game.get_player_by_id(target.id)
        role_str = ""
        if tp and tp.role:
            role_str = f" Roli: {ROLE_EMOJIS.get(tp.role,'')} {ROLE_NAMES_UZ.get(tp.role,'')}"
        await msg.answer(f"👢 *{target.first_name}* admin tomonidan chiqarildi.{role_str}")
        winner = game.check_win_condition()
        if winner:
            asyncio.create_task(_end_game(bot, game, winner))


SHOP_ITEMS = {
    "shield":        ("🛡",  "Himoya",               "dollar", 140, "shield"),
    "documents":     ("📁",  "Hujjat",               "dollar", 200, "documents"),
    "hang_protect":  ("⚖️", "Osishdan himoya",       "diamond", 1,  "hang_protect"),
    "killer_protect":("⛑️", "Qotildan himoya",       "diamond", 1,  "killer_protect"),
    "drug_protect":  ("💊",  "Doridan himoya",        "diamond", 1,  "drug_protect"),
    "mask":          ("🎭",  "Maska",                 "diamond", 1,  "mask"),
    "slip_protect":  ("🪤",  "Sirpanishdan himoya",   "diamond", 1,  "slip_protect"),
    "hero_protect":  ("🔰",  "Geroydan himoya",       "diamond", 1,  "hero_protect"),
}


def _shop_kb() -> InlineKeyboardMarkup:
    rows = []
    for key, (em, name, currency, price, _) in SHOP_ITEMS.items():
        cur_icon = "💵" if currency == "dollar" else "💎"
        rows.append([InlineKeyboardButton(
            text=f"{em} {name} — {price}{cur_icon}",
            callback_data=f"shop_buy:{key}"
        )])
    rows.append([InlineKeyboardButton(text="👤 Profilim", callback_data="shop_profile")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("shop"))
async def cmd_shop(msg: Message):
    user = msg.from_user
    p = get_profile(user.id, user.first_name)
    diamond_str = "♾️" if p.infinite_diamond else str(p.diamond)
    await msg.answer(
        f"🛒 *DO'KON*\n\n"
        f"💵 Balansingiz: *{p.dollar}$*\n"
        f"💎 Olmoslaringiz: *{diamond_str}*\n\n"
        "Sotib olmoqchi bo'lgan narsani tanlang:",
        reply_markup=_shop_kb(),
    )


@router.message(Command("buy"))
async def cmd_buy(msg: Message):
    parts = msg.text.split()
    if len(parts) < 2:
        items_list = "\n".join(
            f"  `buy {key}` — {em} {name} ({price}{'💵' if cur == 'dollar' else '💎'})"
            for key, (em, name, cur, price, _) in SHOP_ITEMS.items()
        )
        return await msg.answer(
            f"❌ Item nomi kiriting. Mavjud mahsulotlar:\n\n{items_list}"
        )

    key = parts[1].lower()
    item = SHOP_ITEMS.get(key)
    if not item:
        return await msg.answer(
            f"❌ *{key}* — bunday item yo'q.\n\n"
            "Mavjud itemlar: " + ", ".join(f"`{k}`" for k in SHOP_ITEMS)
        )

    em, name, currency, price, field = item
    uid = msg.from_user.id
    p = get_profile(uid, msg.from_user.first_name)

    if currency == "dollar":
        if p.dollar < price:
            return await msg.answer(
                f"❌ Yetarli dollar yo'q!\n{em} *{name}* — {price}💵\nSizda: *{p.dollar}$*"
            )
        p.dollar -= price
    else:
        if not p.infinite_diamond and p.diamond < price:
            return await msg.answer(
                f"❌ Yetarli olmos yo'q!\n{em} *{name}* — {price}💎\nSizda: *{p.diamond}💎*"
            )
        if not p.infinite_diamond:
            p.diamond -= price

    setattr(p, field, getattr(p, field) + 1)
    save_profile(p)

    diamond_str = "♾️" if p.infinite_diamond else str(p.diamond)
    await msg.answer(
        f"✅ {em} *{name}* sotib olindi!\n\n"
        f"💵 Qolgan dollar: *{p.dollar}$*\n"
        f"💎 Qolgan olmos: *{diamond_str}*\n\n"
        f"Barcha xaridlar: /shop"
    )


@router.callback_query(F.data.startswith("shop_buy:"))
async def cb_shop_buy(call: CallbackQuery):
    key = call.data.split(":")[1]
    item = SHOP_ITEMS.get(key)
    if not item:
        return await call.answer("❌ Noma'lum mahsulot.", show_alert=True)

    em, name, currency, price, field = item
    uid = call.from_user.id
    p = get_profile(uid, call.from_user.first_name)

    if currency == "dollar":
        if p.dollar < price:
            return await call.answer(
                f"❌ Yetarli dollar yo'q!\nKerak: {price}$  |  Sizda: {p.dollar}$",
                show_alert=True,
            )
        p.dollar -= price
    else:
        if not p.infinite_diamond and p.diamond < price:
            return await call.answer(
                f"❌ Yetarli olmos yo'q!\nKerak: {price}💎  |  Sizda: {p.diamond}💎",
                show_alert=True,
            )
        if not p.infinite_diamond:
            p.diamond -= price

    setattr(p, field, getattr(p, field) + 1)
    save_profile(p)

    diamond_str = "♾️" if p.infinite_diamond else str(p.diamond)
    await call.answer(f"✅ {em} {name} sotib olindi!", show_alert=False)

    try:
        await call.message.edit_text(
            f"🛒 *DO'KON*\n\n"
            f"💵 Balansingiz: *{p.dollar}$*\n"
            f"💎 Olmoslaringiz: *{diamond_str}*\n\n"
            f"✅ *{em} {name}* muvaffaqiyatli sotib olindi!\n\n"
            "Yana xarid qilish uchun tanlang:",
            reply_markup=_shop_kb(),
        )
    except Exception:
        pass


@router.callback_query(F.data == "shop_profile")
async def cb_shop_profile(call: CallbackQuery):
    uid = call.from_user.id
    p = get_profile(uid, call.from_user.first_name)
    diamond_str = "♾️" if p.infinite_diamond else str(p.diamond)
    win_rate = f"{round(p.wins / p.games * 100)}%" if p.games > 0 else "—"

    items = []
    if p.shield:        items.append(f"🛡 Himoya: {p.shield}")
    if p.documents:     items.append(f"📁 Hujjat: {p.documents}")
    if p.hang_protect:  items.append(f"⚖️ Osishdan himoya: {p.hang_protect}")
    if p.killer_protect:items.append(f"⛑️ Qotildan himoya: {p.killer_protect}")
    if p.gun:           items.append(f"🔫 Miltiq: {p.gun}")
    if p.drug_protect:  items.append(f"💊 Doridan himoya: {p.drug_protect}")
    if p.mask:          items.append(f"🎭 Maska: {p.mask}")
    if p.slip_protect:  items.append(f"🪤 Sirpanishdan himoya: {p.slip_protect}")
    if p.hero_protect:  items.append(f"🔰 Geroydan himoya: {p.hero_protect}")
    if p.mines:         items.append(f"💣 Minalar: {p.mines}")
    items_str = "\n".join(items) if items else "  Hech narsa yo'q"

    await call.answer()
    await call.message.edit_text(
        f"👤 *{call.from_user.first_name}*\n\n"
        f"💵 Dollar: *{p.dollar}$*\n"
        f"💎 Olmos: *{diamond_str}*\n\n"
        f"🎯 G'alabalar: *{p.wins}*  |  🎲 O'yinlar: *{p.games}*  |  📈 {win_rate}\n\n"
        f"🎒 *Inventar:*\n{items_str}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🛒 Do'konga qaytish", callback_data="shop_back")]
        ]),
    )


@router.callback_query(F.data == "shop_back")
async def cb_shop_back(call: CallbackQuery):
    uid = call.from_user.id
    p = get_profile(uid, call.from_user.first_name)
    diamond_str = "♾️" if p.infinite_diamond else str(p.diamond)
    await call.answer()
    await call.message.edit_text(
        f"🛒 *DO'KON*\n\n"
        f"💵 Balansingiz: *{p.dollar}$*\n"
        f"💎 Olmoslaringiz: *{diamond_str}*\n\n"
        "Sotib olmoqchi bo'lgan narsani tanlang:",
        reply_markup=_shop_kb(),
    )


@router.message(Command("mine"))
async def cmd_mine(msg: Message):
    uid = msg.from_user.id
    nums = list(range(1, 11))
    diamond_slots = set(random.sample(nums, 3))
    mine_slots = set(random.sample([x for x in nums if x not in diamond_slots], 2))
    rewards = {}
    for n in nums:
        if n in diamond_slots:
            rewards[n] = ("diamond", random.randint(1, 3))
        elif n in mine_slots:
            rewards[n] = ("mine", 0)
        else:
            rewards[n] = ("money", random.randint(100, 500))

    mine_sessions[uid] = rewards

    buttons = [
        InlineKeyboardButton(text=str(n), callback_data=f"mine_pick:{n}")
        for n in nums
    ]
    kb = InlineKeyboardMarkup(inline_keyboard=[buttons[:5], buttons[5:]])

    await msg.answer(
        "⛏️ *MINE O'YINI*\n\n"
        "10 ta raqam ichida:\n"
        "💎 3 ta olmos slot\n"
        "💣 2 ta mina slot\n"
        "💵 5 ta dollar slot\n\n"
        "Bir raqam tanlang:",
        reply_markup=kb,
    )


# ──────────────────────────────────────────────
# Callback handlers
# ──────────────────────────────────────────────

@router.callback_query(F.data.startswith("join:"))
async def cb_join(call: CallbackQuery):
    chat_id = int(call.data.split(":")[1])
    game = games.get(chat_id)
    if not game or game.phase != Phase.LOBBY:
        return await call.answer("⚠️ Lobby faol emas.", show_alert=True)

    user = call.from_user
    if game.add_player(user.id, user.username or "", user.first_name):
        await call.answer(f"✅ Qo'shildingiz! Jami: {len(game.players)} o'yinchi.")
        await call.message.edit_text(
            f"🎮 *YANGI MAFIYA O'YINI!*\n\n"
            f"Quyidagi tugmani bosib qo'shiling!\n"
            f"Tayyor bo'lganda admin /startgame bossin.\n\n"
            f"*O'yinchilar ({len(game.players)}/{MIN_PLAYERS} min):*\n"
            f"{_player_list(game)}",
            reply_markup=_lobby_kb(chat_id),
        )
        try:
            await call.bot.send_message(user.id,
                "✅ *O'yinga qo'shildingiz!*\n\nO'yin boshlanishini kuting. "
                "⚠️ DM yopiq bo'lsa — rollarni ololmaysiz, /start yozing!")
        except Exception:
            pass
    else:
        if user.id in game.players:
            await call.answer("❌ Siz allaqachon o'yindasiz!", show_alert=True)
        else:
            await call.answer("❌ Lobby to'lgan.", show_alert=True)


@router.callback_query(F.data.startswith("show_players:"))
async def cb_show_players(call: CallbackQuery):
    chat_id = int(call.data.split(":")[1])
    game = games.get(chat_id)
    if not game:
        return await call.answer("O'yin topilmadi.", show_alert=True)
    await call.answer(
        f"O'yinchilar ({len(game.players)}):\n{_player_list(game)}",
        show_alert=True,
    )


# ── Night action callbacks ──

async def _night_cb(call: CallbackQuery, action_key, target_id: int, chat_id: int, confirm_text: str):
    game = games.get(chat_id)
    if not game or game.phase != Phase.NIGHT:
        return await call.answer("⚠️ Kecha tugagan.", show_alert=True)
    actor = game.get_player_by_id(call.from_user.id)
    if not actor or not actor.alive:
        return await call.answer("⚠️ Siz faol o'yinchi emassiz.", show_alert=True)
    target = game.get_player_by_id(target_id)
    if not target or not target.alive:
        return await call.answer("⚠️ Bu o'yinchi mavjud emas.", show_alert=True)

    game.night_actions[action_key] = target_id
    await call.answer(confirm_text)
    await call.message.edit_text(f"✅ {confirm_text}")

    if game.all_night_actions_done():
        asyncio.create_task(_do_night_resolution(call.bot, game))


@router.callback_query(F.data.startswith("nk:"))
async def cb_nk(call: CallbackQuery):
    _, tid, cid = call.data.split(":")
    tid, cid = int(tid), int(cid)
    game = games.get(cid)
    if not game or game.phase != Phase.NIGHT:
        return await call.answer("⚠️ Kecha tugagan.", show_alert=True)
    actor = game.get_player_by_id(call.from_user.id)
    if not actor or not actor.alive:
        return await call.answer("⚠️ Siz faol o'yinchi emassiz.", show_alert=True)
    target = game.get_player_by_id(tid)
    if not target or not target.alive:
        return await call.answer("⚠️ Bu o'yinchi mavjud emas.", show_alert=True)

    game.night_actions["mafia_kill"] = tid
    game.night_actions[actor.user_id] = tid
    await call.answer(f"🔪 Nishon: {target.display_name}")
    await call.message.edit_text(f"🔪 Nishon tanlandi: *{target.display_name}*")
    if game.all_night_actions_done():
        asyncio.create_task(_do_night_resolution(call.bot, game))


@router.callback_query(F.data.startswith("nyq:"))
async def cb_nyq(call: CallbackQuery):
    _, tid, cid = call.data.split(":")
    await _night_cb(call, Role.YOLLANMA_QOTIL, int(tid), int(cid), f"🥷 Nishon tanlandi")


@router.callback_query(F.data.startswith("nadv:"))
async def cb_nadv(call: CallbackQuery):
    _, tid, cid = call.data.split(":")
    await _night_cb(call, Role.ADVOKAT, int(tid), int(cid), "👨🏼‍💼 Himoyaga olindi")


@router.callback_query(F.data.startswith("njurn:"))
async def cb_njurn(call: CallbackQuery):
    _, tid, cid = call.data.split(":")
    await _night_cb(call, Role.JURNALIST, int(tid), int(cid), "👩🏼‍💻 Manzil tanlandi")


@router.callback_query(F.data.startswith("nkom:"))
async def cb_nkom(call: CallbackQuery):
    _, tid, cid = call.data.split(":")
    game = games.get(int(cid))
    if not game or game.phase != Phase.NIGHT:
        return await call.answer("⚠️ Kecha tugagan.", show_alert=True)
    key = Role.KOMISSAR if game.get_alive_by_role(Role.KOMISSAR) else Role.SERZHANT
    await _night_cb(call, key, int(tid), int(cid), "🕵🏼 Tekshirilmoqda")


@router.callback_query(F.data.startswith("ndoc:"))
async def cb_ndoc(call: CallbackQuery):
    _, tid, cid = call.data.split(":")
    await _night_cb(call, Role.DOCTOR, int(tid), int(cid), "💊 Himoyaga olindi")


@router.callback_query(F.data.startswith("nkez:"))
async def cb_nkez(call: CallbackQuery):
    _, tid, cid = call.data.split(":")
    await _night_cb(call, Role.KEZUVCHI, int(tid), int(cid), "💃 Uyqu dori berildi")


@router.callback_query(F.data.startswith("nday:"))
async def cb_nday(call: CallbackQuery):
    _, tid, cid = call.data.split(":")
    await _night_cb(call, Role.DAYDI, int(tid), int(cid), "🧙‍♂️ Tashrif manzili tanlandi")


@router.callback_query(F.data.startswith("nqot:"))
async def cb_nqot(call: CallbackQuery):
    _, tid, cid = call.data.split(":")
    await _night_cb(call, Role.QOTIL, int(tid), int(cid), "🔪 Nishon tanlandi")


@router.callback_query(F.data.startswith("nkimmode:"))
async def cb_nkimmode(call: CallbackQuery):
    _, mode, cid = call.data.split(":")
    cid = int(cid)
    game = games.get(cid)
    if not game or game.phase != Phase.NIGHT:
        return await call.answer("⚠️ Kecha tugagan.", show_alert=True)
    game.night_actions["kimyogar_mode"] = mode
    label = "davolash 🩺" if mode == "heal" else "o'ldirish ☠️"
    actor = game.get_player_by_id(call.from_user.id)
    kb = _target_kb(game, "nkim", actor_id=actor.user_id if actor else None,
                    include_self=(mode == "heal"))
    await call.message.edit_text(
        f"👨‍🔬 *{label.capitalize()}* uchun o'yinchini tanlang:", reply_markup=kb
    )
    await call.answer()


@router.callback_query(F.data.startswith("nkim:"))
async def cb_nkim(call: CallbackQuery):
    _, tid, cid = call.data.split(":")
    mode = games.get(int(cid), Game(0)).night_actions.get("kimyogar_mode", "heal")
    label = "davolash" if mode == "heal" else "o'ldirish"
    await _night_cb(call, Role.KIMYOGAR, int(tid), int(cid), f"👨‍🔬 {label} tanlandi")


@router.callback_query(F.data.startswith("nmin:"))
async def cb_nmin(call: CallbackQuery):
    _, tid, cid = call.data.split(":")
    await _night_cb(call, Role.MINIOR, int(tid), int(cid), "☠️ Mina qo'yildi")


@router.callback_query(F.data.startswith("nafer:"))
async def cb_nafer(call: CallbackQuery):
    _, tid, cid = call.data.split(":")
    await _night_cb(call, Role.AFERIST, int(tid), int(cid), "🤹🏻 Shaxs almashtirildi")


@router.callback_query(F.data.startswith("ngaz:"))
async def cb_ngaz(call: CallbackQuery):
    _, tid, cid = call.data.split(":")
    tid, cid = int(tid), int(cid)
    game = games.get(cid)
    if not game or game.phase != Phase.NIGHT:
        return await call.answer("⚠️ Kecha tugagan.", show_alert=True)
    actor = game.get_player_by_id(call.from_user.id)
    if not actor:
        return await call.answer("⚠️ Siz faol emassiz.", show_alert=True)
    game.night_actions[Role.GAZABKOR] = tid
    if tid == actor.user_id:
        await call.answer("🧟 O'zingizni tanladingiz — natija tunda!")
        await call.message.edit_text("🧟 O'zingizni tanladingiz — natija tunda aniqlanadi!")
    else:
        t = game.get_player_by_id(tid)
        await call.answer(f"🧟 {t.display_name if t else tid} ro'yxatga qo'shildi")
        await call.message.edit_text(f"🧟 *{t.display_name if t else tid}* ro'yxatga qo'shildi.")
    if game.all_night_actions_done():
        asyncio.create_task(_do_night_resolution(call.bot, game))


@router.callback_query(F.data.startswith("njok:"))
async def cb_njok(call: CallbackQuery):
    _, tid, cid = call.data.split(":")
    await _night_cb(call, Role.JOKER, int(tid), int(cid), "🤡 Kartalar yuborildi")


@router.callback_query(F.data.startswith("nsot:"))
async def cb_nsot(call: CallbackQuery):
    _, tid, cid = call.data.split(":")
    tid, cid = int(tid), int(cid)
    game = games.get(cid)
    if not game or game.phase != Phase.NIGHT:
        return await call.answer("⚠️ Kecha tugagan.", show_alert=True)
    game.night_actions[Role.SOTQIN] = tid
    if tid == 0:
        await call.answer("🤓 O'tkazib yubordingiz.")
        await call.message.edit_text("🤓 Bu kecha o'tkazib yubordingiz.")
    else:
        t = game.get_player_by_id(tid)
        await call.answer(f"🤓 Nishon tanlandi")
        await call.message.edit_text(f"🤓 Nishon tanlandi: *{t.display_name if t else tid}*")
    if game.all_night_actions_done():
        asyncio.create_task(_do_night_resolution(call.bot, game))


@router.callback_query(F.data.startswith("sehrgar:"))
async def cb_sehrgar(call: CallbackQuery):
    _, choice, cid = call.data.split(":")
    game = games.get(int(cid))
    if not game or game.phase != Phase.NIGHT:
        return await call.answer("⚠️ Bu harakat amal qilmaydi.", show_alert=True)
    sehrgar = game.get_alive_by_role(Role.SEHRGAR)
    if not sehrgar or sehrgar.user_id != call.from_user.id:
        return await call.answer("⚠️ Bu sizning harakatingiz emas.", show_alert=True)

    if choice == "kill":
        attacker_map = {
            "mafia": [Role.DON, Role.MAFIA],
            "komissar": [Role.KOMISSAR, Role.SERZHANT],
            "qotil": [Role.QOTIL],
        }
        for cause in list(game.sehrgar_pending.keys()):
            for r in attacker_map.get(cause, []):
                attacker = game.get_alive_by_role(r)
                if attacker:
                    game.eliminate_player(attacker.user_id)
        await call.message.edit_text("⚡ Siz dushmanni o'ldirdingiz! Natija tunda e'lon qilinadi.")
    else:
        await call.message.edit_text("🕊️ Rahm qildingiz...")

    game.sehrgar_pending = {}
    await call.answer()
    if game.all_night_actions_done():
        asyncio.create_task(_do_night_resolution(call.bot, game))


# ── Group voting callbacks ──

@router.callback_query(F.data.startswith("gvote:"))
async def cb_gvote(call: CallbackQuery):
    _, tid, cid = call.data.split(":")
    tid, cid = int(tid), int(cid)
    game = games.get(cid)
    if not game or game.phase != Phase.VOTING:
        return await call.answer("⚠️ Ovoz berish tugagan.", show_alert=True)

    voter = game.get_player_by_id(call.from_user.id)
    if not voter or not voter.alive:
        return await call.answer("⚠️ Siz faol o'yinchi emassiz.", show_alert=True)

    target = game.get_player_by_id(tid)
    if not target or not target.alive:
        return await call.answer("⚠️ Bu o'yinchi mavjud emas.", show_alert=True)

    if game.votes.get(voter.user_id) == tid:
        del game.votes[voter.user_id]
        await call.answer(f"Ovozingiz bekor qilindi.", show_alert=False)
    else:
        game.votes[voter.user_id] = tid
        await call.answer(f"✅ {game.get_display_name(target)}ga ovoz berdingiz!", show_alert=False)

    voted = len(game.votes)
    alive  = len(game.alive_players())
    lines  = []
    for p in game.alive_players():
        count = sum(1 for v in game.votes.values() if v == p.user_id)
        weight = sum(
            (2 if game.get_player_by_id(vid).role == Role.JANOB else 1)
            for vid, vtid in game.votes.items()
            if vtid == p.user_id and game.get_player_by_id(vid)
        )
        bar = "█" * weight
        lines.append(f"{game.get_display_name(p)}: {bar} ({weight})")

    try:
        await call.message.edit_text(
            f"🗳️ *OVOZ BERISH* — {game.day_number}-kun\n"
            f"⏳ {VOTE_SECS}s | {voted}/{alive} ovoz\n\n"
            + "\n".join(lines),
            reply_markup=_group_vote_kb(game),
        )
    except Exception:
        pass


@router.callback_query(F.data.startswith("afsungar_revenge:"))
async def cb_afsungar_revenge(call: CallbackQuery):
    _, tid, cid = call.data.split(":")
    tid, cid = int(tid), int(cid)
    game = games.get(cid)
    if not game:
        return await call.answer()

    target = game.get_player_by_id(tid)
    if target and target.alive:
        game.eliminate_player(tid)
        rn = ROLE_NAMES_UZ.get(target.role, "")
        em = ROLE_EMOJIS.get(target.role, "")
        await call.message.edit_text(
            f"💣 *Afsungar* jahannamga ketayotib *{target.display_name}*ni ham olib ketdi!\n"
            f"Roli: {em} *{rn}*"
        )
        await call.answer()
        winner = game.check_win_condition()
        if winner:
            asyncio.create_task(_end_game(call.bot, game, winner))
            return

    game.day_number += 1
    asyncio.create_task(run_night(call.bot, game.chat_id))


@router.callback_query(F.data.startswith("mine_pick:"))
async def cb_mine_pick(call: CallbackQuery):
    uid = call.from_user.id
    rewards = mine_sessions.get(uid)
    if not rewards:
        return await call.answer("⚠️ O'yin topilmadi. /mine bilan yangi o'yin boshlang.", show_alert=True)

    num = int(call.data.split(":")[1])
    typ, amount = rewards[num]
    del mine_sessions[uid]

    p = get_profile(uid, call.from_user.first_name)

    if typ == "diamond":
        add_diamond(uid, amount)
        result = f"💎 *{amount} olmos* topdingiz!"
        detail = f"Umumiy olmos: {p.diamond + amount} 💎"
    elif typ == "money":
        add_dollar(uid, amount)
        result = f"💵 *{amount}$* topdingiz!"
        detail = f"Umumiy dollar: {p.dollar + amount}$"
    else:
        p.mines += 1
        save_profile(p)
        result = "💣 *MINAGA TUSHDINGIZ!*"
        detail = f"Minalar soni: {p.mines} 💣"

    all_labels = {
        "diamond": "💎", "money": "💵", "mine": "💣"
    }
    revealed = " ".join(
        f"[{all_labels[rewards[n][0]]}]" if n == num else f"[{n}]"
        for n in range(1, 11)
    )

    await call.message.edit_text(
        f"⛏️ *MINE O'YINI*\n\n"
        f"Siz *{num}*-raqamni tanladingiz.\n\n"
        f"{result}\n_{detail}_\n\n"
        f"{revealed}"
    )
    await call.answer(result.replace("*", ""))
