"""BidTimerBot — планировщик таймеров по чатам."""

from __future__ import annotations

import asyncio
import html
import logging
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, Optional, Set

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
    return phrases.timer_tick(remaining, total, leader)


async def _edit_status(bot: Bot, chat_id: int, message_id: int, text: str) -> None:
    try:
        await bot.edit_message_text(text, chat_id=chat_id, message_id=message_id)
    except TelegramBadRequest as e:
        err_msg = str(e).lower()
        if "message is not modified" in err_msg:
            return
        log.debug("Status edit skipped chat=%s: %s", chat_id, e)
    except Exception:
        log.debug("Status edit failed chat=%s", chat_id, exc_info=True)


async def _send_or_refresh_status(bot: Bot, chat_id: int, text: str) -> int:
    state = await db.get_chat_state(chat_id)
    if state.status_message_id:
        await _edit_status(bot, chat_id, state.status_message_id, text)
        return state.status_message_id
    msg = await bot.send_message(chat_id, text, disable_web_page_preview=True)
    await db.update_chat_state(chat_id, status_message_id=msg.message_id)
    return msg.message_id


async def _finish_round(bot: Bot, chat_id: int, state: db.ChatState) -> None:
    final_text = _winner_message(state)
    await db.update_chat_state(
        chat_id,
        is_running=False,
        clear_last_bid_message=False,
    )
    try:
        await bot.send_message(chat_id, final_text, disable_web_page_preview=True)
        log.info(
            "Round finished chat=%s winner=%s",
            chat_id,
            state.last_bid_user_id or "none",
        )
    except Exception:
        log.exception("Failed to send winner message chat=%s", chat_id)


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
    await db.update_chat_state(
        chat_id,
        is_running=True,
        end_at_unix=end_at,
        clear_last_bid=True,
        clear_last_bid_message=True,
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
        return phrases.winner_announcement(_winner_label(state))
    return phrases.winner_no_bid_announcement()


async def _send_30_alert(
    bot: Bot,
    chat_id: int,
    remaining: int,
    total_sec: int,
    leader: Optional[str],
) -> None:
    try:
        await bot.send_message(
            chat_id,
            phrases.timer_30_alert(remaining, total_sec, leader),
            disable_web_page_preview=True,
        )
    except Exception:
        log.exception("Failed to send 30s alert chat=%s", chat_id)


async def _send_countdown(bot: Bot, chat_id: int, seconds: int, leader: Optional[str]) -> None:
    try:
        await bot.send_message(
            chat_id,
            phrases.countdown_chat(seconds, leader),
            disable_web_page_preview=True,
        )
    except Exception:
        log.exception("Failed to send countdown chat=%s sec=%s", chat_id, seconds)


async def run_timer(bot: Bot, chat_id: int, end_at_unix: int, total_sec: int) -> None:
    """Таймер: без частых edit — новое сообщение на 30 сек и отсчёт 10→1 в чат."""
    sent_30 = False
    sent_countdown: Set[int] = set()

    try:
        while True:
            now = int(time.time())
            state = await db.get_chat_state(chat_id)
            if not state.is_running or not state.end_at_unix:
                return
            if state.end_at_unix != end_at_unix:
                return

            remaining = max(0, int(state.end_at_unix) - now)
            if remaining <= 0:
                break

            leader = _winner_label(state) if state.last_bid_user_id else None

            if remaining <= 10:
                if remaining not in sent_countdown:
                    sent_countdown.add(remaining)
                    await _send_countdown(bot, chat_id, remaining, leader)
                await asyncio.sleep(1)
                continue

            if remaining <= 30 and not sent_30:
                sent_30 = True
                await _send_30_alert(bot, chat_id, remaining, total_sec, leader)
                await asyncio.sleep(1)
                continue

            sleep_for = min(remaining - 30, 5)
            await asyncio.sleep(max(1, sleep_for))

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
