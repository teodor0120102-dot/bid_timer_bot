"""BidTimerBot — 20 мини-игр (aiogram 3.x Router)."""

from __future__ import annotations

import asyncio
import html
import logging
import random
import time
from typing import Any, Optional

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

log = logging.getLogger("games")

router = Router(name="games")

# ──────────────────────────────────────────────
# Стиль карточек (дублируем, чтобы не создавать
# цикличный импорт с phrases.py)
# ──────────────────────────────────────────────
SEP = "━━━━━━━━━━━━━━━━━━"


def card(title: str, body: str) -> str:
    return f"{SEP}\n<b>{title}</b>\n{SEP}\n\n{body}"


# ──────────────────────────────────────────────
# Хранилища сессий (в памяти)
# ──────────────────────────────────────────────
# Ключ — (chat_id, user_id) или (chat_id,) для групповых
_sessions: dict[str, dict[tuple, dict[str, Any]]] = {}

SESSION_TTL = 1800  # 30 мин


def _key(chat_id: int, user_id: int) -> tuple[int, int]:
    return (chat_id, user_id)


def _get(store: str, key: tuple) -> Optional[dict]:
    bucket = _sessions.setdefault(store, {})
    s = bucket.get(key)
    if s and time.time() - s.get("_ts", 0) > SESSION_TTL:
        bucket.pop(key, None)
        return None
    return s


def _set(store: str, key: tuple, data: dict) -> dict:
    data["_ts"] = time.time()
    _sessions.setdefault(store, {})[key] = data
    return data


def _pop(store: str, key: tuple) -> Optional[dict]:
    return _sessions.get(store, {}).pop(key, None)


def _cleanup_store(store: str) -> None:
    bucket = _sessions.get(store)
    if not bucket:
        return
    now = time.time()
    expired = [k for k, v in bucket.items() if now - v.get("_ts", 0) > SESSION_TTL]
    for k in expired:
        del bucket[k]


async def _periodic_cleanup() -> None:
    """Вызывается при старте — чистит просроченные сессии."""
    while True:
        await asyncio.sleep(300)
        for store_name in list(_sessions.keys()):
            _cleanup_store(store_name)


# Запускаем фоновую чистку при первом импорте
_cleanup_task: Optional[asyncio.Task] = None


def _ensure_cleanup() -> None:
    global _cleanup_task
    if _cleanup_task is None or _cleanup_task.done():
        try:
            loop = asyncio.get_running_loop()
            _cleanup_task = loop.create_task(_periodic_cleanup())
        except RuntimeError:
            pass


# ──────────────────────────────────────────────
# Утилиты
# ──────────────────────────────────────────────
def _mention(user) -> str:
    name = html.escape(user.full_name or "Игрок")
    return f'<a href="tg://user?id={user.id}">{name}</a>'


def _btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def _kb(buttons: list[list[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ──────────────────────────────────────────────
# /games — главное меню
# ──────────────────────────────────────────────
GAMES_MENU = [
    ("🪙 Орёл и Решка", "game_coin"),
    ("🎲 Кубик", "game_dice"),
    ("🎰 Слоты", "game_slots"),
    ("🎯 Дартс", "game_dart"),
    ("🏀 Баскетбол", "game_bball"),
    ("⚽ Футбол", "game_foot"),
    ("🎱 Магический шар", "game_8ball"),
    ("🔢 Угадай число", "game_gnum"),
    ("✊ Камень-Ножницы-Бумага", "game_rps"),
    ("💣 Сапёр-лайт", "game_mine"),
    ("🃏 Больше-Меньше", "game_hilo"),
    ("🎡 Колесо Фортуны", "game_whl"),
    ("📝 Виселица", "game_hang"),
    ("🧠 Викторина", "game_triv"),
    ("🐍 Змейка", "game_snke"),
    ("🎪 Русская рулетка", "game_roul"),
    ("🏆 Дуэль", "game_duel"),
    ("🔮 Предсказание", "game_fort"),
    ("💰 Краш", "game_crsh"),
    ("🏴‍☠️ Сундук", "game_chest"),
]


def _games_keyboard() -> InlineKeyboardMarkup:
    rows = []
    for i in range(0, len(GAMES_MENU), 2):
        row = [_btn(GAMES_MENU[i][0], GAMES_MENU[i][1])]
        if i + 1 < len(GAMES_MENU):
            row.append(_btn(GAMES_MENU[i + 1][0], GAMES_MENU[i + 1][1]))
        rows.append(row)
    return _kb(rows)


@router.message(Command("games", ignore_case=True))
async def cmd_games(message: Message) -> None:
    _ensure_cleanup()
    await message.answer(
        card("🎮 Мини-игры", "Выберите игру:"),
        reply_markup=_games_keyboard(),
    )


# ──────────────────────────────────────────────
# 1. 🪙 Орёл и Решка
# ──────────────────────────────────────────────
@router.callback_query(F.data == "game_coin")
async def game_coin(cb: CallbackQuery) -> None:
    await cb.answer()
    msg = await cb.message.answer(card("🪙 Орёл и Решка", "Подбрасываю монету..."))
    frames = ["🪙 . . .", "  . 🪙 . .", "  . . 🪙 .", "  . . . 🪙", "  . . 🪙 .", "  . 🪙 . ."]
    for f in frames:
        await asyncio.sleep(0.4)
        try:
            await msg.edit_text(card("🪙 Орёл и Решка", f))
        except Exception:
            pass
    result = random.choice(["Орёл 🦅", "Решка 👑"])
    await asyncio.sleep(0.3)
    await msg.edit_text(card("🪙 Орёл и Решка", f"Результат: <b>{result}</b>!"))


# ──────────────────────────────────────────────
# 2. 🎲 Кубик (native)
# ──────────────────────────────────────────────
@router.callback_query(F.data == "game_dice")
async def game_dice(cb: CallbackQuery) -> None:
    await cb.answer("🎲 Бросаю кубик!")
    await cb.message.answer_dice(emoji="🎲")


# ──────────────────────────────────────────────
# 3. 🎰 Слоты (native)
# ──────────────────────────────────────────────
@router.callback_query(F.data == "game_slots")
async def game_slots(cb: CallbackQuery) -> None:
    await cb.answer("🎰 Кручу барабаны!")
    await cb.message.answer_dice(emoji="🎰")


# ──────────────────────────────────────────────
# 4. 🎯 Дартс (native)
# ──────────────────────────────────────────────
@router.callback_query(F.data == "game_dart")
async def game_dart(cb: CallbackQuery) -> None:
    await cb.answer("🎯 Бросаю дротик!")
    await cb.message.answer_dice(emoji="🎯")


# ──────────────────────────────────────────────
# 5. 🏀 Баскетбол (native)
# ──────────────────────────────────────────────
@router.callback_query(F.data == "game_bball")
async def game_bball(cb: CallbackQuery) -> None:
    await cb.answer("🏀 Бросаю мяч!")
    await cb.message.answer_dice(emoji="🏀")


# ──────────────────────────────────────────────
# 6. ⚽ Футбол (native)
# ──────────────────────────────────────────────
@router.callback_query(F.data == "game_foot")
async def game_foot(cb: CallbackQuery) -> None:
    await cb.answer("⚽ Бью по воротам!")
    await cb.message.answer_dice(emoji="⚽")


# ──────────────────────────────────────────────
# 7. 🎱 Магический шар
# ──────────────────────────────────────────────
_8BALL_ANSWERS = [
    "Бесспорно", "Предрешено", "Никаких сомнений",
    "Определённо да", "Можешь быть уверен",
    "Мне кажется — да", "Вероятнее всего", "Хорошие перспективы",
    "Знаки говорят — да", "Да",
    "Пока не ясно, попробуй снова", "Спроси позже",
    "Лучше не рассказывать", "Сейчас нельзя предсказать",
    "Сконцентрируйся и спроси опять",
    "Даже не думай", "Мой ответ — нет", "По моим данным — нет",
    "Перспективы не очень", "Весьма сомнительно",
]


@router.callback_query(F.data == "game_8ball")
async def game_8ball(cb: CallbackQuery) -> None:
    await cb.answer()
    msg = await cb.message.answer(card("🎱 Магический шар", "🔮 Концентрирую энергию..."))
    frames = ["🔮 .", "🔮 . .", "🔮 . . .", "✨ . . .", "✨ ✨ . .", "✨ ✨ ✨ ."]
    for f in frames:
        await asyncio.sleep(0.35)
        try:
            await msg.edit_text(card("🎱 Магический шар", f))
        except Exception:
            pass
    answer = random.choice(_8BALL_ANSWERS)
    await asyncio.sleep(0.3)
    await msg.edit_text(
        card("🎱 Магический шар", f"🔮 Шар говорит:\n\n<b>«{answer}»</b>")
    )


# ──────────────────────────────────────────────
# 8. 🔢 Угадай число (1-100, 7 попыток)
# ──────────────────────────────────────────────
@router.callback_query(F.data == "game_gnum")
async def game_gnum_start(cb: CallbackQuery) -> None:
    await cb.answer()
    key = _key(cb.message.chat.id, cb.from_user.id)
    secret = random.randint(1, 100)
    _set("gnum", key, {"num": secret, "tries": 7, "max_tries": 7})
    await cb.message.answer(
        card(
            "🔢 Угадай число",
            "Я загадал число от <b>1</b> до <b>100</b>.\n"
            "У тебя <b>7</b> попыток.\n\n"
            "Просто отправь число в чат!",
        )
    )


@router.message(F.text.regexp(r"^\d{1,3}$"))
async def game_gnum_guess(message: Message) -> None:
    key = _key(message.chat.id, message.from_user.id)
    sess = _get("gnum", key)
    if not sess:
        return
    guess = int(message.text.strip())
    if guess < 1 or guess > 100:
        return
    secret = sess["num"]
    sess["tries"] -= 1
    left = sess["tries"]
    if guess == secret:
        _pop("gnum", key)
        used = sess["max_tries"] - left
        await message.reply(
            card("🔢 Угадай число", f"🎉 Верно! Это было <b>{secret}</b>!\nПопыток использовано: <b>{used}</b>")
        )
    elif left <= 0:
        _pop("gnum", key)
        await message.reply(
            card("🔢 Угадай число", f"😔 Попытки кончились!\nЗагаданное число: <b>{secret}</b>")
        )
    elif guess < secret:
        await message.reply(
            card("🔢 Угадай число", f"⬆️ <b>Больше!</b>\nОсталось попыток: <b>{left}</b>")
        )
    else:
        await message.reply(
            card("🔢 Угадай число", f"⬇️ <b>Меньше!</b>\nОсталось попыток: <b>{left}</b>")
        )


# ──────────────────────────────────────────────
# 9. ✊ Камень-Ножницы-Бумага
# ──────────────────────────────────────────────
_RPS_ITEMS = {"r": ("✊", "Камень"), "s": ("✌️", "Ножницы"), "p": ("✋", "Бумага")}
_RPS_WINS = {"r": "s", "s": "p", "p": "r"}


@router.callback_query(F.data == "game_rps")
async def game_rps_menu(cb: CallbackQuery) -> None:
    await cb.answer()
    kb = _kb([
        [_btn("✊ Камень", "rps_r"), _btn("✌️ Ножницы", "rps_s"), _btn("✋ Бумага", "rps_p")]
    ])
    await cb.message.answer(card("✊ Камень-Ножницы-Бумага", "Сделай свой выбор!"), reply_markup=kb)


@router.callback_query(F.data.startswith("rps_"))
async def game_rps_play(cb: CallbackQuery) -> None:
    await cb.answer()
    choice = cb.data.split("_")[1]
    if choice not in _RPS_ITEMS:
        return
    bot_choice = random.choice(list(_RPS_ITEMS.keys()))
    p_emoji, p_name = _RPS_ITEMS[choice]
    b_emoji, b_name = _RPS_ITEMS[bot_choice]
    if choice == bot_choice:
        result = "🤝 Ничья!"
    elif _RPS_WINS[choice] == bot_choice:
        result = "🎉 Ты победил!"
    else:
        result = "😔 Бот победил!"
    text = (
        f"Ты: {p_emoji} {p_name}\n"
        f"Бот: {b_emoji} {b_name}\n\n"
        f"<b>{result}</b>"
    )
    try:
        await cb.message.edit_text(card("✊ Камень-Ножницы-Бумага", text))
    except Exception:
        await cb.message.answer(card("✊ Камень-Ножницы-Бумага", text))


# ──────────────────────────────────────────────
# 10. 💣 Сапёр-лайт (5×5, 5 мин)
# ──────────────────────────────────────────────
_MINE_SIZE = 5
_MINE_COUNT = 5


def _mine_board() -> dict:
    mines = set()
    while len(mines) < _MINE_COUNT:
        mines.add((random.randint(0, _MINE_SIZE - 1), random.randint(0, _MINE_SIZE - 1)))
    return {
        "mines": mines,
        "opened": set(),
        "dead": False,
        "won": False,
    }


def _mine_kb(sess: dict, uid: int) -> InlineKeyboardMarkup:
    rows = []
    for r in range(_MINE_SIZE):
        row = []
        for c in range(_MINE_SIZE):
            if (r, c) in sess["opened"]:
                if (r, c) in sess["mines"]:
                    row.append(_btn("💥", "noop"))
                else:
                    # Считаем соседние мины
                    cnt = sum(
                        1
                        for dr in (-1, 0, 1)
                        for dc in (-1, 0, 1)
                        if (dr, dc) != (0, 0)
                        and (r + dr, c + dc) in sess["mines"]
                    )
                    row.append(_btn(str(cnt) if cnt else "·", "noop"))
            elif sess["dead"] or sess["won"]:
                if (r, c) in sess["mines"]:
                    row.append(_btn("💣", "noop"))
                else:
                    row.append(_btn("·", "noop"))
            else:
                row.append(_btn("▪️", f"mn_{uid}_{r}_{c}"))
        rows.append(row)
    return _kb(rows)


def _mine_text(sess: dict) -> str:
    safe = _MINE_SIZE * _MINE_SIZE - _MINE_COUNT
    opened_safe = len(sess["opened"] - sess["mines"])
    if sess["dead"]:
        return card("💣 Сапёр-лайт", "💥 <b>БУМ!</b> Ты наступил на мину!")
    if sess["won"]:
        return card("💣 Сапёр-лайт", "🎉 <b>Победа!</b> Все мины обезврежены!")
    return card("💣 Сапёр-лайт", f"Открыто: <b>{opened_safe}</b> / <b>{safe}</b>\nНе наступи на мину!")


@router.callback_query(F.data == "game_mine")
async def game_mine_start(cb: CallbackQuery) -> None:
    await cb.answer()
    uid = cb.from_user.id
    key = _key(cb.message.chat.id, uid)
    sess = _set("mine", key, _mine_board())
    await cb.message.answer(_mine_text(sess), reply_markup=_mine_kb(sess, uid))


@router.callback_query(F.data.startswith("mn_"))
async def game_mine_click(cb: CallbackQuery) -> None:
    parts = cb.data.split("_")
    if len(parts) != 4:
        await cb.answer("Ошибка")
        return
    uid = int(parts[1])
    if cb.from_user.id != uid:
        await cb.answer("Это не твоя игра!", show_alert=True)
        return
    r, c = int(parts[2]), int(parts[3])
    key = _key(cb.message.chat.id, uid)
    sess = _get("mine", key)
    if not sess or sess["dead"] or sess["won"]:
        await cb.answer()
        return
    sess["opened"].add((r, c))
    if (r, c) in sess["mines"]:
        sess["dead"] = True
        # Открываем все мины
        sess["opened"] |= sess["mines"]
    else:
        safe = _MINE_SIZE * _MINE_SIZE - _MINE_COUNT
        opened_safe = len(sess["opened"] - sess["mines"])
        if opened_safe >= safe:
            sess["won"] = True
    await cb.answer()
    try:
        await cb.message.edit_text(_mine_text(sess), reply_markup=_mine_kb(sess, uid))
    except Exception:
        pass


# ──────────────────────────────────────────────
# 11. 🃏 Больше-Меньше (Hi-Lo)
# ──────────────────────────────────────────────
_CARD_SUITS = ["♠️", "♥️", "♦️", "♣️"]
_CARD_RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]


def _random_card() -> tuple[int, str]:
    rank_i = random.randint(0, 12)
    suit = random.choice(_CARD_SUITS)
    return rank_i, f"{_CARD_RANKS[rank_i]}{suit}"


def _hilo_text(card_str: str, streak: int) -> str:
    return card(
        "🃏 Больше-Меньше",
        f"Текущая карта: <b>{card_str}</b>\n"
        f"Серия: <b>{streak}</b> 🔥\n\n"
        "Следующая карта будет больше или меньше?",
    )


@router.callback_query(F.data == "game_hilo")
async def game_hilo_start(cb: CallbackQuery) -> None:
    await cb.answer()
    uid = cb.from_user.id
    key = _key(cb.message.chat.id, uid)
    rank_i, card_str = _random_card()
    _set("hilo", key, {"rank": rank_i, "card": card_str, "streak": 0})
    kb = _kb([[_btn("⬆️ Больше", f"hl_{uid}_h"), _btn("⬇️ Меньше", f"hl_{uid}_l")]])
    await cb.message.answer(_hilo_text(card_str, 0), reply_markup=kb)


@router.callback_query(F.data.startswith("hl_"))
async def game_hilo_play(cb: CallbackQuery) -> None:
    parts = cb.data.split("_")
    if len(parts) != 3:
        await cb.answer()
        return
    uid = int(parts[1])
    if cb.from_user.id != uid:
        await cb.answer("Это не твоя игра!", show_alert=True)
        return
    action = parts[2]  # h or l
    key = _key(cb.message.chat.id, uid)
    sess = _get("hilo", key)
    if not sess:
        await cb.answer("Сессия истекла", show_alert=True)
        return
    old_rank = sess["rank"]
    new_rank, new_card = _random_card()
    correct = False
    if action == "h" and new_rank >= old_rank:
        correct = True
    elif action == "l" and new_rank <= old_rank:
        correct = True
    if correct:
        sess["streak"] += 1
        sess["rank"] = new_rank
        sess["card"] = new_card
        kb = _kb([[_btn("⬆️ Больше", f"hl_{uid}_h"), _btn("⬇️ Меньше", f"hl_{uid}_l")]])
        await cb.answer("✅ Верно!")
        try:
            await cb.message.edit_text(_hilo_text(new_card, sess["streak"]), reply_markup=kb)
        except Exception:
            pass
    else:
        streak = sess["streak"]
        _pop("hilo", key)
        await cb.answer("❌ Неверно!")
        try:
            await cb.message.edit_text(
                card(
                    "🃏 Больше-Меньше",
                    f"Была: <b>{sess['card']}</b>\n"
                    f"Выпала: <b>{new_card}</b>\n\n"
                    f"❌ Неверно! Серия: <b>{streak}</b>",
                )
            )
        except Exception:
            pass


# ──────────────────────────────────────────────
# 12. 🎡 Колесо Фортуны
# ──────────────────────────────────────────────
_WHEEL_PRIZES = [
    "💎 Бриллиант", "🍀 Удача", "🌟 Звезда", "🎁 Подарок",
    "💰 Джекпот", "🍕 Пицца", "🦄 Единорог", "🏖 Отпуск",
    "🎵 Мелодия", "🍩 Пончик", "🐱 Котик", "🚀 Ракета",
    "📚 Мудрость", "☕ Кофе", "🎭 Маска", "🍀 Трёхлистник",
]

_WHEEL_FRAMES = ["🎡 |", "🎡 /", "🎡 —", "🎡 \\"]


@router.callback_query(F.data == "game_whl")
async def game_wheel(cb: CallbackQuery) -> None:
    await cb.answer()
    msg = await cb.message.answer(card("🎡 Колесо Фортуны", "Кручу колесо..."))
    for i in range(8):
        frame = _WHEEL_FRAMES[i % len(_WHEEL_FRAMES)]
        prize_preview = random.choice(_WHEEL_PRIZES)
        await asyncio.sleep(0.3)
        try:
            await msg.edit_text(card("🎡 Колесо Фортуны", f"{frame}  → {prize_preview}"))
        except Exception:
            pass
    # Замедление
    for i in range(3):
        frame = _WHEEL_FRAMES[i % len(_WHEEL_FRAMES)]
        prize_preview = random.choice(_WHEEL_PRIZES)
        await asyncio.sleep(0.6)
        try:
            await msg.edit_text(card("🎡 Колесо Фортуны", f"{frame}  → {prize_preview}"))
        except Exception:
            pass
    prize = random.choice(_WHEEL_PRIZES)
    await asyncio.sleep(0.5)
    await msg.edit_text(
        card("🎡 Колесо Фортуны", f"🏆 Колесо остановилось!\n\nТвой приз: <b>{prize}</b>!")
    )


# ──────────────────────────────────────────────
# 13. 📝 Виселица
# ──────────────────────────────────────────────
_HANGMAN_WORDS = [
    "ПРОГРАММА", "АЛГОРИТМ", "КОМПЬЮТЕР", "КЛАВИАТУРА", "МОНИТОР",
    "ИНТЕРНЕТ", "ТЕЛЕФОН", "РОБОТ", "ГАЛАКТИКА", "ПЛАНЕТА",
    "МОЛЕКУЛА", "ЭЛЕКТРОН", "МАГНИТ", "ВУЛКАН", "ОКЕАН",
    "ПИНГВИН", "ЖИРАФ", "БАБОЧКА", "КРОКОДИЛ", "ДЕЛЬФИН",
    "ШОКОЛАД", "КАРАМЕЛЬ", "МОРОЖЕНОЕ", "ПИРОЖНОЕ", "ВАРЕНЬЕ",
    "БИБЛИОТЕКА", "ЭНЦИКЛОПЕДИЯ", "УНИВЕРСИТЕТ", "ПРОФЕССОР", "АУДИТОРИЯ",
    "ФОТОГРАФИЯ", "ТЕЛЕВИЗОР", "КИНОТЕАТР", "СПЕКТАКЛЬ", "МУЗЫКАНТ",
    "АРХИТЕКТОР", "ИНЖЕНЕР", "АСТРОНАВТ", "ПУТЕШЕСТВИЕ", "ПРИКЛЮЧЕНИЕ",
    "ДИНОЗАВР", "СКОРПИОН", "ЧЕРЕПАХА", "ВОРОБЕЙ", "РОМАШКА",
    "ВЕЛОСИПЕД", "САМОЛЁТ", "ПАРОВОЗ", "ПОДВОДНАЯ", "СВЕТОФОР",
    "ФЕЙЕРВЕРК", "КРИСТАЛЛ", "ВИТАМИН", "ГРАВИТАЦИЯ", "АТМОСФЕРА",
]

_HANGMAN_STAGES = [
    "  ┌───┐\n  │\n  │\n  │\n══╧══",
    "  ┌───┐\n  │   😶\n  │\n  │\n══╧══",
    "  ┌───┐\n  │   😟\n  │   │\n  │\n══╧══",
    "  ┌───┐\n  │   😟\n  │  /│\n  │\n══╧══",
    "  ┌───┐\n  │   😟\n  │  /│\\\n  │\n══╧══",
    "  ┌───┐\n  │   😟\n  │  /│\\\n  │  /\n══╧══",
    "  ┌───┐\n  │   😵\n  │  /│\\\n  │  / \\\n══╧══",
]

_RU_LETTERS = "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ"


def _hangman_text(sess: dict) -> str:
    word = sess["word"]
    guessed = sess["guessed"]
    errors = sess["errors"]
    display = " ".join(ch if ch in guessed else "▪" for ch in word)
    stage = _HANGMAN_STAGES[min(errors, len(_HANGMAN_STAGES) - 1)]
    wrong = ", ".join(sorted(sess["wrong"])) if sess["wrong"] else "—"
    return card(
        "📝 Виселица",
        f"<code>{stage}</code>\n\n"
        f"<b>{display}</b>\n\n"
        f"Ошибки ({errors}/6): {wrong}",
    )


def _hangman_letter_kb(sess: dict, uid: int) -> InlineKeyboardMarkup:
    guessed = sess["guessed"] | sess["wrong"]
    rows = []
    row: list[InlineKeyboardButton] = []
    for letter in _RU_LETTERS:
        if letter in guessed:
            continue
        row.append(_btn(letter, f"hg_{uid}_{letter}"))
        if len(row) == 7:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return _kb(rows)


@router.callback_query(F.data == "game_hang")
async def game_hang_start(cb: CallbackQuery) -> None:
    await cb.answer()
    uid = cb.from_user.id
    key = _key(cb.message.chat.id, uid)
    word = random.choice(_HANGMAN_WORDS).upper()
    sess = _set("hang", key, {"word": word, "guessed": set(), "wrong": set(), "errors": 0})
    await cb.message.answer(_hangman_text(sess), reply_markup=_hangman_letter_kb(sess, uid))


@router.callback_query(F.data.startswith("hg_"))
async def game_hang_letter(cb: CallbackQuery) -> None:
    parts = cb.data.split("_")
    if len(parts) != 3:
        await cb.answer()
        return
    uid = int(parts[1])
    if cb.from_user.id != uid:
        await cb.answer("Это не твоя игра!", show_alert=True)
        return
    letter = parts[2].upper()
    key = _key(cb.message.chat.id, uid)
    sess = _get("hang", key)
    if not sess:
        await cb.answer("Сессия истекла", show_alert=True)
        return
    word = sess["word"]
    if letter in word:
        sess["guessed"].add(letter)
        await cb.answer(f"✅ Буква «{letter}» есть!")
    else:
        sess["wrong"].add(letter)
        sess["errors"] += 1
        await cb.answer(f"❌ Буквы «{letter}» нет!")
    # Проверяем победу / поражение
    if all(ch in sess["guessed"] for ch in word):
        _pop("hang", key)
        await cb.message.edit_text(
            card("📝 Виселица", f"🎉 <b>Победа!</b>\n\nСлово: <b>{word}</b>")
        )
        return
    if sess["errors"] >= 6:
        _pop("hang", key)
        stage = _HANGMAN_STAGES[-1]
        await cb.message.edit_text(
            card("📝 Виселица", f"<code>{stage}</code>\n\n😵 <b>Проигрыш!</b>\n\nСлово было: <b>{word}</b>")
        )
        return
    try:
        await cb.message.edit_text(_hangman_text(sess), reply_markup=_hangman_letter_kb(sess, uid))
    except Exception:
        pass


# ──────────────────────────────────────────────
# 14. 🧠 Викторина
# ──────────────────────────────────────────────
_TRIVIA_QUESTIONS: list[dict] = [
    {"q": "Какая планета ближе всего к Солнцу?", "a": ["Меркурий", "Венера", "Земля", "Марс"], "c": 0},
    {"q": "Сколько костей в теле взрослого человека?", "a": ["195", "206", "215", "300"], "c": 1},
    {"q": "Какой химический элемент обозначается символом 'O'?", "a": ["Олово", "Осмий", "Кислород", "Озон"], "c": 2},
    {"q": "В каком году человек впервые побывал на Луне?", "a": ["1965", "1969", "1971", "1975"], "c": 1},
    {"q": "Какая самая длинная река в мире?", "a": ["Амазонка", "Нил", "Янцзы", "Миссисипи"], "c": 1},
    {"q": "Какой газ составляет большую часть атмосферы Земли?", "a": ["Кислород", "Водород", "Азот", "Углекислый газ"], "c": 2},
    {"q": "Кто написал «Войну и мир»?", "a": ["Достоевский", "Толстой", "Чехов", "Пушкин"], "c": 1},
    {"q": "Столица Австралии?", "a": ["Сидней", "Мельбурн", "Канберра", "Перт"], "c": 2},
    {"q": "Сколько планет в Солнечной системе?", "a": ["7", "8", "9", "10"], "c": 1},
    {"q": "Какой океан самый большой?", "a": ["Атлантический", "Индийский", "Тихий", "Северный Ледовитый"], "c": 2},
    {"q": "Какое животное самое быстрое на суше?", "a": ["Лев", "Гепард", "Газель", "Антилопа"], "c": 1},
    {"q": "Из чего состоит алмаз?", "a": ["Кремний", "Углерод", "Железо", "Кварц"], "c": 1},
    {"q": "Кто изобрёл телефон?", "a": ["Эдисон", "Тесла", "Белл", "Маркони"], "c": 2},
    {"q": "Какая страна самая большая по площади?", "a": ["Канада", "Китай", "США", "Россия"], "c": 3},
    {"q": "Сколько хромосом у человека?", "a": ["42", "44", "46", "48"], "c": 2},
    {"q": "Как называется единица измерения силы тока?", "a": ["Вольт", "Ампер", "Ватт", "Ом"], "c": 1},
    {"q": "Кто нарисовал Мону Лизу?", "a": ["Микеланджело", "Рафаэль", "Леонардо да Винчи", "Боттичелли"], "c": 2},
    {"q": "Столица Японии?", "a": ["Осака", "Токио", "Киото", "Хиросима"], "c": 1},
    {"q": "Как называется наука о звёздах?", "a": ["Астрология", "Астрономия", "Космология", "Физика"], "c": 1},
    {"q": "Какой витамин вырабатывается на солнце?", "a": ["A", "B", "C", "D"], "c": 3},
    {"q": "В каком году началась Вторая мировая война?", "a": ["1937", "1938", "1939", "1941"], "c": 2},
    {"q": "Какая формула воды?", "a": ["CO2", "H2O", "NaCl", "O2"], "c": 1},
    {"q": "Кто написал «Гамлета»?", "a": ["Мольер", "Шекспир", "Гёте", "Байрон"], "c": 1},
    {"q": "Какой элемент таблицы Менделеева имеет номер 1?", "a": ["Гелий", "Водород", "Литий", "Углерод"], "c": 1},
    {"q": "Сколько цветов в радуге?", "a": ["5", "6", "7", "8"], "c": 2},
    {"q": "Какая валюта в Великобритании?", "a": ["Евро", "Доллар", "Фунт стерлингов", "Крона"], "c": 2},
    {"q": "Какой материк самый маленький?", "a": ["Антарктида", "Европа", "Австралия", "Южная Америка"], "c": 2},
    {"q": "Как называется замёрзшая вода?", "a": ["Пар", "Лёд", "Снег", "Иней"], "c": 1},
    {"q": "Кто придумал теорию относительности?", "a": ["Ньютон", "Бор", "Эйнштейн", "Хокинг"], "c": 2},
    {"q": "Какой самый твёрдый минерал?", "a": ["Кварц", "Топаз", "Корунд", "Алмаз"], "c": 3},
    {"q": "Столица Бразилии?", "a": ["Рио-де-Жанейро", "Сан-Паулу", "Бразилиа", "Салвадор"], "c": 2},
    {"q": "Какой орган фильтрует кровь?", "a": ["Печень", "Почки", "Сердце", "Лёгкие"], "c": 1},
    {"q": "В каком году пал Берлинская стена?", "a": ["1987", "1989", "1991", "1993"], "c": 1},
    {"q": "Какая птица не умеет летать?", "a": ["Орёл", "Пингвин", "Колибри", "Ворона"], "c": 1},
    {"q": "Кто первым полетел в космос?", "a": ["Армстронг", "Гагарин", "Титов", "Терешкова"], "c": 1},
]


def _trivia_text(sess: dict) -> str:
    qi = sess["qi"]
    total = sess["total"]
    score = sess["score"]
    q = sess["questions"][qi]
    return card(
        "🧠 Викторина",
        f"Вопрос <b>{qi + 1}</b> из <b>{total}</b>  |  Счёт: <b>{score}</b>\n\n"
        f"<b>{q['q']}</b>",
    )


def _trivia_kb(sess: dict, uid: int) -> InlineKeyboardMarkup:
    q = sess["questions"][sess["qi"]]
    rows = []
    for i, ans in enumerate(q["a"]):
        rows.append([_btn(ans, f"tv_{uid}_{i}")])
    return _kb(rows)


@router.callback_query(F.data == "game_triv")
async def game_trivia_start(cb: CallbackQuery) -> None:
    await cb.answer()
    uid = cb.from_user.id
    key = _key(cb.message.chat.id, uid)
    questions = random.sample(_TRIVIA_QUESTIONS, min(10, len(_TRIVIA_QUESTIONS)))
    sess = _set("triv", key, {"questions": questions, "qi": 0, "score": 0, "total": len(questions)})
    await cb.message.answer(_trivia_text(sess), reply_markup=_trivia_kb(sess, uid))


@router.callback_query(F.data.startswith("tv_"))
async def game_trivia_answer(cb: CallbackQuery) -> None:
    parts = cb.data.split("_")
    if len(parts) != 3:
        await cb.answer()
        return
    uid = int(parts[1])
    if cb.from_user.id != uid:
        await cb.answer("Это не твоя викторина!", show_alert=True)
        return
    ans_i = int(parts[2])
    key = _key(cb.message.chat.id, uid)
    sess = _get("triv", key)
    if not sess:
        await cb.answer("Сессия истекла", show_alert=True)
        return
    q = sess["questions"][sess["qi"]]
    correct = q["c"]
    if ans_i == correct:
        sess["score"] += 1
        await cb.answer("✅ Правильно!")
    else:
        right_ans = q["a"][correct]
        await cb.answer(f"❌ Неверно! Ответ: {right_ans}", show_alert=True)
    sess["qi"] += 1
    if sess["qi"] >= sess["total"]:
        score = sess["score"]
        total = sess["total"]
        _pop("triv", key)
        emoji = "🏆" if score >= 8 else "👍" if score >= 5 else "😅"
        try:
            await cb.message.edit_text(
                card("🧠 Викторина", f"{emoji} Викторина окончена!\n\nСчёт: <b>{score}</b> / <b>{total}</b>")
            )
        except Exception:
            pass
        return
    try:
        await cb.message.edit_text(_trivia_text(sess), reply_markup=_trivia_kb(sess, uid))
    except Exception:
        pass


# ──────────────────────────────────────────────
# 15. 🐍 Змейка (авто-демо анимация)
# ──────────────────────────────────────────────
_SNAKE_W, _SNAKE_H = 8, 8


@router.callback_query(F.data == "game_snke")
async def game_snake(cb: CallbackQuery) -> None:
    await cb.answer()
    msg = await cb.message.answer(card("🐍 Змейка", "Запускаю демо..."))
    # Простая автоматическая змейка
    snake = [(3, 3), (3, 2), (3, 1)]
    food = (5, 5)
    directions = [(0, 1), (1, 0), (0, -1), (-1, 0)]
    d_idx = 0
    score = 0
    for step in range(20):
        head = snake[0]
        # Простой AI: двигаемся к еде
        hr, hc = head
        fr, fc = food
        if hc < fc:
            d_idx = 0  # right
        elif hr < fr:
            d_idx = 1  # down
        elif hc > fc:
            d_idx = 2  # left
        elif hr > fr:
            d_idx = 3  # up
        dr, dc = directions[d_idx]
        new_head = ((hr + dr) % _SNAKE_H, (hc + dc) % _SNAKE_W)
        snake.insert(0, new_head)
        if new_head == food:
            score += 1
            # Новая еда
            while True:
                food = (random.randint(0, _SNAKE_H - 1), random.randint(0, _SNAKE_W - 1))
                if food not in snake:
                    break
        else:
            snake.pop()
        # Рисуем поле
        grid_lines = []
        for r in range(_SNAKE_H):
            row_str = ""
            for c in range(_SNAKE_W):
                if (r, c) == snake[0]:
                    row_str += "🟢"
                elif (r, c) in snake:
                    row_str += "🟩"
                elif (r, c) == food:
                    row_str += "🍎"
                else:
                    row_str += "⬛"
            grid_lines.append(row_str)
        field = "\n".join(grid_lines)
        await asyncio.sleep(0.5)
        try:
            await msg.edit_text(card("🐍 Змейка", f"{field}\n\n🍎 Счёт: <b>{score}</b>"))
        except Exception:
            pass
    await asyncio.sleep(0.5)
    try:
        await msg.edit_text(
            card("🐍 Змейка", f"Демо окончено!\n\n🍎 Итоговый счёт: <b>{score}</b>")
        )
    except Exception:
        pass


# ──────────────────────────────────────────────
# 16. 🎪 Русская рулетка
# ──────────────────────────────────────────────
@router.callback_query(F.data == "game_roul")
async def game_roulette_start(cb: CallbackQuery) -> None:
    await cb.answer()
    chat_key = (cb.message.chat.id,)
    sess = _get("roul", chat_key)
    if sess and sess.get("active"):
        await cb.message.answer(
            card("🎪 Русская рулетка", "Игра уже идёт! Жми кнопку 🔫")
        )
        return
    bullet = random.randint(1, 6)
    sess = _set("roul", chat_key, {
        "bullet": bullet,
        "chamber": 0,
        "players": [],
        "active": True,
    })
    kb = _kb([[_btn("🔫 Крутить барабан", "rl_spin")]])
    await cb.message.answer(
        card(
            "🎪 Русская рулетка",
            "Револьвер заряжен! Одна пуля в барабане.\n"
            "Кто хочет испытать судьбу? Жмите кнопку!\n\n"
            f"🔫 Выстрел: <b>0</b> / 6",
        ),
        reply_markup=kb,
    )


@router.callback_query(F.data == "rl_spin")
async def game_roulette_spin(cb: CallbackQuery) -> None:
    chat_key = (cb.message.chat.id,)
    sess = _get("roul", chat_key)
    if not sess or not sess.get("active"):
        await cb.answer("Игра не активна!", show_alert=True)
        return
    sess["chamber"] += 1
    chamber = sess["chamber"]
    player_name = _mention(cb.from_user)
    if chamber == sess["bullet"]:
        sess["active"] = False
        _pop("roul", chat_key)
        await cb.answer("💥 БАХ!")
        try:
            await cb.message.edit_text(
                card(
                    "🎪 Русская рулетка",
                    f"💥 <b>ВЫСТРЕЛ!</b>\n\n"
                    f"{player_name} не повезло!\n"
                    f"Пуля была в камере <b>#{chamber}</b>",
                )
            )
        except Exception:
            pass
    else:
        await cb.answer("*клик* — пусто!")
        kb = _kb([[_btn("🔫 Крутить барабан", "rl_spin")]])
        try:
            await cb.message.edit_text(
                card(
                    "🎪 Русская рулетка",
                    f"*клик* — пусто! 😮‍💨\n\n"
                    f"{player_name} выжил(а)!\n"
                    f"🔫 Выстрел: <b>{chamber}</b> / 6\n\n"
                    "Следующий смельчак?",
                ),
                reply_markup=kb,
            )
        except Exception:
            pass
    if chamber >= 6 and sess.get("active"):
        sess["active"] = False
        _pop("roul", chat_key)


# ──────────────────────────────────────────────
# 17. 🏆 Дуэль
# ──────────────────────────────────────────────
@router.callback_query(F.data == "game_duel")
async def game_duel_start(cb: CallbackQuery) -> None:
    await cb.answer()
    chat_key = (cb.message.chat.id,)
    old = _get("duel", chat_key)
    if old and old.get("active") and time.time() - old.get("_ts", 0) < 60:
        await cb.message.answer(card("🏆 Дуэль", "Дуэль уже идёт! Ждём участников."))
        return
    initiator = cb.from_user
    sess = _set("duel", chat_key, {
        "active": True,
        "p1_id": initiator.id,
        "p1_name": initiator.full_name or "Игрок 1",
        "p2_id": None,
        "p2_name": None,
        "p1_time": None,
        "p2_time": None,
        "started": False,
    })
    p1_name = _mention(initiator)
    kb = _kb([[_btn("⚔️ Принять вызов!", "du_join")]])
    await cb.message.answer(
        card("🏆 Дуэль", f"{p1_name} бросает вызов!\n\nЖмите кнопку, чтобы принять!"),
        reply_markup=kb,
    )


@router.callback_query(F.data == "du_join")
async def game_duel_join(cb: CallbackQuery) -> None:
    chat_key = (cb.message.chat.id,)
    sess = _get("duel", chat_key)
    if not sess or not sess.get("active"):
        await cb.answer("Дуэль не активна!", show_alert=True)
        return
    if cb.from_user.id == sess["p1_id"]:
        await cb.answer("Нельзя принять свой вызов!", show_alert=True)
        return
    if sess.get("started"):
        await cb.answer("Дуэль уже началась!", show_alert=True)
        return
    sess["p2_id"] = cb.from_user.id
    sess["p2_name"] = cb.from_user.full_name or "Игрок 2"
    sess["started"] = True
    await cb.answer()
    p1n = html.escape(sess["p1_name"])
    p2n = html.escape(sess["p2_name"])
    try:
        await cb.message.edit_text(
            card("🏆 Дуэль", f"<b>{p1n}</b> ⚔️ <b>{p2n}</b>\n\nПриготовьтесь...")
        )
    except Exception:
        pass
    await asyncio.sleep(random.uniform(1.5, 4.0))
    kb = _kb([[_btn("⚡ ОГОНЬ!", f"du_fire")]])
    sess["fire_time"] = time.time()
    try:
        await cb.message.edit_text(
            card("🏆 Дуэль", f"<b>{p1n}</b> ⚔️ <b>{p2n}</b>\n\n🔥 <b>ОГОНЬ!</b> Жмите кнопку!"),
            reply_markup=kb,
        )
    except Exception:
        pass


@router.callback_query(F.data == "du_fire")
async def game_duel_fire(cb: CallbackQuery) -> None:
    chat_key = (cb.message.chat.id,)
    sess = _get("duel", chat_key)
    if not sess or not sess.get("active") or not sess.get("started"):
        await cb.answer("Дуэль не активна!", show_alert=True)
        return
    uid = cb.from_user.id
    if uid not in (sess["p1_id"], sess["p2_id"]):
        await cb.answer("Ты не участник дуэли!", show_alert=True)
        return
    fire_time = sess.get("fire_time", time.time())
    reaction = round((time.time() - fire_time) * 1000)
    if uid == sess["p1_id"] and sess["p1_time"] is None:
        sess["p1_time"] = reaction
    elif uid == sess["p2_id"] and sess["p2_time"] is None:
        sess["p2_time"] = reaction
    else:
        await cb.answer("Ты уже нажал!")
        return
    await cb.answer(f"⚡ {reaction} мс!")
    if sess["p1_time"] is not None and sess["p2_time"] is not None:
        sess["active"] = False
        p1n = html.escape(sess["p1_name"])
        p2n = html.escape(sess["p2_name"])
        p1t = sess["p1_time"]
        p2t = sess["p2_time"]
        if p1t < p2t:
            winner = p1n
        elif p2t < p1t:
            winner = p2n
        else:
            winner = "Ничья!"
        result = (
            f"<b>{p1n}</b>: {p1t} мс\n"
            f"<b>{p2n}</b>: {p2t} мс\n\n"
        )
        if winner == "Ничья!":
            result += "🤝 <b>Ничья!</b>"
        else:
            result += f"🏆 Победитель: <b>{winner}</b>!"
        _pop("duel", chat_key)
        try:
            await cb.message.edit_text(card("🏆 Дуэль", result))
        except Exception:
            pass


# ──────────────────────────────────────────────
# 18. 🔮 Предсказание
# ──────────────────────────────────────────────
_FORTUNES = [
    "Сегодня звёзды на твоей стороне. Всё получится! ✨",
    "Жди приятный сюрприз от близкого человека. 🎁",
    "Финансовая удача не за горами. Следи за знаками. 💸",
    "Сегодня отличный день для новых начинаний! 🚀",
    "Не бойся перемен — они к лучшему. 🌈",
    "Кто-то думает о тебе прямо сейчас. 💭",
    "Удача улыбнётся тебе дважды сегодня. 🍀🍀",
    "Будь осторожен с обещаниями — не все искренни. ⚠️",
    "Творческая энергия зашкаливает — используй её! 🎨",
    "Путешествие скоро изменит твою жизнь. ✈️",
    "Старый друг напомнит о себе. 📱",
    "Доверься интуиции — она не подведёт. 🧘",
    "Сегодня ты обретёшь ответ на давний вопрос. 💡",
    "Космос посылает тебе энергию изобилия. 🌌",
    "Маленькое доброе дело принесёт большую награду. 🤲",
    "Не спеши — терпение принесёт результат. ⏳",
    "Жди хорошие новости к вечеру. 📬",
    "Ты на пороге важного открытия. 🔬",
    "Любовь витает в воздухе. 💕",
    "Сегодня отличный день — наслаждайся каждой минутой! ☀️",
]


@router.callback_query(F.data == "game_fort")
async def game_fortune(cb: CallbackQuery) -> None:
    await cb.answer()
    msg = await cb.message.answer(card("🔮 Предсказание", "Заглядываю в будущее..."))
    anim = [
        "🔮 Настраиваю кристалл...",
        "🌙 Читаю звёзды...",
        "✨ Ловлю сигналы вселенной...",
        "🌀 Вижу образы...",
        "💫 Формулирую послание...",
    ]
    for frame in anim:
        await asyncio.sleep(0.5)
        try:
            await msg.edit_text(card("🔮 Предсказание", frame))
        except Exception:
            pass
    fortune = random.choice(_FORTUNES)
    await asyncio.sleep(0.4)
    await msg.edit_text(
        card("🔮 Предсказание", f"🔮 Вселенная говорит:\n\n<i>«{fortune}»</i>")
    )


# ──────────────────────────────────────────────
# 19. 💰 Краш
# ──────────────────────────────────────────────
@router.callback_query(F.data == "game_crsh")
async def game_crash_start(cb: CallbackQuery) -> None:
    await cb.answer()
    uid = cb.from_user.id
    key = _key(cb.message.chat.id, uid)
    old = _get("crsh", key)
    if old and old.get("active"):
        await cb.message.answer(card("💰 Краш", "У тебя уже идёт раунд! Жми «Забрать»!"))
        return
    crash_at = round(random.uniform(1.1, 5.0), 2)
    # Нормализуем вероятность — чаще краш на низких множителях
    if random.random() < 0.4:
        crash_at = round(random.uniform(1.1, 2.0), 2)
    sess = _set("crsh", key, {"crash_at": crash_at, "mult": 1.0, "active": True, "cashed": False})
    kb = _kb([[_btn("💵 Забрать", f"cr_{uid}_out")]])
    msg = await cb.message.answer(
        card("💰 Краш", f"Множитель: <b>1.00x</b>\n\n📈 Растёт..."),
        reply_markup=kb,
    )
    sess["msg_id"] = msg.message_id
    # Анимация роста
    mult = 1.0
    for _ in range(50):
        await asyncio.sleep(0.5)
        s = _get("crsh", key)
        if not s or not s.get("active") or s.get("cashed"):
            return
        mult += round(random.uniform(0.05, 0.25), 2)
        mult = round(mult, 2)
        s["mult"] = mult
        if mult >= crash_at:
            s["active"] = False
            _pop("crsh", key)
            try:
                await msg.edit_text(
                    card("💰 Краш", f"💥 <b>КРАШ на {mult:.2f}x!</b>\n\nТы не успел забрать!")
                )
            except Exception:
                pass
            return
        bar = "📈" * min(int(mult), 10)
        try:
            await msg.edit_text(
                card("💰 Краш", f"Множитель: <b>{mult:.2f}x</b>\n\n{bar}"),
                reply_markup=kb,
            )
        except Exception:
            pass
    # Если дошли сюда — автоматический кэшаут
    s = _get("crsh", key)
    if s and s.get("active"):
        s["active"] = False
        s["cashed"] = True
        _pop("crsh", key)
        try:
            await msg.edit_text(
                card("💰 Краш", f"🏆 Авто-кэшаут!\n\nМножитель: <b>{mult:.2f}x</b>")
            )
        except Exception:
            pass


@router.callback_query(F.data.startswith("cr_"))
async def game_crash_cashout(cb: CallbackQuery) -> None:
    parts = cb.data.split("_")
    if len(parts) != 3:
        await cb.answer()
        return
    uid = int(parts[1])
    if cb.from_user.id != uid:
        await cb.answer("Это не твоя игра!", show_alert=True)
        return
    key = _key(cb.message.chat.id, uid)
    sess = _get("crsh", key)
    if not sess or not sess.get("active"):
        await cb.answer("Раунд уже окончен!", show_alert=True)
        return
    mult = sess["mult"]
    sess["active"] = False
    sess["cashed"] = True
    _pop("crsh", key)
    await cb.answer(f"💵 Забрал на {mult:.2f}x!")
    try:
        await cb.message.edit_text(
            card("💰 Краш", f"💵 <b>Кэшаут!</b>\n\nМножитель: <b>{mult:.2f}x</b>\n\n🎉 Успел забрать вовремя!")
        )
    except Exception:
        pass


# ──────────────────────────────────────────────
# 20. 🏴‍☠️ Сундук (9 сундуков)
# ──────────────────────────────────────────────
def _chest_board() -> dict:
    cells = list(range(9))
    random.shuffle(cells)
    treasure = cells[0]
    traps = set(cells[1:3])
    return {
        "treasure": treasure,
        "traps": traps,
        "opened": set(),
        "dead": False,
        "won": False,
    }


def _chest_text(sess: dict) -> str:
    if sess["won"]:
        return card("🏴‍☠️ Сундук", "🎉 <b>Ты нашёл сокровище!</b> 💎")
    if sess["dead"]:
        return card("🏴‍☠️ Сундук", "💀 <b>Ловушка!</b> Ты попался!")
    opened = len(sess["opened"])
    return card("🏴‍☠️ Сундук", f"Открыто: <b>{opened}</b> / 9\n\n🔍 Найди сокровище! Избегай ловушек!")


def _chest_kb(sess: dict, uid: int) -> InlineKeyboardMarkup:
    rows = []
    for r in range(3):
        row = []
        for c in range(3):
            idx = r * 3 + c
            if idx in sess["opened"]:
                if idx == sess["treasure"]:
                    row.append(_btn("💎", "noop"))
                elif idx in sess["traps"]:
                    row.append(_btn("💀", "noop"))
                else:
                    row.append(_btn("📭", "noop"))
            elif sess["dead"] or sess["won"]:
                if idx == sess["treasure"]:
                    row.append(_btn("💎", "noop"))
                elif idx in sess["traps"]:
                    row.append(_btn("💀", "noop"))
                else:
                    row.append(_btn("📭", "noop"))
            else:
                row.append(_btn("📦", f"ch_{uid}_{idx}"))
        rows.append(row)
    return _kb(rows)


@router.callback_query(F.data == "game_chest")
async def game_chest_start(cb: CallbackQuery) -> None:
    await cb.answer()
    uid = cb.from_user.id
    key = _key(cb.message.chat.id, uid)
    sess = _set("chest", key, _chest_board())
    await cb.message.answer(_chest_text(sess), reply_markup=_chest_kb(sess, uid))


@router.callback_query(F.data.startswith("ch_"))
async def game_chest_open(cb: CallbackQuery) -> None:
    parts = cb.data.split("_")
    if len(parts) != 3:
        await cb.answer()
        return
    uid = int(parts[1])
    if cb.from_user.id != uid:
        await cb.answer("Это не твоя игра!", show_alert=True)
        return
    idx = int(parts[2])
    key = _key(cb.message.chat.id, uid)
    sess = _get("chest", key)
    if not sess or sess["dead"] or sess["won"]:
        await cb.answer()
        return
    sess["opened"].add(idx)
    if idx == sess["treasure"]:
        sess["won"] = True
        await cb.answer("💎 Сокровище!")
    elif idx in sess["traps"]:
        sess["dead"] = True
        # Показать всё
        sess["opened"] = set(range(9))
        await cb.answer("💀 Ловушка!")
    else:
        await cb.answer("📭 Пусто...")
    try:
        await cb.message.edit_text(_chest_text(sess), reply_markup=_chest_kb(sess, uid))
    except Exception:
        pass


# ──────────────────────────────────────────────
# noop callback — для неактивных кнопок
# ──────────────────────────────────────────────
@router.callback_query(F.data == "noop")
async def noop_handler(cb: CallbackQuery) -> None:
    await cb.answer()
