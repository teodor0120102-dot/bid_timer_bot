"""Обработка ставок (перебив) в группах."""

from __future__ import annotations

import logging
import re
import time
from typing import Optional

from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.types import Message

import database as db
import permissions
import phrases
import scheduler
import stars

log = logging.getLogger("bidtimer.bid")

_SERVICE_MESSAGE_FIELDS = (
    "new_chat_members",
    "left_chat_member",
    "new_chat_title",
    "new_chat_photo",
    "delete_chat_photo",
    "group_chat_created",
    "supergroup_chat_created",
    "channel_chat_created",
    "migrate_to_chat_id",
    "migrate_from_chat_id",
    "pinned_message",
    "forum_topic_created",
    "forum_topic_closed",
    "forum_topic_reopened",
    "general_forum_topic_hidden",
    "general_forum_topic_unhidden",
    "video_chat_scheduled",
    "video_chat_started",
    "video_chat_ended",
    "video_chat_participants_invited",
    "message_auto_delete_timer_changed",
)


def _format_remaining(end_at_unix: Optional[int]) -> str:
    if not end_at_unix:
        return "—"
    return phrases.format_time(max(0, int(end_at_unix) - int(time.time())))


def _user_mention(user) -> str:
    import html

    name = html.escape(user.full_name or user.username or "участник")
    return f'<a href="tg://user?id={user.id}">{name}</a>'


def _state_bidder_mention(state: db.ChatState) -> Optional[str]:
    import html

    if not state.last_bid_user_id:
        return None
    name = f"@{state.last_bid_username}" if state.last_bid_username else "участник"
    return f'<a href="tg://user?id={state.last_bid_user_id}">{html.escape(name)}</a>'


async def _edit_or_send_bid_panel(message: Message, state: db.ChatState, text: str) -> int:
    if state.last_bid_message_id:
        try:
            await message.bot.edit_message_text(
                text,
                chat_id=message.chat.id,
                message_id=state.last_bid_message_id,
                disable_web_page_preview=True,
            )
            return state.last_bid_message_id
        except Exception:
            log.debug("Bid panel edit failed chat=%s msg=%s", message.chat.id, state.last_bid_message_id)

    msg = await message.answer(text, disable_web_page_preview=True)
    return msg.message_id


def _paid_star_value(message: Message) -> Optional[int]:
    for attr in ("paid_star_count", "paid_message_star_count"):
        val = getattr(message, attr, None)
        if val is not None and int(val) > 0:
            return int(val)

    extra = getattr(message, "model_extra", None) or {}
    for key in ("paid_star_count", "paid_message_star_count"):
        val = extra.get(key)
        if val is not None and int(val) > 0:
            return int(val)
    return None


def _is_paid_bid(message: Message) -> bool:
    """Ставка только если реально оплачены Stars (не бесплатные сообщения админов)."""
    paid_stars = _paid_star_value(message)
    if paid_stars:
        log.info(
            "PAID BID: chat=%s user=%s stars=%s text=%r",
            message.chat.id,
            message.from_user.id if message.from_user else "?",
            paid_stars,
            (message.text or "")[:50],
        )
        return True

    if getattr(message, "successful_payment", None) is not None:
        log.info("PAID BID via successful_payment: chat=%s", message.chat.id)
        return True

    return False


def _is_regex_bid(message: Message, state: db.ChatState) -> bool:
    text = (message.text or "").strip()
    if not text:
        return False
    try:
        rx = re.compile(state.trigger_regex, flags=re.IGNORECASE)
    except re.error:
        return False
    return bool(rx.search(text))


async def _bidder_exempt(message: Message, user) -> bool:
    """Админы/владельцы группы и анонимные посты от имени чата — не участвуют."""
    if message.sender_chat and message.sender_chat.id == message.chat.id:
        log.info("BID IGNORED anonymous admin chat=%s", message.chat.id)
        return True
    if await permissions.is_chat_staff(message.bot, message.chat.id, user.id):
        log.info("BID IGNORED staff user=%s chat=%s", user.id, message.chat.id)
        return True
    return False


async def process_group_bid(message: Message) -> None:
    """Обработчик перебива на Dispatcher.message (SkipHandler → следующие роутеры)."""
    if getattr(message.chat, "type", None) not in ("group", "supergroup"):
        raise SkipHandler()

    if getattr(message, "paid_message_price_changed", None):
        raise SkipHandler()

    text = (message.text or message.caption or "").strip()
    if text.startswith("/"):
        raise SkipHandler()

    state = await db.get_chat_state(message.chat.id)
    if not state.is_running:
        raise SkipHandler()

    user = message.from_user
    if not user:
        return

    if await _bidder_exempt(message, user):
        return

    log.info(
        "GROUP MSG chat=%s user=%s paid_field=%s text=%r",
        message.chat.id,
        user.id,
        _paid_star_value(message),
        text[:40],
    )

    if not scheduler.timers.is_active(message.chat.id):
        await scheduler.arm_timer(message.bot, message.chat.id)

    if await scheduler.finalize_if_expired(message.bot, message.chat.id):
        return

    mode = state.trigger_mode
    is_bid = False
    is_potentially_paid = _is_paid_bid(message)

    if mode in ("paid", "both") and is_potentially_paid:
        is_bid = True
    if not is_bid and mode in ("regex", "both") and _is_regex_bid(message, state):
        is_bid = True

    if not is_bid:
        return

    async with scheduler.chat_locks[message.chat.id]:
        state = await db.get_chat_state(message.chat.id)
        if not state.is_running:
            return
        if state.end_at_unix and int(time.time()) >= int(state.end_at_unix):
            return

        if state.last_bid_user_id == user.id:
            log.info("BID IGNORED same user=%s chat=%s", user.id, message.chat.id)
            return

        mode = state.trigger_mode
        is_potentially_paid = _is_paid_bid(message)
        is_bid = False
        if mode in ("paid", "both") and is_potentially_paid:
            is_bid = True
        if not is_bid and mode in ("regex", "both") and _is_regex_bid(message, state):
            is_bid = True
        if not is_bid:
            return

        log.info(
            "BID ACCEPTED: chat=%s user=%s (%s) mode=%s paid=%s",
            message.chat.id, user.id, user.username or "?", mode, is_potentially_paid,
        )

        prev_mention = _state_bidder_mention(state)
        end_at = await scheduler.reset_round_on_bid(
            message.bot,
            message.chat.id,
            duration_seconds=state.duration_seconds,
            bidder_user_id=user.id,
            bidder_username=user.username,
        )
        remaining = max(0, end_at - int(time.time()))
        bid_msg_id = await _edit_or_send_bid_panel(
            message,
            state,
            phrases.bid_reset(
                mention=_user_mention(user),
                time_str=_format_remaining(end_at),
                total_sec=state.duration_seconds,
                remaining_sec=remaining,
                prev_mention=prev_mention,
            ),
        )
        await db.update_chat_state(message.chat.id, last_bid_message_id=bid_msg_id)
