"""Конфигурация — читает .env, без валидации и плясок."""

import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не задан. Скопируй .env.example в .env и впиши токен.")

ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
if not ADMIN_ID:
    raise RuntimeError("ADMIN_ID не задан.")

SUPPORT_GROUP_ID = int(os.getenv("SUPPORT_GROUP_ID", "0"))

MINIMUM_ORDER_AMOUNT = 5000
DELIVERY_FEE = 400
WORKING_HOURS_START = 9
WORKING_HOURS_END = 21
REFERRAL_REWARD = 500

DELIVERY_TIME_SLOTS = [
    "08:00–10:00", "10:00–12:00", "12:00–14:00",
    "14:00–16:00", "16:00–18:00", "18:00–20:00", "20:00–22:00",
]

PAYMENT_METHODS = {"kaspi": "💳 Перевод по Kaspi", "cash": "💵 Наличные курьеру"}

ORDER_STATUSES = {
    "new": "🆕 Новый",
    "processing": "📦 Собирается",
    "sent": "🚚 Отправлен",
    "delivered": "✅ Доставлен",
    "cancelled": "❌ Отменён",
}

DATABASE_PATH = "qazyna_delivery.db"
