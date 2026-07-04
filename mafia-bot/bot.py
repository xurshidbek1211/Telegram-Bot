import asyncio
import logging
import os
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand
from handlers import router

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logging.getLogger("aiogram").setLevel(logging.WARNING)


async def _run_health_server(port: int):
    """Bind a minimal HTTP server on PORT.

    Hosting platforms such as Render run apps as "web services" and only
    consider a deploy healthy once something is listening on the port they
    assign (via the PORT env var) and answers HTTP health checks. The bot
    itself keeps talking to Telegram via long polling — this server has no
    other purpose than satisfying that health check.
    """
    from aiohttp import web

    async def health(_request):
        return web.Response(text="OK")

    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/healthz", health)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=port)
    await site.start()
    logging.info(f"Health-check server {port}-portda ishga tushdi.")


async def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN o'rnatilmagan.")

    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
    dp = Dispatcher()
    dp.include_router(router)

    # Render (and similar platforms) set PORT automatically for web services.
    # Locally / on Replit PORT is not set, so we just poll as before.
    port = os.environ.get("PORT")
    if port:
        await _run_health_server(int(port))

    # Make sure no leftover webhook is registered — start_polling silently
    # receives nothing if Telegram still thinks a webhook is active.
    await bot.delete_webhook(drop_pending_updates=True)

    await bot.set_my_commands([
        BotCommand(command="game", description="🎮 Ro'yxatdan o'tishni boshlash"),
        BotCommand(command="start", description="🟢 O'yinni boshlash / botni ishga tushirish"),
        BotCommand(command="players", description="👥 O'yinchilar ro'yxati"),
        BotCommand(command="endgame", description="🛑 O'yinni tugatish"),
        BotCommand(command="kick", description="👢 O'yinchini chiqarish"),
        BotCommand(command="roles", description="🎭 Rollar ro'yxati"),
        BotCommand(command="profile", description="👤 Profilni ko'rish"),
        BotCommand(command="give", description="💎 Olmos berish"),
        BotCommand(command="money", description="💵 Pul berish"),
        BotCommand(command="shop", description="🛒 Do'kon"),
        BotCommand(command="stats", description="📊 Statistika"),
        BotCommand(command="settings", description="⚙️ Sozlamalar"),
        BotCommand(command="help", description="❓ Yordam"),
    ])

    logging.info("Mafiya boti ishga tushmoqda...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
