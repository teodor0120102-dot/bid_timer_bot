"""BidTimerBot — команды и обработка сообщений-ставок."""

from __future__ import annotations

import html
import logging
import re
import time
from typing import Awaitable, Callable, Optional

from aiogram import F, Router
from aiogram.filters import Command, ChatMemberUpdatedFilter, IS_MEMBER, IS_NOT_MEMBER
from aiogram.types import ChatMemberUpdated, Message, FSInputFile

import database as db
import permissions
import phrases
import scheduler
import stars

log = logging.getLogger("bidtimer")

router = Router(name="bid_timer")

Handler = Callable[[Message, str], Awaitable[None]]


def _format_remaining(end_at_unix: Optional[int]) -> str:
    if not end_at_unix:
        return "—"
    return phrases.format_time(max(0, int(end_at_unix) - int(time.time())))


async def _require_stars(message: Message) -> Optional[int]:
    paid = await stars.fetch_paid_stars(message.bot, message.chat.id)
    if not stars.stars_enabled(paid):
        await message.reply(phrases.stars_required())
        return None
    return paid


def _bid_args(message: Message) -> tuple[str, str]:
    parts = (message.text or "").split(maxsplit=2)
    sub = parts[1].lower() if len(parts) > 1 else "help"
    rest = parts[2] if len(parts) > 2 else ""
    return sub, rest


def _target_from_message(message: Message, arg: str) -> tuple[Optional[int], Optional[str]]:
    if message.reply_to_message and message.reply_to_message.from_user:
        u = message.reply_to_message.from_user
        return u.id, u.username
    arg = arg.strip().lstrip("@")
    if arg.isdigit():
        return int(arg), None
    if arg:
        return None, arg
    return None, None


@router.my_chat_member(ChatMemberUpdatedFilter(IS_MEMBER >> IS_NOT_MEMBER))
async def on_bot_removed(event: ChatMemberUpdated) -> None:
    await scheduler.stop_round(event.chat.id)


@router.my_chat_member(ChatMemberUpdatedFilter(IS_NOT_MEMBER >> IS_MEMBER))
async def on_bot_added(event: ChatMemberUpdated) -> None:
    chat_id = event.chat.id
    await db.get_chat_state(chat_id)
    paid = await stars.fetch_paid_stars(event.bot, chat_id, force=True)
    try:
        banner = FSInputFile("assets/welcome_banner.png")
        await event.bot.send_photo(
            chat_id=chat_id,
            photo=banner,
            caption=phrases.welcome(paid)
        )
    except Exception:
        await event.answer(phrases.welcome(paid))
    log.info("Bot added to chat=%s stars=%s", chat_id, paid)


@router.message(F.paid_message_price_changed)
async def on_paid_price_changed(message: Message) -> None:
    change = message.paid_message_price_changed
    if not change:
        return
    count = int(change.paid_message_star_count)
    stars.invalidate_paid_cache(message.chat.id)
    await db.update_chat_state(message.chat.id, paid_message_star_count=count)
    if not stars.stars_enabled(count):
        await scheduler.stop_round(message.chat.id)
        await message.answer(phrases.stars_disabled())


async def _help(message: Message, _: str) -> None:
    if await permissions.deny_if_cannot_manage(message):
        return
    try:
        banner = FSInputFile("assets/welcome_banner.png")
        await message.answer_photo(
            banner,
            caption=phrases.help_text(),
        )
    except Exception:
        await message.answer(phrases.help_text())


async def _status(message: Message, _: str) -> None:
    if await permissions.deny_if_cannot_manage(message):
        return
    paid = await stars.fetch_paid_stars(message.bot, message.chat.id)
    state = await db.get_chat_state(message.chat.id)
    managers = await db.list_chat_managers(message.chat.id)
    mgr_lines = []
    for uid, uname in managers:
        if uname:
            mgr_lines.append(f"@{html.escape(uname)}")
        elif uid:
            mgr_lines.append(f"<code>{uid}</code>")
    await message.answer(
        phrases.status(
            stars=paid,
            stars_on=stars.stars_enabled(paid),
            running=state.is_running,
            remaining=_format_remaining(state.end_at_unix),
            duration=state.duration_seconds,
            mode=state.trigger_mode,
            regex=state.trigger_regex,
            managers=", ".join(mgr_lines) if mgr_lines else "—",
        )
    )


async def _start(message: Message, arg: str) -> None:
    if await permissions.deny_if_cannot_manage(message):
        return
    if await _require_stars(message) is None:
        return
    state = await db.get_chat_state(message.chat.id)
    seconds = state.duration_seconds
    if arg.strip().isdigit():
        seconds = int(arg.strip())
    await scheduler.start_new_round(message.bot, message.chat.id, seconds)
    log.info("Round started chat=%s sec=%s by=%s", message.chat.id, seconds, message.from_user.id)


async def _stop(message: Message, _: str) -> None:
    if await permissions.deny_if_cannot_manage(message):
        return
    await scheduler.stop_round(message.chat.id)
    await message.answer(phrases.stopped())


async def _time(message: Message, arg: str) -> None:
    if await permissions.deny_if_cannot_manage(message):
        return
    if not arg.strip().isdigit():
        await message.answer(phrases.card("Подсказка", "Пример: <code>/bid time 150</code>"))
        return
    seconds = int(arg.strip())
    if seconds < 5 or seconds > 86400:
        await message.answer(phrases.card("Ошибка", "Допустимо от 5 до 86400 секунд."))
        return

    state = await db.get_chat_state(message.chat.id)

    # Если раунд идёт — меняем время прямо на лету
    if state.is_running and state.end_at_unix:
        now = int(time.time())
        old_remaining = max(0, state.end_at_unix - now)
        # Новый конец = сейчас + новая длительность
        new_end = now + seconds
        await db.update_chat_state(
            message.chat.id,
            duration_seconds=seconds,
            end_at_unix=new_end,
        )
        # Перезапустить таймер с новым end_at
        scheduler.timers.cancel(message.chat.id)
        scheduler.timers.schedule(
            message.chat.id,
            scheduler.run_timer(message.bot, message.chat.id, new_end, seconds),
        )
        await scheduler.update_status_now(message.bot, message.chat.id, new_end, seconds)
        await message.answer(
            phrases.card(
                "⏱ Время изменено на лету",
                f"Было: <b>{phrases.format_time(old_remaining)}</b> осталось\n"
                f"Новая длительность: <b>{seconds}</b> сек ({phrases.format_time(seconds)})\n"
                f"Таймер сброшен на <b>{phrases.format_time(seconds)}</b>",
            )
        )
        log.info("Time changed mid-round chat=%s new_sec=%s by=%s", message.chat.id, seconds, message.from_user.id)
    else:
        await db.update_chat_state(message.chat.id, duration_seconds=seconds)
        await message.answer(phrases.setting_time(seconds))


async def _regex(message: Message, arg: str) -> None:
    if await permissions.deny_if_cannot_manage(message):
        return
    pattern = arg.strip()
    if not pattern:
        await message.answer(phrases.card("Подсказка", "Пример: <code>/bid regex перебил</code>"))
        return
    try:
        re.compile(pattern, flags=re.IGNORECASE)
    except re.error as e:
        await message.answer(phrases.card("Ошибка", f"Regex невалиден: {e}"))
        return
    await db.update_chat_state(message.chat.id, trigger_regex=pattern)
    await message.answer(phrases.setting_regex(pattern))


async def _mode(message: Message, arg: str) -> None:
    if await permissions.deny_if_cannot_manage(message):
        return
    mode = arg.strip().lower()
    if mode not in ("paid", "regex", "both"):
        await message.answer(phrases.card("Режимы", "<code>paid</code> · <code>regex</code> · <code>both</code>"))
        return
    await db.update_chat_state(message.chat.id, trigger_mode=mode)
    hints = {
        "paid": "Ставка — только платное сообщение за ⭐",
        "regex": "Ставка — текст по заданному шаблону",
        "both": "Ставка — платное сообщение или совпадение с шаблоном",
    }
    await message.answer(phrases.setting_mode(mode, hints[mode]))


async def _add(message: Message, arg: str) -> None:
    if await permissions.deny_if_cannot_manage(message):
        return
    user_id, username = _target_from_message(message, arg)
    if user_id is None and not username:
        await message.answer(
            phrases.card(
                "Добавить менеджера",
                "Ответьте на сообщение: <code>/bid add</code>\n"
                "или укажите: <code>/bid add @username</code>",
            )
        )
        return
    await db.add_chat_manager(message.chat.id, user_id=user_id, username=username)
    label = f"@{username}" if username else f"id {user_id}"
    await message.answer(phrases.manager_added(label))


async def _del(message: Message, arg: str) -> None:
    if await permissions.deny_if_cannot_manage(message):
        return
    user_id, username = _target_from_message(message, arg)
    if user_id is None and not username:
        await message.answer(phrases.card("Подсказка", "Пример: <code>/bid del @username</code>"))
        return
    await db.remove_chat_manager(message.chat.id, user_id=user_id, username=username)
    label = f"@{username}" if username else f"id {user_id}"
    await message.answer(phrases.manager_removed(label))


async def _managers(message: Message, _: str) -> None:
    if await permissions.deny_if_cannot_manage(message):
        return
    items = await db.list_chat_managers(message.chat.id)
    lines = []
    for uid, uname in items:
        if uname:
            lines.append(f"▸ @{html.escape(uname)}")
        elif uid:
            lines.append(f"▸ id <code>{uid}</code>")
    await message.answer(phrases.managers_list("\n".join(lines)))


_BID_HANDLERS: dict[str, Handler] = {
    "help": _help,
    "status": _status,
    "start": _start,
    "stop": _stop,
    "time": _time,
    "regex": _regex,
    "mode": _mode,
    "add": _add,
    "del": _del,
    "managers": _managers,
}


@router.message(Command("bid", ignore_case=True))
async def cmd_bid(message: Message) -> None:
    sub, rest = _bid_args(message)
    handler = _BID_HANDLERS.get(sub, _help)
    await handler(message, rest)


@router.message(Command("timer_help", "help", ignore_case=True))
async def cmd_help_legacy(message: Message) -> None:
    await _help(message, "")


@router.message(Command("timer_status", "status", ignore_case=True))
async def cmd_status_legacy(message: Message) -> None:
    await _status(message, "")


@router.message(Command("timer_start", "start", "t", "go", "старт", ignore_case=True))
async def cmd_start_legacy(message: Message) -> None:
    parts = (message.text or "").split(maxsplit=1)
    await _start(message, parts[1] if len(parts) > 1 else "")


@router.message(Command("timer_stop", "stop", "стоп", ignore_case=True))
async def cmd_stop_legacy(message: Message) -> None:
    await _stop(message, "")


@router.message(Command("timer_set_seconds", ignore_case=True))
async def cmd_time_legacy(message: Message) -> None:
    parts = (message.text or "").split(maxsplit=1)
    await _time(message, parts[1] if len(parts) > 1 else "")


@router.message(Command("timer_set_regex", ignore_case=True))
async def cmd_regex_legacy(message: Message) -> None:
    parts = (message.text or "").split(maxsplit=1)
    await _regex(message, parts[1] if len(parts) > 1 else "")


@router.message(Command("timer_mode", ignore_case=True))
async def cmd_mode_legacy(message: Message) -> None:
    parts = (message.text or "").split(maxsplit=1)
    await _mode(message, parts[1] if len(parts) > 1 else "")


@router.message(Command("timer_add", "bid_add", ignore_case=True))
async def cmd_add_legacy(message: Message) -> None:
    parts = (message.text or "").split(maxsplit=1)
    await _add(message, parts[1] if len(parts) > 1 else "")


@router.message(Command("timer_del", "timer_remove", "bid_del", ignore_case=True))
async def cmd_del_legacy(message: Message) -> None:
    parts = (message.text or "").split(maxsplit=1)
    await _del(message, parts[1] if len(parts) > 1 else "")


@router.message(Command("timer_managers", "bid_managers", ignore_case=True))
async def cmd_managers_legacy(message: Message) -> None:
    await _managers(message, "")


# ── ОПРЕДЕЛЕНИЕ СТАВКИ ──────────────────────────────────────────────────────

def _is_paid_bid(message: Message) -> bool:
    """Проверяем несколько атрибутов — совместимость с разными версиями Bot API.

    aiogram 3.17+ может иметь:
      - message.paid_star_count  (Bot API 8.x+)
      - message.paid_message_star_count  (старые Bot API)
      - successful_payment
    """
    for attr in ("paid_star_count", "paid_message_star_count"):
        val = getattr(message, attr, None)
        if val is not None and int(val) > 0:
            log.info(
                "PAID BID: chat=%s user=%s attr=%s val=%s text=%r",
                message.chat.id,
                message.from_user.id if message.from_user else "?",
                attr, val,
                (message.text or "")[:50],
            )
            return True
    # Проверяем successful_payment (для некоторых типов Stars-платежей)
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


@router.message()
async def on_any_message(message: Message) -> None:
    if message.paid_message_price_changed:
        return

    # 1. Проверяем, запущен ли раунд
    state = await db.get_chat_state(message.chat.id)
    if not state.is_running:
        return

    if await scheduler.finalize_if_expired(message.bot, message.chat.id):
        return

    user = message.from_user
    if not user:
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

    log.info(
        "BID ACCEPTED: chat=%s user=%s (%s) mode=%s paid=%s",
        message.chat.id, user.id, user.username or "?", mode, is_potentially_paid,
    )

    end_at = await scheduler.reset_round_on_bid(
        message.bot,
        message.chat.id,
        duration_seconds=state.duration_seconds,
        bidder_user_id=user.id,
        bidder_username=user.username,
    )
    remaining = max(0, end_at - int(time.time()))
    mention_name = html.escape(user.full_name or "участник")
    mention = f'<a href="tg://user?id={user.id}">{mention_name}</a>'
    await message.reply(
        phrases.bid_reset(
            mention=mention,
            time_str=_format_remaining(end_at),
            total_sec=state.duration_seconds,
            remaining_sec=remaining,
        )
    )
