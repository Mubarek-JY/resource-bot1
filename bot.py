"""Entry point: python bot.py

On Render (RENDER_EXTERNAL_URL is set automatically) the bot runs in webhook
mode and serves GET/HEAD / and /health for an uptime pinger. Locally, with no
RENDER_EXTERNAL_URL, it falls back to long polling.
"""
import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN
from handlers import notify_admin, router

WEBHOOK_PATH = "/webhook"


def build() -> tuple[Bot, Dispatcher]:
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    return bot, dp


async def run_polling() -> None:
    bot, dp = build()
    # Drop updates that piled up while the bot was offline.
    await bot.delete_webhook(drop_pending_updates=True)
    await notify_admin(bot, "Resource bot started (polling). If this follows a crash, check Render logs.")
    await dp.start_polling(bot)


def run_webhook(base_url: str) -> None:
    from aiohttp import web
    from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

    secret = os.getenv("WEBHOOK_SECRET", "").strip()
    if not secret:
        raise SystemExit("WEBHOOK_SECRET is required in webhook mode (A-Z a-z 0-9 _ -)")

    bot, dp = build()

    async def on_startup(bot: Bot) -> None:
        await bot.set_webhook(
            url=base_url.rstrip("/") + WEBHOOK_PATH,
            secret_token=secret,
            drop_pending_updates=True,
        )
        await notify_admin(bot, "Resource bot started (webhook). If this follows a crash, check Render logs.")

    async def on_shutdown(bot: Bot) -> None:
        # Leave the webhook set: Telegram retries deliveries while we wake up.
        await bot.session.close()

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    async def health(_request: web.Request) -> web.Response:
        return web.Response(text="ok")

    app = web.Application()
    app.router.add_get("/", health)        # also answers HEAD
    app.router.add_get("/health", health)
    SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=secret).register(
        app, path=WEBHOOK_PATH
    )
    setup_application(app, dp, bot=bot)
    web.run_app(app, host="0.0.0.0", port=int(os.getenv("PORT", "10000")))


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    base_url = os.getenv("RENDER_EXTERNAL_URL", "").strip()
    if base_url:
        run_webhook(base_url)
    else:
        asyncio.run(run_polling())
