"""Юнит-тесты логики перебива — без Telegram Stars и без сети."""

from __future__ import annotations

import asyncio
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


# handlers тянет aiogram — на CI/хостинге он есть; локально тесты тоже должны пройти.
import handlers
import stars


def _msg(**kwargs):
    defaults = {
        "bot": SimpleNamespace(),
        "chat": SimpleNamespace(id=-100123, type="supergroup"),
        "from_user": SimpleNamespace(id=42, is_bot=False, username="wartan", full_name="Wartan"),
        "text": "ставка",
        "caption": None,
        "sender_chat": None,
        "photo": None,
        "video": None,
        "animation": None,
        "sticker": None,
        "voice": None,
        "audio": None,
        "document": None,
        "successful_payment": None,
        "paid_message_price_changed": None,
        "paid_star_count": None,
        "paid_message_star_count": None,
        "model_extra": {},
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class PaidStarValueTests(unittest.TestCase):
    def test_reads_paid_star_count(self):
        m = _msg(paid_star_count=1)
        self.assertEqual(handlers._paid_star_value(m), 1)

    def test_reads_paid_message_star_count(self):
        m = _msg(paid_message_star_count=3)
        self.assertEqual(handlers._paid_star_value(m), 3)

    def test_reads_model_extra(self):
        m = _msg(model_extra={"paid_star_count": 2})
        self.assertEqual(handlers._paid_star_value(m), 2)

    def test_zero_is_not_paid(self):
        m = _msg(paid_star_count=0)
        self.assertIsNone(handlers._paid_star_value(m))


class UserBidMessageTests(unittest.TestCase):
    def test_text_message_ok(self):
        self.assertTrue(handlers._is_user_bid_message(_msg(text="привет")))

    def test_command_rejected(self):
        self.assertFalse(handlers._is_user_bid_message(_msg(text="/bid status")))

    def test_bot_rejected(self):
        self.assertFalse(
            handlers._is_user_bid_message(
                _msg(from_user=SimpleNamespace(id=1, is_bot=True, username="bot"))
            )
        )

    def test_service_message_rejected(self):
        self.assertFalse(handlers._is_user_bid_message(_msg(left_chat_member=[1])))

    def test_price_change_rejected(self):
        self.assertFalse(
            handlers._is_user_bid_message(_msg(paid_message_price_changed=SimpleNamespace()))
        )


class PaidBidAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_api_field_counts_as_bid(self):
        m = _msg(paid_star_count=1, text="хуй")
        self.assertTrue(await handlers._is_paid_bid(m))

    async def test_heuristic_when_stars_gated(self):
        m = _msg(text="перебил")
        with patch.object(stars, "fetch_paid_stars", AsyncMock(return_value=1)):
            self.assertTrue(await handlers._is_paid_bid(m))

    async def test_no_bid_without_stars_and_no_field(self):
        m = _msg(text="обычное")
        with patch.object(stars, "fetch_paid_stars", AsyncMock(return_value=None)):
            self.assertFalse(await handlers._is_paid_bid(m))

    async def test_no_bid_when_stars_disabled(self):
        m = _msg(text="обычное")
        with patch.object(stars, "fetch_paid_stars", AsyncMock(return_value=0)):
            self.assertFalse(await handlers._is_paid_bid(m))


class RegexBidTests(unittest.TestCase):
    def test_regex_match(self):
        state = SimpleNamespace(trigger_regex=r"перебил")
        m = _msg(text="я перебил!")
        self.assertTrue(handlers._is_regex_bid(m, state))

    def test_regex_no_match(self):
        state = SimpleNamespace(trigger_regex=r"перебил")
        m = _msg(text="просто текст")
        self.assertFalse(handlers._is_regex_bid(m, state))


class StarsHelperTests(unittest.TestCase):
    def test_stars_enabled(self):
        self.assertTrue(stars.stars_enabled(1))
        self.assertFalse(stars.stars_enabled(0))
        self.assertFalse(stars.stars_enabled(None))

    def test_extract_from_chat_object(self):
        chat = SimpleNamespace(paid_message_star_count=5, model_extra={})
        self.assertEqual(stars._extract_paid_stars(chat), 5)


class SchedulerSmokeTests(unittest.IsolatedAsyncioTestCase):
    async def test_arm_timer_schedules_task(self):
        import scheduler as sched

        chat_id = -999001
        sched.timers.cancel(chat_id)

        bot = SimpleNamespace()
        end_at = 2_000_000_000

        with patch.object(sched.db, "get_chat_state", AsyncMock(return_value=SimpleNamespace(
            is_running=True,
            end_at_unix=end_at,
            duration_seconds=120,
            status_message_id=1,
            last_bid_user_id=None,
            last_bid_username=None,
        ))):
            await sched.arm_timer(bot, chat_id)

        self.assertTrue(sched.timers.is_active(chat_id))
        sched.timers.cancel(chat_id)


if __name__ == "__main__":
    result = unittest.main(verbosity=2, exit=False)
    sys.exit(0 if result.result.wasSuccessful() else 1)
