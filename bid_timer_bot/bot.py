"""BidTimerBot — точка входа (polling)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, ChatMemberUpdated, Message, TelegramObject

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


class RecipientTrackerMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        try:
            await self._remember(event)
        except Exception:
            log.debug("Recipient tracking skipped", exc_info=True)
        return await handler(event, data)

    async def _remember(self, event: TelegramObject) -> None:
        chat = None
        user = None

        if isinstance(event, Message):
            chat = event.chat
            user = event.from_user
        elif isinstance(event, CallbackQuery):
            user = event.from_user
            if event.message:
                chat = event.message.chat
        elif isinstance(event, ChatMemberUpdated):
            chat = event.chat
            user = event.from_user

        if chat:
            await db.remember_chat(
                chat.id,
                chat_type=getattr(chat, "type", None),
                title=getattr(chat, "title", None) or getattr(chat, "full_name", None),
                username=getattr(chat, "username", None),
            )
        if user:
            await db.remember_user(
                user.id,
                username=user.username,
                full_name=user.full_name,
                is_bot=user.is_bot,
            )


async def run_polling() -> None:
    await db.init_db()

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode="HTML"),
    )
    # На хостингах иногда остаётся webhook/зависшие апдейты — это ломает polling.
    await bot.delete_webhook(drop_pending_updates=True)
    dp = Dispatcher(storage=MemoryStorage())
    tracker = RecipientTrackerMiddleware()
    dp.message.outer_middleware(tracker)
    dp.callback_query.outer_middleware(tracker)
    dp.my_chat_member.outer_middleware(tracker)

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
