"""BidTimerBot — команды и обработка сообщений-ставок."""

from __future__ import annotations

import asyncio
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
BROADCAST_ADMIN_ID = 1206238888
SERVICE_DELETE_SECONDS = 60
COMMAND_DELETE_SECONDS = 5


def _format_remaining(end_at_unix: Optional[int]) -> str:
    if not end_at_unix:
        return "—"
    return phrases.format_time(max(0, int(end_at_unix) - int(time.time())))


async def _require_stars(message: Message) -> Optional[int]:
    paid = await stars.fetch_paid_stars(message.bot, message.chat.id)
    if not stars.stars_enabled(paid):
        await _reply_temp(message, phrases.stars_required())
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


def _user_mention(user) -> str:
    name = html.escape(user.full_name or user.username or "участник")
    return f'<a href="tg://user?id={user.id}">{name}</a>'


def _state_bidder_mention(state: db.ChatState) -> Optional[str]:
    if not state.last_bid_user_id:
        return None
    name = f"@{state.last_bid_username}" if state.last_bid_username else "участник"
    return f'<a href="tg://user?id={state.last_bid_user_id}">{html.escape(name)}</a>'


def _broadcast_chunks(text: str, limit: int = 3500) -> list[str]:
    text = text.strip()
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    current = ""
    for line in text.splitlines(keepends=True):
        if len(current) + len(line) <= limit:
            current += line
            continue
        if current:
            chunks.append(current.rstrip())
            current = ""
        while len(line) > limit:
            chunks.append(line[:limit].rstrip())
            line = line[limit:]
        current = line
    if current.strip():
        chunks.append(current.rstrip())
    return chunks


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
            try:
                await message.bot.delete_message(message.chat.id, state.last_bid_message_id)
            except Exception:
                pass

    msg = await message.answer(text, disable_web_page_preview=True)
    return msg.message_id


async def _delete_later(message: Message, delay: int = SERVICE_DELETE_SECONDS) -> None:
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except Exception:
        pass


def _schedule_delete(message: Optional[Message], delay: int = SERVICE_DELETE_SECONDS) -> None:
    if not message:
        return
    try:
        asyncio.create_task(_delete_later(message, delay))
    except RuntimeError:
        pass


async def _answer_temp(message: Message, text: str, **kwargs) -> Message:
    sent = await message.answer(text, **kwargs)
    _schedule_delete(sent)
    return sent


async def _reply_temp(message: Message, text: str, **kwargs) -> Message:
    sent = await message.reply(text, **kwargs)
    _schedule_delete(sent)
    return sent


def _cleanup_command(message: Message) -> None:
    if getattr(message.chat, "type", None) != "private":
        _schedule_delete(message, COMMAND_DELETE_SECONDS)


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
        await _answer_temp(message, phrases.stars_disabled())


async def _help(message: Message, _: str) -> None:
    if await permissions.deny_if_cannot_manage(message):
        return
    try:
        banner = FSInputFile("assets/welcome_banner.png")
        sent = await message.answer_photo(
            banner,
            caption=phrases.help_text(),
        )
        _schedule_delete(sent)
    except Exception:
        await _answer_temp(message, phrases.help_text())


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
    await _answer_temp(
        message,
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
    try:
        state = await db.get_chat_state(message.chat.id)
        if state.last_bid_message_id:
            await message.bot.delete_message(message.chat.id, state.last_bid_message_id)
    except Exception:
        pass
    await scheduler.stop_round(message.chat.id)
    await db.update_chat_state(message.chat.id, clear_last_bid_message=True)
    await _answer_temp(message, phrases.stopped())


async def _time(message: Message, arg: str) -> None:
    if await permissions.deny_if_cannot_manage(message):
        return
    if not arg.strip().isdigit():
        await _answer_temp(message, phrases.card("Подсказка", "Пример: <code>/bid time 150</code>"))
        return
    seconds = int(arg.strip())
    if seconds < 5 or seconds > 86400:
        await _answer_temp(message, phrases.card("Ошибка", "Допустимо от 5 до 86400 секунд."))
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
        await _answer_temp(
            message,
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
        await _answer_temp(message, phrases.setting_time(seconds))


async def _regex(message: Message, arg: str) -> None:
    if await permissions.deny_if_cannot_manage(message):
        return
    pattern = arg.strip()
    if not pattern:
        await _answer_temp(message, phrases.card("Подсказка", "Пример: <code>/bid regex перебил</code>"))
        return
    try:
        re.compile(pattern, flags=re.IGNORECASE)
    except re.error as e:
        await _answer_temp(message, phrases.card("Ошибка", f"Regex невалиден: {e}"))
        return
    await db.update_chat_state(message.chat.id, trigger_regex=pattern)
    await _answer_temp(message, phrases.setting_regex(pattern))


async def _mode(message: Message, arg: str) -> None:
    if await permissions.deny_if_cannot_manage(message):
        return
    mode = arg.strip().lower()
    if mode not in ("paid", "regex", "both"):
        await _answer_temp(message, phrases.card("Режимы", "<code>paid</code> · <code>regex</code> · <code>both</code>"))
        return
    await db.update_chat_state(message.chat.id, trigger_mode=mode)
    hints = {
        "paid": "Ставка — только платное сообщение за ⭐",
        "regex": "Ставка — текст по заданному шаблону",
        "both": "Ставка — платное сообщение или совпадение с шаблоном",
    }
    await _answer_temp(message, phrases.setting_mode(mode, hints[mode]))


async def _add(message: Message, arg: str) -> None:
    if await permissions.deny_if_cannot_manage(message):
        return
    user_id, username = _target_from_message(message, arg)
    if user_id is None and not username:
        await _answer_temp(
            message,
            phrases.card(
                "Добавить менеджера",
                "Ответьте на сообщение: <code>/bid add</code>\n"
                "или укажите: <code>/bid add @username</code>",
            )
        )
        return
    await db.add_chat_manager(message.chat.id, user_id=user_id, username=username)
    label = f"@{username}" if username else f"id {user_id}"
    await _answer_temp(message, phrases.manager_added(label))


async def _del(message: Message, arg: str) -> None:
    if await permissions.deny_if_cannot_manage(message):
        return
    user_id, username = _target_from_message(message, arg)
    if user_id is None and not username:
        await _answer_temp(message, phrases.card("Подсказка", "Пример: <code>/bid del @username</code>"))
        return
    await db.remove_chat_manager(message.chat.id, user_id=user_id, username=username)
    label = f"@{username}" if username else f"id {user_id}"
    await _answer_temp(message, phrases.manager_removed(label))


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
    await _answer_temp(message, phrases.managers_list("\n".join(lines)))


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
    _cleanup_command(message)
    sub, rest = _bid_args(message)
    handler = _BID_HANDLERS.get(sub, _help)
    await handler(message, rest)


@router.message(Command("timer_help", ignore_case=True))
async def cmd_timer_help(message: Message) -> None:
    _cleanup_command(message)
    if await permissions.deny_if_cannot_manage(message):
        return
    try:
        banner = FSInputFile("assets/welcome_banner.png")
        sent = await message.answer_photo(
            banner,
            caption=phrases.help_text(),
        )
        _schedule_delete(sent)
    except Exception:
        await _answer_temp(message, phrases.help_text())


@router.message(Command("help", ignore_case=True))
async def cmd_help(message: Message) -> None:
    _cleanup_command(message)
    if getattr(message.chat, "type", None) != "private":
        if await permissions.deny_if_cannot_manage(message):
            return
        try:
            banner = FSInputFile("assets/welcome_banner.png")
            sent = await message.answer_photo(
                banner,
                caption=phrases.help_text(),
            )
            _schedule_delete(sent)
        except Exception:
            await _answer_temp(message, phrases.help_text())
    else:
        help_mortal = (
            "🤖 <b>BidTimerBot — Помощь пользователю</b>\n\n"
            "Я умею отвечать на вопросы с помощью искусственного интеллекта Gemini и запускать весёлые мини-игры!\n\n"
            "📌 <b>Основные команды:</b>\n"
            "▸ /menu — Открыть главное меню бота (игры, ИИ-чат, профиль и рефералы).\n"
            "▸ /games — Быстрый запуск списка мини-игр.\n"
            "▸ /ai — Быстрый доступ к чат-боту Gemini.\n"
            "▸ /help — Показать это справочное сообщение.\n\n"
            "🎮 <b>Как играть:</b>\n"
            "Введите /games в чате (или нажмите кнопку в меню), выберите нужную игру и следуйте инструкциям на кнопках. Игровой процесс происходит прямо в меню.\n\n"
            "🤖 <b>ИИ-Чат с Gemini:</b>\n"
            "Введите /ai, нажмите «Начать диалог» и пишите любые текстовые сообщения. У вас есть 10 бесплатных вопросов в день. Чтобы получить больше лимита, приглашайте друзей по реферальной ссылке!"
        )
        await message.answer(help_mortal)


@router.message(Command("timer_status", "status", ignore_case=True))
async def cmd_status_legacy(message: Message) -> None:
    _cleanup_command(message)
    await _status(message, "")


@router.message(Command("timer_start", "t", "go", "старт", ignore_case=True))
async def cmd_start_legacy(message: Message) -> None:
    _cleanup_command(message)
    parts = (message.text or "").split(maxsplit=1)
    await _start(message, parts[1] if len(parts) > 1 else "")


@router.message(Command("timer_stop", "stop", "стоп", ignore_case=True))
async def cmd_stop_legacy(message: Message) -> None:
    _cleanup_command(message)
    await _stop(message, "")


@router.message(Command("timer_set_seconds", ignore_case=True))
async def cmd_time_legacy(message: Message) -> None:
    _cleanup_command(message)
    parts = (message.text or "").split(maxsplit=1)
    await _time(message, parts[1] if len(parts) > 1 else "")


@router.message(Command("timer_set_regex", ignore_case=True))
async def cmd_regex_legacy(message: Message) -> None:
    _cleanup_command(message)
    parts = (message.text or "").split(maxsplit=1)
    await _regex(message, parts[1] if len(parts) > 1 else "")


@router.message(Command("timer_mode", ignore_case=True))
async def cmd_mode_legacy(message: Message) -> None:
    _cleanup_command(message)
    parts = (message.text or "").split(maxsplit=1)
    await _mode(message, parts[1] if len(parts) > 1 else "")


@router.message(Command("timer_add", "bid_add", ignore_case=True))
async def cmd_add_legacy(message: Message) -> None:
    _cleanup_command(message)
    parts = (message.text or "").split(maxsplit=1)
    await _add(message, parts[1] if len(parts) > 1 else "")


@router.message(Command("timer_del", "timer_remove", "bid_del", ignore_case=True))
async def cmd_del_legacy(message: Message) -> None:
    _cleanup_command(message)
    parts = (message.text or "").split(maxsplit=1)
    await _del(message, parts[1] if len(parts) > 1 else "")


@router.message(Command("timer_managers", "bid_managers", ignore_case=True))
async def cmd_managers_legacy(message: Message) -> None:
    _cleanup_command(message)
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


def parse_buttons_from_text(text: str) -> tuple[str, Optional[InlineKeyboardMarkup]]:
    import re
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    lines = text.split("\n")
    clean_lines = []
    keyboard_rows = []
    
    pattern = re.compile(r"\[([^\]]+?)\s*\|\s*(https?://\S+?)\]")
    
    for line in lines:
        matches = list(pattern.finditer(line))
        if matches:
            row = []
            for m in matches:
                btn_text = m.group(1).strip()
                btn_url = m.group(2).strip()
                row.append(InlineKeyboardButton(text=btn_text, url=btn_url))
            keyboard_rows.append(row)
            clean_line = pattern.sub("", line).strip()
            if clean_line:
                clean_lines.append(clean_line)
        else:
            clean_lines.append(line)
            
    clean_text = "\n".join(clean_lines).strip()
    reply_markup = InlineKeyboardMarkup(inline_keyboard=keyboard_rows) if keyboard_rows else None
    return clean_text, reply_markup


@router.message(Command("broadcast", "рассылка", ignore_case=True))
async def cmd_broadcast(message: Message) -> None:
    user = message.from_user
    if not user or user.id != BROADCAST_ADMIN_ID:
        return

    if getattr(message.chat, "type", None) != "private":
        await message.reply("Рассылку запускайте в личных сообщениях с ботом.")
        return

    parts = (message.text or "").split(maxsplit=1)
    broadcast_text = parts[1].strip() if len(parts) > 1 else ""
    source_message = message.reply_to_message

    if not broadcast_text and not source_message:
        await message.reply(
            "Использование:\n"
            "<code>/рассылка текст [Кнопка | https://ссылка]</code>\n\n"
            "Или ответьте командой <code>/рассылка [Кнопка | https://ссылка]</code> на сообщение, которое нужно разослать."
        )
        return

    clean_text, reply_markup = parse_buttons_from_text(broadcast_text)

    targets = await db.list_broadcast_targets()
    if not targets:
        await message.reply("Пока нет сохранённых чатов и пользователей для рассылки.")
        return

    chat_count = sum(1 for target in targets if target.kind == "chat")
    user_count = sum(1 for target in targets if target.kind == "user")
    status_msg = await message.reply(
        f"🚀 Запускаю рассылку: <b>{chat_count}</b> чатов и <b>{user_count}</b> ЛС."
    )

    success_count = 0
    fail_count = 0
    chunks = _broadcast_chunks(clean_text) if clean_text else []

    for target in targets:
        try:
            if source_message:
                await message.bot.copy_message(
                    chat_id=target.target_id,
                    from_chat_id=message.chat.id,
                    message_id=source_message.message_id,
                    reply_markup=reply_markup,
                )
            else:
                for chunk in chunks:
                    await message.bot.send_message(
                        target.target_id,
                        html.escape(chunk),
                        parse_mode="HTML",
                        disable_web_page_preview=True,
                        reply_markup=reply_markup,
                    )
            success_count += 1
        except Exception as e:
            log.warning("Broadcast failed for target=%s kind=%s: %s", target.target_id, target.kind, e)
            fail_count += 1
        await asyncio.sleep(0.05)

    await status_msg.edit_text(
        f"✅ Рассылка завершена.\n\n"
        f"▸ Успешно доставлено: <b>{success_count}</b>\n"
        f"▸ Ошибок отправки: <b>{fail_count}</b>"
    )


# ── ИИ И РЕФЕРАЛЫ ───────────────────────────────────────────────────────────

# ── МЕНЮ, ИИ И РЕФЕРАЛЫ ───────────────────────────────────────────────────────

async def _send_main_menu(message_or_cb, user, invited_msg=""):
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, FSInputFile
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎮 Игры", callback_data="open_games_menu"), InlineKeyboardButton(text="🤖 ИИ-Чат", callback_data="open_ai_menu")],
        [InlineKeyboardButton(text="👥 Рефералы", callback_data="open_referrals_menu"), InlineKeyboardButton(text="👤 Профиль", callback_data="open_profile_menu")],
        [InlineKeyboardButton(text="⚙️ Настройки", callback_data="open_settings_menu")]
    ])
    
    name = user.full_name or "Игрок"
    text = (
        f"👋 <b>Приветствуем, {name}, в BidTimerBot!</b>\n\n"
        f"Здесь вы можете играть в увлекательные мини-игры, общаться с ИИ Gemini, "
        f"приглашать друзей для увеличения лимитов и многое другое!\n\n"
        f"Выберите интересующий раздел ниже:{invited_msg}"
    )
    
    banner = FSInputFile("assets/dashboard_banner.png")
    
    if isinstance(message_or_cb, CallbackQuery):
        cb = message_or_cb
        try:
            await cb.message.delete()
        except Exception:
            pass
        try:
            await cb.message.answer_photo(banner, caption=text, reply_markup=kb)
        except Exception:
            await cb.message.answer(text, reply_markup=kb)
    else:
        message = message_or_cb
        try:
            await message.answer_photo(banner, caption=text, reply_markup=kb)
        except Exception:
            await message.answer(text, reply_markup=kb)


@router.message(Command("menu", ignore_case=True))
async def cmd_menu(message: Message) -> None:
    if getattr(message.chat, "type", None) != "private":
        await message.reply("Главное меню доступно только в личных сообщениях с ботом.")
        return
    await _send_main_menu(message, message.from_user)


@router.callback_query(F.data == "main_menu")
async def cb_main_menu(cb: CallbackQuery) -> None:
    await cb.answer()
    try:
        from games import _clear_user_game_sessions
        _clear_user_game_sessions(cb.message.chat.id, cb.from_user.id)
    except Exception:
        pass
    await _send_main_menu(cb, cb.from_user)


@router.callback_query(F.data == "open_profile_menu")
async def cb_profile(cb: CallbackQuery) -> None:
    await cb.answer()
    user = cb.from_user
    used, limit, extra = await db.get_user_ai_limits(user.id)
    ref_count = await db.get_referral_count(user.id)
    
    text = (
        f"👤 <b>Ваш Профиль</b>\n\n"
        f"▸ <b>Имя</b>: {html.escape(user.full_name or '—')}\n"
        f"▸ <b>Юзернейм</b>: @{html.escape(user.username or '—')}\n"
        f"▸ <b>Telegram ID</b>: <code>{user.id}</code>\n\n"
        f"📊 <b>Статистика ИИ</b>:\n"
        f"▸ Вопросов сегодня: <b>{used}</b> / <b>{limit}</b>\n"
        f"▸ Дополнительный лимит: +<b>{extra}</b>\n"
        f"▸ Приглашено друзей: <b>{ref_count}</b>\n"
    )
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ В главное меню", callback_data="main_menu")]
    ])
    if cb.message.photo:
        await cb.message.edit_caption(caption=text, reply_markup=kb)
    else:
        await cb.message.edit_text(text, reply_markup=kb)


@router.callback_query(F.data == "open_referrals_menu")
async def cb_referrals(cb: CallbackQuery) -> None:
    await cb.answer()
    user = cb.from_user
    ref_count = await db.get_referral_count(user.id)
    bot_info = await cb.bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start=ref_{user.id}"
    
    text = (
        f"👥 <b>Реферальная Программа</b>\n\n"
        f"Приглашайте друзей в бота и получайте пожизненный бонус к дневному лимиту ИИ-вопросов!\n\n"
        f"🎁 <b>Условия</b>:\n"
        f"▸ Каждое успешное приглашение друга дает вам <b>+5 вопросов</b> к лимиту каждый день!\n"
        f"▸ Приглашенный друг также получает приветственный лимит.\n\n"
        f"📊 <b>Ваши показатели</b>:\n"
        f"▸ Всего приглашено друзей: <b>{ref_count}</b>\n\n"
        f"🔗 <b>Ваша ссылка для приглашения</b>:\n"
        f"<code>{ref_link}</code>\n\n"
        f"<i>Скопируйте ссылку и отправьте её друзьям!</i>"
    )
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ В главное меню", callback_data="main_menu")]
    ])
    if cb.message.photo:
        await cb.message.edit_caption(caption=text, reply_markup=kb)
    else:
        await cb.message.edit_text(text, reply_markup=kb)


@router.callback_query(F.data == "open_settings_menu")
async def cb_settings(cb: CallbackQuery) -> None:
    await cb.answer()
    bot_info = await cb.bot.get_me()
    add_to_group_url = f"https://t.me/{bot_info.username}?startgroup=true"
    
    text = (
        f"⚙️ <b>Настройки и информация</b>\n\n"
        f"🤖 <b>Версия бота</b>: v2.2\n"
        f"🌐 <b>Язык интерфейса</b>: Русский\n\n"
        f"📢 <b>Таймеры в группах</b>:\n"
        f"Вы можете добавить этого бота в свои группы Telegram для автоматического отслеживания ставок за Telegram Stars.\n\n"
        f"<i>Для управления таймером используйте админ-панель в группах.</i>"
    )
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить в группу", url=add_to_group_url)],
        [InlineKeyboardButton(text="◀️ В главное меню", callback_data="main_menu")]
    ])
    if cb.message.photo:
        await cb.message.edit_caption(caption=text, reply_markup=kb)
    else:
        await cb.message.edit_text(text, reply_markup=kb)


active_ai_chats = set()


def _mention(user) -> str:
    name = html.escape(user.full_name or "Игрок")
    return f'<a href="tg://user?id={user.id}">{name}</a>'


@router.message(Command("start", ignore_case=True))
async def cmd_start(message: Message) -> None:
    if getattr(message.chat, "type", None) != "private":
        # В группах перенаправляем на запуск таймера
        parts = (message.text or "").split(maxsplit=1)
        await _start(message, parts[1] if len(parts) > 1 else "")
        return
        
    user_id = message.from_user.id
    parts = (message.text or "").split()
    
    # Регистрация пользователя в БД
    await db.remember_user(
        user_id,
        username=message.from_user.username,
        full_name=message.from_user.full_name,
        is_bot=message.from_user.is_bot
    )
    
    referrer_id_str = None
    if len(parts) > 1:
        param = parts[1]
        if param.startswith("ref_"):
            referrer_id_str = param.split("_")[1]
        elif param == "ai":
            await cmd_ai(message)
            return

    invited_msg = ""
    if referrer_id_str and referrer_id_str.isdigit():
        referrer_id = int(referrer_id_str)
        # Регистрируем реферала
        success = await db.add_referral(user_id, referrer_id)
        if success:
            invited_msg = "\n\n🎉 Вы успешно зарегистрировались по приглашению другого пользователя! Ему начислено +5 квоты на вопросы ИИ."
            try:
                # Уведомляем пригласившего
                _, limit, _ = await db.get_user_ai_limits(referrer_id)
                await message.bot.send_message(
                    referrer_id,
                    f"🎉 <b>У вас новый реферал!</b>\n\n"
                    f"Пользователь {_mention(message.from_user)} присоединился по вашей ссылке.\n"
                    f"Ваш новый суточный лимит ИИ-вопросов: <b>{limit}</b> вопр."
                )
            except Exception:
                pass

    await _send_main_menu(message, message.from_user, invited_msg)


async def _render_ai_menu(message_or_cb, user):
    user_id = user.id
    used, limit, extra = await db.get_user_ai_limits(user_id)
    ref_count = await db.get_referral_count(user_id)
    bot_info = await message_or_cb.bot.get_me() if isinstance(message_or_cb, CallbackQuery) else message_or_cb.bot.get_me()
    # bot_info is a coroutine or object, await it
    if hasattr(bot_info, "__await__"):
        bot_info = await bot_info
    ref_link = f"https://t.me/{bot_info.username}?start=ref_{user_id}"
    
    stats_text = (
        f"🤖 <b>Интеллектуальный Ассистент Gemini</b>\n\n"
        f"Здесь вы можете общаться с искусственным интеллектом!\n\n"
        f"📊 <b>Ваша суточная квота вопросов:</b>\n"
        f"▸ Доступно сегодня: <b>{max(0, limit - used)}</b> из <b>{limit}</b>\n"
        f"▸ Использовано сегодня: <b>{used}</b>\n"
        f"▸ Приглашено друзей: <b>{ref_count}</b> (+{extra} к лимиту)\n\n"
        f"🔗 <b>Ваша реферальная ссылка:</b>\n"
        f"<code>{ref_link}</code>\n"
        f"<i>Отправьте ссылку другу. За каждого нового пользователя вы будете получать +5 вопросов к лимиту каждый день!</i>"
    )
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Начать диалог", callback_data="ai_start_chat")],
        [InlineKeyboardButton(text="◀️ В главное меню", callback_data="main_menu")]
    ])
    
    if isinstance(message_or_cb, CallbackQuery):
        cb = message_or_cb
        if cb.message.photo:
            await cb.message.edit_caption(caption=stats_text, reply_markup=kb)
        else:
            await cb.message.edit_text(stats_text, reply_markup=kb)
    else:
        await message_or_cb.answer(stats_text, reply_markup=kb)


@router.message(Command("ai", "ии", ignore_case=True))
async def cmd_ai(message: Message) -> None:
    if getattr(message.chat, "type", None) != "private":
        await message.reply("Общение с ИИ доступно только в личных сообщениях с ботом.")
        return
    await _render_ai_menu(message, message.from_user)


@router.callback_query(F.data == "open_ai_menu")
async def cb_open_ai_menu(cb: CallbackQuery) -> None:
    await cb.answer()
    await _render_ai_menu(cb, cb.from_user)


from aiogram.types import CallbackQuery
@router.callback_query(F.data == "ai_start_chat")
async def cb_ai_start_chat(cb: CallbackQuery) -> None:
    await cb.answer()
    user_id = cb.from_user.id
    active_ai_chats.add(user_id)
    
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Выйти из чата", callback_data="ai_exit_chat")]
    ])
    
    if cb.message.photo:
        await cb.message.edit_caption(
            caption="🤖 <b>Диалог с ИИ запущен!</b>\n\n"
                    "Отправьте мне любое текстовое сообщение, и я отвечу.\n\n"
                    "<i>Для выхода нажмите кнопку ниже.</i>",
            reply_markup=kb
        )
    else:
        await cb.message.edit_text(
            "🤖 <b>Диалог с ИИ запущен!</b>\n\n"
            "Отправьте мне любое текстовое сообщение, и я отвечу.\n\n"
            "<i>Для выхода нажмите кнопку ниже.</i>",
            reply_markup=kb
        )


@router.callback_query(F.data == "ai_exit_chat")
async def cb_ai_exit_chat(cb: CallbackQuery) -> None:
    await cb.answer()
    user_id = cb.from_user.id
    active_ai_chats.discard(user_id)
    await _render_ai_menu(cb, cb.from_user)


@router.message(F.text, F.chat.type == "private")
async def on_private_text_message(message: Message) -> None:
    user_id = message.from_user.id
    if user_id not in active_ai_chats:
        return

    # Игнорируем команды
    if message.text.startswith("/"):
        active_ai_chats.discard(user_id)
        return

    # Проверяем лимит
    used, limit, extra = await db.get_user_ai_limits(user_id)
    if used >= limit:
        await message.reply(
            "⚠️ <b>Превышен суточный лимит вопросов к ИИ!</b>\n\n"
            f"Вы использовали все свои <b>{limit}</b> вопросов на сегодня. Лимит обновится завтра.\n\n"
            "🔗 Пригласите друзей по вашей ссылке, чтобы получить +5 вопросов к лимиту каждый день:\n"
            f"<code>https://t.me/{(await message.bot.get_me()).username}?start=ref_{user_id}</code>"
        )
        return

    from config import GEMINI_API_KEY
    if not GEMINI_API_KEY:
        await message.reply(
            "⚠️ <b>Ошибка:</b> API-ключ Gemini не настроен.\n"
            "Пожалуйста, добавьте <code>GEMINI_API_KEY</code> в переменные окружения на хостинге (например, Railway)."
        )
        return

    await message.bot.send_chat_action(message.chat.id, "typing")

    import aiohttp
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": message.text}]}]
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=30) as resp:
                if resp.status == 200:
                    res = await resp.json()
                    try:
                        reply_text = res["candidates"][0]["content"]["parts"][0]["text"]
                        await db.increment_user_ai_questions(user_id)
                        
                        try:
                            await message.reply(reply_text, parse_mode="Markdown")
                        except Exception:
                            try:
                                await message.reply(reply_text)
                            except Exception:
                                pass
                    except (KeyError, IndexError):
                        log.error("Invalid Gemini response format: %s", res)
                        await message.reply("❌ Произошла ошибка при обработке ответа ИИ.")
                else:
                    err_body = await resp.text()
                    log.error("Gemini API error status=%s response=%s", resp.status, err_body)
                    await message.reply("❌ Ошибка при запросе к ИИ. Попробуйте позже.")
    except Exception as e:
        log.exception("Gemini API connection error")
        await message.reply(f"❌ Ошибка подключения к ИИ: {e}")


@router.message()
async def on_any_message(message: Message) -> None:
    if message.paid_message_price_changed:
        return
    if not scheduler.timers.is_active(message.chat.id):
        return

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

    async with scheduler.chat_locks[message.chat.id]:
        state = await db.get_chat_state(message.chat.id)
        if not state.is_running:
            return
        if state.end_at_unix and int(time.time()) >= int(state.end_at_unix):
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
