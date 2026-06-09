"""Клавиатуры."""

from datetime import datetime
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import DELIVERY_TIME_SLOTS, PAYMENT_METHODS, WORKING_HOURS_END
from locales import LANGUAGES, t


# ==================== Главное меню ====================


def main_menu_keyboard(lang="ru"):
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text=t(lang, "menu_catalog"), callback_data="catalog"))
    b.row(InlineKeyboardButton(text=t(lang, "menu_cart"), callback_data="cart"))
    b.row(
        InlineKeyboardButton(text=t(lang, "menu_history"), callback_data="history"),
        InlineKeyboardButton(text=t(lang, "menu_profile"), callback_data="profile"),
    )
    b.row(
        InlineKeyboardButton(text=t(lang, "menu_support"), callback_data="support"),
        InlineKeyboardButton(text=t(lang, "menu_language"), callback_data="language"),
    )
    return b.as_markup()


def back_to_main_keyboard(lang="ru"):
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text=t(lang, "to_main_menu"), callback_data="main_menu"))
    return b.as_markup()


def language_keyboard():
    b = InlineKeyboardBuilder()
    for code, name in LANGUAGES.items():
        b.row(InlineKeyboardButton(text=name, callback_data=f"lang_{code}"))
    return b.as_markup()


# ==================== Каталог ====================


def categories_keyboard(categories, lang="ru"):
    b = InlineKeyboardBuilder()
    for cat in categories:
        b.row(InlineKeyboardButton(
            text=f"{cat['emoji']} {cat['name']}",
            callback_data=f"category_{cat['id']}",
        ))
    b.row(InlineKeyboardButton(text=t(lang, "menu_cart"), callback_data="cart"))
    b.row(InlineKeyboardButton(text=t(lang, "back"), callback_data="main_menu"))
    return b.as_markup()


def products_keyboard(products, category_id, lang="ru"):
    b = InlineKeyboardBuilder()
    for p in products:
        b.row(InlineKeyboardButton(
            text=f"🛒 {p['name']} — {p['price']:.0f} ₸",
            callback_data=f"product_{p['id']}",
        ))
    b.row(InlineKeyboardButton(text=t(lang, "menu_cart"), callback_data="cart"))
    b.row(InlineKeyboardButton(text=t(lang, "back_to_categories"), callback_data="catalog"))
    return b.as_markup()


def product_detail_keyboard(product_id, in_cart=False, lang="ru"):
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(
        text=t(lang, "add_more"), callback_data=f"add_to_cart_{product_id}"
    ))
    if in_cart:
        b.row(InlineKeyboardButton(text=t(lang, "go_to_cart"), callback_data="cart"))
    b.row(InlineKeyboardButton(text=t(lang, "back_to_products"), callback_data="back_to_products"))
    return b.as_markup()


# ==================== Корзина ====================


def cart_keyboard(items, lang="ru"):
    b = InlineKeyboardBuilder()
    for item in items:
        b.row(
            InlineKeyboardButton(
                text=f"➖ {item['name'][:20]} ({item['quantity']})",
                callback_data=f"cart_minus_{item['id']}",
            ),
            InlineKeyboardButton(text="➕", callback_data=f"cart_plus_{item['id']}"),
        )
    b.row(InlineKeyboardButton(text=t(lang, "clear_cart"), callback_data="clear_cart"))
    b.row(InlineKeyboardButton(text=t(lang, "checkout"), callback_data="checkout"))
    b.row(InlineKeyboardButton(text=t(lang, "continue_shopping"), callback_data="catalog"))
    b.row(InlineKeyboardButton(text=t(lang, "to_main_menu"), callback_data="main_menu"))
    return b.as_markup()


def empty_cart_keyboard(lang="ru"):
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text=t(lang, "continue_shopping"), callback_data="catalog"))
    b.row(InlineKeyboardButton(text=t(lang, "to_main_menu"), callback_data="main_menu"))
    return b.as_markup()


# ==================== Оформление заказа ====================


def address_keyboard(has_address=False, lang="ru"):
    b = InlineKeyboardBuilder()
    if has_address:
        b.row(InlineKeyboardButton(text=t(lang, "use_saved"), callback_data="use_saved_address"))
    b.row(InlineKeyboardButton(text=t(lang, "enter_new"), callback_data="enter_new_address"))
    b.row(InlineKeyboardButton(text=t(lang, "back"), callback_data="cart"))
    return b.as_markup()


def delivery_time_keyboard(lang="ru"):
    b = InlineKeyboardBuilder()
    now = datetime.now()
    if now.hour >= WORKING_HOURS_END:
        b.row(InlineKeyboardButton(text=t(lang, "too_late"), callback_data="time_late"))
        b.row(InlineKeyboardButton(
            text=t(lang, "tomorrow_slot", slot="08:00–10:00"),
            callback_data="time_завтра_08:00–10:00",
        ))
        b.row(InlineKeyboardButton(
            text=t(lang, "tomorrow_slot", slot="10:00–12:00"),
            callback_data="time_завтра_10:00–12:00",
        ))
    else:
        b.row(InlineKeyboardButton(text=t(lang, "asap"), callback_data="time_asap"))
        for slot in DELIVERY_TIME_SLOTS:
            b.row(InlineKeyboardButton(
                text=t(lang, "time_slot", slot=slot), callback_data=f"time_{slot}"
            ))
    b.row(InlineKeyboardButton(text=t(lang, "back"), callback_data="checkout"))
    return b.as_markup()


def payment_keyboard(lang="ru"):
    b = InlineKeyboardBuilder()
    for key, value in PAYMENT_METHODS.items():
        b.row(InlineKeyboardButton(text=value, callback_data=f"pay_{key}"))
    b.row(InlineKeyboardButton(text=t(lang, "back"), callback_data="checkout"))
    return b.as_markup()


def confirm_order_keyboard(lang="ru"):
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text=t(lang, "confirm_btn"), callback_data="confirm_order"))
    b.row(InlineKeyboardButton(text=t(lang, "change_data"), callback_data="checkout"))
    b.row(InlineKeyboardButton(text=t(lang, "back_to_cart"), callback_data="cart"))
    return b.as_markup()


# ==================== Профиль ====================


def profile_keyboard(lang="ru"):
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text=t(lang, "edit_address"), callback_data="edit_address"))
    b.row(InlineKeyboardButton(text=t(lang, "edit_phone"), callback_data="edit_phone"))
    b.row(InlineKeyboardButton(text=t(lang, "referral"), callback_data="referral"))
    b.row(InlineKeyboardButton(text=t(lang, "to_main_menu"), callback_data="main_menu"))
    return b.as_markup()


# ==================== Админ ====================


def admin_main_keyboard():
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🆕 Новые заказы", callback_data="admin_orders_new"))
    b.row(InlineKeyboardButton(text="📦 В работе", callback_data="admin_orders_processing"))
    b.row(InlineKeyboardButton(text="🚚 Отправленные", callback_data="admin_orders_sent"))
    b.row(InlineKeyboardButton(text="📋 Все заказы", callback_data="admin_orders"))
    b.row(InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats"))
    b.row(InlineKeyboardButton(text="🛠 Управление товарами", callback_data="admin_products"))
    return b.as_markup()


def admin_order_status_keyboard(order_id, current_status):
    b = InlineKeyboardBuilder()
    flow = {
        "new": [("processing", "📦 Взять в работу"), ("cancelled", "❌ Отменить")],
        "processing": [("sent", "🚚 Отправить"), ("cancelled", "❌ Отменить")],
        "sent": [("delivered", "✅ Доставлен"), ("cancelled", "❌ Отменить")],
    }
    if current_status in flow:
        for status, text in flow[current_status]:
            b.row(InlineKeyboardButton(
                text=text, callback_data=f"admin_status_{order_id}_{status}"
            ))
    b.row(InlineKeyboardButton(text="📋 Все заказы", callback_data="admin_orders"))
    return b.as_markup()


def admin_products_keyboard():
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="➕ Добавить товар", callback_data="admin_add_product"))
    b.row(InlineKeyboardButton(text="📝 Редактировать товар", callback_data="admin_edit_product"))
    b.row(InlineKeyboardButton(text="🗑 Удалить товар", callback_data="admin_delete_product"))
    b.row(InlineKeyboardButton(text="➕ Добавить категорию", callback_data="admin_add_category"))
    b.row(InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back"))
    return b.as_markup()


def admin_categories_for_product_keyboard(categories):
    b = InlineKeyboardBuilder()
    for cat in categories:
        b.row(InlineKeyboardButton(
            text=f"{cat['emoji']} {cat['name']}",
            callback_data=f"admin_cat_{cat['id']}",
        ))
    b.row(InlineKeyboardButton(text="◀️ Отмена", callback_data="admin_cancel"))
    return b.as_markup()


def admin_confirm_product_keyboard():
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="✅ Сохранить", callback_data="admin_save_product"))
    b.row(InlineKeyboardButton(text="🔄 Изменить", callback_data="admin_change_product"))
    b.row(InlineKeyboardButton(text="❌ Отмена", callback_data="admin_cancel"))
    return b.as_markup()


def admin_skip_photo_keyboard():
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="⏭ Пропустить фото", callback_data="admin_skip_photo"))
    b.row(InlineKeyboardButton(text="❌ Отмена", callback_data="admin_cancel"))
    return b.as_markup()


def admin_cancel_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_cancel")]
    ])


def admin_skip_desc_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭ Пропустить", callback_data="admin_skip_desc")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_cancel")],
    ])
