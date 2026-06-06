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
    FSInputFile,
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
    ("🏎️ Гонки (2-4 игр.)", "game_race"),
    ("🃏 Блэкджек (2-4 игр.)", "game_bj"),
    ("💣 Бомба (2-4 игр.)", "game_bomb"),
    ("🎲 Покер (2-4 игр.)", "game_dice"),
    ("❌ Крестики-нолики (2 игр.)", "game_ttt"),
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


def _get_lobby_kb(game_type: str, players: list, chat_id: int, creator_id: int) -> InlineKeyboardMarkup:
    buttons = [
        [_btn("⚔️ Принять вызов", f"jo_{game_type}")],
        [_btn("⚡ Начать игру", f"st_{game_type}")] if len(players) >= 2 else [],
        [_btn("◀️ В меню", "games_back")]
    ]
    return _kb([b for b in buttons if b])


@router.message(Command("games", ignore_case=True))
async def cmd_games(message: Message) -> None:
    _ensure_cleanup()
    text = card("🎮 Mini-игры", "Выберите игру:")
    markup = _games_keyboard()
    try:
        banner = FSInputFile("assets/games_banner.png")
        await message.answer_photo(
            banner,
            caption=text,
            reply_markup=markup,
        )
    except Exception:
        await message.answer(text, reply_markup=markup)


@router.message(Command("games_help", ignore_case=True))
async def cmd_games_help(message: Message) -> None:
    help_body = (
        "🎮 <b>Мини-игры — Список и описание:</b>\n\n"
        "🪙 <b>Орёл и Решка</b> — подбрасывание монеты с анимацией.\n"
        "🏎️ <b>Гонки (2-4 игр.)</b> — multiplayer emoji гоночная дуэль на скорость.\n"
        "🃏 <b>Блэкджек (2-4 игр.)</b> — классическая карточная игра блэкджек (до 21) на кнопках.\n"
        "💣 <b>Бомба (2-4 игр.)</b> — интерактивный сапёр-мультиплеер: обрежь провод и не взорвись.\n"
        "🎲 <b>Покер на костях (2-4 игр.)</b> — виртуальный покер на костях, бросок 5 кубиков.\n"
        "❌ <b>Крестики-нолики (2 игр.)</b> — классическая дуэль крестики-нолики 3х3 на кнопках.\n"
        "🎱 <b>Магический шар</b> — мистический ответ на твой вопрос.\n"
        "🔢 <b>Угадай число (1-4 игр.)</b> — угадай число 1-100 за 7 попыток (одиночно) или пошаговое лобби.\n"
        "✊ <b>Камень-Ножницы-Бумага (1-2 игр.)</b> — игра против бота или скрытая дуэль 1х1.\n"
        "💣 <b>Сапёр-лайт</b> — поле 5х5, найди пустые клетки и не взорвись.\n"
        "🃏 <b>Больше-Меньше</b> — угадай, следующая карта больше или меньше.\n"
        "🎡 <b>Колесо Фортуны</b> — вращай колесо и выиграй случайный приз.\n"
        "📝 <b>Виселица (1-4 игр.)</b> — угадай слово по буквам (одиночно или кооператив).\n"
        "🧠 <b>Викторина (1-4 игр.)</b> — 10 вопросов (одиночно или соревнование в лобби).\n"
        "🐍 <b>Змейка</b> — пошаговое интерактивное управление змейкой.\n"
        "🎪 <b>Русская рулетка</b> — групповая игра на выбывание.\n"
        "🏆 <b>Дуэль</b> — дуэль реакции против другого игрока.\n"
        "🔮 <b>Предсказание</b> — получи предсказание на сегодняшний день.\n"
        "💰 <b>Краш</b> — забери деньги до того, как график рухнет.\n"
        "🏴‍☠️ <b>Сундук</b> — найди сокровище среди 9 сундуков.\n\n"
        "Для запуска меню выбора игр отправьте команду /games."
    )
    await message.answer(card("❓ Помощь по играм", help_body))


@router.callback_query(F.data == "games_back")
async def callback_games_back(cb: CallbackQuery) -> None:
    await cb.answer()
    text = card("🎮 Mini-игры", "Выберите игру:")
    markup = _games_keyboard()
    try:
        if cb.message.photo:
            await cb.message.edit_caption(caption=text, reply_markup=markup)
        else:
            await cb.message.edit_text(text, reply_markup=markup)
    except Exception:
        try:
            banner = FSInputFile("assets/games_banner.png")
            await cb.message.answer_photo(banner, caption=text, reply_markup=markup)
            await cb.message.delete()
        except Exception:
            await cb.message.answer(text, reply_markup=markup)


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
    await msg.edit_text(
        card("🪙 Орёл и Решка", f"Результат: <b>{result}</b>!"),
        reply_markup=_kb([[_btn("◀️ В меню", "games_back")]]),
    )


# ──────────────────────────────────────────────
# 2. 🏎️ Гоночная трасса (Race)
# ──────────────────────────────────────────────
VEHICLES = ["🏎️", "🏍️", "🚗", "🏎️"]


def _get_race_track_str(sess: dict) -> str:
    lines = []
    for i, p in enumerate(sess["players"]):
        pos = sess["positions"][p.id]
        vehicle = VEHICLES[i % len(VEHICLES)]
        track = "🟦" * pos + "⬜" * (8 - pos)
        lines.append(f"{vehicle} {_mention(p)}:\n{track} 🏁")
    return "\n\n".join(lines)


def _get_race_kb(sess: dict) -> InlineKeyboardMarkup:
    rows = []
    for p in sess["players"]:
        rows.append([_btn(f"⏩ Газ: {p.first_name}", f"rc_gs_{p.id}")])
    rows.append([_btn("◀️ В меню", "games_back")])
    return _kb(rows)


async def _update_race_screen(message: Message, sess: dict) -> None:
    track_str = _get_race_track_str(sess)
    if sess["winner"]:
        w_name = _mention(sess["winner"])
        await message.edit_text(
            card("🏎️ Гоночная трасса (Финиш!)", f"{track_str}\n\n🏆 Победитель: {w_name}!"),
            reply_markup=_kb([[_btn("◀️ В меню", "games_back")]])
        )
    else:
        await message.edit_text(
            card("🏎️ Гоночная трасса", f"{track_str}\n\nЖмите кнопку «Газ» своего транспорта!"),
            reply_markup=_get_race_kb(sess)
        )


@router.callback_query(F.data == "game_race")
async def game_race_lobby(cb: CallbackQuery) -> None:
    await cb.answer()
    chat_id = cb.message.chat.id
    uid = cb.from_user.id
    key = (chat_id,)
    sess = _set("race_lobby", key, {
        "players": [cb.from_user],
        "active": False
    })
    players_str = "\n".join(f"▸ {_mention(p)}" for p in sess["players"])
    await cb.message.answer(
        card("🏎️ Гоночная трасса (Лобби)", f"Ожидание игроков (2-4 игрока)...\n\nУчастники:\n{players_str}"),
        reply_markup=_get_lobby_kb("rc", sess["players"], chat_id, uid)
    )


@router.callback_query(F.data == "jo_rc")
async def game_race_join(cb: CallbackQuery) -> None:
    chat_key = (cb.message.chat.id,)
    sess = _get("race_lobby", chat_key)
    if not sess or sess.get("active"):
        await cb.answer("Лобби не найдено или игра уже началась!", show_alert=True)
        return
    if cb.from_user.id in [p.id for p in sess["players"]]:
        await cb.answer("Ты уже в лобби!", show_alert=True)
        return
    if len(sess["players"]) >= 4:
        await cb.answer("Лобби переполнено (макс. 4 игрока)!", show_alert=True)
        return
    sess["players"].append(cb.from_user)
    _set("race_lobby", chat_key, sess)
    await cb.answer("Ты присоединился!")
    players_str = "\n".join(f"▸ {_mention(p)}" for p in sess["players"])
    await cb.message.edit_text(
        card("🏎️ Гоночная трасса (Лобби)", f"Ожидание игроков (2-4 игрока)...\n\nУчастники:\n{players_str}"),
        reply_markup=_get_lobby_kb("rc", sess["players"], cb.message.chat.id, sess["players"][0].id)
    )


@router.callback_query(F.data == "st_rc")
async def game_race_start(cb: CallbackQuery) -> None:
    chat_key = (cb.message.chat.id,)
    sess = _get("race_lobby", chat_key)
    if not sess or sess.get("active"):
        await cb.answer("Лобби не найдено!", show_alert=True)
        return
    if len(sess["players"]) < 2:
        await cb.answer("Нужно как минимум 2 игрока!", show_alert=True)
        return
    sess["active"] = True
    players = sess["players"]
    positions = {p.id: 0 for p in players}
    game_sess = _set("race_game", chat_key, {
        "players": players,
        "positions": positions,
        "winner": None
    })
    _pop("race_lobby", chat_key)
    await cb.answer("Гонка начинается!")
    await _update_race_screen(cb.message, game_sess)


@router.callback_query(F.data.startswith("rc_gs_"))
async def game_race_gas(cb: CallbackQuery) -> None:
    target_uid = int(cb.data.split("_")[2])
    if cb.from_user.id != target_uid:
        await cb.answer("Это не твоя кнопка!", show_alert=True)
        return
    chat_key = (cb.message.chat.id,)
    sess = _get("race_game", chat_key)
    if not sess or sess["winner"]:
        await cb.answer()
        return
    sess["positions"][target_uid] += 1
    if sess["positions"][target_uid] >= 8:
        sess["winner"] = cb.from_user
        _pop("race_game", chat_key)
    else:
        _set("race_game", chat_key, sess)
    await cb.answer()
    try:
        await _update_race_screen(cb.message, sess)
    except Exception:
        pass


# ──────────────────────────────────────────────
# 3. 🃏 Блэкджек (Blackjack Multiplayer)
# ──────────────────────────────────────────────
def _bj_value(card_rank: str) -> int:
    if card_rank in ("J", "Q", "K"):
        return 10
    if card_rank == "A":
        return 11
    return int(card_rank)


def _bj_hand_value(hand: list[str]) -> int:
    total = 0
    aces = 0
    for c in hand:
        rank = c[:-2]
        val = _bj_value(rank)
        if rank == "A":
            aces += 1
        total += val
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total


async def _update_bj_screen(message: Message, sess: dict) -> None:
    lines = []
    players = sess["players"]
    turn_i = sess["turn_i"]
    current_player = players[turn_i] if turn_i < len(players) else None

    for p in players:
        hand = sess["hands"][p.id]
        val = _bj_hand_value(hand)
        cards_str = ", ".join(hand)
        status = ""
        if p.id in sess["stand"]:
            status = " 🛑 (Пас)"
        if val > 21:
            status = " 💥 (Перебор!)"
        lines.append(f"▸ {_mention(p)}: <b>{cards_str}</b> (Счёт: <b>{val}</b>){status}")

    kb_buttons = []
    if current_player:
        lines.append(f"\nХод: {_mention(current_player)}")
        kb_buttons = [
            [_btn("🃏 Ещё (Hit)", "bj_hit"), _btn("🛑 Достаточно (Stand)", "bj_stand")],
            [_btn("◀️ В меню", "games_back")]
        ]
    else:
        best_val = -1
        winners = []
        for p in players:
            val = _bj_hand_value(sess["hands"][p.id])
            if val <= 21:
                if val > best_val:
                    best_val = val
                    winners = [p]
                elif val == best_val:
                    winners.append(p)
        if winners:
            w_str = ", ".join(_mention(w) for w in winners)
            lines.append(f"\n🏆 Победитель: {w_str} (Счёт: <b>{best_val}</b>)")
        else:
            lines.append("\n💥 Никто не выиграл (у всех перебор)!")
        kb_buttons = [[_btn("◀️ В меню", "games_back")]]

    await message.edit_text(
        card("🃏 Блэкджек", "\n".join(lines)),
        reply_markup=_kb(kb_buttons)
    )


@router.callback_query(F.data == "game_bj")
async def game_bj_lobby(cb: CallbackQuery) -> None:
    await cb.answer()
    chat_id = cb.message.chat.id
    uid = cb.from_user.id
    key = (chat_id,)
    sess = _set("bj_lobby", key, {
        "players": [cb.from_user],
        "active": False
    })
    players_str = "\n".join(f"▸ {_mention(p)}" for p in sess["players"])
    await cb.message.answer(
        card("🃏 Блэкджек (Лобби)", f"Ожидание игроков (2-4 игрока)...\n\nУчастники:\n{players_str}"),
        reply_markup=_get_lobby_kb("bj", sess["players"], chat_id, uid)
    )


@router.callback_query(F.data == "jo_bj")
async def game_bj_join(cb: CallbackQuery) -> None:
    chat_key = (cb.message.chat.id,)
    sess = _get("bj_lobby", chat_key)
    if not sess or sess.get("active"):
        await cb.answer("Лобби не найдено или игра уже началась!", show_alert=True)
        return
    if cb.from_user.id in [p.id for p in sess["players"]]:
        await cb.answer("Ты уже в лобби!", show_alert=True)
        return
    if len(sess["players"]) >= 4:
        await cb.answer("Лобби переполнено (макс. 4 игрока)!", show_alert=True)
        return
    sess["players"].append(cb.from_user)
    _set("bj_lobby", chat_key, sess)
    await cb.answer("Ты присоединился!")
    players_str = "\n".join(f"▸ {_mention(p)}" for p in sess["players"])
    await cb.message.edit_text(
        card("🃏 Блэкджек (Лобби)", f"Ожидание игроков (2-4 игрока)...\n\nУчастники:\n{players_str}"),
        reply_markup=_get_lobby_kb("bj", sess["players"], cb.message.chat.id, sess["players"][0].id)
    )


@router.callback_query(F.data == "st_bj")
async def game_bj_start(cb: CallbackQuery) -> None:
    chat_key = (cb.message.chat.id,)
    sess = _get("bj_lobby", chat_key)
    if not sess or sess.get("active"):
        await cb.answer("Лобби не найдено!", show_alert=True)
        return
    if len(sess["players"]) < 2:
        await cb.answer("Нужно как минимум 2 игрока!", show_alert=True)
        return
    sess["active"] = True
    players = sess["players"]
    suits = ["♠️", "♥️", "♦️", "♣️"]
    ranks = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
    deck = [f"{r}{s}" for r in ranks for s in suits]
    random.shuffle(deck)
    hands = {}
    for p in players:
        hands[p.id] = [deck.pop(), deck.pop()]
    game_sess = _set("bj_game", chat_key, {
        "players": players,
        "hands": hands,
        "deck": deck,
        "turn_i": 0,
        "stand": set()
    })
    _pop("bj_lobby", chat_key)
    await cb.answer("Блэкджек начинается!")
    await _update_bj_screen(cb.message, game_sess)


@router.callback_query(F.data == "bj_hit")
async def game_bj_hit(cb: CallbackQuery) -> None:
    chat_key = (cb.message.chat.id,)
    sess = _get("bj_game", chat_key)
    if not sess:
        await cb.answer()
        return
    players = sess["players"]
    turn_i = sess["turn_i"]
    if turn_i >= len(players):
        await cb.answer()
        return
    current_player = players[turn_i]
    if cb.from_user.id != current_player.id:
        await cb.answer("Сейчас ход другого игрока!", show_alert=True)
        return
    card_drawn = sess["deck"].pop()
    sess["hands"][cb.from_user.id].append(card_drawn)
    val = _bj_hand_value(sess["hands"][cb.from_user.id])
    if val >= 21:
        sess["stand"].add(cb.from_user.id)
        sess["turn_i"] += 1
    _set("bj_game", chat_key, sess)
    await cb.answer("Взял карту!")
    try:
        await _update_bj_screen(cb.message, sess)
    except Exception:
        pass


@router.callback_query(F.data == "bj_stand")
async def game_bj_stand(cb: CallbackQuery) -> None:
    chat_key = (cb.message.chat.id,)
    sess = _get("bj_game", chat_key)
    if not sess:
        await cb.answer()
        return
    players = sess["players"]
    turn_i = sess["turn_i"]
    if turn_i >= len(players):
        await cb.answer()
        return
    current_player = players[turn_i]
    if cb.from_user.id != current_player.id:
        await cb.answer("Сейчас ход другого игрока!", show_alert=True)
        return
    sess["stand"].add(cb.from_user.id)
    sess["turn_i"] += 1
    _set("bj_game", chat_key, sess)
    await cb.answer("Пас!")
    try:
        await _update_bj_screen(cb.message, sess)
    except Exception:
        pass


# ──────────────────────────────────────────────
# 4. 💣 Бомба (Bomb Tag)
# ──────────────────────────────────────────────
async def _update_bomb_screen(message: Message, sess: dict) -> None:
    lines = []
    players = sess["players"]
    turn_i = sess["turn_i"]
    current_player = players[turn_i] if turn_i < len(players) else None

    lines.append("💣 <b>Бомба тикает!</b> Режьте провода по очереди.")
    lines.append("\nУчастники:")
    for p in players:
        status = ""
        if p in sess["eliminated"]:
            status = " 💀 (Взорвался!)"
        elif p == current_player:
            status = " 👈 Режет..."
        lines.append(f"▸ {_mention(p)}{status}")

    kb_buttons = []
    if current_player:
        lines.append(f"\nХод: {_mention(current_player)}")
        rows = []
        for i, w in enumerate(sess["wires"]):
            rows.append([_btn(f"✂️ {w}", f"bm_cut_{i}")])
        rows.append([_btn("◀️ В меню", "games_back")])
        kb_buttons = rows
    else:
        survivors = [p for p in players if p not in sess["eliminated"]]
        if len(survivors) == 1:
            lines.append(f"\n🏆 Победитель: {_mention(survivors[0])}!")
        else:
            lines.append("\nНикто не выжил!")
        kb_buttons = [[_btn("◀️ В меню", "games_back")]]

    await message.edit_text(
        card("💣 Бомба", "\n".join(lines)),
        reply_markup=_kb(kb_buttons)
    )


@router.callback_query(F.data == "game_bomb")
async def game_bomb_lobby(cb: CallbackQuery) -> None:
    await cb.answer()
    chat_id = cb.message.chat.id
    uid = cb.from_user.id
    key = (chat_id,)
    sess = _set("bomb_lobby", key, {
        "players": [cb.from_user],
        "active": False
    })
    players_str = "\n".join(f"▸ {_mention(p)}" for p in sess["players"])
    await cb.message.answer(
        card("💣 Бомба (Лобби)", f"Ожидание игроков (2-4 игрока)...\n\nУчастники:\n{players_str}"),
        reply_markup=_get_lobby_kb("bm", sess["players"], chat_id, uid)
    )


@router.callback_query(F.data == "jo_bm")
async def game_bomb_join(cb: CallbackQuery) -> None:
    chat_key = (cb.message.chat.id,)
    sess = _get("bomb_lobby", chat_key)
    if not sess or sess.get("active"):
        await cb.answer("Лобби не найдено или игра уже началась!", show_alert=True)
        return
    if cb.from_user.id in [p.id for p in sess["players"]]:
        await cb.answer("Ты уже в лобби!", show_alert=True)
        return
    if len(sess["players"]) >= 4:
        await cb.answer("Лобби переполнено (макс. 4 игрока)!", show_alert=True)
        return
    sess["players"].append(cb.from_user)
    _set("bomb_lobby", chat_key, sess)
    await cb.answer("Ты присоединился!")
    players_str = "\n".join(f"▸ {_mention(p)}" for p in sess["players"])
    await cb.message.edit_text(
        card("💣 Бомба (Лобби)", f"Ожидание игроков (2-4 игрока)...\n\nУчастники:\n{players_str}"),
        reply_markup=_get_lobby_kb("bm", sess["players"], cb.message.chat.id, sess["players"][0].id)
    )


@router.callback_query(F.data == "st_bm")
async def game_bomb_start(cb: CallbackQuery) -> None:
    chat_key = (cb.message.chat.id,)
    sess = _get("bomb_lobby", chat_key)
    if not sess or sess.get("active"):
        await cb.answer("Лобби не найдено!", show_alert=True)
        return
    if len(sess["players"]) < 2:
        await cb.answer("Нужно как минимум 2 игрока!", show_alert=True)
        return
    sess["active"] = True
    players = list(sess["players"])
    wires = ["🔴 Красный", "🔵 Синий", "🟢 Зелёный", "🟡 Жёлтый", "🟣 Фиолетовый"]
    explosive = random.choice(wires)
    game_sess = _set("bomb_game", chat_key, {
        "players": players,
        "wires": wires,
        "explosive": explosive,
        "turn_i": 0,
        "eliminated": []
    })
    _pop("bomb_lobby", chat_key)
    await cb.answer("Игра началась!")
    await _update_bomb_screen(cb.message, game_sess)


@router.callback_query(F.data.startswith("bm_cut_"))
async def game_bomb_cut(cb: CallbackQuery) -> None:
    wire_i = int(cb.data.split("_")[2])
    chat_key = (cb.message.chat.id,)
    sess = _get("bomb_game", chat_key)
    if not sess:
        await cb.answer()
        return
    players = sess["players"]
    turn_i = sess["turn_i"]
    current_player = players[turn_i]
    if cb.from_user.id != current_player.id:
        await cb.answer("Сейчас ход другого игрока!", show_alert=True)
        return
    wire = sess["wires"][wire_i]
    if wire == sess["explosive"]:
        sess["eliminated"].append(current_player)
        await cb.answer("💥 БУМ! Провод оказался взрывным!", show_alert=True)
        survivors = [p for p in players if p not in sess["eliminated"]]
        if len(survivors) <= 1:
            sess["turn_i"] = len(players)
        else:
            sess["wires"] = ["🔴 Красный", "🔵 Синий", "🟢 Зелёный", "🟡 Жёлтый", "🟣 Фиолетовый"]
            sess["explosive"] = random.choice(sess["wires"])
            next_i = (turn_i + 1) % len(players)
            while players[next_i] in sess["eliminated"]:
                next_i = (next_i + 1) % len(players)
            sess["turn_i"] = next_i
    else:
        await cb.answer("Safe! Провод обрезан.", show_alert=True)
        sess["wires"].pop(wire_i)
        next_i = (turn_i + 1) % len(players)
        while players[next_i] in sess["eliminated"]:
            next_i = (next_i + 1) % len(players)
        sess["turn_i"] = next_i

    _set("bomb_game", chat_key, sess)
    try:
        await _update_bomb_screen(cb.message, sess)
    except Exception:
        pass


# ──────────────────────────────────────────────
# 5. 🎲 Покер на костях (Dice Poker)
# ──────────────────────────────────────────────
def _dp_hand_name(hand: list[int]) -> tuple[int, str]:
    counts = {}
    for x in hand:
        counts[x] = counts.get(x, 0) + 1
    vals = sorted(counts.values(), reverse=True)
    distinct = sorted(list(counts.keys()))

    if 5 in vals:
        return 8, "Покер (5 одинаковых)"
    if 4 in vals:
        return 7, "Каре"
    if 3 in vals and 2 in vals:
        return 6, "Фулл-Хаус"
    if len(distinct) == 5 and (distinct[-1] - distinct[0] == 4):
        return 5, "Стрит"
    if 3 in vals:
        return 4, "Тройка"
    if vals.count(2) == 2:
        return 3, "Две пары"
    if 2 in vals:
        return 2, "Пара"
    return 1, f"Старшая кость ({max(hand)})"


@router.callback_query(F.data == "game_dice")
async def game_dice_lobby(cb: CallbackQuery) -> None:
    await cb.answer()
    chat_id = cb.message.chat.id
    uid = cb.from_user.id
    key = (chat_id,)
    sess = _set("dice_lobby", key, {
        "players": [cb.from_user],
        "active": False
    })
    players_str = "\n".join(f"▸ {_mention(p)}" for p in sess["players"])
    await cb.message.answer(
        card("🎲 Покер на костях (Лобби)", f"Ожидание игроков (2-4 игрока)...\n\nУчастники:\n{players_str}"),
        reply_markup=_get_lobby_kb("dp", sess["players"], chat_id, uid)
    )


@router.callback_query(F.data == "jo_dp")
async def game_dice_join(cb: CallbackQuery) -> None:
    chat_key = (cb.message.chat.id,)
    sess = _get("dice_lobby", chat_key)
    if not sess or sess.get("active"):
        await cb.answer("Лобби не найдено или игра уже началась!", show_alert=True)
        return
    if cb.from_user.id in [p.id for p in sess["players"]]:
        await cb.answer("Ты уже в лобби!", show_alert=True)
        return
    if len(sess["players"]) >= 4:
        await cb.answer("Лобби переполнено (макс. 4 игрока)!", show_alert=True)
        return
    sess["players"].append(cb.from_user)
    _set("dice_lobby", chat_key, sess)
    await cb.answer("Ты присоединился!")
    players_str = "\n".join(f"▸ {_mention(p)}" for p in sess["players"])
    await cb.message.edit_text(
        card("🎲 Покер на костях (Лобби)", f"Ожидание игроков (2-4 игрока)...\n\nУчастники:\n{players_str}"),
        reply_markup=_get_lobby_kb("dp", sess["players"], cb.message.chat.id, sess["players"][0].id)
    )


@router.callback_query(F.data == "st_dp")
async def game_dice_start(cb: CallbackQuery) -> None:
    chat_key = (cb.message.chat.id,)
    sess = _get("dice_lobby", chat_key)
    if not sess or sess.get("active"):
        await cb.answer("Лобби не найдено!", show_alert=True)
        return
    if len(sess["players"]) < 2:
        await cb.answer("Нужно как минимум 2 игрока!", show_alert=True)
        return
    sess["active"] = True
    players = sess["players"]
    _pop("dice_lobby", chat_key)
    await cb.answer("Бросаем кости!")

    msg = await cb.message.edit_text(card("🎲 Покер на костях", "🎲 Кости вращаются..."))
    anim_faces = ["⚀", "⚁", "⚂", "⚃", "⚄", "⚅"]
    for _ in range(4):
        temp_lines = []
        for p in players:
            faces = " ".join(random.choice(anim_faces) for _ in range(5))
            temp_lines.append(f"▸ {_mention(p)}: {faces}")
        try:
            await msg.edit_text(card("🎲 Покер на костях", "\n".join(temp_lines)))
        except Exception:
            pass
        await asyncio.sleep(0.4)

    rolls = {}
    lines = []
    best_rank = -1
    best_sum = -1
    winners = []
    faces_map = {1: "⚀", 2: "⚁", 3: "⚂", 4: "⚃", 5: "⚄", 6: "⚅"}

    for p in players:
        hand = [random.randint(1, 6) for _ in range(5)]
        rank, name = _dp_hand_name(hand)
        hand_sum = sum(hand)
        faces = " ".join(faces_map[x] for x in hand)
        rolls[p.id] = (rank, hand_sum, name, faces)
        lines.append(f"▸ {_mention(p)}:\n{faces} — <b>{name}</b>")

        if rank > best_rank:
            best_rank = rank
            best_sum = hand_sum
            winners = [p]
        elif rank == best_rank:
            if hand_sum > best_sum:
                best_sum = hand_sum
                winners = [p]
            elif hand_sum == best_sum:
                winners.append(p)

    w_str = ", ".join(_mention(w) for w in winners)
    lines.append(f"\n🏆 Победитель: {w_str}!")

    await msg.edit_text(
        card("🎲 Покер на костях", "\n\n".join(lines)),
        reply_markup=_kb([[_btn("◀️ В меню", "games_back")]])
    )


# ──────────────────────────────────────────────
# 6. ❌ Крестики-нолики (Tic-Tac-Toe)
# ──────────────────────────────────────────────
def _ttt_check_winner(board: list[str]) -> Optional[str]:
    win_combos = [
        (0, 1, 2), (3, 4, 5), (6, 7, 8),
        (0, 3, 6), (1, 4, 7), (2, 5, 8),
        (0, 4, 8), (2, 4, 6)
    ]
    for combo in win_combos:
        if board[combo[0]] == board[combo[1]] == board[combo[2]] != "⬜":
            return board[combo[0]]
    return None


def _get_ttt_kb(sess: dict) -> InlineKeyboardMarkup:
    rows = []
    board = sess["board"]
    winner = sess["winner"]
    draw = sess["draw"]
    for r in range(3):
        row = []
        for c in range(3):
            idx = r * 3 + c
            if board[idx] != "⬜" or winner or draw:
                row.append(_btn(board[idx], "noop"))
            else:
                row.append(_btn("⬜", f"tt_pl_{idx}"))
        rows.append(row)
    rows.append([_btn("◀️ В меню", "games_back")])
    return _kb(rows)


async def _update_ttt_screen(message: Message, sess: dict) -> None:
    players = sess["players"]
    turn_i = sess["turn_i"]
    current_player = players[turn_i]

    p1_mention = f"{_mention(players[0])} (❌)"
    p2_mention = f"{_mention(players[1])} (⭕)"

    status_lines = [
        f"❌: {p1_mention}",
        f"⭕: {p2_mention}\n"
    ]

    if sess["winner"]:
        winner_name = _mention(players[0]) if sess["winner"] == "❌" else _mention(players[1])
        status_lines.append(f"🏆 Победитель: {winner_name} ({sess['winner']})!")
    elif sess["draw"]:
        status_lines.append("🤝 Ничья!")
    else:
        status_lines.append(f"Ход: {_mention(current_player)} ({"❌" if turn_i == 0 else "⭕"})")

    await message.edit_text(
        card("❌ Крестики-нолики", "\n".join(status_lines)),
        reply_markup=_get_ttt_kb(sess)
    )


@router.callback_query(F.data == "game_ttt")
async def game_ttt_lobby(cb: CallbackQuery) -> None:
    await cb.answer()
    chat_id = cb.message.chat.id
    uid = cb.from_user.id
    key = (chat_id,)
    sess = _set("ttt_lobby", key, {
        "players": [cb.from_user],
        "active": False
    })
    players_str = "\n".join(f"▸ {_mention(p)}" for p in sess["players"])
    await cb.message.answer(
        card("❌ Крестики-нолики (Лобби)", f"Ожидание соперника (2 игрока)...\n\nУчастники:\n{players_str}"),
        reply_markup=_kb([
            [_btn("⚔️ Принять вызов", "jo_tt")],
            [_btn("◀️ В меню", "games_back")]
        ])
    )


@router.callback_query(F.data == "jo_tt")
async def game_ttt_join(cb: CallbackQuery) -> None:
    chat_key = (cb.message.chat.id,)
    sess = _get("ttt_lobby", chat_key)
    if not sess or sess.get("active"):
        await cb.answer("Лобби не найдено или игра уже началась!", show_alert=True)
        return
    if cb.from_user.id == sess["players"][0].id:
        await cb.answer("Нельзя сыграть с самим собой!", show_alert=True)
        return
    sess["players"].append(cb.from_user)
    sess["active"] = True

    players = sess["players"]
    board = ["⬜"] * 9
    game_sess = _set("ttt_game", chat_key, {
        "players": players,
        "board": board,
        "turn_i": 0,
        "winner": None,
        "draw": False
    })
    _pop("ttt_lobby", chat_key)
    await cb.answer("Игра начинается!")
    await _update_ttt_screen(cb.message, game_sess)


@router.callback_query(F.data.startswith("tt_pl_"))
async def game_ttt_click(cb: CallbackQuery) -> None:
    idx = int(cb.data.split("_")[2])
    chat_key = (cb.message.chat.id,)
    sess = _get("ttt_game", chat_key)
    if not sess or sess["winner"] or sess["draw"]:
        await cb.answer()
        return
    players = sess["players"]
    turn_i = sess["turn_i"]
    current_player = players[turn_i]
    if cb.from_user.id != current_player.id:
        await cb.answer("Сейчас не твой ход!", show_alert=True)
        return
    mark = "❌" if turn_i == 0 else "⭕"
    sess["board"][idx] = mark

    win_mark = _ttt_check_winner(sess["board"])
    if win_mark:
        sess["winner"] = win_mark
        _pop("ttt_game", chat_key)
    elif "⬜" not in sess["board"]:
        sess["draw"] = True
        _pop("ttt_game", chat_key)
    else:
        sess["turn_i"] = 1 - turn_i
        _set("ttt_game", chat_key, sess)

    await cb.answer()
    try:
        await _update_ttt_screen(cb.message, sess)
    except Exception:
        pass


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
        card("🎱 Магический шар", f"🔮 Шар говорит:\n\n<b>«{answer}»</b>"),
        reply_markup=_kb([[_btn("◀️ В меню", "games_back")]]),
    )


# ──────────────────────────────────────────────
# 8. 🔢 Угадай число (1-100, 7 попыток)
# ──────────────────────────────────────────────
@router.callback_query(F.data == "game_gnum")
async def game_gnum_menu(cb: CallbackQuery) -> None:
    await cb.answer()
    kb = _kb([
        [_btn("👤 1 Игрок", "gn_mode_1"), _btn("👥 2 Игрока", "gn_mode_2")],
        [_btn("👥 3 Игрока", "gn_mode_3"), _btn("👥 4 Игрока", "gn_mode_4")],
        [_btn("◀️ В меню", "games_back")]
    ])
    await cb.message.answer(
        card("🔢 Угадай число", "Выберите количество игроков:"),
        reply_markup=kb
    )


@router.callback_query(F.data.startswith("gn_mode_"))
async def game_gnum_select_mode(cb: CallbackQuery) -> None:
    await cb.answer()
    mode = int(cb.data.split("_")[2])
    chat_id = cb.message.chat.id
    uid = cb.from_user.id
    
    if mode == 1:
        key = _key(chat_id, uid)
        secret = random.randint(1, 100)
        _set("gnum", key, {"num": secret, "tries": 7, "max_tries": 7})
        await cb.message.answer(
            card(
                "🔢 Угадай число",
                "Я загадал число от <b>1</b> до <b>100</b>.\n"
                "У тебя <b>7</b> попыток.\n\n"
                "Просто отправь число в чат!",
            ),
            reply_markup=_kb([[_btn("◀️ В меню", "games_back")]]),
        )
    else:
        chat_key = (chat_id,)
        sess = _set("gnum_lobby", chat_key, {
            "players": [cb.from_user],
            "max_players": mode,
            "active": False
        })
        players_str = "\n".join(f"▸ {_mention(p)}" for p in sess["players"])
        await cb.message.answer(
            card(
                "🔢 Угадай число (Лобби)",
                f"Режим: <b>{mode} игроков</b>\n"
                f"Ожидание участников...\n\n"
                f"Участники:\n{players_str}"
            ),
            reply_markup=_get_lobby_kb("gn", sess["players"], chat_id, uid)
        )


@router.callback_query(F.data == "jo_gn")
async def game_gnum_join(cb: CallbackQuery) -> None:
    chat_key = (cb.message.chat.id,)
    sess = _get("gnum_lobby", chat_key)
    if not sess or sess.get("active"):
        await cb.answer("Лобби не найдено или игра уже началась!", show_alert=True)
        return
    if cb.from_user.id in [p.id for p in sess["players"]]:
        await cb.answer("Ты уже в лобби!", show_alert=True)
        return
    if len(sess["players"]) >= sess["max_players"]:
        await cb.answer("Лобби переполнено!", show_alert=True)
        return
    
    sess["players"].append(cb.from_user)
    _set("gnum_lobby", chat_key, sess)
    await cb.answer("Ты присоединился!")
    
    if len(sess["players"]) >= sess["max_players"]:
        await _game_gnum_start_mp(cb, sess)
    else:
        players_str = "\n".join(f"▸ {_mention(p)}" for p in sess["players"])
        await cb.message.edit_text(
            card(
                "🔢 Угадай число (Лобби)",
                f"Режим: <b>{sess['max_players']} игроков</b>\n"
                f"Ожидание участников...\n\n"
                f"Участники:\n{players_str}"
            ),
            reply_markup=_get_lobby_kb("gn", sess["players"], cb.message.chat.id, sess["players"][0].id)
        )


@router.callback_query(F.data == "st_gn")
async def game_gnum_start_btn(cb: CallbackQuery) -> None:
    chat_key = (cb.message.chat.id,)
    sess = _get("gnum_lobby", chat_key)
    if not sess or sess.get("active"):
        await cb.answer("Лобби не найдено!", show_alert=True)
        return
    if len(sess["players"]) < 2:
        await cb.answer("Нужно как минимум 2 игрока!", show_alert=True)
        return
    await _game_gnum_start_mp(cb, sess)


async def _game_gnum_start_mp(cb: CallbackQuery, sess: dict) -> None:
    chat_key = (cb.message.chat.id,)
    sess["active"] = True
    players = sess["players"]
    secret = random.randint(1, 100)
    
    game_sess = _set("gnum_mp", chat_key, {
        "players": players,
        "num": secret,
        "turn_i": 0,
        "history": [],
    })
    _pop("gnum_lobby", chat_key)
    
    await cb.answer("Игра начинается!")
    await cb.message.answer(
        card(
            "🔢 Угадай число (Мультиплеер)",
            f"Я загадал число от <b>1</b> до <b>100</b>.\n"
            f"Игроки по очереди делают ходы, отправляя числа в чат.\n\n"
            f"Сейчас ход игрока: {_mention(players[0])}\n"
            f"Ждем ваше число!"
        ),
        reply_markup=_kb([[_btn("◀️ В меню", "games_back")]])
    )


@router.message(F.text.regexp(r"^\d{1,3}$"))
async def game_gnum_guess(message: Message) -> None:
    chat_id = message.chat.id
    uid = message.from_user.id
    guess = int(message.text.strip())
    if guess < 1 or guess > 100:
        return

    # Мультиплеер
    chat_key = (chat_id,)
    sess_mp = _get("gnum_mp", chat_key)
    if sess_mp:
        players = sess_mp["players"]
        turn_i = sess_mp["turn_i"]
        current_player = players[turn_i]
        
        player_ids = [p.id for p in players]
        if uid not in player_ids:
            return
            
        if uid != current_player.id:
            await message.reply(f"❌ Сейчас ход игрока {_mention(current_player)}!")
            return
            
        secret = sess_mp["num"]
        history = sess_mp["history"]
        
        if guess == secret:
            _pop("gnum_mp", chat_key)
            await message.reply(
                card(
                    "🔢 Угадай число (Мультиплеер)",
                    f"🎉 {_mention(message.from_user)} угадал число <b>{secret}</b> и ПОБЕДИЛ!\n\n"
                    f"Игра окончена!"
                ),
                reply_markup=_kb([[_btn("◀️ В меню", "games_back")]]),
            )
        else:
            hint = "больше ⬆️" if guess < secret else "меньше ⬇️"
            history.append(f"▸ {_mention(message.from_user)}: {guess} (Загаданное число {hint})")
            
            next_turn_i = (turn_i + 1) % len(players)
            sess_mp["turn_i"] = next_turn_i
            next_player = players[next_turn_i]
            _set("gnum_mp", chat_key, sess_mp)
            
            hist_str = "\n".join(history[-5:])
            await message.reply(
                card(
                    "🔢 Угадай число (Мультиплеер)",
                    f"Число {guess} неверно!\n\n"
                    f"<b>История ходов:</b>\n{hist_str}\n\n"
                    f"Сейчас ход игрока: {_mention(next_player)}\n"
                    f"Ждем ваше число!"
                )
            )
        return

    # Одиночная игра
    key = _key(chat_id, uid)
    sess_sp = _get("gnum", key)
    if sess_sp:
        secret = sess_sp["num"]
        sess_sp["tries"] -= 1
        left = sess_sp["tries"]
        if guess == secret:
            _pop("gnum", key)
            used = sess_sp["max_tries"] - left
            await message.reply(
                card("🔢 Угадай число", f"🎉 Верно! Это было <b>{secret}</b>!\nПопыток использовано: <b>{used}</b>"),
                reply_markup=_kb([[_btn("◀️ В меню", "games_back")]]),
            )
        elif left <= 0:
            _pop("gnum", key)
            await message.reply(
                card("🔢 Угадай число", f"😔 Попытки кончились!\nЗагаданное число: <b>{secret}</b>"),
                reply_markup=_kb([[_btn("◀️ В меню", "games_back")]]),
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
# 9. ✊ Камень-Ножницы-Бумага (Дуэль)
# ──────────────────────────────────────────────
_RPS_ITEMS = {"r": ("✊", "Камень"), "s": ("✌️", "Ножницы"), "p": ("✋", "Бумага")}
_RPS_WINS = {"r": "s", "s": "p", "p": "r"}


@router.callback_query(F.data == "game_rps")
async def game_rps_mode_menu(cb: CallbackQuery) -> None:
    await cb.answer()
    kb = _kb([
        [_btn("👤 Против бота", "rps_bot_start")],
        [_btn("👥 Дуэль 1х1", "rps_duel_lobby")],
        [_btn("◀️ В меню", "games_back")]
    ])
    await cb.message.answer(
        card("✊ Камень-Ножницы-Бумага", "Выберите режим игры:"),
        reply_markup=kb
    )


@router.callback_query(F.data == "rps_bot_start")
async def game_rps_bot_start(cb: CallbackQuery) -> None:
    await cb.answer()
    kb = _kb([
        [_btn("✊ Камень", "rps_b_r"), _btn("✌️ Ножницы", "rps_b_s"), _btn("✋ Бумага", "rps_b_p")],
        [_btn("◀️ В меню", "games_back")]
    ])
    await cb.message.answer(card("✊ Камень-Ножницы-Бумага", "Сделай свой выбор (игра против бота):"), reply_markup=kb)


@router.callback_query(F.data.startswith("rps_b_"))
async def game_rps_bot_play(cb: CallbackQuery) -> None:
    await cb.answer()
    choice = cb.data.split("_")[2]
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
    kb = _kb([[_btn("◀️ В меню", "games_back")]])
    try:
        await cb.message.edit_text(card("✊ Камень-Ножницы-Бумага", text), reply_markup=kb)
    except Exception:
        await cb.message.answer(card("✊ Камень-Ножницы-Бумага", text), reply_markup=kb)


@router.callback_query(F.data == "rps_duel_lobby")
async def game_rps_lobby(cb: CallbackQuery) -> None:
    await cb.answer()
    chat_id = cb.message.chat.id
    uid = cb.from_user.id
    chat_key = (chat_id,)
    sess = _set("rps_lobby", chat_key, {
        "players": [cb.from_user],
        "active": False
    })
    players_str = "\n".join(f"▸ {_mention(p)}" for p in sess["players"])
    await cb.message.answer(
        card("✊ КНБ: Дуэль (Лобби)", f"Ожидание оппонента (2 игрока)...\n\nУчастники:\n{players_str}"),
        reply_markup=_get_lobby_kb("rps", sess["players"], chat_id, uid)
    )


@router.callback_query(F.data == "jo_rps")
async def game_rps_join(cb: CallbackQuery) -> None:
    chat_key = (cb.message.chat.id,)
    sess = _get("rps_lobby", chat_key)
    if not sess or sess.get("active"):
        await cb.answer("Лобби не найдено или дуэль началась!", show_alert=True)
        return
    if cb.from_user.id in [p.id for p in sess["players"]]:
        await cb.answer("Ты уже в лобби!", show_alert=True)
        return
    if len(sess["players"]) >= 2:
        await cb.answer("Лобби уже полное!", show_alert=True)
        return
    sess["players"].append(cb.from_user)
    _set("rps_lobby", chat_key, sess)
    await cb.answer("Ты принял вызов!")
    await _game_rps_start_mp(cb, sess)


@router.callback_query(F.data == "st_rps")
async def game_rps_start_btn(cb: CallbackQuery) -> None:
    chat_key = (cb.message.chat.id,)
    sess = _get("rps_lobby", chat_key)
    if not sess or sess.get("active"):
        await cb.answer("Лобби не найдено!", show_alert=True)
        return
    if len(sess["players"]) < 2:
        await cb.answer("Нужен оппонент!", show_alert=True)
        return
    await _game_rps_start_mp(cb, sess)


def _get_rps_kb(sess: dict) -> InlineKeyboardMarkup:
    p1, p2 = sess["players"]
    rows = []
    
    rows.append([_btn(f"{p1.first_name}: Выберите...", "noop")])
    if p1.id not in sess["choices"]:
        rows.append([
            _btn("✊", f"rps_ch_{p1.id}_r"),
            _btn("✌️", f"rps_ch_{p1.id}_s"),
            _btn("✋", f"rps_ch_{p1.id}_p")
        ])
    else:
        rows.append([_btn("✅ Выбор сделан", "noop")])
        
    rows.append([_btn(f"{p2.first_name}: Выберите...", "noop")])
    if p2.id not in sess["choices"]:
        rows.append([
            _btn("✊", f"rps_ch_{p2.id}_r"),
            _btn("✌️", f"rps_ch_{p2.id}_s"),
            _btn("✋", f"rps_ch_{p2.id}_p")
        ])
    else:
        rows.append([_btn("✅ Выбор сделан", "noop")])
        
    rows.append([_btn("◀️ В меню", "games_back")])
    return _kb(rows)


async def _game_rps_start_mp(cb: CallbackQuery, sess: dict) -> None:
    chat_key = (cb.message.chat.id,)
    sess["active"] = True
    p1, p2 = sess["players"][0], sess["players"][1]
    
    game_sess = _set("rps_game", chat_key, {
        "players": [p1, p2],
        "choices": {},
        "winner": None
    })
    _pop("rps_lobby", chat_key)
    
    await cb.message.answer(
        card(
            "✊ КНБ: Дуэль",
            f"Игроки: {_mention(p1)} vs {_mention(p2)}\n\n"
            f"Сделайте ваш секретный выбор ниже!"
        ),
        reply_markup=_get_rps_kb(game_sess)
    )


@router.callback_query(F.data.startswith("rps_ch_"))
async def game_rps_duel_choice(cb: CallbackQuery) -> None:
    parts = cb.data.split("_")
    if len(parts) != 4:
        await cb.answer()
        return
    
    target_uid = int(parts[2])
    choice = parts[3]
    
    if cb.from_user.id != target_uid:
        await cb.answer("Это не твоя кнопка!", show_alert=True)
        return
        
    chat_key = (cb.message.chat.id,)
    sess = _get("rps_game", chat_key)
    if not sess:
        await cb.answer("Игра не найдена или завершена!", show_alert=True)
        return
        
    if target_uid in sess["choices"]:
        await cb.answer("Ты уже сделал свой выбор!", show_alert=True)
        return
        
    sess["choices"][target_uid] = choice
    _set("rps_game", chat_key, sess)
    await cb.answer("Выбор принят!")
    
    p1, p2 = sess["players"]
    if len(sess["choices"]) == 2:
        _pop("rps_game", chat_key)
        
        c1 = sess["choices"][p1.id]
        c2 = sess["choices"][p2.id]
        
        emoji1, name1 = _RPS_ITEMS[c1]
        emoji2, name2 = _RPS_ITEMS[c2]
        
        if c1 == c2:
            res_str = "🤝 <b>Ничья!</b>"
        elif _RPS_WINS[c1] == c2:
            res_str = f"🏆 {_mention(p1)} <b>ПОБЕДИЛ!</b>"
        else:
            res_str = f"🏆 {_mention(p2)} <b>ПОБЕДИЛ!</b>"
            
        result_text = (
            f"Результаты дуэли:\n\n"
            f"▸ {_mention(p1)}: {emoji1} {name1}\n"
            f"▸ {_mention(p2)}: {emoji2} {name2}\n\n"
            f"{res_str}"
        )
        
        await cb.message.edit_text(
            card("✊ КНБ: Дуэль окончена", result_text),
            reply_markup=_kb([[_btn("◀️ В меню", "games_back")]])
        )
    else:
        try:
            await cb.message.edit_text(
                card(
                    "✊ КНБ: Дуэль",
                    f"Игроки: {_mention(p1)} vs {_mention(p2)}\n\n"
                    f"Ожидаем выбора другого игрока..."
                ),
                reply_markup=_get_rps_kb(sess)
            )
        except Exception:
            pass


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
    rows.append([_btn("◀️ В меню", "games_back")])
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
    kb = _kb([
        [_btn("⬆️ Больше", f"hl_{uid}_h"), _btn("⬇️ Меньше", f"hl_{uid}_l")],
        [_btn("◀️ В меню", "games_back")]
    ])
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
        kb = _kb([
            [_btn("⬆️ Больше", f"hl_{uid}_h"), _btn("⬇️ Меньше", f"hl_{uid}_l")],
            [_btn("◀️ В меню", "games_back")]
        ])
        await cb.answer("✅ Верно!")
        try:
            await cb.message.edit_text(_hilo_text(new_card, sess["streak"]), reply_markup=kb)
        except Exception:
            pass
    else:
        streak = sess["streak"]
        _pop("hilo", key)
        await cb.answer("❌ Неверно!")
        kb = _kb([[_btn("◀️ В меню", "games_back")]])
        try:
            await cb.message.edit_text(
                card(
                    "🃏 Больше-Меньше",
                    f"Была: <b>{sess['card']}</b>\n"
                    f"Выпала: <b>{new_card}</b>\n\n"
                    f"❌ Неверно! Серия: <b>{streak}</b>",
                ),
                reply_markup=kb
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
        card("🎡 Колесо Фортуны", f"🏆 Колесо остановилось!\n\nТвой приз: <b>{prize}</b>!"),
        reply_markup=_kb([[_btn("◀️ В меню", "games_back")]]),
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
    rows.append([_btn("◀️ В меню", "games_back")])
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
            card("📝 Виселица", f"🎉 <b>Победа!</b>\n\nСлово: <b>{word}</b>"),
            reply_markup=_kb([[_btn("◀️ В меню", "games_back")]]),
        )
        return
    if sess["errors"] >= 6:
        _pop("hang", key)
        stage = _HANGMAN_STAGES[-1]
        await cb.message.edit_text(
            card("📝 Виселица", f"<code>{stage}</code>\n\n😵 <b>Проигрыш!</b>\n\nСлово было: <b>{word}</b>"),
            reply_markup=_kb([[_btn("◀️ В меню", "games_back")]]),
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
    rows.append([_btn("◀️ В меню", "games_back")])
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
                card("🧠 Викторина", f"{emoji} Викторина окончена!\n\nСчёт: <b>{score}</b> / <b>{total}</b>"),
                reply_markup=_kb([[_btn("◀️ В меню", "games_back")]]),
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
            card("🐍 Змейка", f"Демо окончено!\n\n🍎 Итоговый счёт: <b>{score}</b>"),
            reply_markup=_kb([[_btn("◀️ В меню", "games_back")]]),
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
    kb = _kb([
        [_btn("🔫 Крутить барабан", "rl_spin")],
        [_btn("◀️ В меню", "games_back")]
    ])
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
                ),
                reply_markup=_kb([[_btn("◀️ В меню", "games_back")]]),
            )
        except Exception:
            pass
    else:
        await cb.answer("*клик* — пусто!")
        kb = _kb([
            [_btn("🔫 Крутить барабан", "rl_spin")],
            [_btn("◀️ В меню", "games_back")]
        ])
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
    kb = _kb([
        [_btn("⚔️ Принять вызов!", "du_join")],
        [_btn("◀️ В меню", "games_back")]
    ])
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
            await cb.message.edit_text(
                card("🏆 Дуэль", result),
                reply_markup=_kb([[_btn("◀️ В меню", "games_back")]]),
            )
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
        card("🔮 Предсказание", f"🔮 Вселенная говорит:\n\n<i>«{fortune}»</i>"),
        reply_markup=_kb([[_btn("◀️ В меню", "games_back")]]),
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
    kb = _kb([
        [_btn("💵 Забрать", f"cr_{uid}_out")],
        [_btn("◀️ В меню", "games_back")]
    ])
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
                    card("💰 Краш", f"💥 <b>КРАШ на {mult:.2f}x!</b>\n\nТы не успел забрать!"),
                    reply_markup=_kb([[_btn("◀️ В меню", "games_back")]]),
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
                card("💰 Краш", f"🏆 Авто-кэшаут!\n\nМножитель: <b>{mult:.2f}x</b>"),
                reply_markup=_kb([[_btn("◀️ В меню", "games_back")]]),
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
            card("💰 Краш", f"💵 <b>Кэшаут!</b>\n\nМножитель: <b>{mult:.2f}x</b>\n\n🎉 Успел забрать вовремя!"),
            reply_markup=_kb([[_btn("◀️ В меню", "games_back")]]),
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
    rows.append([_btn("◀️ В меню", "games_back")])
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
