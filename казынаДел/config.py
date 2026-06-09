"""Конфигурация бота"""

import os

from dotenv import load_dotenv

load_dotenv()

# Telegram Bot Token
BOT_TOKEN = os.getenv("BOT_TOKEN", "8740191163:AAFhfQ0ooixwGDdwO1pY_vHPPIUhNyNXUok")

# ID администратора (владелицы магазина)
ADMIN_ID = int(os.getenv("ADMIN_ID", 6431458502))

# ID группы поддержки (куда пересылать сообщения)
SUPPORT_GROUP_ID = int(os.getenv("SUPPORT_GROUP_ID", 0))

# Настройки доставки
MINIMUM_ORDER_AMOUNT = 5000
DELIVERY_FEE = 400

# График работы
WORKING_HOURS_START = 9
WORKING_HOURS_END = 21

# Реферальная программа
REFERRAL_REWARD = 500

DELIVERY_TIME_SLOTS = [
    "08:00–10:00",
    "10:00–12:00",
    "12:00–14:00",
    "14:00–16:00",
    "16:00–18:00",
    "18:00–20:00",
    "20:00–22:00",
]

PAYMENT_METHODS = {"kaspi": "💳 Перевод по Kaspi", "cash": "💵 Наличные курьеру"}

ORDER_STATUSES = {
    "new": "🆕 Новый",
    "processing": "📦 Собирается",
    "sent": "🚚 Отправлен",
    "delivered": "✅ Доставлен",
    "cancelled": "❌ Отменён",
}
