"""BidTimerBot — планировщик таймеров по чатам."""

from __future__ import annotations

import asyncio
import html
import logging
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, Optional

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest

import database as db
import phrases

log = logging.getLogger("bidtimer.scheduler")

chat_locks = defaultdict(asyncio.Lock)


@dataclass(slots=True)
class TimerResult:
    chat_id: int
    winner_user_id: Optional[int]
    winner_username: Optional[str]


class ChatTimers:
    def __init__(self) -> None:
        self._tasks: Dict[int, asyncio.Task] = {}

    def cancel(self, chat_id: int) -> None:
        task = self._tasks.pop(chat_id, None)
        if task and not task.done():
            task.cancel()

    def schedule(self, chat_id: int, coro) -> None:
        self.cancel(chat_id)
        self._tasks[chat_id] = asyncio.create_task(coro)

    def is_active(self, chat_id: int) -> bool:
        task = self._tasks.get(chat_id)
        return bool(task and not task.done())


timers = ChatTimers()


def _status_text(remaining: int, total: int, state: db.ChatState) -> str:
    leader = _winner_label(state) if state.last_bid_user_id else None
    if remaining <= 10:
        return phrases.timer_countdown(remaining, total, leader)
    return phrases.timer_tick(remaining, total, leader)


async def _edit_status(bot: Bot, chat_id: int, message_id: int, text: str) -> None:
    try:
        await bot.edit_message_text(text, chat_id=chat_id, message_id=message_id)
    except TelegramBadRequest as e:
        err_msg = str(e).lower()
        if "message is not modified" in err_msg:
            return
        if "message to edit not found" in err_msg or "message is not found" in err_msg or "chat not found" in err_msg:
            try:
                # Recreate message
                msg = await bot.send_message(chat_id, text, disable_web_page_preview=True)
                await db.update_chat_state(chat_id, status_message_id=msg.message_id)
            except Exception:
                log.debug("Failed to send replacement status message chat=%s", chat_id, exc_info=True)
        else:
            log.debug("Status edit skipped chat=%s: %s", chat_id, e)
    except Exception:
        log.debug("Status edit failed chat=%s", chat_id, exc_info=True)


async def _send_or_refresh_status(bot: Bot, chat_id: int, text: str) -> int:
    state = await db.get_chat_state(chat_id)
    if state.status_message_id:
        await _edit_status(bot, chat_id, state.status_message_id, text)
        # Re-fetch state in case it was recreated and ID changed
        updated_state = await db.get_chat_state(chat_id)
        return updated_state.status_message_id or state.status_message_id
    msg = await bot.send_message(chat_id, text, disable_web_page_preview=True)
    await db.update_chat_state(chat_id, status_message_id=msg.message_id)
    return msg.message_id


async def _delete_bid_panel(bot: Bot, chat_id: int, state: db.ChatState) -> None:
    if not state.last_bid_message_id:
        return
    try:
        await bot.delete_message(chat_id, state.last_bid_message_id)
    except Exception:
        pass


async def _finish_round(bot: Bot, chat_id: int, state: db.ChatState) -> None:
    await _delete_bid_panel(bot, chat_id, state)
    final_text = _winner_message(state)
    await db.update_chat_state(
        chat_id,
        is_running=False,
        clear_last_bid_message=True,
    )
    if state.status_message_id:
        await _edit_status(bot, chat_id, state.status_message_id, final_text)
    else:
        await bot.send_message(chat_id, final_text, disable_web_page_preview=True)


async def update_status_now(bot: Bot, chat_id: int, end_at_unix: int, total_sec: int) -> None:
    state = await db.get_chat_state(chat_id)
    if not state.status_message_id:
        return
    remaining = max(0, end_at_unix - int(time.time()))
    await _edit_status(
        bot,
        chat_id,
        state.status_message_id,
        _status_text(remaining, total_sec, state),
    )


async def arm_timer(bot: Bot, chat_id: int) -> None:
    state = await db.get_chat_state(chat_id)
    if not state.is_running or not state.end_at_unix:
        return
    timers.schedule(chat_id, run_timer(bot, chat_id, state.end_at_unix, state.duration_seconds))


async def start_new_round(bot: Bot, chat_id: int, duration_seconds: int) -> int:
    end_at = int(time.time()) + int(duration_seconds)
    old_state = await db.get_chat_state(chat_id)
    await _delete_bid_panel(bot, chat_id, old_state)
    await db.update_chat_state(
        chat_id,
        is_running=True,
        end_at_unix=end_at,
        clear_last_bid=True,
    )
    await _send_or_refresh_status(
        bot,
        chat_id,
        phrases.timer_start(duration_seconds, duration_seconds),
    )
    timers.schedule(chat_id, run_timer(bot, chat_id, end_at, duration_seconds))
    return end_at


async def reset_round_on_bid(
    bot: Bot,
    chat_id: int,
    *,
    duration_seconds: int,
    bidder_user_id: int,
    bidder_username: Optional[str],
) -> int:
    end_at = int(time.time()) + int(duration_seconds)
    await db.update_chat_state(
        chat_id,
        is_running=True,
        last_bid_user_id=bidder_user_id,
        last_bid_username=bidder_username,
        end_at_unix=end_at,
    )
    await update_status_now(bot, chat_id, end_at, duration_seconds)
    timers.schedule(chat_id, run_timer(bot, chat_id, end_at, duration_seconds))
    return end_at


async def stop_round(chat_id: int) -> None:
    timers.cancel(chat_id)
    await db.update_chat_state(chat_id, is_running=False, clear_last_bid=True, clear_status_message=True)


def _winner_label(state: db.ChatState) -> str:
    if not state.last_bid_user_id:
        return ""
    if state.last_bid_username:
        return f"@{html.escape(state.last_bid_username)}"
    return f'<a href="tg://user?id={state.last_bid_user_id}">участник</a>'


def _winner_message(state: db.ChatState) -> str:
    if state.last_bid_user_id:
        return phrases.winner_with_bid(_winner_label(state))
    return phrases.winner_no_bid()


async def run_timer(bot: Bot, chat_id: int, end_at_unix: int, total_sec: int) -> None:
    try:
        last_tick = 0
        while True:
            now = int(time.time())
            remaining = end_at_unix - now
            if remaining <= 0:
                break

            state = await db.get_chat_state(chat_id)
            if not state.is_running or state.end_at_unix != end_at_unix:
                return

            if state.status_message_id:
                interval = 1 if remaining <= 10 else (2 if remaining <= 30 else 8)
                if now - last_tick >= interval:
                    await _edit_status(
                        bot,
                        chat_id,
                        state.status_message_id,
                        _status_text(remaining, total_sec, state),
                    )
                    last_tick = now

            await asyncio.sleep(0.4 if remaining <= 10 else min(remaining, 2))

        async with chat_locks[chat_id]:
            state = await db.get_chat_state(chat_id)
            if not state.is_running or state.end_at_unix != end_at_unix:
                return

            await _finish_round(bot, chat_id, state)
    except asyncio.CancelledError:
        return
    except Exception:
        log.exception("Timer crashed for chat_id=%s", chat_id)


async def finalize_if_expired(bot: Bot, chat_id: int) -> bool:
    async with chat_locks[chat_id]:
        state = await db.get_chat_state(chat_id)
        if not state.is_running or not state.end_at_unix:
            return False
        if int(time.time()) < int(state.end_at_unix):
            return False

        timers.cancel(chat_id)

        await _finish_round(bot, chat_id, state)
        return True
