"""BidTimerBot — SQLite хранилище настроек/сессий по чатам."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import List, Optional

import aiosqlite

from config import DB_PATH, DEFAULT_DURATION_SECONDS, DEFAULT_TRIGGER_REGEX


@dataclass(slots=True)
class ChatState:
    chat_id: int
    is_running: bool
    duration_seconds: int
    trigger_regex: str
    trigger_mode: str
    paid_message_star_count: Optional[int]
    last_bid_user_id: Optional[int]
    last_bid_username: Optional[str]
    end_at_unix: Optional[int]
    status_message_id: Optional[int]
    last_bid_message_id: Optional[int] = None


@dataclass(slots=True)
class BroadcastTarget:
    target_id: int
    kind: str


def _normalize_username(username: Optional[str]) -> Optional[str]:
    if not username:
        return None
    return username.lstrip("@").lower()


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_state (
                chat_id INTEGER PRIMARY KEY,
                is_running INTEGER NOT NULL DEFAULT 0,
                duration_seconds INTEGER NOT NULL,
                trigger_regex TEXT NOT NULL,
                trigger_mode TEXT NOT NULL DEFAULT 'paid',
                paid_message_star_count INTEGER,
                last_bid_user_id INTEGER,
                last_bid_username TEXT,
                end_at_unix INTEGER,
                status_message_id INTEGER,
                last_bid_message_id INTEGER
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_managers (
                chat_id INTEGER NOT NULL,
                user_id INTEGER,
                username TEXT,
                PRIMARY KEY (chat_id, user_id, username)
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS known_chats (
                chat_id INTEGER PRIMARY KEY,
                chat_type TEXT,
                title TEXT,
                username TEXT,
                last_seen_unix INTEGER NOT NULL
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS known_users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                is_bot INTEGER NOT NULL DEFAULT 0,
                last_seen_unix INTEGER NOT NULL
            )
            """
        )
        await db.execute("PRAGMA foreign_keys = ON")
        for stmt in (
            "ALTER TABLE chat_state ADD COLUMN trigger_mode TEXT NOT NULL DEFAULT 'paid'",
            "ALTER TABLE chat_state ADD COLUMN paid_message_star_count INTEGER",
            "ALTER TABLE chat_state ADD COLUMN status_message_id INTEGER",
            "ALTER TABLE chat_state ADD COLUMN last_bid_message_id INTEGER",
        ):
            try:
                await db.execute(stmt)
            except Exception:
                pass
        await db.commit()


async def _ensure_chat_row(db: aiosqlite.Connection, chat_id: int) -> None:
    cur = await db.execute("SELECT chat_id FROM chat_state WHERE chat_id=?", (chat_id,))
    row = await cur.fetchone()
    await cur.close()
    if row:
        return
    await db.execute(
        """
        INSERT INTO chat_state (chat_id, is_running, duration_seconds, trigger_regex, trigger_mode)
        VALUES (?, 0, ?, ?, 'paid')
        """,
        (chat_id, DEFAULT_DURATION_SECONDS, DEFAULT_TRIGGER_REGEX),
    )


def _row_to_state(row) -> ChatState:
    return ChatState(
        chat_id=row[0],
        is_running=bool(row[1]),
        duration_seconds=int(row[2]),
        trigger_regex=str(row[3]),
        trigger_mode=str(row[4] or "paid"),
        paid_message_star_count=row[5],
        last_bid_user_id=row[6],
        last_bid_username=row[7],
        end_at_unix=row[8],
        status_message_id=row[9] if len(row) > 9 else None,
        last_bid_message_id=row[10] if len(row) > 10 else None,
    )


async def get_chat_state(chat_id: int) -> ChatState:
    async with aiosqlite.connect(DB_PATH) as db:
        await _ensure_chat_row(db, chat_id)
        cur = await db.execute(
            """
            SELECT chat_id, is_running, duration_seconds, trigger_regex, trigger_mode,
                   paid_message_star_count, last_bid_user_id, last_bid_username,
                   end_at_unix, status_message_id, last_bid_message_id
            FROM chat_state WHERE chat_id=?
            """,
            (chat_id,),
        )
        row = await cur.fetchone()
        await cur.close()
        await db.commit()

    assert row is not None
    return _row_to_state(row)


async def update_chat_state(
    chat_id: int,
    *,
    is_running: Optional[bool] = None,
    duration_seconds: Optional[int] = None,
    trigger_regex: Optional[str] = None,
    trigger_mode: Optional[str] = None,
    paid_message_star_count: Optional[int] = None,
    last_bid_user_id: Optional[int] = None,
    last_bid_username: Optional[str] = None,
    end_at_unix: Optional[int] = None,
    status_message_id: Optional[int] = None,
    last_bid_message_id: Optional[int] = None,
    clear_status_message: bool = False,
    clear_last_bid_message: bool = False,
    clear_last_bid: bool = False,
) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await _ensure_chat_row(db, chat_id)

        sets = []
        params = []

        if is_running is not None:
            sets.append("is_running=?")
            params.append(1 if is_running else 0)
        if duration_seconds is not None:
            sets.append("duration_seconds=?")
            params.append(int(duration_seconds))
        if trigger_regex is not None:
            sets.append("trigger_regex=?")
            params.append(str(trigger_regex))
        if trigger_mode is not None:
            sets.append("trigger_mode=?")
            params.append(str(trigger_mode))
        if paid_message_star_count is not None:
            sets.append("paid_message_star_count=?")
            params.append(int(paid_message_star_count))
        if clear_status_message:
            sets.append("status_message_id=NULL")
        elif status_message_id is not None:
            sets.append("status_message_id=?")
            params.append(int(status_message_id))
        if clear_last_bid_message:
            sets.append("last_bid_message_id=NULL")
        elif last_bid_message_id is not None:
            sets.append("last_bid_message_id=?")
            params.append(int(last_bid_message_id))
        if clear_last_bid:
            sets.append("last_bid_user_id=NULL")
            sets.append("last_bid_username=NULL")
            sets.append("end_at_unix=NULL")
            sets.append("last_bid_message_id=NULL")
        else:
            if last_bid_user_id is not None:
                sets.append("last_bid_user_id=?")
                params.append(int(last_bid_user_id))
            if last_bid_username is not None:
                sets.append("last_bid_username=?")
                params.append(str(last_bid_username))
            if end_at_unix is not None:
                sets.append("end_at_unix=?")
                params.append(int(end_at_unix))

        if not sets:
            return

        params.append(chat_id)
        await db.execute(f"UPDATE chat_state SET {', '.join(sets)} WHERE chat_id=?", tuple(params))
        await db.commit()


async def list_running_chats() -> List[ChatState]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            SELECT chat_id, is_running, duration_seconds, trigger_regex, trigger_mode,
                   paid_message_star_count, last_bid_user_id, last_bid_username,
                   end_at_unix, status_message_id, last_bid_message_id
            FROM chat_state
            WHERE is_running=1 AND end_at_unix IS NOT NULL
            """
        )
        rows = await cur.fetchall()
        await cur.close()

    return [_row_to_state(row) for row in rows]


async def list_all_chats() -> List[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT chat_id FROM chat_state")
        rows = await cur.fetchall()
        await cur.close()
    return [row[0] for row in rows]


async def remember_chat(
    chat_id: int,
    *,
    chat_type: Optional[str] = None,
    title: Optional[str] = None,
    username: Optional[str] = None,
) -> None:
    now = int(time.time())
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO known_chats (chat_id, chat_type, title, username, last_seen_unix)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                chat_type=COALESCE(excluded.chat_type, known_chats.chat_type),
                title=COALESCE(excluded.title, known_chats.title),
                username=COALESCE(excluded.username, known_chats.username),
                last_seen_unix=excluded.last_seen_unix
            """,
            (chat_id, chat_type, title, _normalize_username(username), now),
        )
        await db.commit()


async def remember_user(
    user_id: int,
    *,
    username: Optional[str] = None,
    full_name: Optional[str] = None,
    is_bot: bool = False,
) -> None:
    now = int(time.time())
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO known_users (user_id, username, full_name, is_bot, last_seen_unix)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username=COALESCE(excluded.username, known_users.username),
                full_name=COALESCE(excluded.full_name, known_users.full_name),
                is_bot=excluded.is_bot,
                last_seen_unix=excluded.last_seen_unix
            """,
            (user_id, _normalize_username(username), full_name, 1 if is_bot else 0, now),
        )
        await db.commit()


async def list_broadcast_targets() -> List[BroadcastTarget]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            SELECT chat_id, 'chat' FROM known_chats
            WHERE chat_id < 0 OR chat_type IN ('group', 'supergroup', 'channel')
            UNION
            SELECT chat_id, 'chat' FROM chat_state
            WHERE chat_id < 0
            UNION
            SELECT user_id, 'user' FROM known_users
            WHERE is_bot=0
            UNION
            SELECT chat_id, 'user' FROM known_chats
            WHERE chat_id > 0 AND (chat_type IS NULL OR chat_type='private')
            """
        )
        rows = await cur.fetchall()
        await cur.close()

    targets: list[BroadcastTarget] = []
    seen: set[int] = set()
    for target_id, kind in rows:
        target_id = int(target_id)
        if target_id in seen:
            continue
        seen.add(target_id)
        targets.append(BroadcastTarget(target_id=target_id, kind=str(kind)))
    return targets


async def add_chat_manager(
    chat_id: int,
    *,
    user_id: Optional[int] = None,
    username: Optional[str] = None,
) -> bool:
    uname = _normalize_username(username)
    if user_id is None and not uname:
        return False
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT OR IGNORE INTO chat_managers (chat_id, user_id, username)
            VALUES (?, ?, ?)
            """,
            (chat_id, user_id, uname),
        )
        await db.commit()
    return True


async def remove_chat_manager(
    chat_id: int,
    *,
    user_id: Optional[int] = None,
    username: Optional[str] = None,
) -> bool:
    uname = _normalize_username(username)
    async with aiosqlite.connect(DB_PATH) as db:
        if user_id is not None:
            await db.execute(
                "DELETE FROM chat_managers WHERE chat_id=? AND user_id=?",
                (chat_id, user_id),
            )
        if uname:
            await db.execute(
                "DELETE FROM chat_managers WHERE chat_id=? AND username=?",
                (chat_id, uname),
            )
        await db.commit()
    return True


async def list_chat_managers(chat_id: int) -> List[tuple[Optional[int], Optional[str]]]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT user_id, username FROM chat_managers WHERE chat_id=? ORDER BY rowid",
            (chat_id,),
        )
        rows = await cur.fetchall()
        await cur.close()
    return [(row[0], row[1]) for row in rows]


async def is_chat_manager(chat_id: int, user_id: int, username: Optional[str]) -> bool:
    uname = _normalize_username(username)
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT 1 FROM chat_managers WHERE chat_id=? AND user_id=? LIMIT 1",
            (chat_id, user_id),
        )
        if await cur.fetchone():
            await cur.close()
            return True
        await cur.close()
        if uname:
            cur = await db.execute(
                "SELECT 1 FROM chat_managers WHERE chat_id=? AND username=? LIMIT 1",
                (chat_id, uname),
            )
            found = await cur.fetchone()
            await cur.close()
            if found:
                # Привяжем user_id к username для быстрых проверок дальше
                await add_chat_manager(chat_id, user_id=user_id, username=uname)
                return True
    return False
