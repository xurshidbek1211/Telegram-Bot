import asyncio
import logging
import os
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand
from handlers import router
from database import init_db, close_db

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logging.getLogger("aiogram").setLevel(logging.WARNING)


async def _run_health_server(port: int):
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

    await init_db()

    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
    dp = Dispatcher()
    dp.include_router(router)

    port = os.environ.get("PORT")
    if port:
        await _run_health_server(int(port))

    await bot.delete_webhook(drop_pending_updates=True)

    await bot.set_my_commands([
        BotCommand(command="game", description="🎮 Ro'yxatdan o'tishni boshlash"),
        BotCommand(command="start", description="🟢 O'yinni boshlash / botni ishga tushirish"),
        BotCommand(command="players", description="👥 O'yinchilar ro'yxati"),
        BotCommand(command="endgame", description="🛑 O'yinni tugatish"),
        BotCommand(command="kick", description="👢 O'yinchini chiqarish"),
        BotCommand(command="roles", description="🎭 Rollar ro'yxati"),
        BotCommand(command="profile", description="👤 Profilni ko'rish"),
        BotCommand(command="give", description="💎 Olmos tashlash (guruhda)"),
        BotCommand(command="money", description="💵 Pul tashlash (guruhda)"),
        BotCommand(command="shop", description="🛒 Do'kon"),
        BotCommand(command="top", description="🏆 Reyting"),
        BotCommand(command="stats", description="📊 Statistika"),
        BotCommand(command="sozlash", description="⚙️ Sozlamalar"),
        BotCommand(command="kanal", description="📢 Reklama kanalini sozlash (egasi)"),
        BotCommand(command="utag", description="📢 Guruh a'zolarini o'yinga chaqirish"),
        BotCommand(command="help", description="❓ Yordam"),
    ])

    logging.info("Mafiya boti ishga tushmoqda...")
    try:
        await dp.start_polling(bot)
    finally:
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())
