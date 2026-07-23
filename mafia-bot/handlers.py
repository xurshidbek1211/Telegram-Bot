import asyncio
import logging
import random
import time
from typing import Optional
from aiogram import Router, Bot, F
from aiogram.exceptions import TelegramRetryAfter
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
from profiles import (
    get_profile, save_profile, transfer_diamond, transfer_dollar,
    record_game_start, record_win, add_dollar, add_diamond,
    spend_dollar, spend_diamond, OWNER_ID,
)
from hero import (
    get_hero, save_hero, delete_hero,
    hero_level_threshold, hero_level_from_xp, hero_damage, hero_next_xp,
    hero_upgrade_cost,
    Hero, MAX_HP, MAX_CHARGES,
    HP_RESTORE_COST, CHARGE_RESTORE_COST, NAME_CHANGE_COST,
    HERO_BUY_COST, XP_BUY_COST, XP_BUY_AMOUNT, XP_PER_ATTACK,
    KILL_MISSIONS, LEVEL_MISSIONS, ACTIVITY_MISSIONS, check_and_award_missions,
)
from settings import get_settings, save_settings, ChatSettings
from chest import (
    ODDIY_COST, NOYOB_COST, OLTIN_COST, OLTIN_LIMIT,
    box_emoji, apply_box_reward,
    can_open_oltin, record_oltin_open,
    start_session, get_session, clear_session,
)
from bot_config import get_promo_channel, set_promo_channel
from mdutil import escape_md
from ratings import record_game_result, get_top_ratings

logger = logging.getLogger(__name__)
router = Router()

games: dict[int, Game] = {}

ROLE_NAMES_UZ = {
    Role.DON: "Don", Role.MAFIA: "Mafia",
    Role.YOLLANMA_QOTIL: "Yollanma Qotil", Role.ADVOKAT: "Advokat",
    Role.JURNALIST: "Jurnalist", Role.KOMISSAR: "Komissar Katani",
    Role.DOCTOR: "Doktor", Role.SERZHANT: "Serjant",
    Role.CITIZEN: "Tinch Aholi",
    Role.DAYDI: "Daydi", Role.KEZUVCHI: "Kezuvchi",
    Role.OMADLI: "Omadli", Role.ADMIRAL: "Admiral",
    Role.SOTQIN: "Sotqin", Role.QOTIL: "Qotil",
    Role.BO_RI: "Bo'ri",
    Role.AFSUNGAR: "Afsungar", Role.AFERIST: "Aferist",
    Role.SEHRGAR: "Sehrgar", Role.GAZABKOR: "G'azabkor",
    Role.JOKER: "Joker", Role.KIMYOGAR: "Kimyogar",
    Role.MINIOR: "Minior", Role.KONCHI: "Konchi",
    Role.TULKI: "Tulki", Role.LABARANT: "Labarant",
    Role.QAROQCHI: "Qaroqchi",
    # New roles
    Role.HAMSHIRA: "Hamshira", Role.RAIS: "Rais",
    Role.AYGOQCHI: "Ayg'oqchi", Role.KOLDUN: "Koldun",
}

PASSIVE_NIGHT_ROLES = {
    Role.CITIZEN, Role.OMADLI,
    Role.BO_RI, Role.AFSUNGAR, Role.SEHRGAR, Role.ADMIRAL,
    Role.HAMSHIRA,  # passive while Doctor is alive; auto-becomes Doctor when Doctor dies
}

PASSIVE_MESSAGES = {
    Role.CITIZEN:  "👨🏼 Siz *Tinch Aholi*siz. Dam oling — ertaga shahar himoyangizga muhtoj!",
    Role.OMADLI:   "🤞🏼 Siz *Omadli*siz. Kechasi nishonga olinsangiz 50% ehtimolda omon qolasiz!",
    Role.BO_RI:    "🐺 Siz *Bo'ri*siz. Dam oling — kimning qo'lidan o'lishingiz kelajagingizni belgilaydi!",
    Role.AFSUNGAR: "💣 Siz *Afsungar*siz. Kechasi o'ldirilsangiz, o'ldirgan ham halok bo'ladi!",
    Role.SEHRGAR:  "🧙‍ Siz *Sehrgar*siz. Don/Qotil/Komissar hujumida siz xabar olasiz va tanlov berasiz.",
    Role.ADMIRAL:  "🧑🏻‍✈️ Siz *Admiral*siz. Komissar+Serjant tirik ekan — o'lmaysiz. Ikkovi o'lsa Komissar bo'lasiz.",
    Role.HAMSHIRA: "👩🏼‍⚕️ Siz *Hamshira*siz. Doktor tirik ekan, dam olasiz. Doktor vafot etsa — siz *Doktorga aylanasiz!*",
}

# Kunduzi Geroydan foydalana oladigan rollar
HERO_ROLES = {
    Role.DON, Role.KOMISSAR, Role.QOTIL, Role.KIMYOGAR,
    Role.QAROQCHI, Role.LABARANT, Role.ADMIRAL, Role.JOKER,
}

# Pending state for hero rename / transfer flows (private message)
_pending_hero_rename: set[int] = set()
_pending_hero_transfer: set[int] = set()

# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

async def _dm(bot: Bot, uid: int, text: str, kb=None):
    try:
        await bot.send_message(uid, text, reply_markup=kb, parse_mode="Markdown")
    except Exception as e:
        logger.debug(f"DM xatosi {uid}: {e}")


def _player_mention_html(game: "Game", p) -> str:
    """Clickable HTML mention for a player (uses raw first/last name)."""
    name = f"{p.first_name} {p.last_name}".strip() if p.last_name else p.first_name
    if game.vs_mode:
        if p.user_id in game.vs_red_team:
            name = f"🔴 {name}"
        elif p.user_id in game.vs_blue_team:
            name = f"🔵 {name}"
    safe = name.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f'<a href="tg://user?id={p.user_id}">{safe}</a>'


async def _safe_edit_text(bot: Bot, chat_id: int, message_id: int, text: str, **kwargs):
    """edit_message_text with automatic retry on Telegram flood control."""
    for attempt in range(4):
        try:
            return await bot.edit_message_text(
                chat_id=chat_id, message_id=message_id, text=text, **kwargs
            )
        except TelegramRetryAfter as e:
            wait = e.retry_after + 1
            logger.warning(f"Flood control (edit_message_text): {wait}s kutish, urinish {attempt + 1}")
            await asyncio.sleep(wait)
        except Exception:
            break
    return None


async def _safe_edit_markup(bot: Bot, chat_id: int, message_id: int, markup):
    """edit_message_reply_markup with automatic retry on Telegram flood control."""
    for attempt in range(4):
        try:
            return await bot.edit_message_reply_markup(
                chat_id=chat_id, message_id=message_id, reply_markup=markup
            )
        except TelegramRetryAfter as e:
            wait = e.retry_after + 1
            logger.warning(f"Flood control (edit_reply_markup): {wait}s kutish, urinish {attempt + 1}")
            await asyncio.sleep(wait)
        except Exception:
            break
    return None


async def _safe_send(bot: Bot, chat_id: int, text: str, **kwargs):
    """send_message with automatic retry on Telegram flood control."""
    for attempt in range(4):
        try:
            return await bot.send_message(chat_id, text, **kwargs)
        except TelegramRetryAfter as e:
            wait = e.retry_after + 1
            logger.warning(f"Flood control (send_message): {wait}s kutish, urinish {attempt + 1}")
            await asyncio.sleep(wait)
        except Exception:
            break
    return None


def _safe_task(coro):
    """Create an asyncio task that logs exceptions instead of silently swallowing them."""
    async def _wrapper():
        try:
            await coro
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception(f"Background task xatosi: {exc}")
    return asyncio.create_task(_wrapper())


# ─────────────────────────────────────────────
# Hero helper functions
# ─────────────────────────────────────────────

def _hero_text(hero: "Hero") -> str:
    min_d = 40 + (hero.level - 1) * 15
    max_d = 50 + (hero.level - 1) * 15
    next_xp    = hero_next_xp(hero)
    next_thresh = hero_level_threshold(hero.level + 1)
    return (
        f"🥷 *Geroy: {escape_md(hero.name)}*\n\n"
        f"⭐ Daraja: *{hero.level}*\n"
        f"☑️ Ball: *{hero.xp}* / {next_thresh} ({next_xp} kerak)\n"
        f"👊 Kuch: *{min_d}–{max_d} HP*\n"
        f"🛡 Himoya: *{hero.hp}/{MAX_HP} HP*\n"
        f"🩸 Zaryad: *{hero.charges}/{MAX_CHARGES}*\n"
        f"⏫ Keyingi daraja: *{next_xp} ball*"
    )


def _hero_panel_kb(back_cb: str = "cb_profile_back", hero_level: int = 1) -> InlineKeyboardMarkup:
    upgrade_cost = hero_upgrade_cost(hero_level)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"⬆️ Daraja oshirish ({upgrade_cost}💎)",
            callback_data="hero_upgrade")],
        [InlineKeyboardButton(
            text=f"🩸 Zaryadlash ({CHARGE_RESTORE_COST}💶)",
            callback_data="hero_recharge")],
        [InlineKeyboardButton(
            text=f"🛡 Himoyani tiklash ({HP_RESTORE_COST}💶)",
            callback_data="hero_restore")],
        [InlineKeyboardButton(
            text=f"➕ Ball sotib olish ({XP_BUY_COST}💶 = +{XP_BUY_AMOUNT})",
            callback_data="hero_buy_xp")],
        [InlineKeyboardButton(
            text=f"🖋 Nomni o'zgartirish ({NAME_CHANGE_COST}💶)",
            callback_data="hero_rename")],
        [InlineKeyboardButton(text="🔄 Geroyni o'tkazish", callback_data="hero_transfer")],
        [InlineKeyboardButton(text="◀️ Orqaga", callback_data=back_cb)],
    ])


def _no_hero_kb(back_cb: str = "cb_profile_back") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"💰 Geroy sotib olish ({HERO_BUY_COST}💎)",
            callback_data="hero_buy")],
        [InlineKeyboardButton(text="📖 Geroy haqida", callback_data="hero_info")],
        [InlineKeyboardButton(text="◀️ Orqaga", callback_data=back_cb)],
    ])


def _profile_nav_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🎯 Mission",  callback_data="cb_profile_missions"),
        InlineKeyboardButton(text="🦸 Geroy",   callback_data="cb_profile_hero"),
        InlineKeyboardButton(text="🛒 Shop",    callback_data="open_shop"),
    ]])


def _missions_text(hero: "Hero") -> str:
    cm = hero.completed_missions
    lines: list[str] = ["🎯 *Missiyalar*\n"]

    lines.append("☠️ *Yo'q qilish missiyalari:*")
    for i, (threshold, rewards) in enumerate(KILL_MISSIONS):
        done = threshold in cm.get("kills", [])
        parts: list[str] = []
        if "diamond" in rewards: parts.append(f"💎{rewards['diamond']}")
        if "dollar"  in rewards: parts.append(f"💶{rewards['dollar']}")
        rwd = " + ".join(parts)
        prev_done = (i == 0) or (KILL_MISSIONS[i - 1][0] in cm.get("kills", []))
        if done:
            lines.append(f"  ✅ ☠️ {threshold} ta — {rwd}")
        elif prev_done:
            lines.append(f"  🔲 ☠️ {threshold} ta ({hero.kills}/{threshold}) — {rwd}")
        else:
            lines.append(f"  🔒 ☠️ {threshold} ta — {rwd}")

    lines.append("\n⭐ *Daraja missiyalari:*")
    for i, (threshold, rewards) in enumerate(LEVEL_MISSIONS):
        done = threshold in cm.get("levels", [])
        parts = []
        if "diamond" in rewards: parts.append(f"💎{rewards['diamond']}")
        rwd = " + ".join(parts)
        prev_done = (i == 0) or (LEVEL_MISSIONS[i - 1][0] in cm.get("levels", []))
        if done:
            lines.append(f"  ✅ ⭐ {threshold}-daraja — {rwd}")
        elif prev_done:
            lines.append(f"  🔲 ⭐ {threshold}-daraja ({hero.level}/{threshold}) — {rwd}")
        else:
            lines.append(f"  🔒 ⭐ {threshold}-daraja — {rwd}")

    lines.append("\n⚔️ *Faoliyat missiyalari:*")
    for i, (threshold, rewards) in enumerate(ACTIVITY_MISSIONS):
        done = threshold in cm.get("activity", [])
        parts = []
        if "dollar"  in rewards: parts.append(f"💶{rewards['dollar']}")
        if "diamond" in rewards: parts.append(f"💎{rewards['diamond']}")
        if "charges" in rewards: parts.append(f"🩸×{rewards['charges']}")
        rwd = " + ".join(parts)
        prev_done = (i == 0) or (ACTIVITY_MISSIONS[i - 1][0] in cm.get("activity", []))
        if done:
            lines.append(f"  ✅ ⚔️ {threshold} ta — {rwd}")
        elif prev_done:
            lines.append(f"  🔲 ⚔️ {threshold} ta ({hero.total_attacks}/{threshold}) — {rwd}")
        else:
            lines.append(f"  🔒 ⚔️ {threshold} ta — {rwd}")

    lines.append("\n💡 1000 ☑️ ball = 💎 50")
    return "\n".join(lines)


async def _send_hero_day_dms(bot: Bot, game: "Game"):
    """Kun boshida Geroy ega bo'lgan, mos rolga ega, tirik o'yinchilarga hujum DM'i yuboradi."""
    settings = await get_settings(game.chat_id)
    if not settings.hero_enabled:
        return
    for player in game.alive_players():
        if player.role not in HERO_ROLES:
            continue
        hero = await get_hero(player.user_id)
        if not hero or hero.charges <= 0:
            continue
        min_d = 40 + (hero.level - 1) * 15
        max_d = 50 + (hero.level - 1) * 15
        try:
            await bot.send_message(
                player.user_id,
                f"🦸 *Geroy bilan hujum qilish vaqti!*\n\n"
                f"🥷 Geroy: *{escape_md(hero.name)}*\n"
                f"👊 Zarba kuchi: *{min_d}–{max_d} HP*\n"
                f"🩸 Zaryad: *{hero.charges}/{MAX_CHARGES}*",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(
                        text="🦸 Geroy bilan urish",
                        callback_data=f"hero_attack_kb:{game.chat_id}",
                    )
                ]]),
                parse_mode="Markdown",
            )
        except Exception:
            pass


def _day_status_block(game: Game) -> str:
    alive = game.alive_players()
    dead = [p for p in game.players.values() if not p.alive]

    alive_list = "\n".join(f"  {i}. {game.get_display_name(p)}" for i, p in enumerate(alive, 1)) or "  —"

    role_counts: dict = {}
    for p in game.players.values():
        if p.role:
            role_counts[p.role] = role_counts.get(p.role, 0) + 1
    counts_list = "\n".join(
        f"  {ROLE_EMOJIS.get(r,'')} {ROLE_NAMES_UZ.get(r, r.value)}: *{c}*"
        for r, c in sorted(role_counts.items(), key=lambda kv: ROLE_NAMES_UZ.get(kv[0], ""))
    ) or "  —"

    return (
        f"📊 *Holat:*\n"
        f"🟢 Tirik ({len(alive)}):\n{alive_list}\n"
        f"☠️ O'lganlar: *{len(dead)}*\n\n"
        f"🎭 *Rollar taqsimoti:*\n{counts_list}"
    )


def _alive_status_block(game: Game) -> str:
    alive = game.alive_players()
    alive_list = "\n".join(
        f"{i}. {game.get_display_name(p)}" for i, p in enumerate(alive, 1)
    ) or "—"
    tinchlar = [p for p in alive if p.role and p.role not in MAFIA_TEAM and p.role != Role.QOTIL]
    mafiyalar = [p for p in alive if p.role and p.role in MAFIA_TEAM]
    tinch_roles = "\n".join(
        f"{ROLE_EMOJIS.get(p.role, '')} {ROLE_NAMES_UZ.get(p.role, '')}"
        for p in tinchlar
    ) or "—"
    mafia_roles = "\n".join(
        f"{ROLE_EMOJIS.get(p.role, '')} {ROLE_NAMES_UZ.get(p.role, '')}"
        for p in mafiyalar
    ) or "—"
    return (
        f"Tirik o'yinchilar:\n\n{alive_list}\n\n"
        f"Tinchlar: {len(tinchlar)}\n{tinch_roles}\n\n"
        f"Mafiyalar: {len(mafiyalar)}\n{mafia_roles}\n\n"
        f"Jami: {len(alive)} ta"
    )


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


def _dm_entry_kb(bot_username: Optional[str], text: str, chat_id: int = None, payload: str = None) -> Optional[InlineKeyboardMarkup]:
    if not bot_username:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=text, url=f"https://t.me/{bot_username}")
    ]])


def _lobby_kb(chat_id: int, bot_username: Optional[str] = None) -> InlineKeyboardMarkup:
    if bot_username:
        rows = [[InlineKeyboardButton(
            text="🎮 O'yinga qo'shilish",
            url=f"https://t.me/{bot_username}?start=join_{chat_id}",
        )]]
    else:
        rows = [[InlineKeyboardButton(text="🎮 Qo'shilish", callback_data=f"join:{chat_id}")]]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _lobby_text_html(game: Game) -> str:
    """HTML formatida lobby matni (mention bilan)."""
    lines = []
    for i, p in enumerate(game.players.values(), 1):
        name = f"{p.first_name} {p.last_name}".strip() if p.last_name else p.first_name
        safe = name.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        lines.append(f'{i}. <a href="tg://user?id={p.user_id}">{safe}</a>')
    player_list = "\n".join(lines) if lines else "Hali o'yinchilar yo'q."
    return (
        f"📋 <b>Ro'yxatdan o'tish davom etmoqda!</b>\n\n"
        f"👥 Ro'yxatdan o'tganlar: {len(game.players)} ta\n\n"
        f"{player_list}"
    )


def _lobby_text(game: Game) -> str:
    return (
        f"Ro'yxatdan o'tish davom etmoqda!\n\n"
        f"Ro'yxatdan o'tganlar:\n"
        f"{_player_list(game)}\n\n"
        f"Jami: {len(game.players)} ta"
    )


async def _update_lobby_message(bot: Bot, game: Game):
    if not game.lobby_msg_id:
        return
    try:
        bot_username = await _get_bot_username(bot)
        await bot.edit_message_text(
            chat_id=game.chat_id,
            message_id=game.lobby_msg_id,
            text=_lobby_text_html(game),
            reply_markup=_lobby_kb(game.chat_id, bot_username),
            parse_mode="HTML",
        )
    except Exception:
        pass


def _player_list(game: Game, show_roles: bool = False) -> str:
    lines = []
    for i, p in enumerate(game.players.values(), 1):
        dead = " ☠️" if not p.alive else ""
        role_str = ""
        if show_roles and p.role:
            role_str = f" ({ROLE_EMOJIS[p.role]} {ROLE_NAMES_UZ[p.role]})"
        lines.append(f"{i}. {game.get_display_name(p)}{role_str}{dead}")
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
            text=game.get_display_name(p),
            callback_data=f"{prefix}:{p.user_id}:{game.chat_id}"
        )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _mafia_target_kb(game: Game, prefix: str, actor_id: int = None,
                     exclude_mafia: bool = False) -> InlineKeyboardMarkup:
    """Target keyboard for mafia-side roles. Shows 🤵 badge before mafia team members."""
    rows = []
    for p in game.alive_players():
        if actor_id and p.user_id == actor_id:
            continue
        if exclude_mafia and p.role in MAFIA_TEAM:
            continue
        badge = "🤵 " if p.role in MAFIA_TEAM else ""
        rows.append([InlineKeyboardButton(
            text=f"{badge}{game.get_display_name(p)}",
            callback_data=f"{prefix}:{p.user_id}:{game.chat_id}"
        )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _komissar_target_kb(game: Game, prefix: str, actor_id: int = None) -> InlineKeyboardMarkup:
    """Target keyboard for Komissar/Serjant. Shows 👮 badge before Komissar/Serjant members."""
    ally_roles = {Role.KOMISSAR, Role.SERZHANT}
    rows = []
    for p in game.alive_players():
        if actor_id and p.user_id == actor_id:
            continue
        badge = "👮 " if p.role in ally_roles else ""
        rows.append([InlineKeyboardButton(
            text=f"{badge}{game.get_display_name(p)}",
            callback_data=f"{prefix}:{p.user_id}:{game.chat_id}"
        )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _with_skip(kb: InlineKeyboardMarkup, chat_id: int) -> InlineKeyboardMarkup:
    """Append ⏭ O'tkazib yuborish row to any night-action keyboard."""
    rows = list(kb.inline_keyboard) + [[
        InlineKeyboardButton(text="⏭ O'tkazib yuborish", callback_data=f"night_skip:{chat_id}")
    ]]
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

    settings = await get_settings(chat_id)

    # Kezuvchi: unrestrict previously blocked player
    if game.kezuvchi_restricted_uid:
        try:
            from aiogram.types import ChatPermissions
            await bot.restrict_chat_member(
                chat_id, game.kezuvchi_restricted_uid,
                ChatPermissions(
                    can_send_messages=True,
                    can_send_media_messages=True,
                    can_send_other_messages=True,
                    can_add_web_page_previews=True,
                )
            )
        except Exception:
            pass
        game.kezuvchi_restricted_uid = None

    game.reset_night_state()
    game.phase = Phase.NIGHT
    _auto_passive(game)

    bot_username = await _get_bot_username(bot)
    alive_list_night = "\n".join(
        f"{i}. {game.get_display_name(p)}"
        for i, p in enumerate(game.alive_players(), 1)
    )
    night_msg = await bot.send_message(
        chat_id,
        f"Tun\n\nTirik o'yinchilar:\n\n{alive_list_night}\n\n"
        f"⏳ Tonggacha: {settings.night_secs} sekund",
        reply_markup=_dm_entry_kb(bot_username, "🤖 Botga kirish", chat_id, "group"),
    )
    if night_msg:
        await _auto_pin(bot, game, night_msg.message_id)

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


async def _atmosphere(bot: Bot, chat_id: int, text: str):
    try:
        settings = await get_settings(chat_id)
        if not settings.night_atmosphere:
            return
        await bot.send_message(chat_id, f"_{text}_", parse_mode="Markdown")
    except Exception:
        pass


async def _auto_pin(bot: Bot, game: Game, message_id: int):
    """Yangi xabarni pin qiladi (eski pinni avval olib tashlaydi)."""
    settings = await get_settings(game.chat_id)
    if not settings.auto_pin:
        return
    if game.pinned_msg_id:
        try:
            await bot.unpin_chat_message(game.chat_id, game.pinned_msg_id)
        except Exception:
            pass
    try:
        await bot.pin_chat_message(game.chat_id, message_id, disable_notification=True)
        game.pinned_msg_id = message_id
    except Exception:
        pass


def _format_night_summary(deaths: list) -> str:
    """Build the '📋 Kecha natijalari' block: one entry per victim with their
    role and the role(s) of whoever came to kill them ('Mehmoni'/'Mehmonlari'),
    in arrival order. If nobody died, show the standard fallback line."""
    if not deaths:
        return "📋 *Kecha natijalari*\n\n🌅 Bu tun hech kim halok bo'lmadi."

    blocks = []
    for d in deaths:
        lines = [f"• ☠️ *{d['name']}* yo'q qilindi.", f"Roli: {d['role_emoji']} {d['role_name']}"]
        attackers = d["attackers"]
        if len(attackers) == 1:
            em, nm = attackers[0]
            lines.append(f"Mehmoni: {em} {nm}")
        elif len(attackers) > 1:
            lines.append("Mehmonlari:\n")
            lines.extend(f"• {em} {nm}" for em, nm in attackers)
        blocks.append("\n".join(lines))

    return "📋 *Kecha natijalari*\n\n" + "\n\n".join(blocks)


def _format_night_deaths_html(game: "Game", deaths: list) -> str:
    """HTML night deaths block with clickable player mentions."""
    if not deaths:
        return "🌅 Bu tun hech kim halok bo'lmadi."
    blocks = []
    for d in deaths:
        uid = d.get("uid")
        p = game.get_player_by_id(uid) if uid else None
        if p:
            mention = _player_mention_html(game, p)
        else:
            raw = (d.get("name") or "Noma'lum").replace("*", "").replace("_", "")
            mention = raw.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        lines = [
            f"• ☠️ {mention} yo'q qilindi.",
            f"Roli: {d.get('role_emoji', '')} {d.get('role_name', '')}",
        ]
        attackers = d.get("attackers", [])
        if len(attackers) == 1:
            em, nm = attackers[0]
            safe_nm = nm.replace("*", "").replace("_", "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            lines.append(f"Mehmoni: {em} {safe_nm}")
        elif len(attackers) > 1:
            lines.append("Mehmonlari:")
            for em, nm in attackers:
                safe_nm = nm.replace("*", "").replace("_", "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                lines.append(f"• {em} {safe_nm}")
        blocks.append("\n".join(lines))
    return "Tunda o'ldirilganlar:\n\n" + "\n\n".join(blocks)


def _alive_status_html(game: "Game") -> str:
    """HTML alive players block with clickable mentions and team role counts."""
    alive = game.alive_players()
    alive_list = "\n".join(
        f"{i}. {_player_mention_html(game, p)}"
        for i, p in enumerate(alive, 1)
    ) or "—"
    tinchlar = [p for p in alive if p.role and p.role in CITIZEN_TEAM]
    mafiyalar = [p for p in alive if p.role and p.role in MAFIA_TEAM]
    yakkalar = [p for p in alive if p.role and p.role not in MAFIA_TEAM and p.role not in CITIZEN_TEAM]
    tinch_roles = "\n".join(
        f"{ROLE_EMOJIS.get(p.role, '')} {ROLE_NAMES_UZ.get(p.role, '')}" for p in tinchlar
    ) or "—"
    mafia_roles_txt = "\n".join(
        f"{ROLE_EMOJIS.get(p.role, '')} {ROLE_NAMES_UZ.get(p.role, '')}" for p in mafiyalar
    ) or "—"
    yakka_roles = "\n".join(
        f"{ROLE_EMOJIS.get(p.role, '')} {ROLE_NAMES_UZ.get(p.role, '')}" for p in yakkalar
    ) or "—"
    return (
        f"Tirik o'yinchilar:\n\n{alive_list}\n\n"
        f"Tinchlar - {len(tinchlar)}:\n{tinch_roles}\n\n"
        f"Mafiyalar - {len(mafiyalar)}:\n{mafia_roles_txt}\n\n"
        f"Yakkalar - {len(yakkalar)}:\n{yakka_roles}\n\n"
        f"Jami: {len(alive)} ta\n\n"
        f"Endi kechaning natijalarini muhokama qilamiz..."
    )


async def _send_last_words_dm(bot: Bot, game: Game, uid: int):
    """DM a dead player inviting them to send a last-words text (once)."""
    game.pending_last_words.add(uid)
    try:
        await bot.send_message(
            uid,
            "☠️ *Siz halok bo'ldingiz.*\n\n"
            "📝 So'nggi so'zingizni yuboring.",
            parse_mode="Markdown",
        )
    except Exception:
        pass


async def _do_night_resolution(bot: Bot, game: Game):
    if game.phase != Phase.NIGHT:
        return
    settings = await get_settings(game.chat_id)
    deaths, events = await resolve_night(game, bot)

    # ── AFK check ──
    required = game.night_required_snapshot
    acted = game.night_acted_uids
    afk_kicked = []
    for uid in list(required):
        player = game.get_player_by_id(uid)
        if not player or not player.alive:
            game.afk_counters.pop(uid, None)
            continue
        if uid in acted:
            game.afk_counters[uid] = 0
        else:
            game.afk_counters[uid] = game.afk_counters.get(uid, 0) + 1
            if game.afk_counters[uid] >= 2:
                game.eliminate_player(uid)
                afk_kicked.append(player)
                game.afk_counters.pop(uid, None)

    for p in afk_kicked:
        rn = ROLE_NAMES_UZ.get(p.role, "")
        em = ROLE_EMOJIS.get(p.role, "")
        events.append(
            f"😴 *{game.get_display_name(p)}* uxlab qolgani uchun o'yindan chiqarildi. Roli: {em} *{rn}*"
        )

    game.phase = Phase.DAY

    # Send "last words" DM to each player who died this night
    for d in deaths:
        uid = d.get("uid")
        if uid:
            await _send_last_words_dm(bot, game, uid)
    for p in afk_kicked:
        await _send_last_words_dm(bot, game, p.user_id)

    winner = game.check_win_condition()
    # Build HTML-safe version of events (strip Markdown markers)
    extra_html = "\n".join(
        f"• {e.replace('*', '').replace('_', '')}" for e in events
    ) if events else ""

    if winner:
        deaths_text = _format_night_deaths_html(game, deaths)
        if extra_html:
            deaths_text += f"\n\n{extra_html}"
        await _safe_send(bot, game.chat_id, deaths_text, parse_mode="HTML")
        await _end_game(bot, game, winner)
        return

    found_mafia = game.komissar_found_mafia
    game.komissar_found_mafia = None

    # ── Message 1: Morning greeting ──
    await _safe_send(
        bot, game.chat_id,
        f"🌝 Xayrli tong\n🌄 Kun: {game.day_number}\n\n"
        f"Shamollar tundagi mish-mishlarni butun shaharga yetkazmoqda..",
        parse_mode="HTML",
    )

    # ── Message 2: Night deaths with HTML mentions ──
    deaths_text = _format_night_deaths_html(game, deaths)
    if extra_html:
        deaths_text += f"\n\n{extra_html}"
    await _safe_send(bot, game.chat_id, deaths_text, parse_mode="HTML")

    # ── Message 3: Alive players with HTML mentions ──
    await _safe_send(bot, game.chat_id, _alive_status_html(game), parse_mode="HTML")

    # ── Hero system: reset daily uses + send attack DMs ──
    game.hero_used_today = set()
    _safe_task(_send_hero_day_dms(bot, game))

    # Kezuvchi: restrict blocked player from writing until next night
    kez_target = game.night_actions.get(Role.KEZUVCHI)
    if kez_target:
        try:
            from aiogram.types import ChatPermissions
            await bot.restrict_chat_member(
                game.chat_id, kez_target,
                ChatPermissions(can_send_messages=False)
            )
            game.kezuvchi_restricted_uid = kez_target
        except Exception:
            game.kezuvchi_restricted_uid = kez_target  # still track for auto-delete

    if found_mafia and settings.komissar_auto_announce:
        fuid = found_mafia.get("uid")
        fp = game.get_player_by_id(fuid) if fuid else None
        if fp:
            fmention = _player_mention_html(game, fp)
        else:
            raw_fn = found_mafia.get("name", "Noma'lum").replace("*", "").replace("_", "")
            fmention = raw_fn.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        role_em = found_mafia["role_emoji"]
        role_nm = found_mafia["role_name"]
        await _safe_send(
            bot, game.chat_id,
            f"🚨 <b>Komissar Mafia a'zosini fosh qildi!</b>\n\n"
            f"👤 {fmention}\n"
            f"🎭 Roli: {role_em} <b>{role_nm}</b>",
            parse_mode="HTML",
        )

    await asyncio.sleep(settings.day_secs)
    await run_vote(bot, game.chat_id)


async def run_vote(bot: Bot, chat_id: int):
    game = games.get(chat_id)
    if not game or game.phase == Phase.ENDED:
        return

    settings = await get_settings(chat_id)
    game.phase = Phase.VOTING
    game.votes = {}

    alive = game.alive_players()
    bot_username = await _get_bot_username(bot)

    vote_url = f"https://t.me/{bot_username}" if bot_username else None
    vote_inline_kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🗳️ Ovoz berish", url=vote_url)
    ]]) if vote_url else None
    vote_msg = await _safe_send(
        bot, chat_id,
        f"Aybdorlarni aniqlash va jazolash vaqti keldi.\n\nOvoz berish uchun: {settings.vote_secs} soniya.",
        reply_markup=vote_inline_kb,
    )
    game.vote_msg_id = vote_msg.message_id if vote_msg else None
    if vote_msg:
        await _auto_pin(bot, game, vote_msg.message_id)
    game.joker_pick = None  # reset target's choice for this vote

    # Send Joker cards to the selected target at the start of voting
    await _send_joker_cards(bot, game, chat_id)

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
    # Ovoz berish tugadi — guruh xabaridagi eski tugmani o'chir
    if game.vote_msg_id and game.phase == Phase.VOTING:
        await _safe_edit_markup(bot, chat_id, game.vote_msg_id, None)
    await _do_vote_resolution(bot, game)


def _like_dislike_kb(likes: int = 0, dislikes: int = 0) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=f"👍 Ha ({likes})", callback_data="hangvote:like"),
        InlineKeyboardButton(text=f"👎 Yo'q ({dislikes})", callback_data="hangvote:dislike"),
    ]])


async def _run_hang_confirmation(bot: Bot, game: Game, eliminated, summary: str) -> bool:
    settings = await get_settings(game.chat_id)
    secs = settings.hang_confirm_secs
    game.hang_confirm_votes = {}

    el_mention = _player_mention_html(game, eliminated)

    confirm_msg = await _safe_send(
        bot, game.chat_id,
        f"Rostdan ham {el_mention}ni osmoqchimisiz?\n\n"
        f"⏳ {secs} soniya ichida ovoz bering:",
        reply_markup=_like_dislike_kb(0, 0),
        parse_mode="HTML",
    )
    if confirm_msg:
        game.hang_confirm_msg_id = confirm_msg.message_id

    await asyncio.sleep(secs)

    likes = sum(1 for v in game.hang_confirm_votes.values() if v == "like")
    dislikes = sum(1 for v in game.hang_confirm_votes.values() if v == "dislike")
    confirmed = likes > dislikes

    result_text = (
        f"Ovoz berish natijalari:\n\n"
        f"👍 {likes} | 👎 {dislikes}\n\n"
        + (f"{el_mention} kunduzgi yig'ilishda osiladi!"
           if confirmed else
           f"🕊️ Ko'pchilik rozi emas — {el_mention} tirik qoladi!")
    )

    edited = None
    if confirm_msg:
        edited = await _safe_edit_text(
            bot, game.chat_id, confirm_msg.message_id,
            result_text, parse_mode="HTML",
        )
    if not edited:
        await _safe_send(bot, game.chat_id, result_text, parse_mode="HTML")

    game.hang_confirm_votes = {}
    game.hang_confirm_msg_id = None
    return confirmed


async def _do_vote_resolution(bot: Bot, game: Game):
    if game.phase != Phase.VOTING:
        return
    # Move out of VOTING immediately so stale vote callbacks are rejected
    game.phase = Phase.DAY

    # If Joker's target never picked a card, treat it as the Death Card.
    if game.joker_pending and game.joker_pick is None:
        await _resolve_joker_card(bot, game, game.chat_id, 0, auto=True)

    eliminated_id = game.tally_votes()
    counts: dict = {}
    for vid, tid in game.votes.items():
        voter = game.get_player_by_id(vid)
        target = game.get_player_by_id(tid)
        if voter and voter.alive and target and target.alive:
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
            "Ovoz berish natijalari:\n\n"
            "⚖️ Tenglashdi! Bugun hech kim chiqarilmadi.\n\nKecha tushdi...",
        )
        game.day_number += 1
        await run_night(bot, game.chat_id)
        return

    eliminated = game.get_player_by_id(eliminated_id)
    role_name = ROLE_NAMES_UZ.get(eliminated.role, "")
    emoji = ROLE_EMOJIS.get(eliminated.role, "")

    settings = await get_settings(game.chat_id)
    if settings.hang_confirm_enabled:
        confirmed = await _run_hang_confirmation(bot, game, eliminated, summary)
        if not confirmed:
            game.day_number += 1
            await run_night(bot, game.chat_id)
            return

    # Check Advokat vote protection (set during the previous night)
    if game.advokat_protected and eliminated_id == game.advokat_protected:
        game.advokat_protected = None
        await bot.send_message(
            game.chat_id,
            f"Ovoz berish natijalari:\n\n"
            f"🛡️ *Advokat himoyasi* sababli *{game.get_display_name(eliminated)}* osilmadi.\n\n"
            "Kecha tushdi...",
        )
        game.day_number += 1
        await run_night(bot, game.chat_id)
        return

    # Check Koldun hang protection (game-state protection from Koldun's night action)
    if eliminated_id in game.koldun_protected:
        game.koldun_protected.discard(eliminated_id)
        await bot.send_message(
            game.chat_id,
            f"Ovoz berish natijalari:\n\n"
            f"🧙 *Koldun* himoyasi ishladi! *{game.get_display_name(eliminated)}* osilishdan qutuldi!",
        )
        game.day_number += 1
        await run_night(bot, game.chat_id)
        return

    ep = await get_profile(eliminated_id)
    if ep.hang_protect > 0:
        ep.hang_protect -= 1
        await save_profile(ep)
        await bot.send_message(
            game.chat_id,
            f"Ovoz berish natijalari:\n\n"
            f"🛡️ {game.get_display_name(eliminated)} osishdan himoya ishlatdi va omon qoldi! "
            f"(Qolgan himoya: {ep.hang_protect})",
        )
        game.day_number += 1
        await run_night(bot, game.chat_id)
        return

    if eliminated.role == Role.AFSUNGAR:
        game.eliminate_player(eliminated_id)
        await _send_last_words_dm(bot, game, eliminated_id)
        await bot.send_message(
            game.chat_id,
            f"Ovoz berish natijalari:\n\n"
            f"{game.get_display_name(eliminated)} osildi.\n{emoji} {role_name}\n\n"
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
    await _send_last_words_dm(bot, game, eliminated_id)
    votes_for = counts.get(eliminated_id, 0)
    votes_against = sum(c for tid, c in counts.items() if tid != eliminated_id)
    el_mention = _player_mention_html(game, eliminated)
    msg = (
        f"Ovoz berish natijalari:\n\n"
        f"👍 {votes_for} | 👎 {votes_against}\n\n"
        f"{el_mention} kunduzgi yig'ilishda osildi!\n\n"
        f"U edi: {emoji} {role_name}."
    )
    winner = game.check_win_condition()
    if winner:
        await _safe_send(bot, game.chat_id, msg, parse_mode="HTML")
        await _end_game(bot, game, winner)
        return

    await _safe_send(bot, game.chat_id, msg + "\n\nKecha tushdi...", parse_mode="HTML")
    game.day_number += 1
    await run_night(bot, game.chat_id)


async def _end_game(bot: Bot, game: Game, winner: str):
    game.phase = Phase.ENDED
    game.winner = winner
    game.cancel_phase_task()

    # VS Mode: delegate to vs_game module
    if game.vs_mode:
        from vs_game import end_vs_game
        await end_vs_game(bot, game, winner)
        return

    msgs = {
        "citizens": ("🏆", "🎉 *Fuqarolar g'alaba qozondi!* Barcha Mafiya yo'q qilindi!"),
        "mafia":    ("🔪", "💀 *Mafiya g'alaba qozondi!* Ular shaharga egalik qildi!"),
        "qotil":    ("🔪", "🔪 *Qotil g'alaba qozondi!* Shahar uning qo'liga o'tdi!"),
    }
    em, text = msgs.get(winner, ("🏆", "O'yin tugadi."))

    if winner == "mafia":
        winner_ids = {p.user_id for p in game.players.values() if p.alive and p.role in MAFIA_TEAM}
    elif winner == "qotil":
        q = game.get_alive_by_role(Role.QOTIL)
        winner_ids = {q.user_id} if q else set()
    else:
        winner_ids = {p.user_id for p in game.players.values() if p.alive and p.role not in MAFIA_TEAM and p.role != Role.QOTIL}

    winners = [p for p in game.players.values() if p.role and p.user_id in winner_ids]
    losers = [p for p in game.players.values() if p.role and p.user_id not in winner_ids]

    def _fmt(i, p):
        return f"{i}. {game.get_display_name(p)} — {ROLE_EMOJIS.get(p.role,'')} {ROLE_NAMES_UZ.get(p.role,'')}"

    winners_list = "\n".join(_fmt(i, p) for i, p in enumerate(winners, 1)) or "—"
    losers_list = "\n".join(_fmt(i, p) for i, p in enumerate(losers, 1)) or "—"

    WIN_REWARD = 30
    win_rewards: dict = {}
    for p in winners:
        subscribed = await _is_subscribed_to_promo_channel(bot, p.user_id)
        reward = WIN_REWARD * 2 if subscribed else WIN_REWARD
        win_rewards[p.user_id] = reward
        await record_win(p.user_id, dollar_reward=reward)

    RATING_WIN_POINTS = 10
    RATING_LOSS_POINTS = 1
    for p in winners:
        await record_game_result(game.chat_id, p.user_id, p.first_name, won=True, points=RATING_WIN_POINTS)
    for p in losers:
        await record_game_result(game.chat_id, p.user_id, p.first_name, won=False, points=RATING_LOSS_POINTS)

    reward_text = "\n\n💵 G'oliblarga mukofot berildi!" if winners else ""

    bot_username_end = await _get_bot_username(bot)
    newgame_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎮 Yangi o'yin boshlash", callback_data=f"newgame_btn:{game.chat_id}")],
    ])

    duration_secs = int(time.time() - (game.started_at or time.time()))
    mins, secs_rem = divmod(duration_secs, 60)
    duration_str = f"{mins}m {secs_rem}s" if mins else f"{secs_rem}s"

    end_text = (
        f"O'yin tugadi!\n\n"
        f"G'oliblar:\n{winners_list}\n\n"
        f"Qolgan o'yinchilar:\n{losers_list}\n\n"
        f"O'yin davomiyligi: {duration_str}"
        f"{reward_text}"
    )
    end_msg = await bot.send_message(game.chat_id, end_text, reply_markup=newgame_kb)
    if end_msg:
        await _auto_pin(bot, game, end_msg.message_id)

    # Send Geroy / Mission / Sandiq buttons privately to each player
    if bot_username_end:
        dm_rows = [
            [
                InlineKeyboardButton(text="🦸 Geroy",
                    url=f"https://t.me/{bot_username_end}?start=hero"),
                InlineKeyboardButton(text="🎯 Mission",
                    url=f"https://t.me/{bot_username_end}?start=missions"),
            ],
            [InlineKeyboardButton(text="📦 Sandiq", callback_data=f"open_sandiq:{game.chat_id}")],
        ]
    else:
        dm_rows = [
            [InlineKeyboardButton(text="📦 Sandiq", callback_data=f"open_sandiq:{game.chat_id}")],
        ]
    dm_kb = InlineKeyboardMarkup(inline_keyboard=dm_rows)
    for p in game.players.values():
        if not p.role:
            continue
        try:
            await bot.send_message(
                p.user_id,
                "🎮 O'yin tugadi! Quyidagi imkoniyatlardan foydalaning:",
                reply_markup=dm_kb,
            )
        except Exception:
            pass

    for p in winners:
        reward = win_rewards.get(p.user_id, WIN_REWARD)
        bonus_note = " (2x kanal bonusi bilan!)" if reward > WIN_REWARD else ""
        await _dm(bot, p.user_id,
            f"🎉 Siz {reward}$ yutdingiz!{bonus_note}\n\n"
            + await _profile_text(p.user_id, p.first_name))
    for p in losers:
        await _dm(bot, p.user_id,
            "😔 Siz yutqazdingiz.\n\n" + await _profile_text(p.user_id, p.first_name))

    # Send Shop button DM to every participant after game ends
    _shop_after_game_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Shop", callback_data="open_shop")]
    ])
    for p in game.players.values():
        try:
            await bot.send_message(
                p.user_id,
                "🛒 O'yin tugadi! Do'konga tashrif buyurib yangi itemlar sotib oling:",
                reply_markup=_shop_after_game_kb,
            )
        except Exception:
            pass

    stats = await load_stats()
    stats.total_games += 1
    stats.total_players += len(game.players)
    if winner == "mafia":
        stats.mafia_wins += 1
    elif winner == "citizens":
        stats.citizen_wins += 1
    await save_stats(stats)

# ──────────────────────────────────────────────
# Night action sender
# ──────────────────────────────────────────────

async def _send_night_actions(bot: Bot, game: Game):
    alive = game.alive_players()
    chat_id = game.chat_id
    _night_settings = await get_settings(chat_id)
    secs = _night_settings.night_secs
    lab_show = _night_settings.labarant_show
    mafia_names = ", ".join(
        game.get_display_name(p) for p in alive if p.role in (Role.DON, Role.MAFIA)
    )

    for player in alive:
        role = player.role
        uid  = player.user_id

        if role == Role.DON:
            # LABARANT is in MAFIA_TEAM but Mafia doesn't know — keep them targetable
            targets = [p for p in alive if p.role not in MAFIA_TEAM or p.role == Role.LABARANT]
            kb = _with_skip(InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=game.get_display_name(p), callback_data=f"nk:{p.user_id}:{chat_id}")]
                for p in targets
            ]), chat_id)
            allies = [game.get_display_name(p) for p in alive
                      if p.role == Role.MAFIA or (lab_show and p.role == Role.LABARANT)]
            ally_txt = f"\n🤝 Mafiya: {', '.join(allies)}" if allies else ""
            await _dm(bot, uid,
                f"*{game.day_number}-kecha*{ally_txt}\n\n"
                f"🤵🏻 *Don:* o'ldirish uchun o'yinchini tanlang ({secs}s):", kb)

        elif role == Role.MAFIA:
            # LABARANT is in MAFIA_TEAM but Mafia doesn't know — keep them targetable
            targets = [p for p in alive if p.role not in MAFIA_TEAM or p.role == Role.LABARANT]
            kb = _with_skip(InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=game.get_display_name(p), callback_data=f"nk:{p.user_id}:{chat_id}")]
                for p in targets
            ]), chat_id)
            don = game.get_alive_by_role(Role.DON)
            leader = f"Don: {game.get_display_name(don)}" if don else "Siz lider"
            # Show LABARANT in allies list only if labarant_show is enabled
            allies = [game.get_display_name(p) for p in alive if p.role in MAFIA_TEAM
                      and (lab_show or p.role != Role.LABARANT) and p.user_id != uid]
            ally_txt = f"\n🤝 Jamoa: {', '.join(allies)}" if allies else ""
            await _dm(bot, uid,
                f"*{game.day_number}-kecha*\n_{leader}_{ally_txt}\n\n"
                f"🤵🏼 Nishon tanlang ({secs}s):", kb)

        elif role == Role.YOLLANMA_QOTIL:
            # LABARANT is in MAFIA_TEAM but YQ doesn't know — keep them targetable
            targets = [p for p in alive if p.role not in MAFIA_TEAM or p.role == Role.LABARANT]
            kb = _with_skip(InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=game.get_display_name(p), callback_data=f"nyq:{p.user_id}:{chat_id}")]
                for p in targets
            ]), chat_id)
            # Show LABARANT in allies list only if labarant_show is enabled
            allies = [game.get_display_name(p) for p in alive if p.role in MAFIA_TEAM
                      and (lab_show or p.role != Role.LABARANT)]
            ally_txt = f"\n🤝 Mafiya jamoasi: {', '.join(allies)}" if allies else ""
            await _dm(bot, uid,
                f"*{game.day_number}-kecha*{ally_txt}\n\n"
                f"🥷 Nishon tanlang — ⚠️ Komissarni tanlasangiz, u sizni o'ldiradi! ({secs}s):", kb)

        elif role == Role.ADVOKAT:
            # Advokat now protects any player from being lynched the next day
            targets = [p for p in alive if p.user_id != uid]
            if not targets:
                game.night_actions[Role.ADVOKAT] = uid
                game.night_acted_uids.add(uid)
                await _dm(bot, uid,
                    f"*{game.day_number}-kecha*\n\n"
                    "👨🏼‍💼 Himoya qilish uchun boshqa o'yinchi yo'q. Harakatingiz o'tkazib yuborildi.")
            else:
                kb = _with_skip(_mafia_target_kb(game, "nadv", actor_id=uid), chat_id)
                await _dm(bot, uid,
                    f"*{game.day_number}-kecha*\n\n"
                    f"👨🏼‍💼 Ertangi ovozda osishdan himoya qilish uchun o'yinchini tanlang ({secs}s):", kb)

        elif role == Role.JURNALIST:
            kb = _with_skip(_mafia_target_kb(game, "njurn", actor_id=uid), chat_id)
            # Show LABARANT in allies list only if labarant_show is enabled
            allies = [game.get_display_name(p) for p in alive if p.role in MAFIA_TEAM and (lab_show or p.role != Role.LABARANT)]
            ally_txt = f"\n🤝 Mafiya jamoasi: {', '.join(allies)}" if allies else ""
            await _dm(bot, uid,
                f"*{game.day_number}-kecha*{ally_txt}\n\n"
                f"👩🏼‍💻 Intervyu olish uchun o'yinchini tanlang ({secs}s):", kb)

        elif role == Role.KOMISSAR:
            kb = _with_skip(InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="🔍 Tekshirish", callback_data=f"nkommode:check:{chat_id}"),
                InlineKeyboardButton(text="🔫 O'ldirish", callback_data=f"nkommode:kill:{chat_id}"),
            ]]), chat_id)
            await _dm(bot, uid,
                f"*{game.day_number}-kecha*\n\n"
                f"🕵🏼 Bu kecha nima qilasiz ({secs}s)?", kb)

        elif role == Role.SERZHANT and not game.get_alive_by_role(Role.KOMISSAR):
            kb = _with_skip(InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="🔍 Tekshirish", callback_data=f"nkommode:check:{chat_id}"),
                InlineKeyboardButton(text="🔫 O'ldirish", callback_data=f"nkommode:kill:{chat_id}"),
            ]]), chat_id)
            await _dm(bot, uid,
                f"*{game.day_number}-kecha*\n\n"
                f"👮🏼 Siz hozir Komissar vazifasini bajaryapsiz. Nima qilasiz ({secs}s)?", kb)

        elif role == Role.LABARANT:
            kb = _with_skip(_mafia_target_kb(game, "nlab", actor_id=uid), chat_id)
            lab_allies = [game.get_display_name(p) for p in alive
                          if p.role in MAFIA_TEAM and p.role != Role.LABARANT] if lab_show else []
            lab_ally_txt = f"\n🤝 Mafiya jamoasi: {', '.join(lab_allies)}" if lab_allies else ""
            await _dm(bot, uid,
                f"*{game.day_number}-kecha*{lab_ally_txt}\n\n"
                f"🧪 O'yinchi tanlang — Mafiya bo'lsa himoya qilasiz, boshqa bo'lsa zaharlaysiz ({secs}s):", kb)

        elif role == Role.DOCTOR:
            kb = _with_skip(_target_kb(game, "ndoc", actor_id=uid, include_self=True), chat_id)
            await _dm(bot, uid,
                f"*{game.day_number}-kecha*\n\n"
                f"💊 Himoya qilish uchun o'yinchini tanlang (o'zingizni ham) ({secs}s):", kb)

        elif role == Role.KEZUVCHI:
            kb = _with_skip(_target_kb(game, "nkez", actor_id=uid), chat_id)
            await _dm(bot, uid,
                f"*{game.day_number}-kecha*\n\n"
                f"💃 Uyqu dori berish uchun o'yinchini tanlang ({secs}s):", kb)

        elif role == Role.DAYDI:
            kb = _with_skip(_target_kb(game, "nday", actor_id=uid), chat_id)
            await _dm(bot, uid,
                f"*{game.day_number}-kecha*\n\n"
                f"🍾 Tashrif buyurish uchun o'yinchini tanlang ({secs}s):", kb)

        elif role == Role.QOTIL:
            kb = _with_skip(_target_kb(game, "nqot", actor_id=uid), chat_id)
            await _dm(bot, uid,
                f"*{game.day_number}-kecha*\n\n"
                f"🔪 O'ldirish uchun nishon tanlang ({secs}s):", kb)

        elif role == Role.KIMYOGAR:
            kb = _with_skip(InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="🩺 Davolash", callback_data=f"nkimmode:heal:{chat_id}"),
                InlineKeyboardButton(text="☠️ O'ldirish", callback_data=f"nkimmode:kill:{chat_id}"),
            ]]), chat_id)
            await _dm(bot, uid,
                f"*{game.day_number}-kecha*\n\n"
                f"👨‍🔬 Bu kecha nima qilasiz ({secs}s)?", kb)

        elif role == Role.MINIOR:
            kb = _with_skip(_target_kb(game, "nmin", actor_id=uid), chat_id)
            await _dm(bot, uid,
                f"*{game.day_number}-kecha*\n\n"
                f"☠️ Mina qo'yish uchun o'yinchini tanlang ({secs}s):", kb)

        elif role == Role.AFERIST:
            kb = _with_skip(_target_kb(game, "nafer", actor_id=uid), chat_id)
            await _dm(bot, uid,
                f"*{game.day_number}-kecha*\n\n"
                f"🤹🏻 Kimning ovoz berish shaxsini almashtirmoqchisiz ({secs}s)?", kb)

        elif role == Role.GAZABKOR:
            kb = _with_skip(_target_kb(game, "ngaz", actor_id=uid, include_self=True), chat_id)
            count = len(player.gazabkor_targets)
            await _dm(bot, uid,
                f"*{game.day_number}-kecha*\n\n"
                f"🧟 Ro'yxatga o'yinchi qo'shing (hozir *{count}* ta). "
                f"O'zingizni tanlasangiz, barchasi o'ladi (g'alaba uchun kamida 3 ta) ({secs}s):", kb)

        elif role == Role.JOKER:
            # Joker picks which of the 4 face-down cards is the Death Card,
            # then picks a target. The cards are sent to the target at voting start.
            card_labels = ["🎴 1", "🎴 2", "🎴 3", "🎴 4"]
            kb = _with_skip(InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=label, callback_data=f"jokcard:{i}:{chat_id}")]
                for i, label in enumerate(card_labels)
            ]), chat_id)
            await _dm(bot, uid,
                f"*{game.day_number}-kecha*\n\n"
                f"🤡 *O'lim kartasini tanlang:* 4 ta karta orasida aynan qaysi biri o'lim kartasi?\n"
                f"Tanlangan kartani maqsadli o'yinchiga ovoz berish bosqachasida yuboramiz. ({secs}s):", kb)

        elif role == Role.SOTQIN:
            suspects = [p for p in alive if p.role in (Role.DON, Role.MAFIA, Role.QOTIL)]
            if suspects:
                rows = [
                    [InlineKeyboardButton(text=game.get_display_name(p), callback_data=f"nsot:{p.user_id}:{chat_id}")]
                    for p in suspects
                ] + [[InlineKeyboardButton(text="⏭️ O'tkazib yuborish", callback_data=f"nsot:0:{chat_id}")]]
                await _dm(bot, uid,
                    f"*{game.day_number}-kecha*\n\n"
                    f"🤓 Kimni fosh qilmoqchisiz ({secs}s)?",
                    InlineKeyboardMarkup(inline_keyboard=rows))
            else:
                game.night_actions[Role.SOTQIN] = 0
                game.night_acted_uids.add(uid)
                await _dm(bot, uid,
                    f"*{game.day_number}-kecha*\n\n🤓 Fosh qilish uchun ma'lum nishon yo'q.")

        elif role == Role.TULKI:
            kb = _with_skip(_target_kb(game, "ntulki", actor_id=uid), chat_id)
            await _dm(bot, uid,
                f"*{game.day_number}-kecha*\n\n"
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
            kb = _with_skip(InlineKeyboardMarkup(inline_keyboard=[buttons[:5], buttons[5:]]), chat_id)
            await _dm(bot, uid,
                f"*{game.day_number}-kecha*\n\n"
                f"⛏️ *Konchi:* kon qazing! 10 ta raqam ichida 💎 3 olmos, 💣 2 mina, 💵 5 pul slot bor.\n"
                f"Bir raqam tanlang ({secs}s) — xohlasangiz o'tkazib yuboring:", kb)

        elif role == Role.QAROQCHI:
            # Qaroqchi performs exactly ONE action per night.
            kb = _with_skip(InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💰 Pul o'g'irlash", callback_data=f"qar_mode:steal:{chat_id}")],
                [InlineKeyboardButton(text="⚔️ Jon olish", callback_data=f"qar_mode:attack:{chat_id}")],
            ]), chat_id)
            await _dm(bot, uid,
                f"*{game.day_number}-kecha*\n\n"
                f"🏴‍☠️ *Qaroqchi:* Bu kecha faqat *1 ta amal* tanlaysiz.\n\n"
                f"Amal tanlang ({secs}s):", kb)

        elif role == Role.RAIS:
            kb = _with_skip(_target_kb(game, "nrais", actor_id=uid), chat_id)
            await _dm(bot, uid,
                f"*{game.day_number}-kecha*\n\n"
                f"💰 *Rais:* Bu kecha sovg'a yuborish uchun o'yinchini tanlang.\n"
                f"50–100$ va 20% ehtimol bilan 1–2 Almas yuboriladi ({secs}s):", kb)

        elif role == Role.AYGOQCHI:
            kb = _with_skip(_mafia_target_kb(game, "naygoychi", actor_id=uid), chat_id)
            # Ayg'oqchi is visible to Mafia team; show LABARANT if labarant_show enabled
            allies = [game.get_display_name(p) for p in alive if p.role in MAFIA_TEAM
                      and (lab_show or p.role != Role.LABARANT) and p.user_id != uid]
            ally_txt = f"\n🤝 Mafiya jamoasi: {', '.join(allies)}" if allies else ""
            await _dm(bot, uid,
                f"*{game.day_number}-kecha*{ally_txt}\n\n"
                f"🦇 *Ayg'oqchi:* Kimning rolini bilib olmoqchisiz ({secs}s)?", kb)

        elif role == Role.KOLDUN:
            kb = _with_skip(_target_kb(game, "nkoldun", actor_id=uid), chat_id)
            await _dm(bot, uid,
                f"*{game.day_number}-kecha*\n\n"
                f"🧙 *Koldun:* O'yinchi tanlang:\n"
                f"🔵 Fuqaro bo'lsa → osilishdan himoyalanadi\n"
                f"🔴 Mafiya/Mustaqil bo'lsa → kechasi halok bo'ladi ({secs}s):", kb)

        elif role in PASSIVE_NIGHT_ROLES:
            await _dm(bot, uid,
                f"*{game.day_number}-kecha*\n\n{PASSIVE_MESSAGES.get(role, 'Dam oling.')}")


def _auto_passive(game: Game):
    for p in game.alive_players():
        if p.role in PASSIVE_NIGHT_ROLES:
            game.night_actions[f"passive_{p.user_id}"] = True
            game.night_acted_uids.add(p.user_id)
    serzhant = game.get_alive_by_role(Role.SERZHANT)
    if serzhant and game.get_alive_by_role(Role.KOMISSAR):
        game.night_actions[Role.SERZHANT] = 0
        game.night_acted_uids.add(serzhant.user_id)

# ──────────────────────────────────────────────
# Commands
# ──────────────────────────────────────────────

@router.message(Command("start", "help"))
async def cmd_start(msg: Message, bot: Bot):
    if msg.chat.type == "private":
        group_kb = None
        parts = (msg.text or "").split(maxsplit=1)
        payload = parts[1] if len(parts) > 1 else ""

        if payload.startswith("join_"):
            return await _handle_private_join(msg, bot, payload)

        if payload.startswith("vote_"):
            try:
                cid = int(payload.split("_", 1)[1])
                game = games.get(cid)
                if game and game.phase == Phase.VOTING:
                    p = game.get_player_by_id(msg.from_user.id)
                    if p and p.alive:
                        await msg.answer(
                            "🗳️ *Ovoz berish vaqti!*\n\nKim Mafiya ekanini o'ylab, tanlang:",
                            reply_markup=_vote_kb(game, msg.from_user.id),
                        )
                        return
            except Exception:
                pass

        if payload.startswith("group_"):
            try:
                gid = int(payload.split("_", 1)[1])
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
            "/tekshiruv — Komissar tekshiruv tarixi (shaxsiy)\n"
            "/give N — Javob sifatida: to'g'ridan-to'g'ri o'tkazish. Aks holda: guruhga N olmos tashlash\n"
            "/money N — Javob sifatida: to'g'ridan-to'g'ri o'tkazish. Aks holda: guruhga N$ tashlash\n"
            "/shop — Do'kon\n"
            "/roleshop — Rol do'koni\n"
            "/sozlash — Guruh sozlamalari (admin)\n"
            "/kanal — Reklama kanalini sozlash (bot egasi)\n"
            "/reyting — Guruh reytingi (TOP 20)\n"
            "/utag — Guruh a'zolarini o'yinga chaqirish\n"
            "/stats — Statistika\n"
            "/rules — Qoidalar\n"
            "/roles — Barcha rollar haqida",
            reply_markup=group_kb,
        )
        return

    await _launch_game(msg, bot)


async def _open_lobby(msg: Message, bot: Bot):
    if msg.chat.type == "private":
        return await msg.answer("⚠️ Bu buyruq faqat guruh chatlarda ishlaydi.")

    chat_id = msg.chat.id
    existing = games.get(chat_id)
    if existing and existing.phase not in (Phase.LOBBY, Phase.ENDED):
        return await msg.answer(
            "⚠️ O'yin allaqachon davom etmoqda!\n"
            "Yangi ro'yxat ochish uchun avval /endgame bilan tugatish kerak."
        )

    if existing and existing.phase == Phase.LOBBY:
        bot_username = await _get_bot_username(bot)
        sent = await msg.answer(
            _lobby_text_html(existing),
            reply_markup=_lobby_kb(chat_id, bot_username),
            parse_mode="HTML",
        )
        existing.lobby_msg_id = sent.message_id
        await _auto_pin(bot, existing, sent.message_id)
        return

    games[chat_id] = Game(chat_id=chat_id)
    game = games[chat_id]
    user = msg.from_user
    game.creator_id = user.id
    game.add_player(user.id, user.username or "", user.first_name, user.last_name or "")

    bot_username = await _get_bot_username(bot)
    sent = await msg.answer(
        _lobby_text_html(game),
        reply_markup=_lobby_kb(chat_id, bot_username),
        parse_mode="HTML",
    )
    game.lobby_msg_id = sent.message_id
    await _auto_pin(bot, game, sent.message_id)


async def _handle_private_join(msg: Message, bot: Bot, payload: str):
    try:
        gid = int(payload.split("_", 1)[1])
    except (ValueError, IndexError):
        gid = None

    user = msg.from_user
    game = games.get(gid) if gid is not None else None

    if not game or game.phase != Phase.LOBBY:
        return await msg.answer("⚠️ Bu o'yin lobbysi endi faol emas.")

    link = await _group_link(bot, gid)
    return_kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔙 Guruhga qaytish", url=link)
    ]]) if link else None

    if user.id in game.players:
        return await msg.answer("ℹ️ Siz allaqachon o'yinga qo'shilgansiz.", reply_markup=return_kb)

    if game.add_player(user.id, user.username or "", user.first_name, user.last_name or ""):
        await msg.answer("✅ Siz o'yinga muvaffaqiyatli qo'shildingiz.", reply_markup=return_kb)
        await _update_lobby_message(bot, game)
    else:
        await msg.answer("❌ Lobby to'lgan.", reply_markup=return_kb)


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
    # Auto-generated from role registry — adding a new Role + its entries in
    # ROLE_EMOJIS, ROLE_DESCRIPTIONS_UZ, MAFIA_TEAM / CITIZEN_TEAM is enough
    # to make it appear here automatically.
    all_described = [r for r in ROLE_DESCRIPTIONS_UZ]  # preserves insertion order

    mafia_roles   = [r for r in all_described if r in MAFIA_TEAM]
    citizen_roles = [r for r in all_described if r in CITIZEN_TEAM]
    neutral_roles = [r for r in all_described if r not in MAFIA_TEAM and r not in CITIZEN_TEAM]

    teams = {
        "🔴 *Mafiya jamoasi:*": mafia_roles,
        "🔵 *Fuqarolar jamoasi:*": citizen_roles,
        "⚪ *Mustaqil rollar:*": neutral_roles,
    }
    for label, roles in teams.items():
        if not roles:
            continue
        lines = [label]
        for r in roles:
            em   = ROLE_EMOJIS.get(r, "")
            name = ROLE_NAMES_UZ.get(r, r.value)
            desc = ROLE_DESCRIPTIONS_UZ[r].split("\n")[0]
            lines.append(f"{em} *{name}* — _{desc}_")
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
        text += f"{i}. {game.get_display_name(p)}\n"
    if dead:
        text += f"\n*Chiqarilgan ({len(dead)}):*\n"
        for i, p in enumerate(dead, 1):
            rn = ROLE_NAMES_UZ.get(p.role, "") if p.role else ""
            em = ROLE_EMOJIS.get(p.role, "") if p.role else ""
            text += f"{i}. ☠️ {game.get_display_name(p)} — {em} {rn}\n"

    await msg.answer(text)


@router.message(Command("leave"))
async def cmd_leave(msg: Message):
    if msg.chat.type == "private":
        return await msg.answer("⚠️ Bu buyruq faqat guruh chatlarda ishlaydi.")

    chat_id = msg.chat.id
    settings = await get_settings(chat_id)
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


# ── /utag — Guruh a'zolarini chaqirish ──

@router.message(Command("utag"))
async def cmd_utag(msg: Message, bot: Bot):
    if msg.chat.type == "private":
        return await msg.answer("⚠️ Bu buyruq faqat guruh chatlarda ishlaydi.")

    chat_id = msg.chat.id

    # Collect known players from ratings DB (historical players in this chat)
    from database import get_pool
    known: dict[int, str] = {}  # user_id -> first_name

    pool = await get_pool()
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT user_id, first_name FROM ratings WHERE chat_id=$1", chat_id
            )
            for row in rows:
                if row["first_name"]:
                    known[row["user_id"]] = row["first_name"]
    except Exception:
        pass

    # Also include current game lobby players
    game = games.get(chat_id)
    if game and game.phase == Phase.LOBBY:
        for p in game.players.values():
            if p.first_name:
                known[p.user_id] = p.first_name

    if not known:
        return await msg.answer("Bu guruhda hali hech kim o'ynamagan.")

    # Build UID mention list — verify each user is still a member, skip bots/left users
    valid_mentions: list[str] = []
    for uid, first_name in known.items():
        try:
            member = await bot.get_chat_member(chat_id, uid)
            if member.status in ("left", "kicked", "banned"):
                continue
            if getattr(member.user, "is_bot", False):
                continue
        except Exception:
            continue
        safe = first_name.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        valid_mentions.append(f'<a href="tg://user?id={uid}">{safe}</a>')

    if not valid_mentions:
        return await msg.answer("Hozirda aktiv a'zolar topilmadi.")

    # Send comma-separated mentions in chunks (~30 per message)
    chunk_size = 30
    for i in range(0, len(valid_mentions), chunk_size):
        chunk = valid_mentions[i:i + chunk_size]
        await msg.answer(", ".join(chunk), parse_mode="HTML")
        if i + chunk_size < len(valid_mentions):
            await asyncio.sleep(0.5)


TOGGLEABLE_ROLES = [
    r for r in Role if r not in (Role.DON, Role.MAFIA)
]

DURATION_OPTIONS = [15, 30, 45, 60, 90]

RCFG_MIN_COUNT = 4
RCFG_MAX_COUNT = 30

# Roles that can be added in multiple copies (with ➕/➖ counter, default 0)
COUNTABLE_RCFG_ROLES = [Role.SERZHANT, Role.TULKI, Role.QOTIL, Role.AFSUNGAR, Role.CITIZEN]

RCFG_TOGGLE_ROLES = [
    r for r in Role if r not in (Role.DON, Role.MAFIA) and r not in COUNTABLE_RCFG_ROLES
]

_rcfg_sessions: dict[int, dict] = {}


def _sozlash_main_kb(chat_id: int, settings: ChatSettings) -> InlineKeyboardMarkup:
    leave_label = "✅ /leave yoqilgan" if settings.leave_enabled else "❌ /leave o'chirilgan"
    protect_label = "✅ Himoya buyumlari yoqilgan" if settings.protection_enabled else "❌ Himoya buyumlari o'chirilgan"
    autodel_label = (
        "🗑 O'lik xabarlar: ✅ Yoqilgan"
        if settings.auto_delete_dead
        else "🗑 O'lik xabarlar: ❌ O'chirilgan"
    )
    atm_label = (
        "🌙 Atmosfera xabarlari: ✅ Yoqilgan"
        if settings.night_atmosphere
        else "🌙 Atmosfera xabarlari: ❌ O'chirilgan"
    )
    lab_label = (
        "🧪 Labarantni ko'rish: ✅ Yoqilgan"
        if settings.labarant_show
        else "🧪 Labarantni ko'rish: ❌ O'chirilgan"
    )
    kauto_label = (
        "🚨 Komissar xabari: ✅ Yoqilgan"
        if settings.komissar_auto_announce
        else "🚨 Komissar xabari: ❌ O'chirilgan"
    )
    mstart_label = (
        "👤 A'zo boshlashi: ✅ Yoqilgan"
        if settings.member_can_start
        else "👤 A'zo boshlashi: ❌ O'chirilgan"
    )
    apin_label = (
        "📌 Avtomatik pin: ✅ Yoqilgan"
        if settings.auto_pin
        else "📌 Avtomatik pin: ❌ O'chirilgan"
    )
    hero_label = (
        "🦸 Geroy tizimi: ✅ Yoqilgan"
        if settings.hero_enabled
        else "🦸 Geroy tizimi: ❌ O'chirilgan"
    )
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🃏 Rollarni yoqish/o'chirish", callback_data=f"soz:roles:0:{chat_id}")],
        [InlineKeyboardButton(text="🎭 Rollarni sozlash (o'yinchilar soni bo'yicha)", callback_data=f"soz:rcfgc:0:{chat_id}")],
        [InlineKeyboardButton(text=leave_label, callback_data=f"soz:toggle_leave:{chat_id}")],
        [InlineKeyboardButton(text=protect_label, callback_data=f"soz:toggle_protect:{chat_id}")],
        [InlineKeyboardButton(text=autodel_label, callback_data=f"soz:toggle_autodel:{chat_id}")],
        [InlineKeyboardButton(text=atm_label, callback_data=f"soz:toggle_atm:{chat_id}")],
        [InlineKeyboardButton(text=lab_label, callback_data=f"soz:toggle_lab:{chat_id}")],
        [InlineKeyboardButton(text=kauto_label, callback_data=f"soz:toggle_kauto:{chat_id}")],
        [InlineKeyboardButton(text=mstart_label, callback_data=f"soz:toggle_memberstart:{chat_id}")],
        [InlineKeyboardButton(text=apin_label, callback_data=f"soz:toggle_autopin:{chat_id}")],
        [InlineKeyboardButton(text=hero_label, callback_data=f"soz:toggle_hero:{chat_id}")],
        [InlineKeyboardButton(text="⏳ Vaqtlarni sozlash", callback_data=f"soz:durations:{chat_id}")],
        [InlineKeyboardButton(text="✅ Yopish", callback_data=f"soz:close:{chat_id}")],
    ])


def _rcfg_counts_kb(chat_id: int, settings: ChatSettings, page: int = 0) -> InlineKeyboardMarkup:
    per_page = 10
    counts = list(range(RCFG_MIN_COUNT, RCFG_MAX_COUNT + 1))
    start = page * per_page
    page_counts = counts[start:start + per_page]
    rows = []
    row = []
    for n in page_counts:
        mark = "⭐" if str(n) in settings.custom_role_configs else ""
        row.append(InlineKeyboardButton(text=f"{mark}{n}", callback_data=f"soz:rcfgo:{n}:{page}:{chat_id}"))
        if len(row) == 5:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    nav = []
    if start > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"soz:rcfgc:{page-1}:{chat_id}"))
    if start + per_page < len(counts):
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"soz:rcfgc:{page+1}:{chat_id}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="🔙 Orqaga", callback_data=f"soz:main:{chat_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _rcfg_session_total(session: dict) -> int:
    # 1 Don + mafia_extra Mafias + selected other roles
    roles = session["roles"]
    if isinstance(roles, dict):
        return 1 + session["mafia_extra"] + sum(roles.values())
    return 1 + session["mafia_extra"] + len(roles)


def _rcfg_editor_kb(chat_id: int, session: dict, page: int = 0) -> InlineKeyboardMarkup:
    per_page = 5
    start = page * per_page
    roles_page = RCFG_TOGGLE_ROLES[start:start + per_page]
    mafia_count = session["mafia_extra"]

    # Normalize roles to dict
    roles_dict = session["roles"] if isinstance(session["roles"], dict) else {r: 1 for r in session["roles"]}

    rows = [
        # Mafia counter row
        [
            InlineKeyboardButton(text="➖", callback_data=f"soz:rcfgm:dec:{page}:{chat_id}"),
            InlineKeyboardButton(text=f"{ROLE_EMOJIS[Role.MAFIA]} Mafia: {mafia_count}", callback_data="noop"),
            InlineKeyboardButton(text="➕", callback_data=f"soz:rcfgm:inc:{page}:{chat_id}"),
        ]
    ]

    # Countable roles rows (with ➕/➖ per role)
    for r in COUNTABLE_RCFG_ROLES:
        count = roles_dict.get(r.name, 0)
        em = ROLE_EMOJIS.get(r, "")
        nm = ROLE_NAMES_UZ.get(r, r.value)
        rows.append([
            InlineKeyboardButton(text="➖", callback_data=f"soz:rcfgcr:dec:{r.name}:{page}:{chat_id}"),
            InlineKeyboardButton(text=f"{em} {nm}: {count}", callback_data="noop"),
            InlineKeyboardButton(text="➕", callback_data=f"soz:rcfgcr:inc:{r.name}:{page}:{chat_id}"),
        ])

    # Toggle roles rows (on/off)
    for r in roles_page:
        count = roles_dict.get(r.name, 0)
        on = count > 0
        label = f"{'✅' if on else '❌'} {ROLE_EMOJIS.get(r,'')} {ROLE_NAMES_UZ.get(r, r.value)}"
        rows.append([InlineKeyboardButton(text=label, callback_data=f"soz:rcfgr:{r.name}:{page}:{chat_id}")])

    nav = []
    if start > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"soz:rcfge:{page-1}:{chat_id}"))
    if start + per_page < len(RCFG_TOGGLE_ROLES):
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"soz:rcfge:{page+1}:{chat_id}"))
    if nav:
        rows.append(nav)

    total = _rcfg_session_total(session)
    target = session["count"]
    status = "✅" if total == target else "⚠️"
    rows.append([InlineKeyboardButton(text=f"{status} Jami: {total}/{target}", callback_data="noop")])

    save_row = []
    if total == target:
        save_row.append(InlineKeyboardButton(text="💾 Saqlash", callback_data=f"soz:rcfgs:{page}:{chat_id}"))
    save_row.append(InlineKeyboardButton(text="🗑️ Standartga qaytarish", callback_data=f"soz:rcfgd:{page}:{chat_id}"))
    rows.append(save_row)
    rows.append([InlineKeyboardButton(text="🔙 Orqaga", callback_data=f"soz:rcfgc:0:{chat_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _rcfg_editor_text(session: dict) -> str:
    total = _rcfg_session_total(session)
    target = session["count"]
    return (
        f"🎭 *Rollarni sozlash — {target} o'yinchi*\n\n"
        f"Har bir rolni yoqing/o'chiring. Mafiya sonini +/- bilan o'zgartiring.\n"
        f"Don har doim 1 ta. Mafiya soni 0 dan boshlaydi.\n"
        f"Jami tanlangan rollar soni o'yinchilar soniga teng bo'lishi kerak.\n\n"
        f"Hozirgi holat: *{total}/{target}*"
    )


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

    settings = await get_settings(chat_id)
    try:
        await bot.send_message(
            msg.from_user.id,
            "⚙️ *Guruh sozlamalari*\n\nQuyidagilardan birini tanlang:",
            reply_markup=_sozlash_main_kb(chat_id, settings),
            parse_mode="Markdown",
        )
    except Exception:
        return await msg.answer(
            "⚠️ Sizga shaxsiy xabar yubora olmadim. Avval botga shaxsiy chatda /start yozing, so'ng qayta urinib ko'ring."
        )
    await msg.answer("✅ Sozlash menyusi shaxsiy chattingizga yuborildi.")


@router.callback_query(F.data.startswith("soz:"))
async def cb_sozlash(call: CallbackQuery):
    parts = call.data.split(":")
    action = parts[1]
    chat_id = int(parts[-1])

    if not await _require_admin(call, call.bot, chat_id, call.from_user.id):
        return await call.answer("⚠️ Faqat adminlar uchun.", show_alert=True)

    settings = await get_settings(chat_id)

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
        await save_settings(settings)
        await call.message.edit_text(
            "🃏 *Rollarni yoqish/o'chirish*\n\nBosilganda holat o'zgaradi:",
            reply_markup=_sozlash_roles_kb(chat_id, settings, page),
        )

    elif action == "toggle_leave":
        settings.leave_enabled = not settings.leave_enabled
        await save_settings(settings)
        await call.message.edit_text(
            "⚙️ *Guruh sozlamalari*\n\nQuyidagilardan birini tanlang:",
            reply_markup=_sozlash_main_kb(chat_id, settings),
        )

    elif action == "toggle_protect":
        settings.protection_enabled = not settings.protection_enabled
        await save_settings(settings)
        await call.message.edit_text(
            "⚙️ *Guruh sozlamalari*\n\nQuyidagilardan birini tanlang:",
            reply_markup=_sozlash_main_kb(chat_id, settings),
        )

    elif action == "toggle_autodel":
        settings.auto_delete_dead = not settings.auto_delete_dead
        await save_settings(settings)
        status = "yoqildi ✅" if settings.auto_delete_dead else "o'chirildi ❌"
        await call.answer(f"🗑 O'lik xabarlarni o'chirish {status}", show_alert=False)
        await call.message.edit_text(
            "⚙️ *Guruh sozlamalari*\n\nQuyidagilardan birini tanlang:",
            reply_markup=_sozlash_main_kb(chat_id, settings),
        )

    elif action == "toggle_atm":
        settings.night_atmosphere = not settings.night_atmosphere
        await save_settings(settings)
        status = "yoqildi ✅" if settings.night_atmosphere else "o'chirildi ❌"
        await call.answer(f"🌙 Atmosfera xabarlari {status}", show_alert=False)
        await call.message.edit_text(
            "⚙️ *Guruh sozlamalari*\n\nQuyidagilardan birini tanlang:",
            reply_markup=_sozlash_main_kb(chat_id, settings),
        )

    elif action == "toggle_lab":
        settings.labarant_show = not settings.labarant_show
        await save_settings(settings)
        status = "yoqildi ✅" if settings.labarant_show else "o'chirildi ❌"
        await call.answer(f"🧪 Labarantni ko'rish {status}", show_alert=False)
        await call.message.edit_text(
            "⚙️ *Guruh sozlamalari*\n\nQuyidagilardan birini tanlang:",
            reply_markup=_sozlash_main_kb(chat_id, settings),
        )

    elif action == "toggle_kauto":
        settings.komissar_auto_announce = not settings.komissar_auto_announce
        await save_settings(settings)
        status = "yoqildi ✅" if settings.komissar_auto_announce else "o'chirildi ❌"
        await call.answer(f"🚨 Komissar xabari {status}", show_alert=False)
        await call.message.edit_text(
            "⚙️ *Guruh sozlamalari*\n\nQuyidagilardan birini tanlang:",
            reply_markup=_sozlash_main_kb(chat_id, settings),
        )

    elif action == "toggle_memberstart":
        settings.member_can_start = not settings.member_can_start
        await save_settings(settings)
        status = "yoqildi ✅" if settings.member_can_start else "o'chirildi ❌"
        await call.answer(f"👤 A'zo boshlashi {status}", show_alert=False)
        await call.message.edit_text(
            "⚙️ *Guruh sozlamalari*\n\nQuyidagilardan birini tanlang:",
            reply_markup=_sozlash_main_kb(chat_id, settings),
        )

    elif action == "toggle_autopin":
        settings.auto_pin = not settings.auto_pin
        await save_settings(settings)
        status = "yoqildi ✅" if settings.auto_pin else "o'chirildi ❌"
        await call.answer(f"📌 Avtomatik pin {status}", show_alert=False)
        await call.message.edit_text(
            "⚙️ *Guruh sozlamalari*\n\nQuyidagilardan birini tanlang:",
            reply_markup=_sozlash_main_kb(chat_id, settings),
        )

    elif action == "toggle_hero":
        settings.hero_enabled = not settings.hero_enabled
        await save_settings(settings)
        status = "yoqildi ✅" if settings.hero_enabled else "o'chirildi ❌"
        await call.answer(f"🦸 Geroy tizimi {status}", show_alert=False)
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
        await save_settings(settings)
        await call.message.edit_text(
            "⏳ *Bosqich vaqtlarini sozlash*",
            reply_markup=_sozlash_durations_kb(chat_id, settings),
        )

    elif action == "rcfgc":
        page = int(parts[2])
        await call.message.edit_text(
            "🎭 *Rollarni sozlash*\n\n"
            "O'yinchilar sonini tanlang (⭐ = moslashtirilgan sozlama mavjud):",
            reply_markup=_rcfg_counts_kb(chat_id, settings, page),
        )

    elif action == "rcfgo":
        count, page = int(parts[2]), int(parts[3])
        existing = settings.custom_role_configs.get(str(count))
        if existing:
            # Normalize legacy format: MAFIA value was stored as count (1 = 1 extra Mafia).
            # Any value > 1 or 0 is already the correct "extra mafias" count.
            # Normalize: if MAFIA is stored as bool/1, treat as "1 extra Mafia".
            raw_mafia = existing.get("MAFIA", 0)
            mafia_extra = max(0, int(raw_mafia))
            roles = {name: int(qty) for name, qty in existing.items()
                     if name not in ("DON", "MAFIA") and int(qty) > 0}
            # Ensure countable roles are in dict with their counts (default 0)
            for r in COUNTABLE_RCFG_ROLES:
                if r.name not in roles:
                    roles[r.name] = 0
        else:
            roles = {r.name: 0 for r in COUNTABLE_RCFG_ROLES}
            mafia_extra = 0  # Default: 0 Mafias (only Don)
        session = {"chat_id": chat_id, "count": count, "roles": roles, "mafia_extra": mafia_extra}
        _rcfg_sessions[call.from_user.id] = session
        await call.message.edit_text(_rcfg_editor_text(session), reply_markup=_rcfg_editor_kb(chat_id, session, 0))

    elif action == "rcfge":
        page = int(parts[2])
        session = _rcfg_sessions.get(call.from_user.id)
        if not session or session["chat_id"] != chat_id:
            return await call.answer("⚠️ Sessiya topilmadi, qaytadan boshlang.", show_alert=True)
        await call.message.edit_text(_rcfg_editor_text(session), reply_markup=_rcfg_editor_kb(chat_id, session, page))

    elif action == "rcfgm":
        direction, page = parts[2], int(parts[3])
        session = _rcfg_sessions.get(call.from_user.id)
        if not session or session["chat_id"] != chat_id:
            return await call.answer("⚠️ Sessiya topilmadi, qaytadan boshlang.", show_alert=True)
        if direction == "inc" and _rcfg_session_total(session) < session["count"]:
            session["mafia_extra"] += 1
        elif direction == "dec" and session["mafia_extra"] > 0:
            session["mafia_extra"] -= 1
        await call.message.edit_text(_rcfg_editor_text(session), reply_markup=_rcfg_editor_kb(chat_id, session, page))

    elif action == "rcfgr":
        role_name, page = parts[2], int(parts[3])
        session = _rcfg_sessions.get(call.from_user.id)
        if not session or session["chat_id"] != chat_id:
            return await call.answer("⚠️ Sessiya topilmadi, qaytadan boshlang.", show_alert=True)
        roles = session["roles"]
        if not isinstance(roles, dict):
            roles = {r: 1 for r in roles}
            session["roles"] = roles
        current = roles.get(role_name, 0)
        if current > 0:
            roles[role_name] = 0  # toggle off
        elif _rcfg_session_total(session) < session["count"]:
            roles[role_name] = 1  # toggle on
        else:
            return await call.answer("⚠️ Jami rollar soni o'yinchilar sonidan oshib ketdi.", show_alert=True)
        await call.message.edit_text(_rcfg_editor_text(session), reply_markup=_rcfg_editor_kb(chat_id, session, page))

    elif action == "rcfgcr":
        # Countable role increment/decrement
        direction, role_name, page = parts[2], parts[3], int(parts[4])
        session = _rcfg_sessions.get(call.from_user.id)
        if not session or session["chat_id"] != chat_id:
            return await call.answer("⚠️ Sessiya topilmadi, qaytadan boshlang.", show_alert=True)
        roles = session["roles"]
        if not isinstance(roles, dict):
            roles = {r: 1 for r in roles}
            session["roles"] = roles
        current = roles.get(role_name, 0)
        if direction == "inc":
            if _rcfg_session_total(session) < session["count"]:
                roles[role_name] = current + 1
            else:
                return await call.answer("⚠️ Jami rollar soni o'yinchilar sonidan oshib ketdi.", show_alert=True)
        elif direction == "dec" and current > 0:
            roles[role_name] = current - 1
        await call.message.edit_text(_rcfg_editor_text(session), reply_markup=_rcfg_editor_kb(chat_id, session, page))

    elif action == "rcfgs":
        session = _rcfg_sessions.get(call.from_user.id)
        if not session or session["chat_id"] != chat_id:
            return await call.answer("⚠️ Sessiya topilmadi, qaytadan boshlang.", show_alert=True)
        if _rcfg_session_total(session) != session["count"]:
            return await call.answer("⚠️ Jami rollar soni mos kelmayapti.", show_alert=True)
        # Save: MAFIA = mafia_extra (can be 0)
        config = {"DON": 1, "MAFIA": session["mafia_extra"]}
        roles = session["roles"]
        if isinstance(roles, dict):
            for role_name, count in roles.items():
                if count > 0:
                    config[role_name] = count
        else:
            for role_name in roles:
                config[role_name] = 1
        settings.custom_role_configs[str(session["count"])] = config
        await save_settings(settings)
        del _rcfg_sessions[call.from_user.id]
        await call.message.edit_text(
            f"✅ *{session['count']} o'yinchi uchun sozlama saqlandi!*",
            reply_markup=_rcfg_counts_kb(chat_id, settings, 0),
        )

    elif action == "rcfgd":
        session = _rcfg_sessions.get(call.from_user.id)
        if not session or session["chat_id"] != chat_id:
            return await call.answer("⚠️ Sessiya topilmadi, qaytadan boshlang.", show_alert=True)
        settings.custom_role_configs.pop(str(session["count"]), None)
        await save_settings(settings)
        del _rcfg_sessions[call.from_user.id]
        await call.message.edit_text(
            "🎭 *Rollarni sozlash*\n\n"
            "O'yinchilar sonini tanlang (⭐ = moslashtirilgan sozlama mavjud):",
            reply_markup=_rcfg_counts_kb(chat_id, settings, 0),
        )

    await call.answer()


@router.callback_query(F.data == "noop")
async def cb_noop(call: CallbackQuery):
    await call.answer()


async def _assign_roles_with_preferences(game: Game, disabled_roles: list = None, custom_role_configs: dict = None):
    import random
    from game import get_role_list, get_custom_role_list
    players = list(game.players.values())
    role_pool = None
    if custom_role_configs:
        config = custom_role_configs.get(str(len(players)))
        if config:
            role_pool = get_custom_role_list(config, len(players))
    if role_pool is None:
        role_pool = get_role_list(len(players), disabled_roles=disabled_roles)

    assigned: dict[int, Role] = {}
    remaining = list(role_pool)

    for player in players:
        prof = await get_profile(player.user_id)
        for key in list(prof.active_roles):
            key = ROLE_KEY_ALIASES.get(key, key)
            item = PURCHASABLE_ROLES.get(key)
            if not item:
                continue
            desired_role = item[0]
            if desired_role in remaining:
                assigned[player.user_id] = desired_role
                remaining.remove(desired_role)
                if key in prof.active_roles:
                    prof.active_roles.remove(key)
                await save_profile(prof)
                break

    random.shuffle(remaining)
    pool_iter = iter(remaining)
    for player in players:
        if player.user_id in assigned:
            player.role = assigned[player.user_id]
        else:
            player.role = next(pool_iter)


async def _launch_game(msg: Message, bot: Bot):
    chat_id = msg.chat.id
    game = games.get(chat_id)
    if not game or game.phase == Phase.ENDED:
        return await msg.answer("⚠️ Faol lobby yo'q. /game dan foydalaning.")
    if game.phase != Phase.LOBBY:
        return await msg.answer("⚠️ O'yin allaqachon boshlangan.")

    member = await bot.get_chat_member(chat_id, msg.from_user.id)
    is_admin = member.status in ("administrator", "creator")
    chat_settings_pre = await get_settings(chat_id)
    if not is_admin:
        if not chat_settings_pre.member_can_start:
            return await msg.answer("⚠️ Bu guruhda faqat adminlar o'yinni boshlay oladi.")
        if msg.from_user.id not in game.players:
            return await msg.answer("⚠️ Faqat admin yoki lobby o'yinchilari boshlashi mumkin.")

    if len(game.players) < MIN_PLAYERS:
        return await msg.answer(
            f"⚠️ Kamida *{MIN_PLAYERS}* o'yinchi kerak. Hozir: *{len(game.players)}*"
        )

    game.group_link = await _group_link(bot, chat_id)

    chat_settings = await get_settings(chat_id)
    await _assign_roles_with_preferences(
        game,
        disabled_roles=chat_settings.disabled_roles,
        custom_role_configs=chat_settings.custom_role_configs,
    )
    game.day_number = 1

    for player in game.players.values():
        await record_game_start(player.user_id, player.first_name)

    game.started_at = time.time()

    await msg.answer(f"🟢 *O'YIN BOSHLANDI!*")

    group_kb = None
    if game.group_link:
        group_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👥 Guruhga qaytish", url=game.group_link)]
        ])

    # LABARANT is in MAFIA_TEAM but is a secret member.
    # labarant_show controls whether Labarant is visible to/from the mafia team.
    lab_show = chat_settings.labarant_show

    def _visible_mafia_names(exclude_self_id=None, include_labarant=False):
        return ", ".join(
            game.get_display_name(p) for p in game.players.values()
            if p.role in MAFIA_TEAM
               and (include_labarant or p.role != Role.LABARANT)
               and (exclude_self_id is None or p.user_id != exclude_self_id)
        )

    for player in game.players.values():
        em   = ROLE_EMOJIS[player.role]
        name = ROLE_NAMES_UZ[player.role]
        desc = ROLE_DESCRIPTIONS_UZ[player.role]
        if player.role == Role.LABARANT:
            extra = (
                f"\n\n🤝 *Mafiya jamoangiz:* {_visible_mafia_names(exclude_self_id=player.user_id)}"
                if lab_show else ""
            )
        elif player.role in MAFIA_TEAM:
            extra = f"\n\n🤝 *Mafiya jamoangiz:* {_visible_mafia_names(exclude_self_id=player.user_id, include_labarant=lab_show)}"
        else:
            extra = ""
        await _dm(bot, player.user_id,
            f"🎭 *Sizning rolingiz: {em} {name}*\n\n{desc}{extra}\n\nO'yin boshlandi!", group_kb)

    # ── "Sheriklaringizni eslab qoling!" HTML DM to each team member ──
    async def _sheriklari_dm(uid: int, allies_list: list):
        """Send clickable HTML ally list DM. allies_list: [(player, role_emoji, role_name)]"""
        if not allies_list:
            return
        lines = ["<b>Sheriklaringizni eslab qoling!</b>", ""]
        for ap, aem, anm in allies_list:
            mention = _player_mention_html(game, ap)
            lines.append(f"{mention} — {aem} {anm}")
        try:
            await bot.send_message(uid, "\n".join(lines), parse_mode="HTML")
        except Exception as exc:
            logger.debug(f"Sheriklari DM xatosi {uid}: {exc}")

    # Mafia team sheriklari (sent after role DM)
    for player in game.players.values():
        role = player.role
        uid = player.user_id
        if role == Role.LABARANT:
            if lab_show:
                allies = [
                    (p, ROLE_EMOJIS.get(p.role, ""), ROLE_NAMES_UZ.get(p.role, ""))
                    for p in game.players.values()
                    if p.role in MAFIA_TEAM and p.role != Role.LABARANT and p.user_id != uid
                ]
                await _sheriklari_dm(uid, allies)
        elif role in MAFIA_TEAM:
            allies = [
                (p, ROLE_EMOJIS.get(p.role, ""), ROLE_NAMES_UZ.get(p.role, ""))
                for p in game.players.values()
                if p.role in MAFIA_TEAM
                   and (lab_show or p.role != Role.LABARANT)
                   and p.user_id != uid
            ]
            await _sheriklari_dm(uid, allies)

    # Komissar ↔ Serjant sheriklari
    komissar_p = game.get_alive_by_role(Role.KOMISSAR)
    serzhant_p = game.get_alive_by_role(Role.SERZHANT)
    if komissar_p and serzhant_p:
        await _sheriklari_dm(komissar_p.user_id, [
            (serzhant_p, ROLE_EMOJIS[Role.SERZHANT], ROLE_NAMES_UZ[Role.SERZHANT])
        ])
        await _sheriklari_dm(serzhant_p.user_id, [
            (komissar_p, ROLE_EMOJIS[Role.KOMISSAR], ROLE_NAMES_UZ[Role.KOMISSAR])
        ])
        await _dm(bot, komissar_p.user_id,
            "Botga yozgan xabarlaringiz faqat sherigingizga ko'rinadi.")
        await _dm(bot, serzhant_p.user_id,
            "Botga yozgan xabarlaringiz faqat sherigingizga ko'rinadi.")
    elif komissar_p:
        await _dm(bot, komissar_p.user_id, "ℹ️ Bu o'yinda Serjant yo'q.")
    elif serzhant_p:
        await _dm(bot, serzhant_p.user_id, "ℹ️ Bu o'yinda Komissar yo'q.")

    _safe_task(run_night(bot, chat_id))


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
    is_admin = member.status in ("administrator", "creator")
    is_creator = game.creator_id == msg.from_user.id
    if not is_admin and not is_creator:
        return await msg.answer("⚠️ Faqat admin yoki o'yin yaratuvchisi tugatishi mumkin.")

    game.cancel_phase_task()
    game.phase = Phase.ENDED
    role_list = "\n".join(
        f"  {'☠️' if not p.alive else '✅'} {game.get_display_name(p)} — "
        f"{ROLE_EMOJIS.get(p.role,'')} {ROLE_NAMES_UZ.get(p.role,'')}"
        for p in game.players.values() if p.role
    )
    await msg.answer(f"🛑 *O'yin admin tomonidan tugatildi.*\n\n*Rollar:*\n{role_list}")


@router.message(Command("reyting", "top"))
async def cmd_top(msg: Message):
    if msg.chat.type == "private":
        return await msg.answer("⚠️ Bu buyruq faqat guruh chatlarda ishlaydi.")

    top = await get_top_ratings(msg.chat.id)
    if not top:
        return await msg.answer("📊 Bu guruhda hali reyting yo'q. O'yin o'ynang!")

    lines = ["🏆 *Guruh reytingi — TOP 20*\n"]
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    for i, entry in enumerate(top, 1):
        medal = medals.get(i, f"{i}.")
        display_name = entry.first_name or "Noma'lum"
        lines.append(
            f"{medal} {escape_md(display_name)} — "
            f"*{entry.score}* ball ({entry.wins} g'alaba / {entry.games} o'yin)"
        )
    await msg.answer("\n".join(lines))


@router.message(Command("stats"))
async def cmd_stats(msg: Message):
    stats = await load_stats()
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
    channel = await get_promo_channel()
    if not channel:
        return False
    try:
        member = await bot.get_chat_member(channel, user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception:
        return False


async def _promo_text() -> str:
    channel = await get_promo_channel()
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
        current = await get_promo_channel()
        not_set = "o'rnatilmagan"
        return await msg.answer(
            f"📢 Hozirgi reklama kanali: *{escape_md(current) if current else not_set}*\n\n"
            "O'rnatish uchun: `/kanal @username` yoki `/kanal https://t.me/...`"
        )

    channel = parts[1].strip()
    await set_promo_channel(channel)
    await msg.answer(f"✅ Reklama kanali o'rnatildi: *{escape_md(channel)}*")


async def _profile_text(user_id: int, first_name: str) -> str:
    p = await get_profile(user_id, first_name)
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
    ) + await _promo_text()


@router.message(Command("profile"))
async def cmd_profile(msg: Message):
    user = msg.from_user
    await msg.answer(
        await _profile_text(user.id, user.first_name),
        reply_markup=_profile_nav_kb(),
        parse_mode="Markdown",
    )


@router.callback_query(F.data == "open_shop")
async def cb_open_shop(call: CallbackQuery):
    uid = call.from_user.id
    p = await get_profile(uid, call.from_user.first_name)
    dollar_str = "♾️" if p.infinite_dollar else f"{p.dollar}$"
    diamond_str = "♾️" if p.infinite_diamond else str(p.diamond)
    await call.answer()
    try:
        await call.message.edit_text(
            f"🛒 *DO'KON*\n\n"
            f"💵 Balansingiz: *{dollar_str}*\n"
            f"💎 Olmoslaringiz: *{diamond_str}*\n\n"
            "Sotib olmoqchi bo'lgan narsani tanlang:",
            reply_markup=_shop_kb(),
        )
    except Exception:
        await call.message.answer(
            f"🛒 *DO'KON*\n\n"
            f"💵 Balansingiz: *{dollar_str}*\n"
            f"💎 Olmoslaringiz: *{diamond_str}*\n\n"
            "Sotib olmoqchi bo'lgan narsani tanlang:",
            reply_markup=_shop_kb(),
        )


@router.message(Command("tekshiruv"))
async def cmd_tekshiruv(msg: Message):
    if msg.chat.type != "private":
        return await msg.answer("⚠️ Bu buyruq faqat shaxsiy chatda ishlaydi.")

    user = msg.from_user
    game = next((g for g in games.values() if user.id in g.players and g.phase != Phase.ENDED), None)
    if not game:
        return await msg.answer("ℹ️ Siz hozir faol o'yinda emassiz.")

    history = game.komissar_investigations.get(user.id)
    if not history:
        return await msg.answer("ℹ️ Siz hali hech kimni tekshirmagansiz.")

    lines = [f"  {i}. *{name}* — {role}" for i, (name, role) in enumerate(history, 1)]
    await msg.answer("🕵🏼 *Tekshiruv tarixingiz:*\n\n" + "\n".join(lines))


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

    if msg.reply_to_message and msg.reply_to_message.from_user:
        target = msg.reply_to_message.from_user
        if target.is_bot:
            return await msg.answer("❌ Botga o'tkazib bo'lmaydi.")
        if target.id == giver.id:
            return await msg.answer("❌ O'zingizga o'tkazib bo'lmaydi.")
        await get_profile(giver.id, giver.first_name)
        await get_profile(target.id, target.first_name)
        if not await transfer_diamond(giver.id, target.id, amount):
            return await msg.answer("❌ Yetarli olmos yo'q.")
        return await msg.answer(
            f"💎 *{escape_md(giver.first_name)}* → *{escape_md(target.first_name)}*ga *{amount}* olmos o'tkazdi!"
        )

    giver_p = await get_profile(giver.id, giver.first_name)
    if not giver_p.infinite_diamond and giver_p.diamond < amount:
        return await msg.answer(f"❌ Yetarli olmos yo'q. Sizda: *{giver_p.diamond}* 💎")

    if not giver_p.infinite_diamond:
        giver_p.diamond -= amount
        await save_profile(giver_p)

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
    await get_profile(user.id, user.first_name)
    await add_diamond(user.id, 1)
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

    if msg.reply_to_message and msg.reply_to_message.from_user:
        target = msg.reply_to_message.from_user
        if target.is_bot:
            return await msg.answer("❌ Botga o'tkazib bo'lmaydi.")
        if target.id == giver.id:
            return await msg.answer("❌ O'zingizga o'tkazib bo'lmaydi.")
        await get_profile(giver.id, giver.first_name)
        await get_profile(target.id, target.first_name)
        if not await transfer_dollar(giver.id, target.id, amount):
            return await msg.answer("❌ Yetarli pul yo'q.")
        return await msg.answer(
            f"💵 *{escape_md(giver.first_name)}* → *{escape_md(target.first_name)}*ga *{amount}$* o'tkazdi!"
        )

    giver_p = await get_profile(giver.id, giver.first_name)
    if not giver_p.infinite_dollar and giver_p.dollar < amount:
        return await msg.answer(f"❌ Yetarli pul yo'q. Sizda: *{giver_p.dollar}$*")

    if not giver_p.infinite_dollar:
        giver_p.dollar -= amount
        await save_profile(giver_p)

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
    await get_profile(user.id, user.first_name)
    await add_dollar(user.id, drop["per_claim"])
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
            _safe_task(_end_game(bot, game, winner))


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
    p = await get_profile(user.id, user.first_name)
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
        p = await get_profile(call.from_user.id, call.from_user.first_name)
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
    p = await get_profile(uid, call.from_user.first_name)

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
    await save_profile(p)

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
    p = await get_profile(user.id, user.first_name)
    dollar_str = "♾️" if p.infinite_dollar else f"{p.dollar}$"
    diamond_str = "♾️" if p.infinite_diamond else str(p.diamond)
    await msg.answer(
        f"🛒 *DO'KON*\n\n"
        f"💵 Balansingiz: *{dollar_str}*\n"
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
    p = await get_profile(uid, msg.from_user.first_name)

    if currency == "dollar":
        if not p.infinite_dollar and p.dollar < price:
            return await msg.answer(
                f"❌ Yetarli dollar yo'q!\n{em} *{name}* — {price}💵\nSizda: *{p.dollar}$*"
            )
        if not p.infinite_dollar:
            p.dollar -= price
    else:
        if not p.infinite_diamond and p.diamond < price:
            return await msg.answer(
                f"❌ Yetarli olmos yo'q!\n{em} *{name}* — {price}💎\nSizda: *{p.diamond}💎*"
            )
        if not p.infinite_diamond:
            p.diamond -= price

    setattr(p, field, getattr(p, field) + 1)
    await save_profile(p)

    dollar_str = "♾️" if p.infinite_dollar else f"{p.dollar}$"
    diamond_str = "♾️" if p.infinite_diamond else str(p.diamond)
    await msg.answer(
        f"✅ {em} *{name}* sotib olindi!\n\n"
        f"💵 Qolgan dollar: *{dollar_str}*\n"
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
    p = await get_profile(uid, call.from_user.first_name)

    if currency == "dollar":
        if not p.infinite_dollar and p.dollar < price:
            return await call.answer(
                f"❌ Yetarli dollar yo'q!\nKerak: {price}$  |  Sizda: {p.dollar}$",
                show_alert=True,
            )
        if not p.infinite_dollar:
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
    await save_profile(p)

    dollar_str = "♾️" if p.infinite_dollar else f"{p.dollar}$"
    diamond_str = "♾️" if p.infinite_diamond else str(p.diamond)
    await call.answer(f"✅ {em} {name} sotib olindi!", show_alert=False)

    try:
        await call.message.edit_text(
            f"🛒 *DO'KON*\n\n"
            f"💵 Balansingiz: *{dollar_str}*\n"
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
    p = await get_profile(uid, call.from_user.first_name)
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
    p = await get_profile(uid, call.from_user.first_name)
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
    if existing and existing.phase == Phase.LOBBY:
        return await call.answer("⚠️ Lobby allaqachon mavjud! Yangi lobby yaratib bo'lmaydi.", show_alert=True)

    games[chat_id] = Game(chat_id=chat_id)
    game = games[chat_id]
    user = call.from_user
    game.creator_id = user.id
    game.add_player(user.id, user.username or "", user.first_name, getattr(user, 'last_name', '') or "")

    await call.answer("✅ Yangi lobby ochildi!")
    bot_username = await _get_bot_username(bot)
    sent = await bot.send_message(
        chat_id,
        _lobby_text_html(game),
        reply_markup=_lobby_kb(chat_id, bot_username),
        parse_mode="HTML",
    )
    game.lobby_msg_id = sent.message_id
    await _auto_pin(bot, game, sent.message_id)


@router.callback_query(F.data.startswith("join:"))
async def cb_join(call: CallbackQuery, bot: Bot):
    chat_id = int(call.data.split(":")[1])
    game = games.get(chat_id)
    if not game or game.phase != Phase.LOBBY:
        return await call.answer("⚠️ Lobby faol emas.", show_alert=True)

    user = call.from_user
    if game.add_player(user.id, user.username or "", user.first_name, user.last_name or ""):
        await call.answer(f"✅ Qo'shildingiz! Jami: {len(game.players)} o'yinchi.")
        # Update the lobby message (whether it's this message or the pinned lobby)
        await _update_lobby_message(bot, game)
        # Also edit this message if it's not the lobby message
        if call.message.message_id != game.lobby_msg_id:
            try:
                bot_username = await _get_bot_username(bot)
                await call.message.edit_text(
                    _lobby_text(game),
                    reply_markup=_lobby_kb(chat_id, bot_username),
                )
            except Exception:
                pass
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


# ── Night action callbacks ──

async def _night_cb(call: CallbackQuery, action_key, target_id: int, chat_id: int, confirm_text: str, atmosphere_text: str = ""):
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
    game.night_acted_uids.add(call.from_user.id)
    await call.answer(confirm_text)
    await call.message.edit_text(f"✅ {confirm_text}")
    if atmosphere_text:
        await _atmosphere(call.bot, chat_id, atmosphere_text)

    if game.all_night_actions_done():
        _safe_task(_do_night_resolution(call.bot, game))


async def _notify_mafia_of_vote(bot: Bot, game: Game, voter_name: str, target_name: str, is_don: bool):
    """Send vote notification DM to all visible Mafia members."""
    if is_don:
        text = f"🤵 Don → *{target_name}*ni tanladi."
    else:
        text = f"🤵 {voter_name} → *{target_name}*ga ovoz berdi."
    for p in game.alive_players():
        if p.role in (Role.DON, Role.MAFIA, Role.YOLLANMA_QOTIL,
                      Role.ADVOKAT, Role.JURNALIST, Role.AYGOQCHI):
            try:
                await bot.send_message(p.user_id, text, parse_mode="Markdown")
            except Exception:
                pass


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

    is_don = actor.role == Role.DON

    # Record individual mafia vote
    game.mafia_votes[actor.user_id] = tid
    game.night_actions[actor.user_id] = tid
    game.night_acted_uids.add(call.from_user.id)

    if is_don:
        # Don's vote is final — set kill target and mark ALL mafia members as acted
        game.night_actions["mafia_kill"] = tid
        game.night_actions["mafia_don_voted"] = True
        for p in game.alive_players():
            if p.role in (Role.DON, Role.MAFIA):
                game.night_acted_uids.add(p.user_id)
                game.night_actions[p.user_id] = tid
    else:
        # Tentatively record; will be tallied in resolve_night if Don doesn't vote
        game.night_actions["mafia_kill"] = tid

    await call.answer(f"🔪 Nishon: {game.get_display_name(target)}")
    await call.message.edit_text(f"🔪 Nishon tanlandi: *{game.get_display_name(target)}*")

    # If Don voted — send atmosphere message to group
    if is_don:
        await _atmosphere(call.bot, game.chat_id, "🤵 Don qorong'ulikda nishonni belgiladi...")

    # DM all visible Mafia members about the vote
    await _notify_mafia_of_vote(
        call.bot, game,
        voter_name=game.get_display_name(actor),
        target_name=game.get_display_name(target),
        is_don=is_don,
    )

    if game.all_night_actions_done():
        _safe_task(_do_night_resolution(call.bot, game))


@router.callback_query(F.data.startswith("nyq:"))
async def cb_nyq(call: CallbackQuery):
    _, tid, cid = call.data.split(":")
    await _night_cb(call, Role.YOLLANMA_QOTIL, int(tid), int(cid), "🥷 Nishon tanlandi",
                    "🥷 Yollanma qotil qorong'ulikda ov boshladi...")


@router.callback_query(F.data.startswith("nadv:"))
async def cb_nadv(call: CallbackQuery):
    _, tid, cid = call.data.split(":")
    await _night_cb(call, Role.ADVOKAT, int(tid), int(cid), "👨🏼‍💼 Himoyaga olindi",
                    "👨🏼‍💼 Advokat mijozini himoya qilishga kirishdi...")


@router.callback_query(F.data.startswith("njurn:"))
async def cb_njurn(call: CallbackQuery):
    _, tid, cid = call.data.split(":")
    await _night_cb(call, Role.JURNALIST, int(tid), int(cid), "👩🏼‍💻 Manzil tanlandi",
                    "👩🏼‍💻 Jurnalist yashirin intervyu olish uchun yo'lga chiqdi...")


@router.callback_query(F.data.startswith("nkommode:"))
async def cb_nkommode(call: CallbackQuery):
    _, mode, cid = call.data.split(":")
    cid = int(cid)
    game = games.get(cid)
    if not game or game.phase != Phase.NIGHT:
        return await call.answer("⚠️ Kecha tugagan.", show_alert=True)
    game.night_actions["komissar_mode"] = mode
    actor = game.get_player_by_id(call.from_user.id)
    target_kb = _komissar_target_kb(game, "nkom", actor_id=actor.user_id if actor else None)
    if mode == "kill":
        text = "🔫 *O'ldirish* uchun o'yinchini tanlang:"
        kb = target_kb
    else:
        text = "🔍 *Tekshirish* uchun o'yinchini tanlang:"
        # Add back button only on check mode
        rows = list(target_kb.inline_keyboard) + [[
            InlineKeyboardButton(text="🔙 Orqaga", callback_data=f"nkommode_back:{cid}")
        ]]
        kb = InlineKeyboardMarkup(inline_keyboard=rows)
    await call.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
    await call.answer()


@router.callback_query(F.data.startswith("nkommode_back:"))
async def cb_nkommode_back(call: CallbackQuery):
    """Return to komissar mode-selection from player list."""
    cid = int(call.data.split(":")[1])
    game = games.get(cid)
    if not game or game.phase != Phase.NIGHT:
        return await call.answer("⚠️ Kecha tugagan.", show_alert=True)
    uid = call.from_user.id
    if uid in game.night_acted_uids:
        return await call.answer("✅ Allaqachon harakat qildingiz.", show_alert=True)
    actor = game.get_player_by_id(uid)
    role = actor.role if actor else None
    secs = (await get_settings(cid)).night_secs
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔍 Tekshirish", callback_data=f"nkommode:check:{cid}"),
        InlineKeyboardButton(text="🔫 O'ldirish", callback_data=f"nkommode:kill:{cid}"),
    ], [
        InlineKeyboardButton(text="⏭ O'tkazib yuborish", callback_data=f"night_skip:{cid}"),
    ]])
    text_role = "🕵🏼" if role == Role.KOMISSAR else "👮🏼"
    try:
        await call.message.edit_text(
            f"{text_role} Bu kecha nima qilasiz ({secs}s)?",
            reply_markup=kb,
            parse_mode="Markdown",
        )
    except Exception:
        pass
    await call.answer()


@router.callback_query(F.data.startswith("night_skip:"))
async def cb_night_skip(call: CallbackQuery):
    """Handle ⏭ O'tkazib yuborish for any night role."""
    cid = int(call.data.split(":")[1])
    uid = call.from_user.id
    game = games.get(cid)
    if not game or game.phase != Phase.NIGHT:
        return await call.answer("⚠️ Kecha tugagan.", show_alert=True)
    if uid in game.night_acted_uids:
        return await call.answer("✅ Allaqachon harakat qildingiz.", show_alert=True)
    game.night_acted_uids.add(uid)
    await call.answer("⏭ O'tkazib yubordingiz.", show_alert=False)
    try:
        await call.message.edit_text("⏭ *Harakat o'tkazib yuborildi.*", parse_mode="Markdown")
    except Exception:
        pass
    if game.all_night_actions_done():
        game.cancel_phase_task()
        _safe_task(_do_night_resolution(call.bot, game))


@router.callback_query(F.data.startswith("nkom:"))
async def cb_nkom(call: CallbackQuery):
    _, tid, cid = call.data.split(":")
    game = games.get(int(cid))
    if not game or game.phase != Phase.NIGHT:
        return await call.answer("⚠️ Kecha tugagan.", show_alert=True)
    key = Role.KOMISSAR if game.get_alive_by_role(Role.KOMISSAR) else Role.SERZHANT
    mode = game.night_actions.get("komissar_mode", "check")
    confirm = "🔫 Nishon tanlandi" if mode == "kill" else "🕵🏼 Tekshirilmoqda"
    if mode == "kill":
        atm = "🔫 Komissar pistoletini o'qladi..."
    elif key == Role.SERZHANT:
        atm = "👮🏼 Serjant tungi tekshiruvga yo'l oldi..."
    else:
        atm = "🕵🏼 Komissar tungi tekshiruvga yo'l oldi..."
    await _night_cb(call, key, int(tid), int(cid), confirm, atm)


@router.callback_query(F.data.startswith("nlab:"))
async def cb_nlab(call: CallbackQuery):
    _, tid, cid = call.data.split(":")
    await _night_cb(call, Role.LABARANT, int(tid), int(cid), "🧪 Nishon tanlandi",
                    "🧪 Labarant maxsus eritmasini tayyorlamoqda...")


@router.callback_query(F.data.startswith("ndoc:"))
async def cb_ndoc(call: CallbackQuery):
    _, tid, cid = call.data.split(":")
    await _night_cb(call, Role.DOCTOR, int(tid), int(cid), "💊 Himoyaga olindi",
                    "👨🏼‍⚕️ Doktor kimnidir qutqarish uchun shoshildi...")


@router.callback_query(F.data.startswith("nkez:"))
async def cb_nkez(call: CallbackQuery):
    _, tid, cid = call.data.split(":")
    await _night_cb(call, Role.KEZUVCHI, int(tid), int(cid), "💃 Uyqu dori berildi",
                    "💃 Kezuvchi uyqu dorisini tayyorlamoqda...")


@router.callback_query(F.data.startswith("nday:"))
async def cb_nday(call: CallbackQuery):
    _, tid, cid = call.data.split(":")
    await _night_cb(call, Role.DAYDI, int(tid), int(cid), "🧙‍♂️ Tashrif manzili tanlandi",
                    "🧙‍♂️ Daydi shahar bo'ylab kuzatuv boshladi...")


@router.callback_query(F.data.startswith("nqot:"))
async def cb_nqot(call: CallbackQuery):
    _, tid, cid = call.data.split(":")
    await _night_cb(call, Role.QOTIL, int(tid), int(cid), "🔪 Nishon tanlandi",
                    "🔪 Qotil navbatdagi qurbonini izlamoqda...")


@router.callback_query(F.data.startswith("ntulki:"))
async def cb_ntulki(call: CallbackQuery):
    _, tid, cid = call.data.split(":")
    await _night_cb(call, Role.TULKI, int(tid), int(cid), "🦊 Nishon tanlandi",
                    "🦊 Tulki yangi qiyofasini izlamoqda...")


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
    atm = "🧪 Kimyogar davolash eliksirini tayyorlamoqda..." if mode == "heal" else "☠️ Kimyogar zahar tayyorlamoqda..."
    await _night_cb(call, Role.KIMYOGAR, int(tid), int(cid), f"👨‍🔬 {label} tanlandi", atm)


@router.callback_query(F.data.startswith("nmin:"))
async def cb_nmin(call: CallbackQuery):
    _, tid, cid = call.data.split(":")
    await _night_cb(call, Role.MINIOR, int(tid), int(cid), "☠️ Mina qo'yildi",
                    "☠️ Minyor qorong'ulikdan foydalanib mina o'rnatmoqda...")


@router.callback_query(F.data.startswith("nafer:"))
async def cb_nafer(call: CallbackQuery):
    _, tid, cid = call.data.split(":")
    await _night_cb(call, Role.AFERIST, int(tid), int(cid), "🤹🏻 Shaxs almashtirildi",
                    "🤹🏻 Aferist yangi hiylasini tayyorlamoqda...")


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
    game.night_acted_uids.add(call.from_user.id)
    if tid == actor.user_id:
        await call.answer("🧟 O'zingizni tanladingiz — natija tunda!")
        await call.message.edit_text("🧟 O'zingizni tanladingiz — natija tunda aniqlanadi!")
    else:
        t = game.get_player_by_id(tid)
        await call.answer(f"🧟 {game.get_display_name(t) if t else tid} ro'yxatga qo'shildi")
        await call.message.edit_text(f"🧟 *{game.get_display_name(t) if t else tid}* ro'yxatga qo'shildi.")
    if game.all_night_actions_done():
        _safe_task(_do_night_resolution(call.bot, game))


@router.callback_query(F.data.startswith("jokcard:"))
async def cb_jokcard(call: CallbackQuery):
    """Joker selects which of the 4 face-down cards is the Death Card."""
    _, idx, cid = call.data.split(":")
    idx, cid = int(idx), int(cid)
    game = games.get(cid)
    if not game or game.phase != Phase.NIGHT:
        return await call.answer("⚠️ Kecha tugagan.", show_alert=True)
    actor = game.get_player_by_id(call.from_user.id)
    if not actor or not actor.alive or actor.role != Role.JOKER:
        return await call.answer("⚠️ Bu sizning harakatingiz emas.", show_alert=True)

    game.night_actions["joker_death_card"] = idx
    kb = _target_kb(game, "joktarget", actor_id=actor.user_id)
    await call.message.edit_text(
        f"🤡 *O'lim kartasi tanlandi:* 🎴 *{idx + 1}*\n\n"
        f"Endi 4 ta kartani yuborish uchun maqsadli o'yinchini tanlang:",
        reply_markup=kb,
    )
    await call.answer("🎴 O'lim kartasi tanlandi.")


@router.callback_query(F.data.startswith("joktarget:"))
async def cb_joktarget(call: CallbackQuery):
    """Joker selects the target player for the card game."""
    _, tid, cid = call.data.split(":")
    tid, cid = int(tid), int(cid)
    game = games.get(cid)
    if not game or game.phase != Phase.NIGHT:
        return await call.answer("⚠️ Kecha tugagan.", show_alert=True)
    actor = game.get_player_by_id(call.from_user.id)
    if not actor or not actor.alive or actor.role != Role.JOKER:
        return await call.answer("⚠️ Bu sizning harakatingiz emas.", show_alert=True)
    target = game.get_player_by_id(tid)
    if not target or not target.alive:
        return await call.answer("⚠️ Bu o'yinchi mavjud emas.", show_alert=True)

    death_idx = game.night_actions.get("joker_death_card", 0)
    game.night_actions[Role.JOKER] = tid
    game.night_acted_uids.add(actor.user_id)

    await call.message.edit_text(
        f"✅ *Maqsad tanlandi:* {game.get_display_name(target)}\n\n"
        f"🎴 O'lim kartasi: *{death_idx + 1}*\n"
        f"Kartalar ovoz berish bosqachasida yuboriladi."
    )
    await call.answer("🤡 Maqsad tanlandi.")
    if game.all_night_actions_done():
        _safe_task(_do_night_resolution(call.bot, game))


async def _send_joker_cards(bot: Bot, game: Game, chat_id: int):
    """Send the 4 shuffled cards to the Joker's target at the start of voting."""
    pending = game.joker_pending
    if not pending:
        return
    target = game.get_player_by_id(pending["target"])
    if not target or not target.alive:
        game.joker_pending = None
        game.joker_card_msg_id = None
        return

    cards = list(pending["cards"])  # [0, 1, 2, 3] where one is the death index
    random.shuffle(cards)
    pending["shuffled"] = cards
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🎴 {i+1}", callback_data=f"jokpick:{i}:{chat_id}")]
        for i in range(4)
    ])
    try:
        msg = await bot.send_message(
            target.user_id,
            "🤡 *Joker sizga 4 ta karta yubordi!*\n\n"
            "Bitta karta tanlang. Agar o'lim kartasini tanlasangiz — halok bo'lasiz.\n"
            f"⏳ Ovoz berish tugashiga qadar tanlashingiz kerak!",
            reply_markup=kb,
        )
        game.joker_card_msg_id = msg.message_id
    except Exception:
        pass


async def _resolve_joker_card(bot: Bot, game: Game, chat_id: int, picked_index: int, auto: bool = False):
    """Resolve the Joker card pick: kill if death card, otherwise survive."""
    pending = game.joker_pending
    if not pending:
        return
    target = game.get_player_by_id(pending["target"])
    if not target or not target.alive:
        game.joker_pending = None
        game.joker_card_msg_id = None
        game.joker_pick = None
        return

    if auto:
        is_death = True
    else:
        shuffled = pending.get("shuffled", pending["cards"])
        chosen_card = shuffled[picked_index]
        is_death = (chosen_card == pending["death_index"])
    game.joker_pick = picked_index

    if is_death:
        game.eliminate_player(target.user_id)
        game.votes.pop(target.user_id, None)  # dead players can't vote
        joker = game.get_alive_by_role(Role.JOKER) or next(
            (p for p in game.players.values() if p.role == Role.JOKER), None
        )
        if joker:
            joker.joker_won = True
        await bot.send_message(
            chat_id,
            f"🃏 *Joker xursand!* {game.get_display_name(target)} o'lim kartasini tanladi."
        )
    else:
        await bot.send_message(
            chat_id,
            f"🃏 *Joker xafagarchilikda.* {game.get_display_name(target)} xavfsiz kartani tanladi va omon qoldi."
        )

    # Disable the card buttons on the target's message
    if game.joker_card_msg_id:
        try:
            await bot.edit_message_reply_markup(
                chat_id=target.user_id,
                message_id=game.joker_card_msg_id,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[]),
            )
        except Exception:
            pass

    # Clear temporary data after use
    game.joker_pending = None
    game.joker_card_msg_id = None


@router.callback_query(F.data.startswith("jokpick:"))
async def cb_jokpick(call: CallbackQuery, bot: Bot):
    """The Joker's target picks one of the 4 shuffled cards during voting."""
    _, idx, cid = call.data.split(":")
    idx, cid = int(idx), int(cid)
    game = games.get(cid)
    if not game or game.phase != Phase.VOTING:
        return await call.answer("⚠️ Ovoz berish tugagan.", show_alert=True)
    if not game.joker_pending or call.from_user.id != game.joker_pending.get("target"):
        return await call.answer("⚠️ Bu kartalar siz uchun emas.", show_alert=True)
    if game.joker_pick is not None:
        return await call.answer("⚠️ Siz allaqachon kartani tanladingiz.", show_alert=True)
    await call.answer("🎴 Karta tanlandi.")
    await call.message.edit_text("🎴 Karta tanlandi. Natija guruhda e'lon qilinadi.")
    await _resolve_joker_card(bot, game, cid, idx)


@router.callback_query(F.data.startswith("nsot:"))
async def cb_nsot(call: CallbackQuery):
    _, tid, cid = call.data.split(":")
    tid, cid = int(tid), int(cid)
    game = games.get(cid)
    if not game or game.phase != Phase.NIGHT:
        return await call.answer("⚠️ Kecha tugagan.", show_alert=True)
    game.night_actions[Role.SOTQIN] = tid
    game.night_acted_uids.add(call.from_user.id)
    if tid == 0:
        await call.answer("🤓 O'tkazib yubordingiz.")
        await call.message.edit_text("🤓 Bu kecha o'tkazib yubordingiz.")
    else:
        t = game.get_player_by_id(tid)
        await call.answer(f"🤓 Nishon tanlandi")
        await call.message.edit_text(f"🤓 Nishon tanlandi: *{game.get_display_name(t) if t else tid}*")
    if game.all_night_actions_done():
        _safe_task(_do_night_resolution(call.bot, game))


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
        _safe_task(_do_night_resolution(call.bot, game))


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
    _vote_label = "👍 Ha" if choice == "like" else "👎 Yo'q"
    await call.answer(f"✅ {_vote_label} bosdingiz")
    try:
        await call.message.edit_reply_markup(
            reply_markup=_like_dislike_kb(likes, dislikes)
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

    try:
        voter_m = _player_mention_html(game, voter)
        target_m = _player_mention_html(game, target)
        await _safe_send(
            bot, cid,
            f"🗳️ {voter_m} — {target_m}ga ovoz berdi.",
            parse_mode="HTML",
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
            f"💣 *Afsungar* jahannamga ketayotib *{game.get_display_name(target)}*ni ham olib ketdi!\n"
            f"Roli: {em} *{rn}*"
        )
        await call.answer()
        winner = game.check_win_condition()
        if winner:
            _safe_task(_end_game(call.bot, game, winner))
            return

    game.day_number += 1
    _safe_task(run_night(call.bot, game.chat_id))


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
    game.night_acted_uids.add(uid)

    p = await get_profile(uid, call.from_user.first_name)

    if typ == "diamond":
        await add_diamond(uid, amount)
        result = f"💎 *{amount} olmos* topdingiz!"
        detail = f"Umumiy olmos: {p.diamond + amount} 💎"
        game.konchi_morning_msg = f"⛏️ Konchi tunda {amount} olmos topdi."
    elif typ == "money":
        await add_dollar(uid, amount)
        result = f"💵 *{amount}$* topdingiz!"
        detail = f"Umumiy dollar: {p.dollar + amount}$"
        game.konchi_morning_msg = f"⛏️ Konchi tunda {amount}$ pul topdi."
    else:
        game.night_actions["konchi_mine"] = True
        p.mines += 1
        await save_profile(p)
        result = "💣 *MINAGA TUSHDINGIZ!*"
        detail = "Bu kecha halok bo'lasiz..."
        game.konchi_morning_msg = "⛏️ Konchi tunda minaga tushdi!"

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

    if game.all_night_actions_done():
        _safe_task(_do_night_resolution(call.bot, game))


# ── Qaroqchi night action callbacks (single action per night) ──

@router.callback_query(F.data.startswith("nrais:"))
async def cb_nrais(call: CallbackQuery):
    _, tid, cid = call.data.split(":")
    await _night_cb(call, Role.RAIS, int(tid), int(cid), "💰 Sovg'a manzili tanlandi",
                    "💰 Rais kechalik sovg'asini tayyorlamoqda...")


@router.callback_query(F.data.startswith("naygoychi:"))
async def cb_naygoychi(call: CallbackQuery):
    _, tid, cid = call.data.split(":")
    await _night_cb(call, Role.AYGOQCHI, int(tid), int(cid), "🦇 Nishon tanlandi",
                    "🦇 Ayg'oqchi qorong'ulikda ov boshladi...")


@router.callback_query(F.data.startswith("nkoldun:"))
async def cb_nkoldun(call: CallbackQuery):
    _, tid, cid = call.data.split(":")
    await _night_cb(call, Role.KOLDUN, int(tid), int(cid), "🧙 Nishon tanlandi",
                    "🧙 Koldun sehri bilan harakat qilmoqda...")


@router.callback_query(F.data.startswith("qar_mode:"))
async def cb_qar_mode(call: CallbackQuery):
    """Qaroqchi selects the action type (steal or attack)."""
    _, mode, cid = call.data.split(":")
    cid = int(cid)
    game = games.get(cid)
    if not game or game.phase != Phase.NIGHT:
        return await call.answer("⚠️ Kecha tugagan.", show_alert=True)
    actor = game.get_player_by_id(call.from_user.id)
    if not actor or not actor.alive or actor.role != Role.QAROQCHI:
        return await call.answer("⚠️ Bu sizning harakatingiz emas.", show_alert=True)
    if "qaroqchi_action" in game.night_actions:
        return await call.answer("⚠️ Siz allaqachon amal tanladingiz.", show_alert=True)

    game.night_actions["qaroqchi_mode"] = mode
    label = "💰 Pul o'g'irlash" if mode == "steal" else "⚔️ Jon olish"
    kb = _target_kb(game, "qar_t", actor_id=actor.user_id)
    await call.message.edit_text(
        f"🏴‍☠️ *{label}* — Nishon tanlang:",
        reply_markup=kb,
    )
    await call.answer()


@router.callback_query(F.data.startswith("qar_t:"))
async def cb_qar_t(call: CallbackQuery):
    """Qaroqchi selects the target and locks the single action for this night."""
    _, tid, cid = call.data.split(":")
    tid, cid = int(tid), int(cid)
    game = games.get(cid)
    if not game or game.phase != Phase.NIGHT:
        return await call.answer("⚠️ Kecha tugagan.", show_alert=True)
    actor = game.get_player_by_id(call.from_user.id)
    if not actor or not actor.alive or actor.role != Role.QAROQCHI:
        return await call.answer("⚠️ Bu sizning harakatingiz emas.", show_alert=True)
    if "qaroqchi_action" in game.night_actions:
        return await call.answer("⚠️ Siz allaqachon amal tanladingiz.", show_alert=True)
    target = game.get_player_by_id(tid)
    if not target or not target.alive:
        return await call.answer("⚠️ Bu o'yinchi mavjud emas.", show_alert=True)

    mode = game.night_actions.get("qaroqchi_mode", "steal")
    game.night_actions["qaroqchi_action"] = (mode, tid)
    game.night_actions[Role.QAROQCHI] = True
    game.night_actions[actor.user_id] = True
    game.night_acted_uids.add(call.from_user.id)

    label = "💰 Pul o'g'irlash" if mode == "steal" else "⚔️ Jon olish"
    await call.message.edit_text(
        f"✅ *Qaroqchi amali tanlandi!*\n\n"
        f"*{label}* → *{game.get_display_name(target)}*\n\n"
        f"Bu kecha boshqa amal tanlay olmaysiz. Natija ertalab ma'lum bo'ladi."
    )
    await call.answer("✅ Amal tanlandi!")
    atm = "🏴‍☠️ Qaroqchi kimnidir tunamoqda..." if mode == "steal" else "🥊 Qaroqchi kimnidir kaltaklamoqda..."
    await _atmosphere(call.bot, cid, atm)
    if game.all_night_actions_done():
        _safe_task(_do_night_resolution(call.bot, game))


# ──────────────────────────────────────────────
# Auto-delete dead/spectator messages
# ──────────────────────────────────────────────

def _is_not_command(msg: Message) -> bool:
    """True unless the message is a bot command.

    Used to keep the catch-all group/private handlers below from matching
    (and thereby swallowing) commands — including ones only registered on
    other routers, like /vsgame. Without this, aiogram stops propagating
    an update once ANY handler's filters match, so an unfiltered catch-all
    would prevent commands defined elsewhere from ever being reached.
    """
    return not (msg.text and msg.text.startswith("/"))


@router.message(F.chat.type.in_({"group", "supergroup"}), _is_not_command)
async def auto_delete_handler(msg: Message, bot: Bot):
    """Auto-delete messages from dead players, spectators, and Kezuvchi-blocked players."""
    chat_id = msg.chat.id
    game = games.get(chat_id)

    # Kezuvchi-blocked player: delete silently, no warning
    if game and msg.from_user and game.kezuvchi_restricted_uid == msg.from_user.id:
        if game.phase in (Phase.DAY, Phase.VOTING):
            try:
                await bot.delete_message(chat_id, msg.message_id)
            except Exception:
                pass
            return

    settings = await get_settings(chat_id)
    if not settings.auto_delete_dead:
        return

    if not game or game.phase in (Phase.LOBBY, Phase.ENDED):
        return

    # Allow messages starting with "!"
    text = msg.text or msg.caption or ""
    if text.startswith("!"):
        return

    if not msg.from_user:
        return

    user_id = msg.from_user.id
    player = game.get_player_by_id(user_id)

    should_delete = False
    if player is None:
        # Spectator (not in this game)
        should_delete = True
    elif not player.alive:
        # Dead player
        should_delete = True

    if should_delete:
        try:
            await bot.delete_message(chat_id, msg.message_id)
        except Exception:
            pass


# ──────────────────────────────────────────────
# Hero tizimi — buyruqlar va callbacklar
# ──────────────────────────────────────────────

@router.message(Command("hero"))
async def cmd_hero(msg: Message):
    uid  = msg.from_user.id
    hero = await get_hero(uid)
    if hero:
        await msg.answer(_hero_text(hero), reply_markup=_hero_panel_kb("noop", hero_level=hero.level), parse_mode="Markdown")
    else:
        await msg.answer(
            "🦸 *Sizda hali Geroy mavjud emas.*\n\n"
            "Geroy o'yinda kunduzi dushmanlarga hujum qilish imkonini beradi.\n\n"
            f"💰 Narxi: *{HERO_BUY_COST}💎*",
            reply_markup=_no_hero_kb("noop"),
            parse_mode="Markdown",
        )


@router.message(Command("herogive"))
async def cmd_herogive(msg: Message, bot: Bot):
    uid = msg.from_user.id

    # OWNER: maxsus parametrlar bilan istalgan foydalanuvchiga geroy beradi
    if uid == OWNER_ID:
        parts = msg.text.split()
        if len(parts) < 2:
            return await msg.answer(
                "❓ Foydalanish: `/herogive {user_id} [name:Ism] [level:N] [xp:N] [hp:N] [charges:N]`",
                parse_mode="Markdown",
            )
        try:
            target_id = int(parts[1])
        except ValueError:
            return await msg.answer("❌ User ID raqam bo'lishi kerak.")
        kwargs: dict = {}
        for part in parts[2:]:
            if ":" in part:
                k, v = part.split(":", 1)
                kwargs[k.lower()] = v
        hero = Hero(
            user_id=target_id,
            name=kwargs.get("name", "Geroy"),
            level=int(kwargs.get("level", 1)),
            xp=int(kwargs.get("xp", 0)),
            hp=int(kwargs.get("hp", MAX_HP)),
            charges=int(kwargs.get("charges", MAX_CHARGES)),
        )
        await save_hero(hero)
        return await msg.answer(
            f"✅ *{target_id}*ga Geroy berildi:\n"
            f"🥷 Nom: *{escape_md(hero.name)}*  ⭐ Daraja: *{hero.level}*\n"
            f"🛡 HP: *{hero.hp}*  🩸 Zaryad: *{hero.charges}*",
            parse_mode="Markdown",
        )

    # Oddiy foydalanuvchi: reply orqali boshqasiga o'z geroyini o'tkazadi
    hero = await get_hero(uid)
    if not hero:
        return await msg.answer("❌ Sizda Geroy yo'q — o'tkazishga narsa yo'q.")
    if not msg.reply_to_message or not msg.reply_to_message.from_user:
        return await msg.answer(
            "📌 Geroyni o'tkazish uchun boshqa o'yinchining xabariga *reply* qiling.",
            parse_mode="Markdown",
        )
    target = msg.reply_to_message.from_user
    if target.id == uid:
        return await msg.answer("❌ O'z-o'zingizga o'tkaza olmaysiz.")
    if target.is_bot:
        return await msg.answer("❌ Botga o'tkaza olmaysiz.")
    await delete_hero(uid)
    hero.user_id = target.id
    await save_hero(hero)
    await msg.answer(
        f"✅ Geroy *{escape_md(target.first_name)}*ga muvaffaqiyatli o'tkazildi!\n"
        f"🥷 Nom: *{escape_md(hero.name)}*  ⭐ Daraja: *{hero.level}*",
        parse_mode="Markdown",
    )
    try:
        await bot.send_message(
            target.id,
            f"🎁 *{escape_md(msg.from_user.first_name)}* sizga Geroy o'tkazdi!\n"
            f"🥷 Nom: *{escape_md(hero.name)}*  ⭐ Daraja: *{hero.level}*",
            parse_mode="Markdown",
        )
    except Exception:
        pass


@router.message(Command("geroy"))
async def cmd_geroy(msg: Message):
    """OWNER only: /geroy <daraja> <user_id> — creates/updates hero at given level."""
    if msg.from_user.id != OWNER_ID:
        return
    parts = msg.text.split()
    if len(parts) < 3:
        return await msg.answer(
            "❓ Foydalanish: `/geroy <daraja> <user_id>`",
            parse_mode="Markdown",
        )
    try:
        level   = int(parts[1])
        user_id = int(parts[2])
    except ValueError:
        return await msg.answer("❌ Daraja va user_id raqam bo'lishi kerak.")
    if level < 1:
        return await msg.answer("❌ Daraja 1 dan kichik bo'lishi mumkin emas.")
    hero = await get_hero(user_id) or Hero(user_id=user_id)
    hero.level = level
    hero.xp    = hero_level_threshold(level)
    await save_hero(hero)
    await msg.answer(
        f"✅ *{user_id}* uchun Geroy darajasi *{level}* ga o'rnatildi.",
        parse_mode="Markdown",
    )


# ── Profile navigation callbacks ──────────────────────────────

@router.callback_query(F.data == "cb_profile_hero")
async def cb_profile_hero(call: CallbackQuery):
    await call.answer()
    uid  = call.from_user.id
    hero = await get_hero(uid)
    if hero:
        text = _hero_text(hero)
        kb   = _hero_panel_kb("cb_profile_back")
    else:
        text = (
            "🦸 *Sizda hali Geroy mavjud emas.*\n\n"
            "Geroy o'yinda kunduzi dushmanlarga hujum qilish imkonini beradi.\n\n"
            f"💰 Narxi: *{HERO_BUY_COST}💎*"
        )
        kb = _no_hero_kb("cb_profile_back")
    try:
        await call.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
    except Exception:
        pass


@router.callback_query(F.data == "cb_profile_missions")
async def cb_profile_missions(call: CallbackQuery):
    await call.answer()
    uid  = call.from_user.id
    hero = await get_hero(uid)
    back_kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="◀️ Orqaga", callback_data="cb_profile_back")
    ]])
    if not hero:
        try:
            await call.message.edit_text(
                "🦸 Sizda Geroy yo'q — missiyalar mavjud emas.",
                reply_markup=back_kb,
                parse_mode="Markdown",
            )
        except Exception:
            pass
        return
    try:
        await call.message.edit_text(
            _missions_text(hero),
            reply_markup=back_kb,
            parse_mode="Markdown",
        )
    except Exception:
        pass


@router.callback_query(F.data == "cb_profile_back")
async def cb_profile_back(call: CallbackQuery):
    await call.answer()
    try:
        await call.message.edit_text(
            await _profile_text(call.from_user.id, call.from_user.first_name),
            reply_markup=_profile_nav_kb(),
            parse_mode="Markdown",
        )
    except Exception:
        pass


# ── Hero panel action callbacks ───────────────────────────────

@router.callback_query(F.data == "hero_info")
async def cb_hero_info(call: CallbackQuery):
    await call.answer()
    try:
        await call.message.edit_text(
            "🦸 *Geroy nima?*\n\n"
            "Geroy — o'yin davomida kunduzi tirik o'yinchilarga hujum qilish imkonini beruvchi maxsus qahramon.\n\n"
            f"👊 Zarba kuchi: *40–50 HP* (1-darajada)\n"
            f"🛡 Maksimal himoya: *{MAX_HP} HP*\n"
            f"🩸 Maksimal zaryad: *{MAX_CHARGES} ta*\n\n"
            f"💰 Sotib olish narxi: *{HERO_BUY_COST}💎*\n\n"
            "Geroy profilda doimiy saqlanadi. Har bir o'yin kunida bir marta hujum qilish mumkin.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text=f"💰 Sotib olish ({HERO_BUY_COST}💎)",
                    callback_data="hero_buy")],
                [InlineKeyboardButton(text="◀️ Orqaga", callback_data="cb_profile_back")],
            ]),
            parse_mode="Markdown",
        )
    except Exception:
        pass


@router.callback_query(F.data == "hero_buy")
async def cb_hero_buy(call: CallbackQuery):
    uid = call.from_user.id
    existing = await get_hero(uid)
    if existing:
        return await call.answer("✅ Sizda allaqachon Geroy bor!", show_alert=True)
    ok = await spend_diamond(uid, HERO_BUY_COST)
    if not ok:
        p = await get_profile(uid)
        return await call.answer(
            f"❌ Yetarli olmos yo'q!\nKerak: {HERO_BUY_COST}💎  |  Sizda: {p.diamond}💎",
            show_alert=True,
        )
    hero = Hero(user_id=uid)
    await save_hero(hero)
    await call.answer("🎉 Geroy sotib olindi!", show_alert=False)
    try:
        await call.message.edit_text(
            _hero_text(hero),
            reply_markup=_hero_panel_kb("cb_profile_back", hero_level=1),
            parse_mode="Markdown",
        )
    except Exception:
        pass


@router.callback_query(F.data == "hero_recharge")
async def cb_hero_recharge(call: CallbackQuery):
    uid  = call.from_user.id
    hero = await get_hero(uid)
    if not hero:
        return await call.answer("❌ Sizda Geroy yo'q.", show_alert=True)
    if hero.charges >= MAX_CHARGES:
        return await call.answer(
            f"🩸 Zaryad allaqachon to'la ({MAX_CHARGES}/{MAX_CHARGES}).", show_alert=True
        )
    ok = await spend_dollar(uid, CHARGE_RESTORE_COST)
    if not ok:
        p = await get_profile(uid)
        return await call.answer(
            f"❌ Yetarli dollar yo'q!\nKerak: {CHARGE_RESTORE_COST}💶  |  Sizda: {p.dollar}💶",
            show_alert=True,
        )
    hero.charges = MAX_CHARGES
    await save_hero(hero)
    await call.answer(f"✅ Zaryad to'ldirildi! 🩸 {MAX_CHARGES}/{MAX_CHARGES}", show_alert=False)
    try:
        await call.message.edit_text(
            _hero_text(hero), reply_markup=_hero_panel_kb("cb_profile_back", hero_level=hero.level), parse_mode="Markdown"
        )
    except Exception:
        pass


@router.callback_query(F.data == "hero_restore")
async def cb_hero_restore(call: CallbackQuery):
    uid  = call.from_user.id
    hero = await get_hero(uid)
    if not hero:
        return await call.answer("❌ Sizda Geroy yo'q.", show_alert=True)
    if hero.hp >= MAX_HP:
        return await call.answer(
            f"🛡 Himoya allaqachon to'la ({MAX_HP}/{MAX_HP}).", show_alert=True
        )
    ok = await spend_dollar(uid, HP_RESTORE_COST)
    if not ok:
        p = await get_profile(uid)
        return await call.answer(
            f"❌ Yetarli dollar yo'q!\nKerak: {HP_RESTORE_COST}💶  |  Sizda: {p.dollar}💶",
            show_alert=True,
        )
    hero.hp = MAX_HP
    await save_hero(hero)
    await call.answer(f"✅ Himoya tiklandi! 🛡 {MAX_HP}/{MAX_HP}", show_alert=False)
    try:
        await call.message.edit_text(
            _hero_text(hero), reply_markup=_hero_panel_kb("cb_profile_back", hero_level=hero.level), parse_mode="Markdown"
        )
    except Exception:
        pass


@router.callback_query(F.data == "hero_buy_xp")
async def cb_hero_buy_xp(call: CallbackQuery):
    uid  = call.from_user.id
    hero = await get_hero(uid)
    if not hero:
        return await call.answer("❌ Sizda Geroy yo'q.", show_alert=True)
    ok = await spend_dollar(uid, XP_BUY_COST)
    if not ok:
        p = await get_profile(uid)
        return await call.answer(
            f"❌ Yetarli dollar yo'q!\nKerak: {XP_BUY_COST}💶  |  Sizda: {p.dollar}💶",
            show_alert=True,
        )
    hero.xp    += XP_BUY_AMOUNT
    hero.level  = hero_level_from_xp(hero.xp)
    awards = await check_and_award_missions(hero)
    await save_hero(hero)
    msg_txt = f"✅ +{XP_BUY_AMOUNT} ball qo'shildi!"
    if awards:
        msg_txt += "\n\n🎉 Missiya:\n" + "\n".join(awards)
    await call.answer(msg_txt[:200], show_alert=bool(awards))
    try:
        await call.message.edit_text(
            _hero_text(hero), reply_markup=_hero_panel_kb("cb_profile_back", hero_level=hero.level), parse_mode="Markdown"
        )
    except Exception:
        pass


@router.callback_query(F.data == "hero_upgrade")
async def cb_hero_upgrade(call: CallbackQuery):
    uid  = call.from_user.id
    hero = await get_hero(uid)
    if not hero:
        return await call.answer("❌ Sizda Geroy yo'q.", show_alert=True)
    cost = hero_upgrade_cost(hero.level)
    ok   = await spend_diamond(uid, cost)
    if not ok:
        p = await get_profile(uid)
        return await call.answer(
            f"❌ Yetarli olmos yo'q!\nKerak: {cost}💎  |  Sizda: {p.diamond}💎",
            show_alert=True,
        )
    hero.level += 1
    hero.xp     = hero_level_threshold(hero.level)
    await save_hero(hero)
    await call.answer(f"✅ Daraja oshirildi! ⭐ {hero.level}-daraja", show_alert=False)
    try:
        await call.message.edit_text(
            _hero_text(hero),
            reply_markup=_hero_panel_kb("cb_profile_back", hero_level=hero.level),
            parse_mode="Markdown",
        )
    except Exception:
        pass


@router.callback_query(F.data == "hero_rename")
async def cb_hero_rename(call: CallbackQuery):
    uid  = call.from_user.id
    hero = await get_hero(uid)
    if not hero:
        return await call.answer("❌ Sizda Geroy yo'q.", show_alert=True)
    ok = await spend_dollar(uid, NAME_CHANGE_COST)
    if not ok:
        p = await get_profile(uid)
        return await call.answer(
            f"❌ Yetarli dollar yo'q!\nKerak: {NAME_CHANGE_COST}💶  |  Sizda: {p.dollar}💶",
            show_alert=True,
        )
    _pending_hero_rename.add(uid)
    await call.answer("✅ To'lov qabul qilindi. Nomni yozing.", show_alert=False)
    try:
        await call.message.edit_text(
            "🖋 *Geroyingizning yangi nomini yozing:*\n_(Maksimal 32 belgi)_",
            parse_mode="Markdown",
        )
    except Exception:
        pass


@router.callback_query(F.data == "hero_transfer")
async def cb_hero_transfer(call: CallbackQuery):
    uid  = call.from_user.id
    hero = await get_hero(uid)
    if not hero:
        return await call.answer("❌ Sizda Geroy yo'q.", show_alert=True)
    _pending_hero_transfer.add(uid)
    await call.answer()
    try:
        await call.message.edit_text(
            "🔄 *Geroyni o'tkazish*\n\n"
            "Qabul qiluvchining *user ID*sini yozing.\n"
            "_(Bekor qilish uchun /cancel yozing)_",
            parse_mode="Markdown",
        )
    except Exception:
        pass


@router.callback_query(F.data == "noop")
async def cb_noop(call: CallbackQuery):
    await call.answer()


# ── Hero attack (kun fazasi) ──────────────────────────────────

@router.callback_query(F.data.startswith("hero_attack_kb:"))
async def cb_hero_attack_kb(call: CallbackQuery):
    """Nishon tanlash klaviaturasini ko'rsatadi."""
    cid  = int(call.data.split(":")[1])
    uid  = call.from_user.id
    game = games.get(cid)

    if not game or game.phase != Phase.DAY:
        return await call.answer("❌ Hozir hujum qilish mumkin emas.", show_alert=True)

    _settings_hero = await get_settings(cid)
    if not _settings_hero.hero_enabled:
        return await call.answer("❌ Bu guruhda Geroy tizimi o'chirilgan.", show_alert=True)
    player = game.get_player_by_id(uid)
    if not player or not player.alive:
        return await call.answer("❌ Siz o'yinda yo'qsiz.", show_alert=True)
    if player.role not in HERO_ROLES:
        return await call.answer("❌ Sizning rolingiz Geroydan foydalana olmaydi.", show_alert=True)
    if uid in game.hero_used_today:
        return await call.answer("❌ Siz bugun allaqachon hujum qildingiz.", show_alert=True)

    hero = await get_hero(uid)
    if not hero or hero.charges <= 0:
        return await call.answer("❌ Zaryad yo'q! Zaryadlash uchun /hero.", show_alert=True)

    targets = [p for p in game.alive_players() if p.user_id != uid]
    if not targets:
        return await call.answer("❌ Nishon yo'q.", show_alert=True)

    rows = []
    for p in targets:
        rows.append([InlineKeyboardButton(
            text=game.get_display_name(p),
            callback_data=f"hero_attack:{p.user_id}:{cid}",
        )])
    rows.append([InlineKeyboardButton(text="❌ Bekor qilish", callback_data="hero_attack_cancel")])

    await call.answer()
    try:
        await call.message.edit_text(
            f"🦸 *{escape_md(hero.name)}* — nishon tanlang:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
            parse_mode="Markdown",
        )
    except Exception:
        pass


@router.callback_query(F.data == "hero_attack_cancel")
async def cb_hero_attack_cancel(call: CallbackQuery):
    await call.answer("Bekor qilindi.")
    try:
        await call.message.delete()
    except Exception:
        pass


@router.callback_query(F.data.startswith("hero_attack:"))
async def cb_hero_attack(call: CallbackQuery, bot: Bot):
    """Tanlangan nishonga geroy hujumini bajaradi."""
    parts      = call.data.split(":")
    target_uid = int(parts[1])
    cid        = int(parts[2])
    uid        = call.from_user.id
    game       = games.get(cid)

    if not game or game.phase != Phase.DAY:
        return await call.answer("❌ Hujum vaqti o'tdi.", show_alert=True)
    player = game.get_player_by_id(uid)
    if not player or not player.alive:
        return await call.answer("❌ Siz o'yinda yo'qsiz.", show_alert=True)
    if player.role not in HERO_ROLES:
        return await call.answer("❌ Sizning rolingiz bu imkoniyatdan foydalana olmaydi.", show_alert=True)
    if uid in game.hero_used_today:
        return await call.answer("❌ Bugun allaqachon hujum qildingiz.", show_alert=True)

    _settings_hero_a = await get_settings(cid)
    if not _settings_hero_a.hero_enabled:
        return await call.answer("❌ Bu guruhda Geroy tizimi o'chirilgan.", show_alert=True)

    hero = await get_hero(uid)
    if not hero or hero.charges <= 0:
        return await call.answer("❌ Zaryad tugagan! /hero orqali zaryadlang.", show_alert=True)

    target = game.get_player_by_id(target_uid)
    if not target or not target.alive:
        return await call.answer("❌ Nishon allaqachon hayotda emas.", show_alert=True)

    await call.answer()

    # hero_protect itemini tekshirish
    tp = await get_profile(target_uid)
    if tp.hero_protect > 0:
        tp.hero_protect -= 1
        await save_profile(tp)
        game.hero_used_today.add(uid)
        hero.charges      -= 1
        hero.total_attacks += 1
        hero.xp           += XP_PER_ATTACK
        hero.level         = hero_level_from_xp(hero.xp)
        await save_hero(hero)
        try:
            await call.message.edit_text(
                "🔰 Nishon Geroydan himoyalangan edi!\n"
                "Himoya blokni tutib oldi. Zaryad sarflandi.",
                parse_mode="Markdown",
            )
        except Exception:
            pass
        return

    # Zarar
    damage = hero_damage(hero.level)
    target.hp -= damage
    game.hero_used_today.add(uid)
    hero.charges      -= 1
    hero.total_attacks += 1
    hero.xp           += XP_PER_ATTACK
    hero.level         = hero_level_from_xp(hero.xp)

    t_em  = ROLE_EMOJIS.get(target.role, "")
    t_rn  = ROLE_NAMES_UZ.get(target.role, "")
    a_em  = ROLE_EMOJIS.get(player.role, "")
    a_rn  = ROLE_NAMES_UZ.get(player.role, "")
    t_disp = game.get_display_name(target)

    if target.hp <= 0:
        # Nishon yo'q qilindi
        game.eliminate_player(target_uid)
        hero.kills += 1
        awards = await check_and_award_missions(hero)
        await save_hero(hero)

        group_msg = (
            f"⚰️ {t_em} *{t_disp}*ni\n"
            f"{a_em} *{a_rn}* o'zining "
            f"*{escape_md(hero.name)}* geroyi bilan yer tishlatdi!"
        )
        await _safe_send(bot, cid, group_msg, parse_mode="Markdown")

        dm_text = f"☠️ *{t_disp}* ({t_em} {t_rn}) yo'q qilindi!\n🩸 Qolgan zaryad: *{hero.charges}/{MAX_CHARGES}*"
        if awards:
            dm_text += "\n\n🎉 Missiya:\n" + "\n".join(awards)
        try:
            await call.message.edit_text(dm_text, parse_mode="Markdown")
        except Exception:
            pass

        await _send_last_words_dm(bot, game, target_uid)
        winner = game.check_win_condition()
        if winner:
            _safe_task(_end_game(bot, game, winner))
    else:
        awards = await check_and_award_missions(hero)
        await save_hero(hero)

        group_msg = (
            f"🦸 *{escape_md(hero.name)}* geroyi zarba berdi!\n\n"
            f"{a_em} {a_rn} ➜ {t_em} *{t_disp}*\n"
            f"❤️ Yo'qotilgan HP: *{damage}*\n"
            "Nishon tirik qoldi."
        )
        await _safe_send(bot, cid, group_msg, parse_mode="Markdown")

        dm_text = (
            f"✅ Hujum bajarildi!\n"
            f"❤️ Yo'qotilgan HP: *{damage}*\n"
            f"🩸 Qolgan zaryad: *{hero.charges}/{MAX_CHARGES}*"
        )
        if awards:
            dm_text += "\n\n🎉 Missiya:\n" + "\n".join(awards)
        try:
            await call.message.edit_text(dm_text, parse_mode="Markdown")
        except Exception:
            pass


# ── Sandiq (Chest) callbacks ──────────────────────────────────

@router.callback_query(F.data.startswith("open_sandiq:"))
async def cb_open_sandiq(call: CallbackQuery, bot: Bot):
    """End-game tugmasidan: foydalanuvchiga DM sandiq tanlash klaviaturasini yuboradi."""
    await call.answer()
    uid  = call.from_user.id
    cid  = int(call.data.split(":")[1])

    can_oltin, remaining = await can_open_oltin(uid)
    oltin_label = (
        f"🟡 Oltin sandiq ({OLTIN_COST}💎) — {remaining}/{OLTIN_LIMIT} qoldi"
        if can_oltin else
        f"🟡 Oltin sandiq — bugungi limit tugadi"
    )
    rows = [
        [InlineKeyboardButton(
            text=f"⬜ Oddiy sandiq ({ODDIY_COST}💶)",
            callback_data=f"sandiq_type:oddiy:{cid}")],
        [InlineKeyboardButton(
            text=f"🟣 Noyob sandiq ({NOYOB_COST}💶)",
            callback_data=f"sandiq_type:noyob:{cid}")],
        [InlineKeyboardButton(
            text=oltin_label,
            callback_data=f"sandiq_type:oltin:{cid}" if can_oltin else "noop")],
        [InlineKeyboardButton(text="❌ Yopish", callback_data="sandiq_close")],
    ]
    try:
        await bot.send_message(
            uid,
            "📦 *Sandiq ochish*\n\nQaysi sandiqni ochmoqchisiz?",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
            parse_mode="Markdown",
        )
        await call.answer("📬 DM ga sandiq yuborildi!", show_alert=False)
    except Exception:
        await call.answer("❌ Avval botga /start yuboring.", show_alert=True)


@router.callback_query(F.data.startswith("sandiq_type:"))
async def cb_sandiq_type(call: CallbackQuery):
    """Sandiq turi tanlandi — to'lov amalga oshiriladi va 6 quti ko'rsatiladi."""
    parts      = call.data.split(":")
    chest_type = parts[1]          # oddiy / noyob / oltin
    uid        = call.from_user.id

    # To'lov
    if chest_type == "oddiy":
        ok = await spend_dollar(uid, ODDIY_COST)
        if not ok:
            p = await get_profile(uid)
            return await call.answer(
                f"❌ Yetarli dollar yo'q!\nKerak: {ODDIY_COST}💶  |  Sizda: {p.dollar}💶",
                show_alert=True,
            )
    elif chest_type == "noyob":
        ok = await spend_dollar(uid, NOYOB_COST)
        if not ok:
            p = await get_profile(uid)
            return await call.answer(
                f"❌ Yetarli dollar yo'q!\nKerak: {NOYOB_COST}💶  |  Sizda: {p.dollar}💶",
                show_alert=True,
            )
    elif chest_type == "oltin":
        can, _ = await can_open_oltin(uid)
        if not can:
            return await call.answer("❌ Bugungi oltin sandiq limitiga yetdingiz.", show_alert=True)
        ok = await spend_diamond(uid, OLTIN_COST)
        if not ok:
            p = await get_profile(uid)
            return await call.answer(
                f"❌ Yetarli olmos yo'q!\nKerak: {OLTIN_COST}💎  |  Sizda: {p.diamond}💎",
                show_alert=True,
            )
        await record_oltin_open(uid)
    else:
        return await call.answer("❌ Noto'g'ri sandiq turi.", show_alert=True)

    session = start_session(uid, chest_type)
    picks   = session["picks_left"]

    # 6 ta quti tugmasi
    rows = []
    for i in range(6):
        rows.append([InlineKeyboardButton(
            text="📦",
            callback_data=f"sandiq_pick:{i}",
        )])
    # 2 ustunli tartib: 3 qator × 2
    rows_2col = []
    flat = [InlineKeyboardButton(text="📦", callback_data=f"sandiq_pick:{i}") for i in range(6)]
    for i in range(0, 6, 2):
        rows_2col.append(flat[i:i+2])

    type_name = {"oddiy": "⬜ Oddiy", "noyob": "🟣 Noyob", "oltin": "🟡 Oltin"}.get(chest_type, chest_type)
    await call.answer()
    try:
        await call.message.edit_text(
            f"📦 *{type_name} sandiq*\n\n{picks} ta quti tanlashingiz mumkin.\nQutini tanlang:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows_2col),
            parse_mode="Markdown",
        )
    except Exception:
        pass


@router.callback_query(F.data.startswith("sandiq_pick:"))
async def cb_sandiq_pick(call: CallbackQuery):
    """Quti tanlandi — natija ko'rsatiladi."""
    idx = int(call.data.split(":")[1])
    uid = call.from_user.id

    session = get_session(uid)
    if not session:
        return await call.answer("❌ Sessiya tugagan. Qayta boshlang.", show_alert=True)

    if idx in session["picked"]:
        return await call.answer("❌ Bu quti allaqachon ochilgan.", show_alert=True)

    session["picked"].append(idx)
    session["picks_left"] -= 1

    reward_text = await apply_box_reward(uid, session["boxes"][idx])

    if session["picks_left"] > 0:
        # Hali tanlashlar qoldi — qutini ochiq ko'rsat, boshqalari yopiq
        flat = []
        for i in range(6):
            if i in session["picked"]:
                label = box_emoji(session["boxes"][i], revealed=True)
            else:
                label = "📦"
            flat.append(InlineKeyboardButton(
                text=label,
                callback_data=f"sandiq_pick:{i}" if i not in session["picked"] else "noop",
            ))
        rows_2col = [flat[i:i+2] for i in range(0, 6, 2)]
        await call.answer(f"✅ {reward_text}", show_alert=False)
        try:
            await call.message.edit_reply_markup(
                reply_markup=InlineKeyboardMarkup(inline_keyboard=rows_2col)
            )
        except Exception:
            pass
    else:
        # Barcha tanlashlar tugadi — hammasini ko'rsat
        clear_session(uid)
        flat = []
        for i in range(6):
            if i in session["picked"]:
                label = box_emoji(session["boxes"][i], revealed=True)
            else:
                label = box_emoji(session["boxes"][i], revealed=True)  # reveal all at end
            flat.append(InlineKeyboardButton(text=label, callback_data="noop"))
        rows_2col = [flat[i:i+2] for i in range(0, 6, 2)]

        type_name = {"oddiy": "⬜ Oddiy", "noyob": "🟣 Noyob", "oltin": "🟡 Oltin"}.get(
            session["type"], session["type"]
        )
        await call.answer(f"🎉 {reward_text}", show_alert=True)
        try:
            await call.message.edit_text(
                f"📦 *{type_name} sandiq — Natija*\n\n"
                f"Sizga tegdi: *{reward_text}*\n\n"
                "Barcha qutular:",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=rows_2col),
                parse_mode="Markdown",
            )
        except Exception:
            pass


@router.callback_query(F.data == "sandiq_close")
async def cb_sandiq_close(call: CallbackQuery):
    await call.answer()
    try:
        await call.message.delete()
    except Exception:
        pass


# ──────────────────────────────────────────────
# Private team-chat relay
# (non-command private messages during active game)
# ──────────────────────────────────────────────

_SHERIF_ROLES = {Role.KOMISSAR, Role.SERZHANT}
_MAFIA_CHAT_ROLES = {r for r in MAFIA_TEAM if r != Role.LABARANT}


@router.message(F.chat.type == "private", _is_not_command)
async def _handle_last_words(msg: Message, bot: Bot):
    """Intercept private messages: rename/transfer hero → last words → team relay."""
    uid = msg.from_user.id if msg.from_user else None
    if not uid:
        return

    # ── 0a. Hero rename pending ──────────────────────────────
    if uid in _pending_hero_rename:
        _pending_hero_rename.discard(uid)
        if not msg.text:
            await msg.answer("⚠️ Faqat matn qabul qilinadi.")
            return
        new_name = msg.text.strip()[:32]
        if not new_name:
            await msg.answer("⚠️ Nom bo'sh bo'lishi mumkin emas.")
            return
        hero = await get_hero(uid)
        if not hero:
            await msg.answer("❌ Sizda Geroy yo'q.")
            return
        hero.name = new_name
        await save_hero(hero)
        await msg.answer(
            f"✅ Geroy nomi *{escape_md(new_name)}* ga o'zgartirildi!",
            parse_mode="Markdown",
        )
        return

    # ── 0b. Hero transfer pending ────────────────────────────
    if uid in _pending_hero_transfer:
        if msg.text and msg.text.strip().lower() in ("/cancel", "bekor"):
            _pending_hero_transfer.discard(uid)
            await msg.answer("❌ O'tkazish bekor qilindi.")
            return
        _pending_hero_transfer.discard(uid)
        if not msg.text:
            await msg.answer("⚠️ User ID yozing.")
            return
        try:
            target_id = int(msg.text.strip())
        except ValueError:
            await msg.answer("❌ Faqat raqamli user ID kiriting (masalan: 123456789).")
            return
        if target_id == uid:
            await msg.answer("❌ O'z-o'zingizga o'tkaza olmaysiz.")
            return
        hero = await get_hero(uid)
        if not hero:
            await msg.answer("❌ Sizda Geroy yo'q.")
            return
        await delete_hero(uid)
        hero.user_id = target_id
        await save_hero(hero)
        await msg.answer(
            f"✅ Geroy *{target_id}*ga o'tkazildi!\n🥷 Nom: *{escape_md(hero.name)}*",
            parse_mode="Markdown",
        )
        try:
            await bot.send_message(
                target_id,
                f"🎁 Siz Geroy oldingiz!\n"
                f"🥷 Nom: *{escape_md(hero.name)}*  ⭐ Daraja: *{hero.level}*",
                parse_mode="Markdown",
            )
        except Exception:
            pass
        return

    # ── 1. Last words (eliminated player) ───────────────────
    # Check if player is awaiting last-words in any active game
    for game in list(games.values()):
        if uid not in game.pending_last_words:
            continue
        # Accept only plain text — reject media
        if not msg.text:
            await msg.answer("⚠️ Faqat matn qabul qilinadi. Rasm, video, stiker va boshqa media qabul qilinmaydi.")
            return
        # Remove from pending immediately (one chance only)
        game.pending_last_words.discard(uid)
        player = game.get_player_by_id(uid)
        name = player.display_name if player else (msg.from_user.first_name or "Noma'lum")
        await bot.send_message(
            game.chat_id,
            f"🕊 *So'nggi so'z*\n\n☠️ {name}:\n\n{msg.text}",
            parse_mode="Markdown",
        )
        await msg.answer("✅ So'nggi so'zingiz guruhga yuborildi.")
        return

    # Not a last-words player — fall through to team relay
    await _private_team_relay_inner(msg, bot)


async def _private_team_relay_inner(msg: Message, bot: Bot):
    uid = msg.from_user.id if msg.from_user else None
    if not uid:
        return

    # Find the player's active game
    player_game: Optional[Game] = None
    sender_player = None
    for g in games.values():
        if g.phase in (Phase.LOBBY, Phase.ENDED):
            continue
        p = g.get_player_by_id(uid)
        if p and p.alive and p.role:
            player_game = g
            sender_player = p
            break

    if not player_game or not sender_player:
        return

    role = sender_player.role
    sender_name = player_game.get_display_name(sender_player)

    # Determine teammates for this role
    if role in _SHERIF_ROLES:
        teammates = [
            p for p in player_game.alive_players()
            if p.role in _SHERIF_ROLES and p.user_id != uid
        ]
    elif role in _MAFIA_CHAT_ROLES:
        teammates = [
            p for p in player_game.alive_players()
            if p.role in _MAFIA_CHAT_ROLES and p.user_id != uid
        ]
    else:
        return  # Solo role — no team chat

    if not teammates:
        await msg.answer("⚠️ Hozir faol sheriklari yo'q.")
        return

    relay_text = f"💬 *{sender_name}:*\n{msg.text}"
    sent = 0
    for t in teammates:
        try:
            await bot.send_message(t.user_id, relay_text, parse_mode="Markdown")
            sent += 1
        except Exception:
            pass

    if sent:
        await msg.answer("✅ Sheriklaingizga yetkazildi.")
    else:
        await msg.answer("⚠️ Sheriklaringizga xabar yetkazib bo'lmadi.")
