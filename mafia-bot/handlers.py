import asyncio
import logging
import random
from typing import Optional
from aiogram import Router, Bot, F
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
)

from game import (
    Game, Phase, Role, MIN_PLAYERS, ROLE_EMOJIS, ROLE_DESCRIPTIONS_UZ,
    MAFIA_TEAM, CITIZEN_TEAM,
)
from stats import load_stats, save_stats
from night import resolve_night
from profiles import get_profile, save_profile, transfer_diamond, transfer_dollar, record_game_start, record_win, add_dollar, add_diamond, OWNER_ID
from settings import get_settings, save_settings, ChatSettings
from bot_config import get_promo_channel, set_promo_channel
from mdutil import escape_md

logger = logging.getLogger(__name__)
router = Router()

games: dict[int, Game] = {}

ROLE_NAMES_UZ = {
    Role.DON: "Don", Role.MAFIA: "Mafia",
    Role.YOLLANMA_QOTIL: "Yollanma Qotil", Role.ADVOKAT: "Advokat",
    Role.JURNALIST: "Jurnalist", Role.KOMISSAR: "Komissar Katani",
    Role.DOCTOR: "Doktor", Role.SERZHANT: "Serjant",
    Role.CITIZEN: "Tinch Axoli",
    Role.DAYDI: "Daydi", Role.KEZUVCHI: "Kezuvchi",
    Role.OMADLI: "Omadli", Role.ADMIRAL: "Admiral",
    Role.SOTQIN: "Sotqin", Role.QOTIL: "Qotil",
    Role.BO_RI: "Bo'ri",
    Role.AFSUNGAR: "Afsungar", Role.AFERIST: "Aferist",
    Role.SEHRGAR: "Sehrgar", Role.GAZABKOR: "G'azabkor",
    Role.JOKER: "Joker", Role.KIMYOGAR: "Kimyogar",
    Role.MINIOR: "Minior", Role.KONCHI: "Konchi",
    Role.TULKI: "Tulki", Role.LABARANT: "Labarant",
}

PASSIVE_NIGHT_ROLES = {
    Role.CITIZEN, Role.OMADLI,
    Role.BO_RI, Role.AFSUNGAR, Role.SEHRGAR, Role.ADMIRAL,
}

PASSIVE_MESSAGES = {
    Role.CITIZEN:  "👨🏼 Siz *Tinch Axoli*siz. Dam oling — ertaga shahar himoyangizga muhtoj!",
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


_bot_username: Optional[str] = None


async def _get_bot_username(bot: Bot) -> Optional[str]:
    global _bot_username
    if not _bot_username:
        try:
            me = await bot.get_me()
            _bot_username = me.username
        except Exception:
            return None
    return _bot_username


async def _group_link(bot: Bot, chat_id: int) -> Optional[str]:
    try:
        chat = await bot.get_chat(chat_id)
        if chat.username:
            return f"https://t.me/{chat.username}"
    except Exception:
        pass
    try:
        return await bot.export_chat_invite_link(chat_id)
    except Exception:
        return None


def _dm_entry_kb(bot_username: Optional[str], text: str, chat_id: int, payload: str) -> Optional[InlineKeyboardMarkup]:
    if not bot_username:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=text, url=f"https://t.me/{bot_username}?start={payload}_{chat_id}")
    ]])


def _lobby_kb(chat_id: int, bot_username: Optional[str] = None) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="🎮 Qo'shilish",   callback_data=f"join:{chat_id}")],
        [InlineKeyboardButton(text="👥 O'yinchilar", callback_data=f"show_players:{chat_id}")],
    ]
    if bot_username:
        rows.append([InlineKeyboardButton(
            text="🤖 Botga o'tish",
            url=f"https://t.me/{bot_username}?start=group_{chat_id}",
        )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


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
        rows.append([InlineKeyboardButton(text=label, callback_data=f"dvote:{p.user_id}:{game.chat_id}")])
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

    settings = get_settings(chat_id)
    game.reset_night_state()
    game.phase = Phase.NIGHT
    _auto_passive(game)

    bot_username = await _get_bot_username(bot)
    await bot.send_message(
        chat_id,
        f"🌙 *{game.day_number}-KECHA BOSHLANDI!*\n"
        f"⏳ Vaqt: *{settings.night_secs} soniya*\n\n"
        "Har bir o'yinchi shaxsiy xabarda harakat tanlashini kutmoqda...\n"
        "⚠️ Agar DM kelmasa — botga /start yozing!",
        reply_markup=_dm_entry_kb(bot_username, "🤖 Botga o'tish", chat_id, "group"),
    )

    await _send_night_actions(bot, game)

    try:
        await asyncio.wait_for(
            _wait_for_night_done(game),
            timeout=settings.night_secs
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
    settings = get_settings(game.chat_id)
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

    found_mafia = game.komissar_found_mafia
    game.komissar_found_mafia = None

    if found_mafia:
        await bot.send_message(
            game.chat_id,
            f"🌙 *{game.day_number}-kecha yakunlandi:*\n\n{summary}\n\n"
            f"🕵🏼 *Komissar {found_mafia} mafiyani topdi!*\n\n"
            "☀️ Darhol ovoz berish boshlanadi!",
        )
        await run_vote(bot, game.chat_id)
        return

    await bot.send_message(
        game.chat_id,
        f"🌙 *{game.day_number}-kecha yakunlandi:*\n\n{summary}\n\n"
        f"☀️ *KUN MUHOKAMASI BOSHLANDI!*\n"
        f"⏳ Muhokama vaqti: *{settings.day_secs} soniya*\n\n"
        "Kim Mafiya ekanini aniqlashga harakat qiling!",
    )

    await asyncio.sleep(settings.day_secs)
    await run_vote(bot, game.chat_id)


async def run_vote(bot: Bot, chat_id: int):
    game = games.get(chat_id)
    if not game or game.phase == Phase.ENDED:
        return

    settings = get_settings(chat_id)
    game.phase = Phase.VOTING
    game.votes = {}

    alive = game.alive_players()
    bot_username = await _get_bot_username(bot)

    msg = await bot.send_message(
        chat_id,
        f"🗳️ *OVOZ BERISH BOSHLANDI!*\n"
        f"⏳ Vaqt: *{settings.vote_secs} soniya*\n\n"
        "Kim Mafiya ekanini shaxsiy xabarda (bot bilan) tanlang!\n"
        "⚠️ Ovoz berilgach uni bekor qilib bo'lmaydi.\n\n"
        f"0/{len(alive)} ovoz berdi.",
        reply_markup=_dm_entry_kb(bot_username, "🗳️ Ovoz berish (DM)", chat_id, "vote"),
    )
    game.vote_msg_id = msg.message_id

    for p in alive:
        try:
            await bot.send_message(
                p.user_id,
                "🗳️ *Ovoz berish vaqti!*\n\nKim Mafiya ekanini o'ylab, tanlang:",
                reply_markup=_vote_kb(game, p.user_id),
            )
        except Exception:
            pass

    await asyncio.sleep(settings.vote_secs)
    await _do_vote_resolution(bot, game)


def _like_dislike_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="👍 Like (0)", callback_data="hangvote:like"),
        InlineKeyboardButton(text="👎 Dislike (0)", callback_data="hangvote:dislike"),
    ]])


async def _run_hang_confirmation(bot: Bot, game: Game, eliminated, summary: str) -> bool:
    settings = get_settings(game.chat_id)
    secs = settings.hang_confirm_secs
    game.hang_confirm_votes = {}

    msg = await bot.send_message(
        game.chat_id,
        f"🗳️ *Ovoz natijalari — {game.day_number}-kun:*\n{summary}\n\n"
        f"⚖️ *{eliminated.display_name}* osilmoqchi!\n"
        "Rostdan ham shu o'yinchini osmoqchimisiz?\n"
        f"⏳ {secs} soniya ichida ovoz bering:",
        reply_markup=_like_dislike_kb(),
    )
    game.hang_confirm_msg_id = msg.message_id

    await asyncio.sleep(secs)

    likes = sum(1 for v in game.hang_confirm_votes.values() if v == "like")
    dislikes = sum(1 for v in game.hang_confirm_votes.values() if v == "dislike")
    confirmed = likes > dislikes

    result_text = (
        f"👍 Like: *{likes}* | 👎 Dislike: *{dislikes}*\n\n"
        + (f"☠️ Ko'pchilik rozi — *{eliminated.display_name}* osiladi!"
           if confirmed else
           f"🕊️ Ko'pchilik rozi emas — *{eliminated.display_name}* tirik qoladi!")
    )
    try:
        await bot.edit_message_text(
            chat_id=game.chat_id, message_id=msg.message_id,
            text=result_text,
        )
    except Exception:
        await bot.send_message(game.chat_id, result_text)

    game.hang_confirm_votes = {}
    return confirmed


async def _do_vote_resolution(bot: Bot, game: Game):
    if game.phase != Phase.VOTING:
        return

    eliminated_id = game.tally_votes()
    counts: dict = {}
    for vid, tid in game.votes.items():
        voter = game.get_player_by_id(vid)
        if voter:
            counts[tid] = counts.get(tid, 0) + 1

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

    settings = get_settings(game.chat_id)
    if settings.hang_confirm_enabled:
        confirmed = await _run_hang_confirmation(bot, game, eliminated, summary)
        if not confirmed:
            game.day_number += 1
            await run_night(bot, game.chat_id)
            return

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

    if winner == "mafia":
        winner_ids = {p.user_id for p in game.players.values() if p.role in MAFIA_TEAM}
    elif winner == "qotil":
        q = game.get_alive_by_role(Role.QOTIL)
        winner_ids = {q.user_id} if q else set()
    else:
        winner_ids = {p.user_id for p in game.players.values() if p.role not in MAFIA_TEAM and p.role != Role.QOTIL}

    winners = [p for p in game.players.values() if p.role and p.user_id in winner_ids]
    losers = [p for p in game.players.values() if p.role and p.user_id not in winner_ids]

    def _fmt(p):
        return f"  {'☠️' if not p.alive else '✅'} {p.display_name} — {ROLE_EMOJIS.get(p.role,'')} {ROLE_NAMES_UZ.get(p.role,'')}"

    winners_list = "\n".join(_fmt(p) for p in winners) or "  —"
    losers_list = "\n".join(_fmt(p) for p in losers) or "  —"

    WIN_REWARD = 30
    win_rewards: dict = {}
    for p in winners:
        subscribed = await _is_subscribed_to_promo_channel(bot, p.user_id)
        reward = WIN_REWARD * 2 if subscribed else WIN_REWARD
        win_rewards[p.user_id] = reward
        record_win(p.user_id, dollar_reward=reward)

    reward_text = f"\n💵 *G'oliblarga mukofot berildi!*" if winners else ""

    newgame_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎮 Yangi o'yin boshlash", callback_data=f"newgame_btn:{game.chat_id}")]
    ])

    await bot.send_message(
        game.chat_id,
        f"{em} *O'YIN TUGADI!*\n\n{text}\n\n"
        f"🏆 *G'oliblar:*\n{winners_list}\n\n"
        f"💀 *Mag'lublar:*\n{losers_list}{reward_text}",
        reply_markup=newgame_kb,
    )

    for p in winners:
        reward = win_rewards.get(p.user_id, WIN_REWARD)
        bonus_note = " (2x kanal bonusi bilan!)" if reward > WIN_REWARD else ""
        await _dm(bot, p.user_id,
            f"🎉 Siz {reward}$ yutdingiz!{bonus_note}\n\n"
            + _profile_text(p.user_id, p.first_name))
    for p in losers:
        await _dm(bot, p.user_id,
            "😔 Siz yutqazdingiz.\n\n" + _profile_text(p.user_id, p.first_name))

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
    secs = get_settings(chat_id).night_secs
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
                f"🤵🏻 *Don:* o'ldirish uchun o'yinchini tanlang ({secs}s):", kb)

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
                f"🤵🏼 Nishon tanlang ({secs}s):", kb)

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
                f"🥷 Nishon tanlang — ⚠️ Komissarni tanlasangiz, u sizni o'ldiradi! ({secs}s):", kb)

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
                    f"👨🏼‍💼 Komissardan himoya qilish uchun Mafiya a'zosini tanlang ({secs}s):", kb)

        elif role == Role.JURNALIST:
            kb = _target_kb(game, "njurn", actor_id=uid)
            allies = [p.display_name for p in alive if p.role in MAFIA_TEAM]
            ally_txt = f"\n🤝 Mafiya jamoasi: {', '.join(allies)}" if allies else ""
            await _dm(bot, uid,
                f"🌙 *{game.day_number}-kecha*{ally_txt}\n\n"
                f"👩🏼‍💻 Intervyu olish uchun o'yinchini tanlang ({secs}s):", kb)

        elif role == Role.KOMISSAR:
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="🔍 Tekshirish", callback_data=f"nkommode:check:{chat_id}"),
                InlineKeyboardButton(text="🔫 O'ldirish", callback_data=f"nkommode:kill:{chat_id}"),
            ]])
            await _dm(bot, uid,
                f"🌙 *{game.day_number}-kecha*\n\n"
                f"🕵🏼 Bu kecha nima qilasiz ({secs}s)?", kb)

        elif role == Role.SERZHANT and not game.get_alive_by_role(Role.KOMISSAR):
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="🔍 Tekshirish", callback_data=f"nkommode:check:{chat_id}"),
                InlineKeyboardButton(text="🔫 O'ldirish", callback_data=f"nkommode:kill:{chat_id}"),
            ]])
            await _dm(bot, uid,
                f"🌙 *{game.day_number}-kecha*\n\n"
                f"👮🏼 Siz hozir Komissar vazifasini bajaryapsiz. Nima qilasiz ({secs}s)?", kb)

        elif role == Role.LABARANT:
            kb = _target_kb(game, "nlab", actor_id=uid)
            await _dm(bot, uid,
                f"🌙 *{game.day_number}-kecha*\n\n"
                f"🧪 O'yinchi tanlang — Mafiya bo'lsa himoya qilasiz, boshqa bo'lsa zaharlaysiz ({secs}s):", kb)

        elif role == Role.DOCTOR:
            kb = _target_kb(game, "ndoc", actor_id=uid, include_self=True)
            await _dm(bot, uid,
                f"🌙 *{game.day_number}-kecha*\n\n"
                f"💊 Himoya qilish uchun o'yinchini tanlang (o'zingizni ham) ({secs}s):", kb)

        elif role == Role.KEZUVCHI:
            kb = _target_kb(game, "nkez", actor_id=uid)
            await _dm(bot, uid,
                f"🌙 *{game.day_number}-kecha*\n\n"
                f"💃 Uyqu dori berish uchun o'yinchini tanlang — u bu kecha harakatsiz ({secs}s):", kb)

        elif role == Role.DAYDI:
            kb = _target_kb(game, "nday", actor_id=uid)
            await _dm(bot, uid,
                f"🌙 *{game.day_number}-kecha*\n\n"
                f"🧙‍♂️ Tashrif buyurish uchun o'yinchini tanlang ({secs}s):", kb)

        elif role == Role.QOTIL:
            kb = _target_kb(game, "nqot", actor_id=uid)
            await _dm(bot, uid,
                f"🌙 *{game.day_number}-kecha*\n\n"
                f"🔪 O'ldirish uchun nishon tanlang ({secs}s):", kb)

        elif role == Role.KIMYOGAR:
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="🩺 Davolash", callback_data=f"nkimmode:heal:{chat_id}"),
                InlineKeyboardButton(text="☠️ O'ldirish", callback_data=f"nkimmode:kill:{chat_id}"),
            ]])
            await _dm(bot, uid,
                f"🌙 *{game.day_number}-kecha*\n\n"
                f"👨‍🔬 Bu kecha nima qilasiz ({secs}s)?", kb)

        elif role == Role.MINIOR:
            kb = _target_kb(game, "nmin", actor_id=uid)
            await _dm(bot, uid,
                f"🌙 *{game.day_number}-kecha*\n\n"
                f"☠️ Mina qo'yish uchun o'yinchini tanlang ({secs}s):", kb)

        elif role == Role.AFERIST:
            kb = _target_kb(game, "nafer", actor_id=uid)
            await _dm(bot, uid,
                f"🌙 *{game.day_number}-kecha*\n\n"
                f"🤹🏻 Kimning ovoz berish shaxsini almashtirmoqchisiz ({secs}s)?", kb)

        elif role == Role.GAZABKOR:
            kb = _target_kb(game, "ngaz", actor_id=uid, include_self=True)
            count = len(player.gazabkor_targets)
            await _dm(bot, uid,
                f"🌙 *{game.day_number}-kecha*\n\n"
                f"🧟 Ro'yxatga o'yinchi qo'shing (hozir *{count}* ta). "
                f"O'zingizni tanlasangiz, barchasi o'ladi (g'alaba uchun kamida 3 ta) ({secs}s):", kb)

        elif role == Role.JOKER:
            kb = _target_kb(game, "njok", actor_id=uid)
            await _dm(bot, uid,
                f"🌙 *{game.day_number}-kecha*\n\n"
                f"🤡 Kimga 4 ta karta yuborasiz? (25% o'lim ehtimoli) ({secs}s):", kb)

        elif role == Role.SOTQIN:
            suspects = [p for p in alive if p.role in (Role.DON, Role.MAFIA, Role.QOTIL)]
            if suspects:
                rows = [
                    [InlineKeyboardButton(text=p.display_name, callback_data=f"nsot:{p.user_id}:{chat_id}")]
                    for p in suspects
                ] + [[InlineKeyboardButton(text="⏭️ O'tkazib yuborish", callback_data=f"nsot:0:{chat_id}")]]
                await _dm(bot, uid,
                    f"🌙 *{game.day_number}-kecha*\n\n"
                    f"🤓 Kimni fosh qilmoqchisiz ({secs}s)?",
                    InlineKeyboardMarkup(inline_keyboard=rows))
            else:
                game.night_actions[Role.SOTQIN] = 0
                await _dm(bot, uid,
                    f"🌙 *{game.day_number}-kecha*\n\n🤓 Fosh qilish uchun ma'lum nishon yo'q.")

        elif role == Role.TULKI:
            kb = _target_kb(game, "ntulki", actor_id=uid)
            await _dm(bot, uid,
                f"🌙 *{game.day_number}-kecha*\n\n"
                f"🦊 Nishon tanlang — uning jamoasiga qarab siz o'zgarasiz ({secs}s):", kb)

        elif role == Role.KONCHI:
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
            game.konchi_rewards[uid] = rewards
            buttons = [
                InlineKeyboardButton(text=str(n), callback_data=f"nkonchi:{n}:{chat_id}")
                for n in nums
            ]
            kb = InlineKeyboardMarkup(inline_keyboard=[buttons[:5], buttons[5:]])
            await _dm(bot, uid,
                f"🌙 *{game.day_number}-kecha*\n\n"
                f"⛏️ *Konchi:* kon qazing! 10 ta raqam ichida 💎 3 olmos, 💣 2 mina, 💵 5 pul slot bor.\n"
                f"Bir raqam tanlang ({secs}s) — xohlasangiz o'tkazib yuboring:", kb)

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
async def cmd_start(msg: Message, bot: Bot):
    if msg.chat.type == "private":
        group_kb = None
        parts = (msg.text or "").split(maxsplit=1)
        if len(parts) > 1 and parts[1].startswith("group_"):
            try:
                gid = int(parts[1].split("_", 1)[1])
                link = await _group_link(bot, gid)
                if link:
                    group_kb = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="👥 Guruhga qaytish", url=link)]
                    ])
            except Exception:
                pass
        await msg.answer(
            "👋 Salom! Men *Mafiya O'yin Boti*man.\n\n"
            "Meni guruh chatiga qo'shing va /game bilan ro'yxatdan o'tishni boshlang!\n\n"
            "*Buyruqlar:*\n"
            "/game — Yangi o'yin lobby'si (ro'yxatdan o'tish)\n"
            "/join — Lobbyga qo'shilish\n"
            "/leave — Lobbydan chiqish\n"
            "/start — O'yinni boshlash (guruhda, admin)\n"
            "/endgame — O'yinni tugatish (admin)\n"
            "/players — O'yinchilar ro'yxati\n"
            "/profile — Profilingiz\n"
            "/give N — Guruhga N olmos tashlash (har kim 1 tadan oladi)\n"
            "/money N — Guruhga N$ tashlash (har kim ulush oladi)\n"
            "/shop — Do'kon\n"
            "/roleshop — Rol do'koni\n"
            "/sozlash — Guruh sozlamalari (admin)\n"
            "/kanal — Reklama kanalini sozlash (bot egasi)\n"
            "/stats — Statistika\n"
            "/rules — Qoidalar\n"
            "/roles — Barcha rollar haqida",
            reply_markup=group_kb,
        )
        return

    # Group chat: /start now launches the game (previously /startgame)
    await _launch_game(msg, bot)


async def _open_lobby(msg: Message, bot: Bot):
    """Registration: create/open the join lobby for a new game."""
    if msg.chat.type == "private":
        return await msg.answer("⚠️ Bu buyruq faqat guruh chatlarda ishlaydi.")

    chat_id = msg.chat.id
    existing = games.get(chat_id)
    if existing and existing.phase not in (Phase.LOBBY, Phase.ENDED):
        return await msg.answer(
            "⚠️ O'yin allaqachon davom etmoqda!\n"
            "Yangi ro'yxat ochish uchun avval /endgame bilan tugatish kerak."
        )

    games[chat_id] = Game(chat_id=chat_id)
    game = games[chat_id]
    user = msg.from_user
    game.add_player(user.id, user.username or "", user.first_name)

    bot_username = await _get_bot_username(bot)
    await msg.answer(
        f"🎮 *RO'YXATDAN O'TISH BOSHLANDI!*\n\n"
        f"👤 *{escape_md(user.first_name)}* o'yinni yaratdi.\n\n"
        "Quyidagi tugmani bosib qo'shiling!\n"
        "Tayyor bo'lganda admin /start bossin.\n\n"
        f"*O'yinchilar ({len(game.players)}/{MIN_PLAYERS} min):*\n"
        f"{_player_list(game)}",
        reply_markup=_lobby_kb(chat_id, bot_username),
    )


@router.message(Command("game"))
async def cmd_game(msg: Message, bot: Bot):
    await _open_lobby(msg, bot)


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
        "🔵 *Fuqarolar jamoasi:*": [Role.KOMISSAR, Role.DOCTOR, Role.SERZHANT, Role.CITIZEN,
                                    Role.DAYDI, Role.KEZUVCHI, Role.OMADLI, Role.ADMIRAL, Role.SOTQIN,
                                    Role.KONCHI],
        "⚪ *Mustaqil rollar:*": [Role.QOTIL, Role.BO_RI, Role.AFSUNGAR, Role.AFERIST,
                                  Role.SEHRGAR, Role.GAZABKOR, Role.JOKER, Role.KIMYOGAR, Role.MINIOR,
                                  Role.TULKI],
    }
    for label, roles in teams.items():
        lines = [label]
        for r in roles:
            desc_short = ROLE_DESCRIPTIONS_UZ[r].split("\n")[0]
            lines.append(f"{ROLE_EMOJIS[r]} *{ROLE_NAMES_UZ[r]}* — _{desc_short}_")
        await msg.answer("\n".join(lines))


@router.message(Command("newgame"))
async def cmd_newgame(msg: Message, bot: Bot):
    await _open_lobby(msg, bot)


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


@router.message(Command("leave"))
async def cmd_leave(msg: Message):
    if msg.chat.type == "private":
        return await msg.answer("⚠️ Bu buyruq faqat guruh chatlarda ishlaydi.")

    chat_id = msg.chat.id
    settings = get_settings(chat_id)
    if not settings.leave_enabled:
        return await msg.answer("⚠️ Bu guruhda /leave o'chirilgan.")

    game = games.get(chat_id)
    if not game or game.phase == Phase.ENDED:
        return await msg.answer("⚠️ Bu chatda faol lobby yo'q.")
    if game.phase != Phase.LOBBY:
        return await msg.answer("⚠️ O'yin boshlangandan keyin chiqib bo'lmaydi.")

    user = msg.from_user
    if user.id not in game.players:
        return await msg.answer("⚠️ Siz lobbyda emassiz.")

    game.remove_player(user.id)
    await msg.answer(
        f"👋 *{escape_md(user.first_name)}* lobbydan chiqdi.\n\n"
        f"*O'yinchilar ({len(game.players)}/{MIN_PLAYERS} min):*\n"
        f"{_player_list(game)}",
        reply_markup=_lobby_kb(chat_id),
    )


TOGGLEABLE_ROLES = [
    r for r in Role if r not in (Role.CITIZEN, Role.DON, Role.MAFIA)
]

DURATION_OPTIONS = [15, 30, 45, 60, 90]


def _sozlash_main_kb(chat_id: int, settings: ChatSettings) -> InlineKeyboardMarkup:
    leave_label = "✅ /leave yoqilgan" if settings.leave_enabled else "❌ /leave o'chirilgan"
    protect_label = "✅ Himoya buyumlari yoqilgan" if settings.protection_enabled else "❌ Himoya buyumlari o'chirilgan"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🃏 Rollarni yoqish/o'chirish", callback_data=f"soz:roles:0:{chat_id}")],
        [InlineKeyboardButton(text=leave_label, callback_data=f"soz:toggle_leave:{chat_id}")],
        [InlineKeyboardButton(text=protect_label, callback_data=f"soz:toggle_protect:{chat_id}")],
        [InlineKeyboardButton(text="⏳ Vaqtlarni sozlash", callback_data=f"soz:durations:{chat_id}")],
        [InlineKeyboardButton(text="✅ Yopish", callback_data=f"soz:close:{chat_id}")],
    ])


def _sozlash_roles_kb(chat_id: int, settings: ChatSettings, page: int = 0) -> InlineKeyboardMarkup:
    per_page = 8
    start = page * per_page
    roles_page = TOGGLEABLE_ROLES[start:start + per_page]
    rows = []
    for r in roles_page:
        disabled = r.name in settings.disabled_roles
        label = f"❌ {ROLE_NAMES_UZ.get(r, r.value)}" if disabled else f"✅ {ROLE_NAMES_UZ.get(r, r.value)}"
        rows.append([InlineKeyboardButton(text=label, callback_data=f"soz:role:{r.name}:{page}:{chat_id}")])

    nav = []
    if start > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"soz:roles:{page-1}:{chat_id}"))
    if start + per_page < len(TOGGLEABLE_ROLES):
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"soz:roles:{page+1}:{chat_id}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="🔙 Orqaga", callback_data=f"soz:main:{chat_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _sozlash_durations_kb(chat_id: int, settings: ChatSettings) -> InlineKeyboardMarkup:
    def _row(field, label, current):
        return [InlineKeyboardButton(
            text=f"{v}s{' ✅' if v == current else ''}",
            callback_data=f"soz:set:{field}:{v}:{chat_id}",
        ) for v in DURATION_OPTIONS]

    rows = [
        [InlineKeyboardButton(text="🌙 Kecha vaqti", callback_data="noop")],
        _row("night_secs", "Kecha", settings.night_secs),
        [InlineKeyboardButton(text="☀️ Kunduz vaqti", callback_data="noop")],
        _row("day_secs", "Kunduz", settings.day_secs),
        [InlineKeyboardButton(text="🗳️ Ovoz vaqti", callback_data="noop")],
        _row("vote_secs", "Ovoz", settings.vote_secs),
        [InlineKeyboardButton(text="🔙 Orqaga", callback_data=f"soz:main:{chat_id}")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _require_admin(msg_or_call, bot: Bot, chat_id: int, user_id: int) -> bool:
    member = await bot.get_chat_member(chat_id, user_id)
    return member.status in ("administrator", "creator")


@router.message(Command("sozlash"))
async def cmd_sozlash(msg: Message, bot: Bot):
    if msg.chat.type == "private":
        return await msg.answer("⚠️ Bu buyruq faqat guruh chatlarda ishlaydi.")

    chat_id = msg.chat.id
    if not await _require_admin(msg, bot, chat_id, msg.from_user.id):
        return await msg.answer("⚠️ Faqat adminlar sozlashlarni o'zgartira oladi.")

    settings = get_settings(chat_id)
    await msg.answer(
        "⚙️ *Guruh sozlamalari*\n\nQuyidagilardan birini tanlang:",
        reply_markup=_sozlash_main_kb(chat_id, settings),
    )


@router.callback_query(F.data.startswith("soz:"))
async def cb_sozlash(call: CallbackQuery):
    parts = call.data.split(":")
    action = parts[1]
    chat_id = int(parts[-1])

    if not await _require_admin(call, call.bot, chat_id, call.from_user.id):
        return await call.answer("⚠️ Faqat adminlar uchun.", show_alert=True)

    settings = get_settings(chat_id)

    if action == "main":
        await call.message.edit_text(
            "⚙️ *Guruh sozlamalari*\n\nQuyidagilardan birini tanlang:",
            reply_markup=_sozlash_main_kb(chat_id, settings),
        )

    elif action == "close":
        await call.message.edit_text("⚙️ Sozlamalar yopildi.")

    elif action == "roles":
        page = int(parts[2])
        await call.message.edit_text(
            "🃏 *Rollarni yoqish/o'chirish*\n\nBosilganda holat o'zgaradi:",
            reply_markup=_sozlash_roles_kb(chat_id, settings, page),
        )

    elif action == "role":
        role_val, page = parts[2], int(parts[3])
        if role_val in settings.disabled_roles:
            settings.disabled_roles.remove(role_val)
        else:
            settings.disabled_roles.append(role_val)
        save_settings(settings)
        await call.message.edit_text(
            "🃏 *Rollarni yoqish/o'chirish*\n\nBosilganda holat o'zgaradi:",
            reply_markup=_sozlash_roles_kb(chat_id, settings, page),
        )

    elif action == "toggle_leave":
        settings.leave_enabled = not settings.leave_enabled
        save_settings(settings)
        await call.message.edit_text(
            "⚙️ *Guruh sozlamalari*\n\nQuyidagilardan birini tanlang:",
            reply_markup=_sozlash_main_kb(chat_id, settings),
        )

    elif action == "toggle_protect":
        settings.protection_enabled = not settings.protection_enabled
        save_settings(settings)
        await call.message.edit_text(
            "⚙️ *Guruh sozlamalari*\n\nQuyidagilardan birini tanlang:",
            reply_markup=_sozlash_main_kb(chat_id, settings),
        )

    elif action == "durations":
        await call.message.edit_text(
            "⏳ *Bosqich vaqtlarini sozlash*",
            reply_markup=_sozlash_durations_kb(chat_id, settings),
        )

    elif action == "set":
        field, value = parts[2], int(parts[3])
        setattr(settings, field, value)
        save_settings(settings)
        await call.message.edit_text(
            "⏳ *Bosqich vaqtlarini sozlash*",
            reply_markup=_sozlash_durations_kb(chat_id, settings),
        )

    await call.answer()


@router.callback_query(F.data == "noop")
async def cb_noop(call: CallbackQuery):
    await call.answer()


def _assign_roles_with_preferences(game: Game, disabled_roles: list = None):
    """Assign roles, honoring active_role preferences from player profiles."""
    import random
    from game import get_role_list
    players = list(game.players.values())
    role_pool = get_role_list(len(players), disabled_roles=disabled_roles)

    assigned: dict[int, Role] = {}
    remaining = list(role_pool)

    for player in players:
        prof = get_profile(player.user_id)
        for key in list(prof.active_roles):
            key = ROLE_KEY_ALIASES.get(key, key)
            item = PURCHASABLE_ROLES.get(key)
            if not item:
                continue
            desired_role = item[0]
            if desired_role in remaining:
                assigned[player.user_id] = desired_role
                remaining.remove(desired_role)
                prof.active_roles.remove(key if key in prof.active_roles else key)
                save_profile(prof)
                break

    random.shuffle(remaining)
    pool_iter = iter(remaining)
    for player in players:
        if player.user_id in assigned:
            player.role = assigned[player.user_id]
        else:
            player.role = next(pool_iter)


async def _launch_game(msg: Message, bot: Bot):
    """Starts the actual game from an open lobby (was /startgame)."""
    chat_id = msg.chat.id
    game = games.get(chat_id)
    if not game or game.phase == Phase.ENDED:
        return await msg.answer("⚠️ Faol lobby yo'q. /game dan foydalaning.")
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

    game.group_link = await _group_link(bot, chat_id)

    disabled_roles = get_settings(chat_id).disabled_roles
    _assign_roles_with_preferences(game, disabled_roles=disabled_roles)
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

    group_kb = None
    if game.group_link:
        group_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👥 Guruhga qaytish", url=game.group_link)]
        ])

    mafia_names = ", ".join(
        p.display_name for p in game.players.values() if p.role in MAFIA_TEAM
    )
    for player in game.players.values():
        em   = ROLE_EMOJIS[player.role]
        name = ROLE_NAMES_UZ[player.role]
        desc = ROLE_DESCRIPTIONS_UZ[player.role]
        extra = f"\n\n🤝 *Mafiya jamoangiz:* {mafia_names}" if player.role in MAFIA_TEAM else ""
        await _dm(bot, player.user_id,
            f"🎭 *Sizning rolingiz: {em} {name}*\n\n{desc}{extra}\n\nO'yin boshlandi!", group_kb)

    asyncio.create_task(run_night(bot, chat_id))


@router.message(Command("startgame"))
async def cmd_startgame(msg: Message, bot: Bot):
    if msg.chat.type == "private":
        return await msg.answer("⚠️ Bu buyruq faqat guruh chatlarda ishlaydi.")
    await _launch_game(msg, bot)


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


async def _is_subscribed_to_promo_channel(bot: Bot, user_id: int) -> bool:
    channel = get_promo_channel()
    if not channel:
        return False
    try:
        member = await bot.get_chat_member(channel, user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception:
        return False


def _promo_text() -> str:
    channel = get_promo_channel()
    if not channel:
        return ""
    link = channel if channel.startswith("http") or channel.startswith("@") else f"@{channel}"
    return f"\n\n📢 *{escape_md(link)}* kanaliga a'zo bo'ling va mukofotlaringiz *2x* bo'lsin!"


@router.message(Command("kanal"))
async def cmd_kanal(msg: Message):
    if msg.from_user.id != OWNER_ID:
        return await msg.answer("⚠️ Bu buyruqni faqat bot egasi ishlatishi mumkin.")

    parts = msg.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        current = get_promo_channel()
        return await msg.answer(
            f"📢 Hozirgi reklama kanali: *{escape_md(current) if current else 'o‘rnatilmagan'}*\n\n"
            "O'rnatish uchun: `/kanal @username` yoki `/kanal https://t.me/...`"
        )

    channel = parts[1].strip()
    set_promo_channel(channel)
    await msg.answer(f"✅ Reklama kanali o'rnatildi: *{escape_md(channel)}*")


def _profile_text(user_id: int, first_name: str) -> str:
    p = get_profile(user_id, first_name)
    diamond_str = "♾️" if p.infinite_diamond else str(p.diamond)
    dollar_str = "♾️" if p.infinite_dollar else f"{p.dollar}$"
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

    return (
        f"👤 *{escape_md(first_name)}*\n\n"
        f"💵 Dollar: *{dollar_str}*\n"
        f"💎 Olmos: *{diamond_str}*\n\n"
        f"🎯 G'alabalar: *{p.wins}*\n"
        f"🎲 Jami o'yinlar: *{p.games}*\n"
        f"📈 G'alaba foizi: *{win_rate}*\n\n"
        f"🎒 *Inventar:*\n{items_str}\n\n"
        f"🃏 Faol rollar: {roles_str}"
    ) + _promo_text()


@router.message(Command("profile"))
async def cmd_profile(msg: Message):
    user = msg.from_user
    await msg.answer(_profile_text(user.id, user.first_name))


@router.message(Command("give"))
async def cmd_give(msg: Message):
    if msg.chat.type == "private":
        return await msg.answer("⚠️ Bu buyruq faqat guruhda ishlaydi.")

    giver = msg.from_user
    parts = msg.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        return await msg.answer("❌ Miqdor kiriting. Masalan: `/give 10`")

    amount = int(parts[1])
    if amount <= 0:
        return await msg.answer("❌ Miqdor musbat son bo'lishi kerak.")

    giver_p = get_profile(giver.id, giver.first_name)
    if not giver_p.infinite_diamond and giver_p.diamond < amount:
        return await msg.answer(f"❌ Yetarli olmos yo'q. Sizda: *{giver_p.diamond}* 💎")

    if not giver_p.infinite_diamond:
        giver_p.diamond -= amount
        save_profile(giver_p)

    game = games.get(msg.chat.id)
    if game is None:
        game = Game(chat_id=msg.chat.id)
        games[msg.chat.id] = game
    drop_id = f"{msg.message_id}"
    game.give_drops[drop_id] = {"remaining": amount, "claimed": set(), "giver": giver.id}

    await msg.answer(
        f"💎 *{escape_md(giver.first_name)}* *{amount}* olmos tashladi!\n\n"
        f"Har bir o'yinchi faqat *1 marta* bosib, *1 olmos* olishi mumkin.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="💎 Olish", callback_data=f"claimdiamond:{drop_id}:{msg.chat.id}")
        ]]),
    )


@router.callback_query(F.data.startswith("claimdiamond:"))
async def cb_claim_diamond(call: CallbackQuery):
    _, drop_id, cid = call.data.split(":")
    cid = int(cid)
    game = games.get(cid)
    if not game or drop_id not in game.give_drops:
        return await call.answer("⚠️ Bu tashlama endi faol emas.", show_alert=True)

    drop = game.give_drops[drop_id]
    user = call.from_user
    if user.id == drop["giver"]:
        return await call.answer("❌ O'zingiz tashlagan narsani ololmaysiz.", show_alert=True)
    if user.id in drop["claimed"]:
        return await call.answer("⚠️ Siz allaqachon oldingiz!", show_alert=True)
    if drop["remaining"] <= 0:
        return await call.answer("⚠️ Olmoslar tugadi.", show_alert=True)

    drop["claimed"].add(user.id)
    drop["remaining"] -= 1
    get_profile(user.id, user.first_name)
    add_diamond(user.id, 1)
    await call.answer("✅ Siz 1 olmos oldingiz!", show_alert=True)

    if drop["remaining"] <= 0:
        try:
            await call.message.edit_text(f"💎 Olmoslar tugadi! Barchasi tarqatildi.")
        except Exception:
            pass
        del game.give_drops[drop_id]


@router.message(Command("money"))
async def cmd_money(msg: Message):
    if msg.chat.type == "private":
        return await msg.answer("⚠️ Bu buyruq faqat guruhda ishlaydi.")

    giver = msg.from_user
    parts = msg.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        return await msg.answer("❌ Miqdor kiriting. Masalan: `/money 50`")

    amount = int(parts[1])
    if amount <= 0:
        return await msg.answer("❌ Miqdor musbat son bo'lishi kerak.")

    giver_p = get_profile(giver.id, giver.first_name)
    if not giver_p.infinite_dollar and giver_p.dollar < amount:
        return await msg.answer(f"❌ Yetarli pul yo'q. Sizda: *{giver_p.dollar}$*")

    if not giver_p.infinite_dollar:
        giver_p.dollar -= amount
        save_profile(giver_p)

    per_claim = 10 if amount <= 100 else 100

    game = games.get(msg.chat.id)
    if game is None:
        game = Game(chat_id=msg.chat.id)
        games[msg.chat.id] = game
    drop_id = f"{msg.message_id}"
    game.money_drops[drop_id] = {"per_claim": per_claim, "claimed": set(), "giver": giver.id, "pool": amount}

    await msg.answer(
        f"💵 *{escape_md(giver.first_name)}* *{amount}$* tashladi!\n\n"
        f"Har bir o'yinchi bosib *{per_claim}$* olishi mumkin (faqat 1 marta).",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="💵 Olish", callback_data=f"claimmoney:{drop_id}:{msg.chat.id}")
        ]]),
    )


@router.callback_query(F.data.startswith("claimmoney:"))
async def cb_claim_money(call: CallbackQuery):
    _, drop_id, cid = call.data.split(":")
    cid = int(cid)
    game = games.get(cid)
    if not game or drop_id not in game.money_drops:
        return await call.answer("⚠️ Bu tashlama endi faol emas.", show_alert=True)

    drop = game.money_drops[drop_id]
    user = call.from_user
    if user.id == drop["giver"]:
        return await call.answer("❌ O'zingiz tashlagan narsani ololmaysiz.", show_alert=True)
    if user.id in drop["claimed"]:
        return await call.answer("⚠️ Siz allaqachon oldingiz!", show_alert=True)

    drop["claimed"].add(user.id)
    get_profile(user.id, user.first_name)
    add_dollar(user.id, drop["per_claim"])
    await call.answer(f"✅ Siz {drop['per_claim']}$ oldingiz!", show_alert=True)


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
        return await msg.answer(f"⚠️ *{escape_md(target.first_name)}* bu o'yinda emas.")

    if game.phase == Phase.LOBBY:
        game.remove_player(target.id)
        await msg.answer(f"👢 *{escape_md(target.first_name)}* lobbydan chiqarildi.")
    else:
        game.eliminate_player(target.id)
        tp = game.get_player_by_id(target.id)
        role_str = ""
        if tp and tp.role:
            role_str = f" Roli: {ROLE_EMOJIS.get(tp.role,'')} {ROLE_NAMES_UZ.get(tp.role,'')}"
        await msg.answer(f"👢 *{escape_md(target.first_name)}* admin tomonidan chiqarildi.{role_str}")
        winner = game.check_win_condition()
        if winner:
            asyncio.create_task(_end_game(bot, game, winner))


PURCHASABLE_ROLES = {
    "don":       (Role.DON,       "🤵🏻", "Don",           2),
    "qotil":     (Role.QOTIL,     "🔪",  "Qotil",         2),
    "sehrgar":   (Role.SEHRGAR,   "🧙‍",  "Sehrgar",       2),
    "komissar":  (Role.KOMISSAR,  "🕵🏼", "Komissar",      2),
    "doctor":    (Role.DOCTOR,    "👨🏼‍⚕️", "Doktor",       1),
    "joker":     (Role.JOKER,     "🤡",  "Joker",         1),
    "bori":      (Role.BO_RI,     "🐺",  "Bo'ri",         1),
    "kimyogar":  (Role.KIMYOGAR,  "👨‍🔬", "Kimyogar",      1),
    "afsungar":  (Role.AFSUNGAR,  "💣",  "Afsungar",      1),
    "omadli":    (Role.OMADLI,    "🤞🏼", "Omadli",        1),
}

ROLE_KEY_ALIASES = {
    "killer": "qotil", "detective": "komissar",
    "beast": "bori",   "wizard": "sehrgar",
}


def _role_shop_kb() -> InlineKeyboardMarkup:
    rows = []
    for key, (role, em, name, price) in PURCHASABLE_ROLES.items():
        rows.append([InlineKeyboardButton(
            text=f"{em} {name} — {price}💎",
            callback_data=f"role_{key}",
        )])
    rows.append([InlineKeyboardButton(text="👤 Faol rollarim", callback_data="role_mylist")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("roleshop"))
async def cmd_roleshop(msg: Message):
    user = msg.from_user
    p = get_profile(user.id, user.first_name)
    diamond_str = "♾️" if p.infinite_diamond else str(p.diamond)
    active = ", ".join(p.active_roles) if p.active_roles else "Yo'q"
    await msg.answer(
        f"🃏 *FAOL ROL DO'KONI*\n\n"
        f"💎 Olmoslaringiz: *{diamond_str}*\n"
        f"🎯 Faol rollaringiz: *{active}*\n\n"
        "Kerakli rolni tanlang — keyingi o'yinda shu rol beriladi!\n"
        "_(Rol faqat bir marta ishlatiladi va o'yindan keyin o'chadi)_",
        reply_markup=_role_shop_kb(),
    )


@router.callback_query(F.data.startswith("role_"))
async def cb_role_buy(call: CallbackQuery):
    key = call.data.removeprefix("role_")

    if key == "mylist":
        p = get_profile(call.from_user.id, call.from_user.first_name)
        active = "\n".join(
            f"  {PURCHASABLE_ROLES[k][1]} {PURCHASABLE_ROLES[k][2]}"
            for k in p.active_roles if k in PURCHASABLE_ROLES
        ) or "  Hech narsa yo'q"
        return await call.answer(f"🎯 Faol rollaringiz:\n{active}", show_alert=True)

    key = ROLE_KEY_ALIASES.get(key, key)
    item = PURCHASABLE_ROLES.get(key)
    if not item:
        return await call.answer("❌ Rol topilmadi.", show_alert=True)

    role_enum, em, name, price = item
    uid = call.from_user.id
    p = get_profile(uid, call.from_user.first_name)

    if not p.infinite_diamond and p.diamond < price:
        return await call.answer(
            f"❌ Yetarli olmos yo'q!\n{em} {name} — {price}💎\nSizda: {p.diamond}💎",
            show_alert=True,
        )

    if key in p.active_roles:
        return await call.answer(
            f"⚠️ Sizda allaqachon {em} {name} roli bor!", show_alert=True
        )

    if not p.infinite_diamond:
        p.diamond -= price
    p.active_roles.append(key)
    save_profile(p)

    diamond_str = "♾️" if p.infinite_diamond else str(p.diamond)
    await call.answer(f"✅ {em} {name} roli sotib olindi!", show_alert=True)
    try:
        await call.message.edit_text(
            f"🃏 *FAOL ROL DO'KONI*\n\n"
            f"💎 Olmoslaringiz: *{diamond_str}*\n"
            f"🎯 Faol rollaringiz: *{', '.join(p.active_roles)}*\n\n"
            f"✅ *{em} {name}* muvaffaqiyatli qo'shildi!\n"
            "_(Keyingi o'yinda shu rol beriladi)_",
            reply_markup=_role_shop_kb(),
        )
    except Exception:
        pass


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


@router.callback_query(F.data.startswith("buy_"))
async def cb_buy_prefix(call: CallbackQuery):
    key = call.data.removeprefix("buy_")
    call.data = f"shop_buy:{key}"
    await cb_shop_buy(call)


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
        f"👤 *{escape_md(call.from_user.first_name)}*\n\n"
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


# ──────────────────────────────────────────────
# Callback handlers
# ──────────────────────────────────────────────

@router.callback_query(F.data.startswith("newgame_btn:"))
async def cb_newgame_btn(call: CallbackQuery, bot: Bot):
    chat_id = int(call.data.split(":")[1])
    existing = games.get(chat_id)
    if existing and existing.phase not in (Phase.LOBBY, Phase.ENDED):
        return await call.answer("⚠️ O'yin allaqachon davom etmoqda!", show_alert=True)

    games[chat_id] = Game(chat_id=chat_id)
    game = games[chat_id]
    user = call.from_user
    game.add_player(user.id, user.username or "", user.first_name)

    await call.answer("✅ Yangi lobby ochildi!")
    bot_username = await _get_bot_username(bot)
    await bot.send_message(
        chat_id,
        f"🎮 *RO'YXATDAN O'TISH BOSHLANDI!*\n\n"
        f"👤 *{escape_md(user.first_name)}* o'yinni yaratdi.\n\n"
        "Quyidagi tugmani bosib qo'shiling!\n"
        "Tayyor bo'lganda admin /start bossin.\n\n"
        f"*O'yinchilar ({len(game.players)}/{MIN_PLAYERS} min):*\n"
        f"{_player_list(game)}",
        reply_markup=_lobby_kb(chat_id, bot_username),
    )


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


@router.callback_query(F.data.startswith("nkommode:"))
async def cb_nkommode(call: CallbackQuery):
    _, mode, cid = call.data.split(":")
    cid = int(cid)
    game = games.get(cid)
    if not game or game.phase != Phase.NIGHT:
        return await call.answer("⚠️ Kecha tugagan.", show_alert=True)
    game.night_actions["komissar_mode"] = mode
    actor = game.get_player_by_id(call.from_user.id)
    kb = _target_kb(game, "nkom", actor_id=actor.user_id if actor else None)
    if mode == "kill":
        text = "🔫 *O'ldirish* uchun o'yinchini tanlang:"
    else:
        text = "🔍 *Tekshirish* uchun o'yinchini tanlang:"
    await call.message.edit_text(text, reply_markup=kb)
    await call.answer()


@router.callback_query(F.data.startswith("nkom:"))
async def cb_nkom(call: CallbackQuery):
    _, tid, cid = call.data.split(":")
    game = games.get(int(cid))
    if not game or game.phase != Phase.NIGHT:
        return await call.answer("⚠️ Kecha tugagan.", show_alert=True)
    key = Role.KOMISSAR if game.get_alive_by_role(Role.KOMISSAR) else Role.SERZHANT
    mode = game.night_actions.get("komissar_mode", "check")
    confirm = "🔫 Nishon tanlandi" if mode == "kill" else "🕵🏼 Tekshirilmoqda"
    await _night_cb(call, key, int(tid), int(cid), confirm)


@router.callback_query(F.data.startswith("nlab:"))
async def cb_nlab(call: CallbackQuery):
    _, tid, cid = call.data.split(":")
    await _night_cb(call, Role.LABARANT, int(tid), int(cid), "🧪 Nishon tanlandi")


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


@router.callback_query(F.data.startswith("ntulki:"))
async def cb_ntulki(call: CallbackQuery):
    _, tid, cid = call.data.split(":")
    await _night_cb(call, Role.TULKI, int(tid), int(cid), "🦊 Nishon tanlandi")


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

@router.callback_query(F.data.startswith("hangvote:"))
async def cb_hangvote(call: CallbackQuery):
    _, choice = call.data.split(":")
    game = None
    for g in games.values():
        if g.hang_confirm_msg_id == call.message.message_id:
            game = g
            break
    if not game:
        return await call.answer("⚠️ Bu ovoz berish tugagan.", show_alert=True)

    voter = game.get_player_by_id(call.from_user.id)
    if not voter or not voter.alive:
        return await call.answer("⚠️ Siz faol o'yinchi emassiz.", show_alert=True)

    game.hang_confirm_votes[voter.user_id] = choice
    likes = sum(1 for v in game.hang_confirm_votes.values() if v == "like")
    dislikes = sum(1 for v in game.hang_confirm_votes.values() if v == "dislike")
    await call.answer(f"✅ {'👍 Like' if choice == 'like' else '👎 Dislike'} bosdingiz")
    try:
        await call.message.edit_reply_markup(
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text=f"👍 Like ({likes})", callback_data="hangvote:like"),
                InlineKeyboardButton(text=f"👎 Dislike ({dislikes})", callback_data="hangvote:dislike"),
            ]])
        )
    except Exception:
        pass


@router.callback_query(F.data.startswith("dvote:"))
async def cb_dvote(call: CallbackQuery, bot: Bot):
    _, tid, cid = call.data.split(":")
    tid, cid = int(tid), int(cid)
    game = games.get(cid)
    if not game or game.phase != Phase.VOTING:
        return await call.answer("⚠️ Ovoz berish tugagan.", show_alert=True)

    voter = game.get_player_by_id(call.from_user.id)
    if not voter or not voter.alive:
        return await call.answer("⚠️ Siz faol o'yinchi emassiz.", show_alert=True)

    if voter.user_id in game.votes:
        return await call.answer("⚠️ Siz allaqachon ovoz berdingiz! Uni o'zgartirib bo'lmaydi.", show_alert=True)

    target = game.get_player_by_id(tid)
    if not target or not target.alive:
        return await call.answer("⚠️ Bu o'yinchi mavjud emas.", show_alert=True)

    game.votes[voter.user_id] = tid
    await call.answer(f"✅ {game.get_display_name(target)}ga ovoz berdingiz! Ovozni o'zgartirib bo'lmaydi.", show_alert=True)

    try:
        await call.message.edit_text(
            f"🗳️ *Ovoz qabul qilindi!*\n\n✅ Siz *{game.get_display_name(target)}*ga ovoz berdingiz."
        )
    except Exception:
        pass

    if game.vote_msg_id:
        voted = len(game.votes)
        alive = len(game.alive_players())
        try:
            await bot.edit_message_text(
                chat_id=cid, message_id=game.vote_msg_id,
                text=(
                    f"🗳️ *OVOZ BERISH BOSHLANDI!*\n\n"
                    "Kim Mafiya ekanini shaxsiy xabarda (bot bilan) tanlang!\n"
                    "⚠️ Ovoz berilgach uni bekor qilib bo'lmaydi.\n\n"
                    f"{voted}/{alive} ovoz berdi."
                ),
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


@router.callback_query(F.data.startswith("nkonchi:"))
async def cb_nkonchi(call: CallbackQuery):
    _, num, cid = call.data.split(":")
    num, cid = int(num), int(cid)
    game = games.get(cid)
    if not game or game.phase != Phase.NIGHT:
        return await call.answer("⚠️ Kecha tugagan.", show_alert=True)

    uid = call.from_user.id
    rewards = game.konchi_rewards.get(uid)
    if not rewards:
        return await call.answer("⚠️ Bu tunda allaqachon o'ynagansiz.", show_alert=True)

    typ, amount = rewards[num]
    del game.konchi_rewards[uid]
    game.night_actions[Role.KONCHI] = num

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
        game.night_actions["konchi_mine"] = True
        p.mines += 1
        save_profile(p)
        result = "💣 *MINAGA TUSHDINGIZ!*"
        detail = "Bu kecha halok bo'lasiz..."

    all_labels = {"diamond": "💎", "money": "💵", "mine": "💣"}
    revealed = " ".join(
        f"[{all_labels[rewards[n][0]]}]" if n == num else f"[{n}]"
        for n in range(1, 11)
    )

    await call.message.edit_text(
        f"⛏️ *KONCHI KECHASI*\n\n"
        f"Siz *{num}*-raqamni tanladingiz.\n\n"
        f"{result}\n_{detail}_\n\n"
        f"{revealed}"
    )
    await call.answer(result.replace("*", ""))
