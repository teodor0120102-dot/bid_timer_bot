"""BidTimerBot — конфигурация через переменные окружения."""

import os


# Единственная обязательная настройка для Railway — токен от @BotFather
BOT_TOKEN = os.getenv("BIDTIMER_BOT_TOKEN", "ВСТАВЬ_ТОКЕН_СЮДА")

DEFAULT_DURATION_SECONDS = int(os.getenv("BIDTIMER_DEFAULT_DURATION_SECONDS", "150"))
DEFAULT_TRIGGER_REGEX = os.getenv("BIDTIMER_DEFAULT_TRIGGER_REGEX", r"перебил")

DB_PATH = os.getenv("BIDTIMER_DB_PATH", "bid_timer.db")
PAID_STARS_CACHE_TTL = int(os.getenv("BIDTIMER_PAID_CACHE_TTL", "30"))
