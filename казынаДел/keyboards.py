"""Клавиатуры бота"""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config import (
    DELIVERY_TIME_SLOTS,
    ORDER_STATUSES,
    PAYMENT_METHODS,
    WORKING_HOURS_END,
)
from locales import LANGUAGES, _

# ==================== Главное меню ====================


def main_menu_keyboard(lang: str = "ru") -> InlineKeyboardMarkup:
    """Главное меню"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=_(lang, "menu_catalog"), callback_data="catalog"),
    )
    builder.row(
        InlineKeyboardButton(text=_(lang, "menu_cart"), callback_data="cart"),
    )
    builder.row(
        InlineKeyboardButton(text=_(lang, "menu_history"), callback_data="history"),
        InlineKeyboardButton(text=_(lang, "menu_profile"), callback_data="profile"),
    )
    builder.row(
        InlineKeyboardButton(text=_(lang, "menu_support"), callback_data="support"),
        InlineKeyboardButton(text=_(lang, "menu_language"), callback_data="language"),
    )
    return builder.as_markup()


def back_to_main_keyboard(lang: str = "ru") -> InlineKeyboardMarkup:
    """Кнопка возврата в главное меню"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=_(lang, "to_main_menu"), callback_data="main_menu"),
    )
    return builder.as_markup()


def language_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора языка"""
    builder = InlineKeyboardBuilder()
    for code, name in LANGUAGES.items():
        builder.row(
            InlineKeyboardButton(text=name, callback_data=f"lang_{code}"),
        )
    return builder.as_markup()


# ==================== Каталог ====================


def categories_keyboard(categories: list, lang: str = "ru") -> InlineKeyboardMarkup:
    """Клавиатура категорий"""
    builder = InlineKeyboardBuilder()
    for cat in categories:
        builder.row(
            InlineKeyboardButton(
                text=f"{cat['emoji']} {cat['name']}",
                callback_data=f"category_{cat['id']}",
            )
        )
    builder.row(
        InlineKeyboardButton(text=_(lang, "menu_cart"), callback_data="cart"),
    )
    builder.row(
        InlineKeyboardButton(text=_(lang, "back"), callback_data="main_menu"),
    )
    return builder.as_markup()


def products_keyboard(
    products: list, category_id: int, lang: str = "ru"
) -> InlineKeyboardMarkup:
    """Клавиатура товаров"""
    builder = InlineKeyboardBuilder()
    for product in products:
        builder.row(
            InlineKeyboardButton(
                text=f"🛒 {product['name']} — {product['price']:.0f} ₸",
                callback_data=f"product_{product['id']}",
            )
        )
    builder.row(
        InlineKeyboardButton(text=_(lang, "menu_cart"), callback_data="cart"),
    )
    builder.row(
        InlineKeyboardButton(
            text=_(lang, "back_to_categories"), callback_data="catalog"
        ),
    )
    return builder.as_markup()


def product_detail_keyboard(
    product_id: int, in_cart: bool = False, lang: str = "ru"
) -> InlineKeyboardMarkup:
    """Клавиатура детали товара"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=_(lang, "add_more"), callback_data=f"add_to_cart_{product_id}"
        ),
    )
    if in_cart:
        builder.row(
            InlineKeyboardButton(text=_(lang, "go_to_cart"), callback_data="cart"),
        )
    builder.row(
        InlineKeyboardButton(
            text=_(lang, "back_to_products"), callback_data="back_to_products"
        ),
    )
    return builder.as_markup()


# ==================== Корзина ====================


def cart_keyboard(cart_items: list, lang: str = "ru") -> InlineKeyboardMarkup:
    """Клавиатура корзины"""
    builder = InlineKeyboardBuilder()
    for item in cart_items:
        builder.row(
            InlineKeyboardButton(
                text=f"➖ {item['name'][:20]} ({item['quantity']} {_(lang, 'piece')})",
                callback_data=f"cart_minus_{item['id']}",
            ),
            InlineKeyboardButton(text=f"➕", callback_data=f"cart_plus_{item['id']}"),
        )
    builder.row(
        InlineKeyboardButton(text=_(lang, "clear_cart"), callback_data="clear_cart"),
    )
    builder.row(
        InlineKeyboardButton(text=_(lang, "checkout"), callback_data="checkout"),
    )
    builder.row(
        InlineKeyboardButton(
            text=_(lang, "continue_shopping"), callback_data="catalog"
        ),
    )
    builder.row(
        InlineKeyboardButton(text=_(lang, "to_main_menu"), callback_data="main_menu"),
    )
    return builder.as_markup()


def empty_cart_keyboard(lang: str = "ru") -> InlineKeyboardMarkup:
    """Клавиатура пустой корзины"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=_(lang, "continue_shopping"), callback_data="catalog"
        ),
    )
    builder.row(
        InlineKeyboardButton(text=_(lang, "to_main_menu"), callback_data="main_menu"),
    )
    return builder.as_markup()


# ==================== Оформление заказа ====================


def address_keyboard(
    has_address: bool = False, lang: str = "ru"
) -> InlineKeyboardMarkup:
    """Клавиатура выбора адреса"""
    builder = InlineKeyboardBuilder()
    if has_address:
        builder.row(
            InlineKeyboardButton(
                text=_(lang, "use_saved"), callback_data="use_saved_address"
            ),
        )
    builder.row(
        InlineKeyboardButton(
            text=_(lang, "enter_new"), callback_data="enter_new_address"
        ),
    )
    builder.row(
        InlineKeyboardButton(text=_(lang, "back"), callback_data="cart"),
    )
    return builder.as_markup()


def delivery_time_keyboard(lang: str = "ru") -> InlineKeyboardMarkup:
    """Клавиатура выбора времени доставки"""
    from datetime import datetime

    now = datetime.now()

    builder = InlineKeyboardBuilder()

    if now.hour >= WORKING_HOURS_END:
        builder.row(
            InlineKeyboardButton(text=_(lang, "too_late"), callback_data="time_late"),
        )
        builder.row(
            InlineKeyboardButton(
                text=_(lang, "tomorrow_slot", slot="08:00–10:00"),
                callback_data="time_завтра_08:00–10:00",
            ),
        )
        builder.row(
            InlineKeyboardButton(
                text=_(lang, "tomorrow_slot", slot="10:00–12:00"),
                callback_data="time_завтра_10:00–12:00",
            ),
        )
    else:
        builder.row(
            InlineKeyboardButton(text=_(lang, "asap"), callback_data="time_asap"),
        )
        for slot in DELIVERY_TIME_SLOTS:
            builder.row(
                InlineKeyboardButton(
                    text=_(lang, "time_slot", slot=slot), callback_data=f"time_{slot}"
                ),
            )

    builder.row(
        InlineKeyboardButton(text=_(lang, "back"), callback_data="checkout"),
    )
    return builder.as_markup()


def payment_keyboard(lang: str = "ru") -> InlineKeyboardMarkup:
    """Клавиатура выбора оплаты"""
    builder = InlineKeyboardBuilder()
    for key, value in PAYMENT_METHODS.items():
        builder.row(
            InlineKeyboardButton(text=value, callback_data=f"pay_{key}"),
        )
    builder.row(
        InlineKeyboardButton(text=_(lang, "back"), callback_data="checkout"),
    )
    return builder.as_markup()


def confirm_order_keyboard(lang: str = "ru") -> InlineKeyboardMarkup:
    """Клавиатура подтверждения заказа"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=_(lang, "confirm_btn"), callback_data="confirm_order"
        ),
    )
    builder.row(
        InlineKeyboardButton(text=_(lang, "change_data"), callback_data="checkout"),
    )
    builder.row(
        InlineKeyboardButton(text=_(lang, "back_to_cart"), callback_data="cart"),
    )
    return builder.as_markup()


# ==================== Профиль ====================


def profile_keyboard(lang: str = "ru") -> InlineKeyboardMarkup:
    """Клавиатура профиля"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=_(lang, "edit_address"), callback_data="edit_address"
        ),
    )
    builder.row(
        InlineKeyboardButton(text=_(lang, "edit_phone"), callback_data="edit_phone"),
    )
    builder.row(
        InlineKeyboardButton(text=_(lang, "referral"), callback_data="referral"),
    )
    builder.row(
        InlineKeyboardButton(text=_(lang, "to_main_menu"), callback_data="main_menu"),
    )
    return builder.as_markup()


# ==================== Админ панель (только русский) ====================


def admin_order_keyboard(order_id: int) -> InlineKeyboardMarkup:
    """Клавиатура управления заказом для админа"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="✅ Взять в работу", callback_data=f"admin_process_{order_id}"
        ),
        InlineKeyboardButton(
            text="❌ Отменить", callback_data=f"admin_cancel_{order_id}"
        ),
    )
    return builder.as_markup()


def admin_order_status_keyboard(
    order_id: int, current_status: str
) -> InlineKeyboardMarkup:
    """Клавиатура изменения статуса заказа"""
    builder = InlineKeyboardBuilder()

    status_flow = {
        "new": [("processing", "📦 Взять в работу"), ("cancelled", "❌ Отменить")],
        "processing": [("sent", "🚚 Отправить"), ("cancelled", "❌ Отменить")],
        "sent": [("delivered", "✅ Доставлен"), ("cancelled", "❌ Отменить")],
    }

    if current_status in status_flow:
        for status, text in status_flow[current_status]:
            builder.row(
                InlineKeyboardButton(
                    text=text, callback_data=f"admin_status_{order_id}_{status}"
                ),
            )

    builder.row(
        InlineKeyboardButton(text="📋 Все заказы", callback_data="admin_orders"),
    )
    return builder.as_markup()


def admin_main_keyboard() -> InlineKeyboardMarkup:
    """Главная клавиатура админа (только русский)"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🆕 Новые заказы", callback_data="admin_orders_new"),
    )
    builder.row(
        InlineKeyboardButton(
            text="📦 В работе", callback_data="admin_orders_processing"
        ),
    )
    builder.row(
        InlineKeyboardButton(text="🚚 Отправленные", callback_data="admin_orders_sent"),
    )
    builder.row(
        InlineKeyboardButton(text="📋 Все заказы", callback_data="admin_orders"),
    )
    builder.row(
        InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats"),
    )
    builder.row(
        InlineKeyboardButton(
            text="🛠 Управление товарами", callback_data="admin_products"
        ),
    )
    return builder.as_markup()


# ==================== Админ: управление товарами (только русский) ====================


def admin_products_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура управления товарами"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="➕ Добавить товар", callback_data="admin_add_product"
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="📝 Редактировать товар", callback_data="admin_edit_product"
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="🗑 Удалить товар", callback_data="admin_delete_product"
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="➕ Добавить категорию", callback_data="admin_add_category"
        ),
    )
    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back"),
    )
    return builder.as_markup()


def admin_categories_for_product_keyboard(categories: list) -> InlineKeyboardMarkup:
    """Выбор категории для нового товара"""
    builder = InlineKeyboardBuilder()
    for cat in categories:
        builder.row(
            InlineKeyboardButton(
                text=f"{cat['emoji']} {cat['name']}",
                callback_data=f"admin_cat_{cat['id']}",
            )
        )
    builder.row(
        InlineKeyboardButton(text="◀️ Отмена", callback_data="admin_cancel"),
    )
    return builder.as_markup()


def admin_confirm_product_keyboard() -> InlineKeyboardMarkup:
    """Подтверждение добавления товара"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Сохранить", callback_data="admin_save_product"),
    )
    builder.row(
        InlineKeyboardButton(text="🔄 Изменить", callback_data="admin_change_product"),
    )
    builder.row(
        InlineKeyboardButton(text="❌ Отмена", callback_data="admin_cancel"),
    )
    return builder.as_markup()


def admin_skip_photo_keyboard() -> InlineKeyboardMarkup:
    """Пропустить загрузку фото"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="⏭ Пропустить фото", callback_data="admin_skip_photo"
        ),
    )
    builder.row(
        InlineKeyboardButton(text="❌ Отмена", callback_data="admin_cancel"),
    )
    return builder.as_markup()
