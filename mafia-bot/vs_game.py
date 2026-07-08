"""
VS Mode — Qizil vs Ko'k jamoa o'yini.
Mavjud Mafia o'yin logikasi asosida ishlaydi.
"""
import asyncio
import logging
import time
from typing import Optional
from aiogram import Router, Bot, F
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
)

from game import Game, Phase, Role, ROLE_EMOJIS, MIN_PLAYERS, MAX_PLAYERS
from profiles import record_game_start, record_win
from ratings import record_game_result
from mdutil import escape_md

logger = logging.getLogger(__name__)
vs_router = Router()

# Colours
RED = "🔴"
BLUE = "🔵"

def _get_games() -> dict:
    """Return the single shared games registry from handlers."""
    from handlers import games
    return games

# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _lobby_kb(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔴 Qizil jamoa", callback_data=f"vs_join:red:{chat_id}"),
            InlineKeyboardButton(text="🔵 Ko'k jamoa",  callback_data=f"vs_join:blue:{chat_id}"),
        ],
        [InlineKeyboardButton(text="▶️ O'yinni boshlash (Admin)", callback_data=f"vs_start:{chat_id}")],
    ])


def _lobby_text(game: Game) -> str:
    red_players = [p for uid, p in game.players.items() if uid in game.vs_red_team]
    blue_players = [p for uid, p in game.players.items() if uid in game.vs_blue_team]

    red_list = "\n".join(f"• {p.display_name}" for p in red_players) or "  _(hech kim yo'q)_"
    blue_list = "\n".join(f"• {p.display_name}" for p in blue_players) or "  _(hech kim yo'q)_"

    return (
        f"⚔️ *VS MODE — RO'YXAT*\n\n"
        f"🔴 *Qizil jamoa* ({len(red_players)})\n{red_list}\n\n"
        f"🔵 *Ko'k jamoa* ({len(blue_players)})\n{blue_list}\n\n"
        f"Jami o'yinchilar: *{len(game.players)}* (minimum {MIN_PLAYERS})\n"
        f"Tayyor bo'lgach admin ▶️ tugmasini bossin."
    )


async def _update_lobby(bot: Bot, game: Game):
    if game.lobby_msg_id:
        try:
            await bot.edit_message_text(
                chat_id=game.chat_id,
                message_id=game.lobby_msg_id,
                text=_lobby_text(game),
                reply_markup=_lobby_kb(game.chat_id),
                parse_mode="Markdown",
            )
        except Exception:
            pass


async def _dm(bot: Bot, uid: int, text: str, kb=None):
    try:
        await bot.send_message(uid, text, reply_markup=kb, parse_mode="Markdown")
    except Exception:
        pass


async def _require_admin(call_or_msg, bot: Bot, chat_id: int, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in ("administrator", "creator")
    except Exception:
        return False


# ──────────────────────────────────────────────
# /vsgame command
# ──────────────────────────────────────────────

@vs_router.message(Command("vsgame"))
async def cmd_vsgame(msg: Message, bot: Bot):
    if msg.chat.type == "private":
        return await msg.answer("⚠️ Bu buyruq faqat guruh chatlarda ishlaydi.")

    chat_id = msg.chat.id
    games = _get_games()

    # Block if ANY active game (regular or VS) exists
    existing = games.get(chat_id)
    if existing and existing.phase not in (Phase.LOBBY, Phase.ENDED):
        mode = "VS" if existing.vs_mode else "odatiy Mafia"
        return await msg.answer(f"⚠️ Bu guruhda {mode} o'yini davom etmoqda. Avval tugating.")

    # Create new VS lobby (replaces any stale lobby)
    game = Game(chat_id=chat_id, vs_mode=True)
    game.phase = Phase.LOBBY
    games[chat_id] = game

    user = msg.from_user
    # Creator joins red team by default
    game.add_player(user.id, user.username or "", user.first_name, user.last_name or "")
    game.vs_red_team.add(user.id)

    sent = await msg.answer(
        _lobby_text(game),
        reply_markup=_lobby_kb(chat_id),
        parse_mode="Markdown",
    )
    game.lobby_msg_id = sent.message_id


# ──────────────────────────────────────────────
# Join buttons
# ──────────────────────────────────────────────

@vs_router.callback_query(F.data.startswith("vs_join:"))
async def cb_vs_join(call: CallbackQuery, bot: Bot):
    parts = call.data.split(":")
    team = parts[1]      # "red" or "blue"
    chat_id = int(parts[2])

    games = _get_games()
    game = games.get(chat_id)
    if not game or not game.vs_mode or game.phase != Phase.LOBBY:
        return await call.answer("⚠️ VS lobby faol emas.", show_alert=True)

    user = call.from_user
    uid = user.id

    # Remove from other team if already joined
    if uid in game.vs_red_team:
        game.vs_red_team.discard(uid)
    if uid in game.vs_blue_team:
        game.vs_blue_team.discard(uid)

    # Add/move player
    if uid not in game.players:
        game.add_player(uid, user.username or "", user.first_name, user.last_name or "")

    if team == "red":
        game.vs_red_team.add(uid)
        team_label = "🔴 Qizil jamoa"
    else:
        game.vs_blue_team.add(uid)
        team_label = "🔵 Ko'k jamoa"

    await call.answer(f"✅ {team_label}ga qo'shildingiz!")
    await _update_lobby(bot, game)


# ──────────────────────────────────────────────
# Start VS game
# ──────────────────────────────────────────────

@vs_router.callback_query(F.data.startswith("vs_start:"))
async def cb_vs_start(call: CallbackQuery, bot: Bot):
    chat_id = int(call.data.split(":")[1])

    if not await _require_admin(call, bot, chat_id, call.from_user.id):
        return await call.answer("⚠️ Faqat adminlar boshlashi mumkin.", show_alert=True)

    games = _get_games()
    game = games.get(chat_id)
    if not game or not game.vs_mode or game.phase != Phase.LOBBY:
        return await call.answer("⚠️ VS lobby topilmadi.", show_alert=True)

    if len(game.vs_red_team) == 0 or len(game.vs_blue_team) == 0:
        return await call.answer("⚠️ Har bir jamoada kamida 1 kishi bo'lishi kerak.", show_alert=True)

    if len(game.players) < MIN_PLAYERS:
        return await call.answer(
            f"⚠️ Kamida {MIN_PLAYERS} o'yinchi kerak. Hozir: {len(game.players)}",
            show_alert=True,
        )

    await call.answer("✅ VS o'yini boshlanmoqda!")
    await _launch_vs_game(call.message, bot, game)


async def _launch_vs_game(msg: Message, bot: Bot, game: Game):
    chat_id = game.chat_id

    # Save original team members BEFORE role assignment (for win tracking)
    game.vs_red_team = set(game.vs_red_team)
    game.vs_blue_team = set(game.vs_blue_team)

    # Assign roles using existing role assignment logic
    from handlers import _assign_roles_with_preferences
    from settings import get_settings
    settings = await get_settings(chat_id)
    await _assign_roles_with_preferences(
        game,
        disabled_roles=settings.disabled_roles,
        custom_role_configs=settings.custom_role_configs,
    )
    game.day_number = 1
    game.started_at = time.time()

    for player in game.players.values():
        await record_game_start(player.user_id, player.first_name)

    # Already in the shared games registry (was set in lobby); nothing to do here

    # Determine team colour for each player
    def _team_emoji(uid: int) -> str:
        if uid in game.vs_red_team:
            return "🔴"
        if uid in game.vs_blue_team:
            return "🔵"
        return "⚪"

    await bot.send_message(
        chat_id,
        f"⚔️ *VS MODE BOSHLANDI!*\n\n"
        f"🔴 Qizil jamoa: {len(game.vs_red_team)} o'yinchi\n"
        f"🔵 Ko'k jamoa: {len(game.vs_blue_team)} o'yinchi\n\n"
        f"Rollar taqsimlanmoqda — shaxsiy xabaringizni tekshiring!",
        parse_mode="Markdown",
    )

    from game import ROLE_DESCRIPTIONS_UZ
    from handlers import ROLE_NAMES_UZ

    # Group link
    try:
        chat = await bot.get_chat(chat_id)
        group_link = chat.invite_link or (f"https://t.me/{chat.username}" if chat.username else None)
    except Exception:
        group_link = None

    group_kb = None
    if group_link:
        group_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👥 Guruhga qaytish", url=group_link)]
        ])

    for player in game.players.values():
        em = ROLE_EMOJIS.get(player.role, "")
        name = ROLE_NAMES_UZ.get(player.role, player.role.value if player.role else "")
        desc = ROLE_DESCRIPTIONS_UZ.get(player.role, "")
        team_em = _team_emoji(player.user_id)
        await _dm(bot, player.user_id,
            f"⚔️ *VS MODE*\n\n"
            f"👤 Sizning jamoangiz: {team_em}\n"
            f"🎭 Sizning rolingiz: {em} *{name}*\n\n"
            f"{desc}\n\nO'yin boshlandi!",
            group_kb,
        )

    # Run night using existing game loop (imported from handlers)
    from handlers import run_night
    asyncio.create_task(run_night(bot, chat_id))


# ──────────────────────────────────────────────
# VS Mode end game handler (called from _end_game)
# ──────────────────────────────────────────────

async def end_vs_game(bot: Bot, game: Game, winner: str):
    """Called from _end_game when vs_mode=True. Announces VS winner and gives rewards."""
    chat_id = game.chat_id
    # Mark game as ended in shared registry
    games_registry = _get_games()
    if games_registry.get(chat_id) is game:
        games_registry.pop(chat_id, None)

    if winner == "vs_red":
        winner_label = "🔴 Qizil jamoa"
        winner_ids = game.vs_red_team
    elif winner == "vs_blue":
        winner_label = "🔵 Ko'k jamoa"
        winner_ids = game.vs_blue_team
    else:
        winner_label = "⚖️ Durrang"
        winner_ids = set()

    from handlers import ROLE_NAMES_UZ

    winner_players = [p for p in game.players.values() if p.user_id in winner_ids and p.role]
    loser_players  = [p for p in game.players.values() if p.user_id not in winner_ids and p.role]

    def _fmt(p):
        team_em = "🔴" if p.user_id in game.vs_red_team else "🔵"
        em = ROLE_EMOJIS.get(p.role, "")
        rn = ROLE_NAMES_UZ.get(p.role, "")
        alive_mark = "✅" if p.alive else "☠️"
        return f"{alive_mark} {team_em} {p.display_name} — {em} {rn}"

    winners_list = "\n".join(_fmt(p) for p in winner_players) or "—"
    losers_list  = "\n".join(_fmt(p) for p in loser_players)  or "—"

    duration_secs = int(time.time() - (game.started_at or time.time()))
    mins, secs_rem = divmod(duration_secs, 60)
    duration_str = f"{mins}m {secs_rem}s" if mins else f"{secs_rem}s"

    WIN_REWARD = 30
    await bot.send_message(
        chat_id,
        f"🏆 *VS MODE TUGADI!*\n\n"
        f"G'olib jamoa: {winner_label}\n\n"
        f"🏅 *G'oliblar:*\n{winners_list}\n\n"
        f"😔 *Mag'lublar:*\n{losers_list}\n\n"
        f"⏱ O'yin davomiyligi: {duration_str}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="⚔️ Yangi VS o'yin",
                callback_data=f"vs_newgame:{chat_id}"
            )]
        ]),
    )

    for p in winner_players:
        await record_win(p.user_id, dollar_reward=WIN_REWARD)
        await record_game_result(chat_id, p.user_id, p.first_name, won=True, points=10)
        await _dm(bot, p.user_id,
            f"🏆 *VS Mode: G'alaba!* {winner_label}\n💵 +{WIN_REWARD}$ mukofot!")

    for p in loser_players:
        await record_game_result(chat_id, p.user_id, p.first_name, won=False, points=1)
        await _dm(bot, p.user_id, "😔 VS Mode: Mag'lubiyat.")


@vs_router.callback_query(F.data.startswith("vs_newgame:"))
async def cb_vs_newgame(call: CallbackQuery, bot: Bot):
    chat_id = int(call.data.split(":")[1])
    await call.answer()

    games = _get_games()
    # Block if a fresh active game already started
    current = games.get(chat_id)
    if current and current.phase not in (Phase.LOBBY, Phase.ENDED):
        return await bot.send_message(chat_id, "⚠️ O'yin allaqachon davom etmoqda.")

    game = Game(chat_id=chat_id, vs_mode=True)
    game.phase = Phase.LOBBY
    games[chat_id] = game

    user = call.from_user
    game.add_player(user.id, user.username or "", user.first_name, user.last_name or "")
    game.vs_red_team.add(user.id)

    sent = await bot.send_message(
        chat_id,
        _lobby_text(game),
        reply_markup=_lobby_kb(chat_id),
        parse_mode="Markdown",
    )
    game.lobby_msg_id = sent.message_id
