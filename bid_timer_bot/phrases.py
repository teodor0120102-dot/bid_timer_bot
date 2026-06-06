"""BidTimerBot — единый стиль сообщений."""

from __future__ import annotations

import html
from typing import Optional

SEP = "━━━━━━━━━━━━━━━━━━"


def format_time(seconds: int) -> str:
    seconds = max(0, int(seconds))
    m, s = divmod(seconds, 60)
    if m:
        return f"{m}:{s:02d}"
    return f"0:{s:02d}"


def progress_bar(remaining: int, total: int, width: int = 12) -> str:
    total = max(1, int(total))
    remaining = max(0, min(remaining, total))
    filled = round(width * remaining / total)
    return "▰" * filled + "▱" * (width - filled)


def countdown_emoji(seconds: int) -> Optional[str]:
    emojis = ("🔟", "9️⃣", "8️⃣", "7️⃣", "6️⃣", "5️⃣", "4️⃣", "3️⃣", "2️⃣", "1️⃣")
    if 1 <= seconds <= 10:
        return emojis[seconds - 1]
    return None


def card(title: str, body: str) -> str:
    return f"{SEP}\n<b>{title}</b>\n{SEP}\n\n{body}"


def welcome(stars: Optional[int]) -> str:
    stars_line = (
        f"⭐ Стоимость сообщения: <b>{stars}</b>"
        if stars and stars > 0
        else "⚠️ Включите <b>Сообщения за Stars</b> в настройках группы"
    )
    return card(
        "BidTimer подключён",
        f"{stars_line}\n\n"
        "Управлять могут <b>владелец</b> и <b>админы</b> чата — ничего настраивать не нужно.\n\n"
        "▸ <code>/bid start</code> — запуск раунда\n"
        "▸ <code>/bid stop</code> — остановка\n"
        "▸ <code>/bid</code> — справка",
    )


def help_text() -> str:
    return card(
        "Справка BidTimer",
        "Бот работает только при включённых <b>Сообщениях за Stars</b>.\n"
        "Платное сообщение = перебив таймера.\n\n"
        "<b>Раунд</b>\n"
        "▸ <code>/bid start [сек]</code>\n"
        "▸ <code>/bid stop</code>\n"
        "▸ <code>/bid status</code>\n\n"
        "<b>Настройки</b>\n"
        "▸ <code>/bid time 150</code> — длительность\n"
        "▸ <code>/bid mode paid</code> — режим ставок\n\n"
        "<b>Делегирование</b>\n"
        "▸ <code>/bid add @user</code> — дать доступ не-админу\n"
        "▸ <code>/bid del @user</code>\n"
        "▸ <code>/bid managers</code>",
    )


def status(
    *,
    stars: Optional[int],
    stars_on: bool,
    running: bool,
    remaining: str,
    duration: int,
    mode: str,
    regex: str,
    managers: str,
) -> str:
    return card(
        "Статус",
        f"Stars: {'✅ <b>' + str(stars) + '</b> ⭐' if stars_on else '❌ выключено'}\n"
        f"Раунд: {'🟢 идёт' if running else '⚪ ожидание'}\n"
        f"Осталось: <b>{remaining}</b>\n"
        f"Длительность: <b>{duration}</b> сек\n"
        f"Режим: <code>{html.escape(mode)}</code>\n"
        f"Менеджеры: {managers}",
    )


def timer_start(remaining_sec: int, total_sec: int) -> str:
    bar = progress_bar(remaining_sec, total_sec)
    time_str = format_time(remaining_sec)
    return card(
        "⏱ Раунд начался",
        f"<code>{bar}</code>  <b>{time_str}</b>\n\n"
        "Каждое сообщение за ⭐ сбрасывает таймер.\n"
        "Побеждает последний перебивший.",
    )


def timer_tick(remaining_sec: int, total_sec: int) -> str:
    bar = progress_bar(remaining_sec, total_sec)
    time_str = format_time(remaining_sec)
    if remaining_sec <= 30:
        return card(
            "⏱ Финишная прямая",
            f"<code>{bar}</code>  <b>{time_str}</b>\n\n"
            "Ждём перебив…",
        )
    return card(
        "⏱ Таймер",
        f"<code>{bar}</code>  <b>{time_str}</b>\n\n"
        "Платное сообщение = ставка",
    )


def timer_countdown(seconds: int, total_sec: int) -> str:
    emoji = countdown_emoji(seconds) or str(seconds)
    bar = progress_bar(seconds, total_sec)
    return card(
        "⚠️ Финальный отсчёт",
        f"       {emoji}\n\n"
        f"<code>{bar}</code>  <b>{seconds}</b> сек",
    )


def timer_finished() -> str:
    return card("🏁 Время вышло", "Подводим итоги…")


def bid_reset(mention: str, time_str: str, total_sec: int, remaining_sec: int) -> str:
    bar = progress_bar(remaining_sec, total_sec)
    return card(
        "💫 Перебив",
        f"{mention}\n\n"
        f"<code>{bar}</code>  <b>{time_str}</b>\n\n"
        "Таймер сброшен.",
    )


def winner_with_bid(winner: str) -> str:
    return card(
        "🏆 Победитель",
        f"{winner}\n\n"
        "Последний перебив забирает победу.\n"
        "Таймер остановлен.",
    )


def winner_no_bid() -> str:
    return card(
        "Раунд завершён",
        "Ставок не было.\n"
        "Запустите новый раунд: <code>/bid start</code>",
    )


def stars_required() -> str:
    return card(
        "Нужен режим Stars",
        "Включите <b>Сообщения за Stars</b>:\n"
        "Настройки группы → Права → Сообщения за Stars.\n\n"
        "После включения бот заработает автоматически.",
    )


def stars_disabled() -> str:
    return card(
        "Stars выключены",
        "Режим платных сообщений отключён.\n"
        "Таймер остановлен.",
    )


def stopped() -> str:
    return card("⏹ Остановлено", "Таймер снят.\nЗапуск: <code>/bid start</code>")


def access_denied() -> str:
    return card(
        "Нет доступа",
        "Управлять могут:\n"
        "▸ владелец чата\n"
        "▸ администраторы\n"
        "▸ назначенные менеджеры (<code>/bid add</code>)",
    )


def manager_added(label: str) -> str:
    return card("Менеджер добавлен", f"<b>{html.escape(label)}</b> может управлять ботом.")


def manager_removed(label: str) -> str:
    return card("Менеджер снят", f"<b>{html.escape(label)}</b> больше не управляет ботом.")


def managers_list(lines: str) -> str:
    return card("Менеджеры", lines or "Пока никого. Добавьте: <code>/bid add @user</code>")


def setting_time(seconds: int) -> str:
    return card("Настройка", f"Длительность раунда: <b>{seconds}</b> сек ({format_time(seconds)})")


def setting_mode(mode: str, hint: str) -> str:
    return card("Режим ставок", f"<code>{html.escape(mode)}</code>\n{hint}")


def setting_regex(pattern: str) -> str:
    return card("Триггер", f"<code>{html.escape(pattern)}</code>")
