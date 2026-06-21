"""BidTimerBot — точка входа (polling)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, ChatMemberUpdated, Message, TelegramObject, Update
from aiogram.types.update import UpdateTypeLookupError

from config import BOT_TOKEN
import bid
import database as db
import handlers
import games
import stars
import visibility
from scheduler import arm_timer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
log = logging.getLogger("bidtimer")


class UpdateLogMiddleware(BaseMiddleware):
    """Логируем тип каждого апдейта — помогает понять «is not handled»."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Update):
            try:
                log.info(
                    "UPDATE id=%s type=%s chat=%s",
                    event.update_id,
                    event.event_type,
                    getattr(getattr(event.event, "chat", None), "id", None),
                )
            except UpdateTypeLookupError:
                log.warning(
                    "UPDATE id=%s UNKNOWN TYPE — обновите aiogram! raw=%s",
                    event.update_id,
                    event.model_dump(exclude_none=True),
                )
        return await handler(event, data)


class RecipientTrackerMiddleware(BaseMiddleware):
    CHAT_WRITE_TTL = 600
    USER_WRITE_TTL = 600

    def __init__(self) -> None:
        self._seen_chats: dict[int, float] = {}
        self._seen_users: dict[int, float] = {}

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
        now = asyncio.get_running_loop().time()

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

        if chat and self._seen_chats.get(chat.id, 0) <= now:
            self._seen_chats[chat.id] = now + self.CHAT_WRITE_TTL
            await db.remember_chat(
                chat.id,
                chat_type=getattr(chat, "type", None),
                title=getattr(chat, "title", None) or getattr(chat, "full_name", None),
                username=getattr(chat, "username", None),
            )
        if user and self._seen_users.get(user.id, 0) <= now:
            self._seen_users[user.id] = now + self.USER_WRITE_TTL
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
    await bot.delete_webhook(drop_pending_updates=True)
    dp = Dispatcher(storage=MemoryStorage())

    dp.update.outer_middleware(UpdateLogMiddleware())
    tracker = RecipientTrackerMiddleware()
    dp.message.outer_middleware(tracker)
    dp.callback_query.outer_middleware(tracker)
    dp.my_chat_member.outer_middleware(tracker)

    # Перебив — напрямую на Dispatcher, ДО игр и прочих роутеров.
    dp.message.register(
        bid.process_group_bid,
        F.chat.type.in_({"group", "supergroup"}),
    )

    dp.include_router(games.router)
    dp.include_router(handlers.router)

    for state in await db.list_running_chats():
        paid = await stars.fetch_paid_stars(bot, state.chat_id, force=True)
        if stars.stars_enabled(paid):
            await arm_timer(bot, state.chat_id)
        else:
            await db.update_chat_state(state.chat_id, is_running=False, clear_last_bid=True)

    me = await bot.get_me()
    sees_all = getattr(me, "can_read_all_group_messages", None)
    log.info(
        "🚀 BidTimerBot запущен: @%s | can_read_all_group_messages=%s",
        me.username,
        sees_all,
    )
    if sees_all is False:
        log.warning(
            "Privacy mode ВКЛ: бот не видит обычные сообщения в группах. "
            "BotFather → /setprivacy → Disable, или сделайте бота админом."
        )

    await dp.start_polling(
        bot,
        allowed_updates=[
            "message",
            "edited_message",
            "callback_query",
            "my_chat_member",
        ],
    )


if __name__ == "__main__":
    asyncio.run(run_polling())
