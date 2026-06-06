"""BidTimerBot — точка входа (polling)."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage

# Railway часто запускает файл как `python bot.py` в Root Directory.
# В этом режиме относительные импорты (`from .x import y`) не работают,
# поэтому используем обычные импорты по файлам в директории.
from config import BOT_TOKEN
import database as db
import handlers
import games
import stars
from scheduler import arm_timer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
log = logging.getLogger("bidtimer")


async def run_polling() -> None:
    await db.init_db()

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode="HTML"),
    )
    # На хостингах иногда остаётся webhook/зависшие апдейты — это ломает polling.
    await bot.delete_webhook(drop_pending_updates=True)
    dp = Dispatcher(storage=MemoryStorage())

    # Игры ПЕРЕД handlers — чтобы /games и callback'и игр обрабатывались первыми,
    # и не перехватывались catch-all хэндлером on_any_message из handlers.
    dp.include_router(games.router)
    dp.include_router(handlers.router)

    # При старте подтянем цену Stars и восстановим таймеры
    for state in await db.list_running_chats():
        paid = await stars.fetch_paid_stars(bot, state.chat_id, force=True)
        if stars.stars_enabled(paid):
            await arm_timer(bot, state.chat_id)
        else:
            await db.update_chat_state(state.chat_id, is_running=False, clear_last_bid=True)

    me = await bot.get_me()
    log.info("🚀 BidTimerBot запущен: @%s", me.username)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(run_polling())
