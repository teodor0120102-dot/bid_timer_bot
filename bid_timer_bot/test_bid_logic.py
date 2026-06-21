"""Юнит-тесты логики перебива — без Telegram Stars и без сети."""

from __future__ import annotations

import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import bid
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
        self.assertEqual(bid._paid_star_value(m), 1)

    def test_reads_paid_message_star_count(self):
        m = _msg(paid_message_star_count=3)
        self.assertEqual(bid._paid_star_value(m), 3)

    def test_reads_model_extra(self):
        m = _msg(model_extra={"paid_star_count": 2})
        self.assertEqual(bid._paid_star_value(m), 2)

    def test_zero_is_not_paid(self):
        m = _msg(paid_star_count=0)
        self.assertIsNone(bid._paid_star_value(m))


class PaidBidTests(unittest.TestCase):
    def test_api_field_counts_as_bid(self):
        m = _msg(paid_star_count=1, text="ставка")
        self.assertTrue(bid._is_paid_bid(m))

    def test_no_heuristic_without_paid_field(self):
        m = _msg(text="перебил")
        self.assertFalse(bid._is_paid_bid(m))

    def test_no_bid_without_stars_and_no_field(self):
        m = _msg(text="обычное")
        self.assertFalse(bid._is_paid_bid(m))


class RegexBidTests(unittest.TestCase):
    def test_regex_match(self):
        state = SimpleNamespace(trigger_regex=r"перебил")
        m = _msg(text="я перебил!")
        self.assertTrue(bid._is_regex_bid(m, state))

    def test_regex_no_match(self):
        state = SimpleNamespace(trigger_regex=r"перебил")
        m = _msg(text="просто текст")
        self.assertFalse(bid._is_regex_bid(m, state))


class BidderExemptTests(unittest.IsolatedAsyncioTestCase):
    async def test_staff_exempt(self):
        m = _msg()
        with patch("bid.permissions.is_chat_staff", AsyncMock(return_value=True)):
            self.assertTrue(await bid._bidder_exempt(m, m.from_user))

    async def test_regular_user_not_exempt(self):
        m = _msg()
        with patch("bid.permissions.is_chat_staff", AsyncMock(return_value=False)):
            self.assertFalse(await bid._bidder_exempt(m, m.from_user))


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
            last_bid_message_id=None,
        ))):
            await sched.arm_timer(bot, chat_id)

        self.assertTrue(sched.timers.is_active(chat_id))
        sched.timers.cancel(chat_id)

    def test_tick_intervals(self):
        import scheduler as sched

        self.assertEqual(sched._tick_interval(5), 1)
        self.assertEqual(sched._tick_interval(20), 2)
        self.assertEqual(sched._tick_interval(90), 5)
        self.assertEqual(sched._tick_interval(200), 10)


if __name__ == "__main__":
    result = unittest.main(verbosity=2, exit=False)
    sys.exit(0 if result.result.wasSuccessful() else 1)
