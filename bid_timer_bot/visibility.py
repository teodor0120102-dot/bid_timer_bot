"""Проверка: видит ли бот обычные сообщения в группе."""

from __future__ import annotations

from typing import Optional, Tuple

from aiogram import Bot


async def group_sees_messages(bot: Bot, chat_id: int) -> Tuple[bool, Optional[str]]:
    """
    True — бот получает обычные сообщения группы (не только /команды).
    False + текст — перебив работать не будет.
    """
    me = await bot.get_me()
    if getattr(me, "can_read_all_group_messages", False):
        return True, None

    try:
        member = await bot.get_chat_member(chat_id, me.id)
        if member.status in ("creator", "administrator"):
            return True, None
    except Exception:
        pass

    return False, (
        "⚠️ Бот <b>не видит</b> обычные сообщения в этой группе.\n"
        "Сделайте одно из двух:\n"
        "▸ BotFather → <code>/setprivacy</code> → Disable, затем <b>передобавьте</b> бота в группу\n"
        "▸ Или сделайте бота <b>администратором</b> группы"
    )
