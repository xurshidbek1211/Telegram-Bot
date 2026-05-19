# Mafia Game Bot

A Telegram group chat bot that runs a full Mafia party game with roles, night/day phases, voting, and game statistics.

## Run & Operate

- `cd mafia-bot && python bot.py` — run the Telegram bot (managed via the "Mafia Bot" workflow)
- Required env: `TELEGRAM_BOT_TOKEN` — Telegram bot token from @BotFather

## Stack

- Python 3.11
- python-telegram-bot (v20+, async)
- JSON file for persistent game statistics

## Where things live

- `mafia-bot/bot.py` — entry point, registers all command and callback handlers
- `mafia-bot/handlers.py` — all game logic and Telegram handler functions
- `mafia-bot/game.py` — Game, Player, Role, Phase data models and game logic
- `mafia-bot/stats.py` — persistent stats load/save (stats.json)

## Architecture decisions

- All game state is held in-memory (a dict keyed by chat_id). Bot restarts reset active games.
- Night actions use inline keyboard callbacks sent to players via private DM.
- Role distribution scales with player count (see `ROLE_DISTRIBUTION` in game.py).
- Stats are persisted to `mafia-bot/stats.json` after each completed game.
- The bot uses python-telegram-bot's `run_polling` — no webhook setup needed.

## Product

Players use /newgame in a group to open a lobby, /join to join, then /startgame to begin. Roles are assigned privately. Night phases send action prompts via DM. Day phases open group discussion and private voting. The game continues until Mafia or Citizens win.

## Bot Commands

| Command | Description |
|---|---|
| /newgame | Start a new game lobby |
| /join | Join the current lobby |
| /leave | Leave the lobby |
| /players | Show player list and status |
| /startgame | Begin the game (admin) |
| /vote | Open day voting |
| /endvote | Tally votes and resolve |
| /endgame | Force-end the game (admin) |
| /stats | Show win/loss statistics |
| /rules | Show game rules |

## User preferences

_Populate as you build — explicit user instructions worth remembering across sessions._

## Gotchas

- Players must start a private chat with the bot before playing — otherwise DMs for role/night actions will fail silently.
- `TELEGRAM_BOT_TOKEN` must be set in Replit Secrets.
- Bot restarts reset all in-progress game state.
