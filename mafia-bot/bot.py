import asyncio
import logging
import os
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand
from handlers import router
from vs_game import vs_router
from database import init_db, close_db

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logging.getLogger("aiogram").setLevel(logging.WARNING)


async def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN o'rnatilmagan.")

    await init_db()

    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
    dp = Dispatcher()
    # vs_router must be included BEFORE the general router: handlers.router
    # registers catch-all group/private message handlers (auto-delete,
    # team-chat relay) that match every message, including unrecognised
    # commands like /vsgame. If router were checked first, those catch-alls
    # would swallow the update and vs_router's Command("vsgame") handler
    # would never run.
    dp.include_router(vs_router)
    dp.include_router(router)

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
        BotCommand(command="vsgame", description="⚔️ VS Mode (Qizil vs Ko'k)"),
        BotCommand(command="help", description="❓ Yordam"),
    ])

    port = os.environ.get("PORT")
    # Render sets RENDER_EXTERNAL_URL; also support a custom WEBHOOK_URL override
    webhook_base = os.environ.get("WEBHOOK_URL") or os.environ.get("RENDER_EXTERNAL_URL")

    if port and webhook_base:
        # ── Webhook mode (Render / any hosted env with PORT + public URL) ──
        from aiohttp import web
        from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

        WEBHOOK_PATH = "/webhook"
        full_webhook_url = webhook_base.rstrip("/") + WEBHOOK_PATH

        await bot.set_webhook(full_webhook_url, drop_pending_updates=True)
        logging.info(f"Webhook o'rnatildi: {full_webhook_url}")

        app = web.Application()

        async def health(_request):
            return web.Response(text="OK")

        app.router.add_get("/", health)
        app.router.add_get("/healthz", health)

        SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=WEBHOOK_PATH)
        setup_application(app, dp, bot=bot)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, host="0.0.0.0", port=int(port))
        await site.start()
        logging.info(f"Webhook server {port}-portda ishga tushdi.")

        try:
            # Run until cancelled / SIGTERM
            await asyncio.Event().wait()
        finally:
            await bot.delete_webhook()
            await close_db()
    else:
        # ── Polling mode (Replit dev / local) ──
        if port:
            # Health check server only (no webhook)
            from aiohttp import web

            async def health(_request):
                return web.Response(text="OK")

            health_app = web.Application()
            health_app.router.add_get("/", health)
            health_app.router.add_get("/healthz", health)
            runner = web.AppRunner(health_app)
            await runner.setup()
            site = web.TCPSite(runner, host="0.0.0.0", port=int(port))
            await site.start()
            logging.info(f"Health-check server {port}-portda ishga tushdi.")

        await bot.delete_webhook(drop_pending_updates=True)
        logging.info("Mafiya boti polling rejimida ishga tushmoqda...")
        try:
            await dp.start_polling(bot)
        finally:
            await close_db()


if __name__ == "__main__":
    asyncio.run(main())
