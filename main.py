import asyncio
import logging
from typing import Optional

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

import uvicorn
from fastapi import FastAPI

from config import BOT_TOKEN, WEBAPP_HOST, WEBAPP_PORT, LOG_LEVEL
from engine import init_db

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

_bot: Optional[Bot] = None


def get_bot() -> Optional[Bot]:
    return _bot


async def set_bot_commands(bot: Bot):
    commands = [
        BotCommand(command="start", description="Botni ishga tushirish"),
        BotCommand(command="admin", description="Admin panel"),
    ]
    await bot.set_my_commands(commands)


async def start_bot():
    global _bot
    from customer import customer_router
    from admin import admin_router
    from cashier import cashier_router

    bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
    _bot = bot
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    dp.include_router(admin_router)
    dp.include_router(cashier_router)
    dp.include_router(customer_router)

    await init_db()
    await set_bot_commands(bot)
    logger.info("Bot ishga tushdi!")

    try:
        await dp.start_polling(bot, allowed_updates=["message", "callback_query"])
    finally:
        await bot.session.close()
        logger.info("Bot to'xtatildi.")


async def start_webapp():
    from webapp import app
    config = uvicorn.Config(
        app,
        host=WEBAPP_HOST,
        port=WEBAPP_PORT,
        log_level="info",
    )
    server = uvicorn.Server(config)
    await server.serve()


async def main():
    await asyncio.gather(
        start_bot(),
        start_webapp(),
    )


if __name__ == "__main__":
    asyncio.run(main())