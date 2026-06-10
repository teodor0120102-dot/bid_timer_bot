"""BidTimerBot — автоматические права без настройки Railway."""

from __future__ import annotations

import asyncio
import time
from typing import Dict, Tuple

from aiogram.types import Message, User

import database as db
import phrases

# (chat_id, user_id) -> (is_admin, expires_at)
_admin_cache: Dict[Tuple[int, int], Tuple[bool, int]] = {}
_CACHE_TTL = 120


async def _is_chat_staff(bot, chat_id: int, user_id: int) -> bool:
    """Владелец или администратор группы — доступ автоматически."""
    # В ЛС пользователь всегда хозяин
    if chat_id > 0 or chat_id == user_id:
        return True

    now = int(time.time())
    key = (chat_id, user_id)
    cached = _admin_cache.get(key)
    if cached and cached[1] > now:
        return cached[0]
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        is_staff = member.status in ("creator", "administrator")
    except Exception:
        # Резервный вариант: получить список всех администраторов
        try:
            admins = await bot.get_chat_administrators(chat_id)
            is_staff = any(admin.user.id == user_id for admin in admins)
        except Exception:
            is_staff = False
    _admin_cache[key] = (is_staff, now + _CACHE_TTL)
    return is_staff


async def can_manage(bot, chat_id: int, user: User) -> bool:
    if await _is_chat_staff(bot, chat_id, user.id):
        return True
    if await db.is_chat_manager(chat_id, user.id, user.username):
        return True
    return False


async def deny_if_cannot_manage(message: Message) -> bool:
    # Если сообщение отправлено от имени самого чата (анонимный администратор)
    if message.sender_chat and message.sender_chat.id == message.chat.id:
        return False

    user = message.from_user
    if not user:
        sent = await message.reply(phrases.card("Ошибка", "Не удалось определить отправителя."))
        _delete_later(sent)
        return True
    if await can_manage(message.bot, message.chat.id, user):
        return False
    sent = await message.reply(phrases.access_denied())
    _delete_later(sent)
    return True


def _delete_later(message: Message, delay: int = 60) -> None:
    async def runner() -> None:
        await asyncio.sleep(delay)
        try:
            await message.delete()
        except Exception:
            pass

    try:
        asyncio.create_task(runner())
    except RuntimeError:
        pass
