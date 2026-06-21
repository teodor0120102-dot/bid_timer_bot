"""BidTimerBot — проверка режима «сообщения за Stars»."""

from __future__ import annotations

import logging
import time
from typing import Dict, Optional, Tuple

from aiogram import Bot

from config import PAID_STARS_CACHE_TTL
import database as db

log = logging.getLogger("bidtimer.stars")

_paid_cache: Dict[int, Tuple[int, int]] = {}


def stars_enabled(star_count: Optional[int]) -> bool:
    return star_count is not None and int(star_count) > 0


def _extract_paid_stars(chat) -> Optional[int]:
    """Пробуем все известные атрибуты для получения цены Stars."""
    for attr in ("paid_message_star_count", "paid_star_count", "send_paid_messages_stars"):
        val = getattr(chat, attr, None)
        if val is not None:
            return int(val)

    extra = getattr(chat, "model_extra", None) or {}
    for key in ("paid_message_star_count", "paid_star_count", "send_paid_messages_stars"):
        val = extra.get(key)
        if val is not None:
            return int(val)
    return None


async def fetch_paid_stars(bot: Bot, chat_id: int, *, force: bool = False) -> Optional[int]:
    now = int(time.time())
    if not force:
        cached = _paid_cache.get(chat_id)
        if cached and cached[1] > now:
            return cached[0]

    try:
        chat = await bot.get_chat(chat_id)
        paid = _extract_paid_stars(chat)
    except Exception as e:
        log.debug("get_chat failed for %s: %s", chat_id, e)
        paid = None

    if paid is not None:
        paid = int(paid)
        _paid_cache[chat_id] = (paid, now + PAID_STARS_CACHE_TTL)
        await db.update_chat_state(chat_id, paid_message_star_count=paid)
        log.debug("Stars for chat %s: %s (from API)", chat_id, paid)
        return paid

    # Fallback: берём из БД
    state = await db.get_chat_state(chat_id)
    if state.paid_message_star_count is not None:
        val = int(state.paid_message_star_count)
        _paid_cache[chat_id] = (val, now + PAID_STARS_CACHE_TTL)
        log.debug("Stars for chat %s: %s (from DB)", chat_id, val)
        return val

    return None


def invalidate_paid_cache(chat_id: int) -> None:
    _paid_cache.pop(chat_id, None)
