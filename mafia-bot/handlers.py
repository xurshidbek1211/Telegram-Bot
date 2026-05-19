import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from game import Game, Phase, Role, MIN_PLAYERS, ROLE_EMOJIS, ROLE_DESCRIPTIONS, get_role_distribution
from stats import load_stats, save_stats

logger = logging.getLogger(__name__)

games: dict[int, Game] = {}


def get_or_create_game(chat_id: int) -> Game:
    if chat_id not in games:
        games[chat_id] = Game(chat_id=chat_id)
    return games[chat_id]


def build_player_list(game: Game, show_roles: bool = False) -> str:
    lines = []
    for i, player in enumerate(game.players.values(), 1):
        status = "" if player.alive else " ☠️"
        role_str = f" ({ROLE_EMOJIS[player.role]} {player.role.value})" if show_roles and player.role else ""
        lines.append(f"{i}. {player.display_name}{role_str}{status}")
    return "\n".join(lines) if lines else "No players yet."


def build_alive_keyboard(game: Game, exclude_ids: list = None) -> InlineKeyboardMarkup:
    exclude_ids = exclude_ids or []
    buttons = []
    for player in game.alive_players():
        if player.user_id not in exclude_ids:
            buttons.append([InlineKeyboardButton(
                player.display_name,
                callback_data=f"target:{player.user_id}"
            )])
    return InlineKeyboardMarkup(buttons)


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
            "👋 Hello! I'm the *Mafia Game Bot*.\n\n"
            "Add me to a group chat and use /newgame to start a game!\n\n"
            "*Available commands:*\n"
            "/newgame — Start a new game lobby\n"
            "/join — Join the current game\n"
            "/leave — Leave the lobby\n"
            "/players — Show current players\n"
            "/startgame — Begin the game (admin)\n"
            "/endgame — Force end the game (admin)\n"
            "/stats — Show game statistics\n"
            "/rules — Show game rules",
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await update.message.reply_text(
            "👋 Use /newgame to start a Mafia game in this group!"
        )


async def cmd_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🃏 *Mafia Game Rules*\n\n"
        "*Roles:*\n"
        "🔪 *Mafia* — Eliminate one player each night. Win when outnumbering citizens.\n"
        "💊 *Doctor* — Protect one player each night from elimination.\n"
        "🔍 *Detective* — Investigate one player each night to check if they're Mafia.\n"
        "👤 *Citizen* — Identify and vote out the Mafia during the day.\n\n"
        "*Phases:*\n"
        "🌙 *Night* — Special roles perform their actions via private message.\n"
        "☀️ *Day* — Players discuss and vote to eliminate a suspect.\n\n"
        "*Win Conditions:*\n"
        "🏆 Citizens win when all Mafia are eliminated.\n"
        "💀 Mafia wins when they equal or outnumber the citizens.\n\n"
        f"*Minimum players:* {MIN_PLAYERS}"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def cmd_newgame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if update.effective_chat.type == "private":
        await update.message.reply_text("⚠️ This command only works in group chats.")
        return

    existing = games.get(chat_id)
    if existing and existing.phase != Phase.ENDED:
        await update.message.reply_text(
            "⚠️ A game is already in progress! Use /endgame to cancel it first."
        )
        return

    games[chat_id] = Game(chat_id=chat_id)
    game = games[chat_id]

    user = update.effective_user
    game.add_player(user.id, user.username or "", user.first_name)

    await update.message.reply_text(
        "🎮 *A new Mafia game is starting!*\n\n"
        f"👤 {user.first_name} has created the game.\n\n"
        "Use /join to join the lobby.\n"
        "Use /startgame when everyone is ready (admin only).\n\n"
        f"*Players ({len(game.players)}/{MIN_PLAYERS} min):*\n"
        f"{build_player_list(game)}",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if update.effective_chat.type == "private":
        await update.message.reply_text("⚠️ Join a game in a group chat.")
        return

    game = games.get(chat_id)
    if not game or game.phase == Phase.ENDED:
        await update.message.reply_text("⚠️ No active lobby. Use /newgame to start one.")
        return

    if game.phase != Phase.LOBBY:
        await update.message.reply_text("⚠️ The game has already started. Wait for the next one!")
        return

    user = update.effective_user
    if game.add_player(user.id, user.username or "", user.first_name):
        await update.message.reply_text(
            f"✅ *{user.first_name}* has joined the game!\n\n"
            f"*Players ({len(game.players)}/{MIN_PLAYERS} min):*\n"
            f"{build_player_list(game)}",
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        if user.id in game.players:
            await update.message.reply_text("⚠️ You're already in the game!")
        else:
            await update.message.reply_text("⚠️ The lobby is full.")


async def cmd_leave(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    game = games.get(chat_id)
    if not game or game.phase != Phase.LOBBY:
        await update.message.reply_text("⚠️ You can only leave during the lobby phase.")
        return

    user = update.effective_user
    if game.remove_player(user.id):
        await update.message.reply_text(
            f"👋 *{user.first_name}* has left the game.\n\n"
            f"*Players ({len(game.players)}):*\n{build_player_list(game)}",
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await update.message.reply_text("⚠️ You're not in the lobby.")


async def cmd_players(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    game = games.get(chat_id)
    if not game or game.phase == Phase.ENDED:
        await update.message.reply_text("⚠️ No active game in this chat.")
        return

    phase_label = {
        Phase.LOBBY: "Lobby",
        Phase.NIGHT: f"Night {game.day_number}",
        Phase.DAY: f"Day {game.day_number}",
        Phase.VOTING: f"Voting — Day {game.day_number}",
    }.get(game.phase, "")

    alive = game.alive_players()
    dead = [p for p in game.players.values() if not p.alive]

    text = f"👥 *Players — {phase_label}*\n\n"
    text += f"*Alive ({len(alive)}):*\n"
    for i, p in enumerate(alive, 1):
        text += f"{i}. {p.display_name}\n"
    if dead:
        text += f"\n*Eliminated ({len(dead)}):*\n"
        for p in dead:
            role_str = f" — {ROLE_EMOJIS[p.role]} {p.role.value}" if p.role else ""
            text += f"☠️ {p.display_name}{role_str}\n"

    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def cmd_startgame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if update.effective_chat.type == "private":
        await update.message.reply_text("⚠️ This command only works in group chats.")
        return

    game = games.get(chat_id)
    if not game or game.phase == Phase.ENDED:
        await update.message.reply_text("⚠️ No active lobby. Use /newgame first.")
        return

    if game.phase != Phase.LOBBY:
        await update.message.reply_text("⚠️ The game has already started.")
        return

    member = await context.bot.get_chat_member(chat_id, update.effective_user.id)
    is_admin = member.status in ("administrator", "creator")
    if not is_admin and update.effective_user.id not in game.players:
        await update.message.reply_text("⚠️ Only admins or players in the lobby can start the game.")
        return

    if len(game.players) < MIN_PLAYERS:
        await update.message.reply_text(
            f"⚠️ Need at least *{MIN_PLAYERS}* players to start. Currently: *{len(game.players)}*",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    await start_game(update, context, game)


async def start_game(update: Update, context: ContextTypes.DEFAULT_TYPE, game: Game):
    game.assign_roles()
    game.phase = Phase.NIGHT
    game.day_number = 1

    dist = get_role_distribution(len(game.players))
    dist_text = "  ".join(f"{ROLE_EMOJIS[r]} {r.value}: {n}" for r, n in dist.items() if n > 0)

    await update.message.reply_text(
        f"🎮 *The Mafia game begins!*\n\n"
        f"*{len(game.players)} players* have been assigned their roles.\n"
        f"{dist_text}\n\n"
        "🌙 *Night 1 begins!*\nCheck your private messages for your role and instructions.",
        parse_mode=ParseMode.MARKDOWN,
    )

    for player in game.players.values():
        try:
            role_emoji = ROLE_EMOJIS[player.role]
            desc = ROLE_DESCRIPTIONS[player.role]
            await context.bot.send_message(
                player.user_id,
                f"🎭 *Your role: {role_emoji} {player.role.value}*\n\n{desc}\n\n"
                "The game has started. Await night action instructions.",
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
            ally_text = f"\n🤝 Your Mafia allies: {', '.join(mafia_allies)}" if mafia_allies else ""
            try:
                await context.bot.send_message(
                    mafia.user_id,
                    f"🌙 *Night {game.day_number}*{ally_text}\n\n"
                    "🔪 Choose a player to *eliminate* tonight:",
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
                    f"🌙 *Night {game.day_number}*\n\n💊 Choose a player to *protect* tonight:",
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
                    f"🌙 *Night {game.day_number}*\n\n🔍 Choose a player to *investigate* tonight:",
                    reply_markup=keyboard,
                    parse_mode=ParseMode.MARKDOWN,
                )
            except Exception:
                pass

        elif player.role == Role.CITIZEN:
            try:
                await context.bot.send_message(
                    player.user_id,
                    f"🌙 *Night {game.day_number}*\n\n"
                    "👤 You are a Citizen. Rest for the night...\n"
                    "The town will need your help during the day!",
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
        await query.edit_message_text("⚠️ This action is no longer valid.")
        return

    actor_id = query.from_user.id
    actor = game.get_player_by_id(actor_id)
    if not actor or not actor.alive:
        await query.edit_message_text("⚠️ You are not an active player.")
        return

    target = game.get_player_by_id(target_id)
    if not target or not target.alive:
        await query.edit_message_text("⚠️ That player is not available.")
        return

    if action == "night_kill" and actor.role == Role.MAFIA:
        game.night_actions[f"kill_{actor_id}"] = target_id
        await query.edit_message_text(
            f"🔪 You chose to eliminate *{target.display_name}* tonight.",
            parse_mode=ParseMode.MARKDOWN,
        )
    elif action == "night_protect" and actor.role == Role.DOCTOR:
        game.night_actions["protect"] = target_id
        await query.edit_message_text(
            f"💊 You chose to protect *{target.display_name}* tonight.",
            parse_mode=ParseMode.MARKDOWN,
        )
    elif action == "night_investigate" and actor.role == Role.DETECTIVE:
        is_mafia = target.role == Role.MAFIA
        result_text = "🔴 *MAFIA*" if is_mafia else "🟢 *Not Mafia*"
        game.night_actions[f"investigate_{actor_id}"] = target_id
        await query.edit_message_text(
            f"🔍 Investigation result for *{target.display_name}*:\n{result_text}",
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await query.edit_message_text("⚠️ Invalid action.")
        return

    await check_night_complete(context, game)


async def check_night_complete(context: ContextTypes.DEFAULT_TYPE, game: Game):
    alive = game.alive_players()
    mafia = game.alive_mafia()

    kill_actions = [k for k in game.night_actions if k.startswith("kill_")]
    has_doctor = any(p.role == Role.DOCTOR for p in alive)
    has_detective = any(p.role == Role.DETECTIVE for p in alive)

    needed = len(mafia)
    if has_doctor:
        needed += 1
    if has_detective:
        needed += 1

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
        role_reveal = f"Their role was: {ROLE_EMOJIS[eliminated.role]} *{eliminated.role.value}*"
        msg = (
            f"☀️ *Day {game.day_number} begins!*\n\n"
            f"☠️ *{eliminated.display_name}* was eliminated last night.\n"
            f"{role_reveal}\n\n"
            "Discuss and vote to eliminate a suspect!\n"
            "Use /vote or the vote button below."
        )
    else:
        msg = (
            f"☀️ *Day {game.day_number} begins!*\n\n"
            "🛡️ The Doctor's protection saved someone — nobody was eliminated last night!\n\n"
            "Discuss and vote to eliminate a suspect!\n"
            "Use /vote or the vote button below."
        )

    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🗳️ Open Voting", callback_data=f"open_voting:{chat_id}")]])
    await context.bot.send_message(chat_id, msg, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)


async def cmd_vote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    game = games.get(chat_id)

    if not game or game.phase not in (Phase.DAY, Phase.VOTING):
        await update.message.reply_text("⚠️ Voting is not currently active.")
        return

    game.phase = Phase.VOTING
    game.votes = {}
    await send_voting_prompt(update.message, context, game)


async def handle_open_voting_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":")
    chat_id = int(parts[1])
    game = games.get(chat_id)

    if not game or game.phase not in (Phase.DAY, Phase.VOTING):
        await query.edit_message_text("⚠️ Voting is no longer active.")
        return

    game.phase = Phase.VOTING
    game.votes = {}
    await query.edit_message_text("🗳️ *Voting has opened!*\nEach player will receive a private voting message.", parse_mode=ParseMode.MARKDOWN)
    await send_voting_to_players(context, game)


async def send_voting_prompt(message, context: ContextTypes.DEFAULT_TYPE, game: Game):
    await message.reply_text(
        "🗳️ *Voting has opened!* Each player will receive a private voting message.",
        parse_mode=ParseMode.MARKDOWN,
    )
    await send_voting_to_players(context, game)


async def send_voting_to_players(context: ContextTypes.DEFAULT_TYPE, game: Game):
    chat_id = game.chat_id
    for player in game.alive_players():
        keyboard = build_vote_keyboard(game, player.user_id)
        try:
            await context.bot.send_message(
                player.user_id,
                f"🗳️ *Day {game.day_number} — Cast your vote!*\n\n"
                "Who do you think is Mafia?\n"
                "Tap a name to vote. Tap again to change your vote.\n\n"
                f"When ready, press /endvote in the group chat.",
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
        await query.edit_message_text("⚠️ No active voting found.")
        return

    game = games[chat_id]
    voter = game.get_player_by_id(voter_id)
    target = game.get_player_by_id(target_id)

    if not voter or not voter.alive:
        await query.edit_message_text("⚠️ You are not an active player.")
        return
    if not target or not target.alive:
        await query.edit_message_text("⚠️ That player is not available.")
        return

    if game.votes.get(voter_id) == target_id:
        del game.votes[voter_id]
        await query.edit_message_text(
            f"🗳️ *Day {game.day_number} — Cast your vote!*\n\n"
            f"Vote for *{target.display_name}* removed.\n\n"
            "Tap a name to vote.",
            reply_markup=build_vote_keyboard(game, voter_id),
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        game.votes[voter_id] = target_id
        await query.edit_message_text(
            f"🗳️ *Day {game.day_number} — Cast your vote!*\n\n"
            f"✅ You voted for *{target.display_name}*.\n\n"
            "Tap again to remove, or tap another name to change.",
            reply_markup=build_vote_keyboard(game, voter_id),
            parse_mode=ParseMode.MARKDOWN,
        )


async def cmd_endvote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    game = games.get(chat_id)

    if not game or game.phase != Phase.VOTING:
        await update.message.reply_text("⚠️ No active vote to end.")
        return

    voted_count = sum(1 for vid in game.votes if game.get_player_by_id(vid) and game.get_player_by_id(vid).alive)
    alive_count = len(game.alive_players())

    if voted_count < alive_count:
        not_voted = [p.display_name for p in game.alive_players() if p.user_id not in game.votes]
        await update.message.reply_text(
            f"⏳ *Waiting for votes...*\n"
            f"{voted_count}/{alive_count} players have voted.\n\n"
            f"*Haven't voted yet:* {', '.join(not_voted)}",
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
            summary_lines.append(f"  {player.display_name}: {count} vote(s)")

    summary_text = "\n".join(summary_lines) or "No votes cast."

    if eliminated_id is None:
        msg = (
            f"🗳️ *Vote Results — Day {game.day_number}:*\n{summary_text}\n\n"
            "⚖️ *It's a tie!* No one is eliminated today.\n\n"
            "🌙 Night falls..."
        )
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
    else:
        eliminated = game.get_player_by_id(eliminated_id)
        game.eliminate_player(eliminated_id)
        role_reveal = f"Their role was: {ROLE_EMOJIS[eliminated.role]} *{eliminated.role.value}*"
        msg = (
            f"🗳️ *Vote Results — Day {game.day_number}:*\n{summary_text}\n\n"
            f"☠️ *{eliminated.display_name}* has been eliminated!\n"
            f"{role_reveal}\n\n"
        )
        winner = game.check_win_condition()
        if winner:
            await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
            await end_game(context, game, winner, update.effective_chat.id)
            return

        msg += "🌙 Night falls..."
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

    game.day_number += 1
    game.phase = Phase.NIGHT
    await send_night_actions(context, game)


async def cmd_endgame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    game = games.get(chat_id)

    if not game or game.phase == Phase.ENDED:
        await update.message.reply_text("⚠️ No active game to end.")
        return

    member = await context.bot.get_chat_member(chat_id, update.effective_user.id)
    is_admin = member.status in ("administrator", "creator")
    if not is_admin:
        await update.message.reply_text("⚠️ Only admins can force-end the game.")
        return

    game.phase = Phase.ENDED
    role_list = "\n".join(
        f"  {p.display_name} — {ROLE_EMOJIS[p.role]} {p.role.value}"
        for p in game.players.values()
        if p.role
    )
    await update.message.reply_text(
        "🛑 *Game ended by admin.*\n\n"
        f"*Roles were:*\n{role_list}",
        parse_mode=ParseMode.MARKDOWN,
    )


async def end_game(context: ContextTypes.DEFAULT_TYPE, game: Game, winner: str, chat_id: int = None):
    game.phase = Phase.ENDED
    game.winner = winner
    cid = chat_id or game.chat_id

    if winner == "citizens":
        result_text = "🎉 *The Citizens win!* All Mafia have been eliminated!"
        emoji = "🏆"
    else:
        result_text = "💀 *The Mafia wins!* They have taken over the town!"
        emoji = "🔪"

    role_list = "\n".join(
        f"  {'☠️' if not p.alive else '✅'} {p.display_name} — {ROLE_EMOJIS[p.role]} {p.role.value}"
        for p in game.players.values()
        if p.role
    )

    await context.bot.send_message(
        cid,
        f"{emoji} *Game Over!*\n\n{result_text}\n\n"
        f"*Final Roles:*\n{role_list}\n\n"
        "Use /newgame to play again!",
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
        await update.message.reply_text("📊 No games played yet!")
        return

    citizen_pct = round(stats.citizen_wins / total * 100) if total else 0
    mafia_pct = round(stats.mafia_wins / total * 100) if total else 0
    avg_players = round(stats.total_players / total, 1) if total else 0

    await update.message.reply_text(
        "📊 *Game Statistics*\n\n"
        f"🎮 Total games: *{total}*\n"
        f"👥 Avg players/game: *{avg_players}*\n\n"
        f"🏆 Citizen wins: *{stats.citizen_wins}* ({citizen_pct}%)\n"
        f"🔪 Mafia wins: *{stats.mafia_wins}* ({mafia_pct}%)\n",
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
        await query.answer("Unknown action.")
