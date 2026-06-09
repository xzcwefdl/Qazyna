"""Обработчики сообщений и callback"""

import logging
import re

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config import (
    ADMIN_ID,
    DELIVERY_FEE,
    MINIMUM_ORDER_AMOUNT,
    ORDER_STATUSES,
    PAYMENT_METHODS,
    REFERRAL_REWARD,
    SUPPORT_GROUP_ID,
    WORKING_HOURS_END,
    WORKING_HOURS_START,
)
from database import (
    add_category,
    add_order_items,
    add_product,
    add_to_cart,
    apply_referral,
    cancel_order_user,
    check_stock,
    clear_cart,
    close_db,
    create_order,
    get_all_orders,
    get_cart_items,
    get_cart_total,
    get_categories,
    get_or_create_user,
    get_order,
    get_order_items,
    get_product,
    get_products_by_category,
    get_stats_day,
    get_stats_week,
    get_support_message_by_support_id,
    get_top_products,
    get_user_by_referral_code,
    get_user_by_telegram_id,
    get_user_language,
    get_user_orders,
    remove_from_cart,
    reorder,
    save_support_message,
    update_cart_quantity,
    update_order_status,
    update_user_language,
    update_user_profile,
    use_referral_balance,
    validate_address,
    validate_phone,
    validate_price,
)
from keyboards import (
    address_keyboard,
    admin_categories_for_product_keyboard,
    admin_confirm_product_keyboard,
    admin_main_keyboard,
    admin_order_keyboard,
    admin_order_status_keyboard,
    admin_products_keyboard,
    admin_skip_photo_keyboard,
    back_to_main_keyboard,
    cart_keyboard,
    categories_keyboard,
    confirm_order_keyboard,
    delivery_time_keyboard,
    empty_cart_keyboard,
    language_keyboard,
    main_menu_keyboard,
    payment_keyboard,
    product_detail_keyboard,
    products_keyboard,
    profile_keyboard,
)
from locales import _
from states import AdminProductState, CheckoutState, ProfileState, SupportState

router = Router()
logger = logging.getLogger(__name__)


# ==================== Унифицированный парсинг callback ====================


def parse_callback(data: str) -> tuple:
    """Парсинг callback_data в (action, *args)"""
    special_prefixes = [
        "add_to_cart",
        "cart_plus",
        "cart_minus",
        "admin_view",
        "admin_process",
        "admin_cancel",
        "admin_status",
        "admin_orders",
        "admin_cat",
        "user_cancel",
        "reorder",
    ]
    for prefix in special_prefixes:
        if data.startswith(prefix + "_"):
            rest = data[len(prefix) + 1 :]
            return prefix, rest.split("_") if rest else []
    parts = data.split("_")
    return parts[0], parts[1:]


# ==================== Вспомогательные функции ====================


def is_working_hours() -> bool:
    """Проверка графика работы"""
    from datetime import datetime

    now = datetime.now()
    return WORKING_HOURS_START <= now.hour < WORKING_HOURS_END


def calculate_delivery(total: float) -> tuple:
    """Рассчитать стоимость доставки. Returns: (final_total, delivery_fee, type)"""
    if total >= MINIMUM_ORDER_AMOUNT:
        return total, 0, "free"
    return total + DELIVERY_FEE, DELIVERY_FEE, "paid"


def get_next_delivery_time() -> str:
    """Ближайшее доступное время доставки"""
    from datetime import datetime

    now = datetime.now()
    if now.hour >= 23:
        return "08:00–10:00"
    slots = [8, 10, 12, 14, 16, 18, 20]
    for s in slots:
        if now.hour < s:
            return f"{s:02d}:00–{s + 2:02d}:00"
    return "08:00–10:00"


def format_cart_text(cart_items: list, total: float, lang: str) -> str:
    """Форматирование текста корзины"""
    if not cart_items:
        return _(lang, "cart_empty")
    text = _(lang, "cart") + "\n\n"
    for item in cart_items:
        item_total = item["quantity"] * item["price"]
        text += (
            _(
                lang,
                "cart_item",
                name=item["name"],
                qty=item["quantity"],
                price=item["price"],
                total=item_total,
            )
            + "\n"
        )
    final_total, fee, dtype = calculate_delivery(total)
    text += "\n" + _(lang, "cart_total", total=total)
    if dtype == "paid":
        text += "\n" + _(lang, "delivery_fee", fee=fee, min=MINIMUM_ORDER_AMOUNT)
        text += "\n" + _(lang, "total_with_delivery", total=final_total)
    else:
        text += "\n" + _(lang, "free_delivery", min=MINIMUM_ORDER_AMOUNT)
        text += "\n" + _(lang, "total_free_delivery", total=final_total)
    return text


def format_order_text(order: dict, items: list, lang: str) -> str:
    """Форматирование текста заказа для пользователя"""
    status = ORDER_STATUSES.get(order["status"], order["status"])
    text = f"📦 <b>Заказ #{order['id']}</b>\n"
    text += f"Статус: {status}\n"
    text += f"Дата: {order['created_at']}\n\n"
    text += _(lang, "confirm_items") + "\n"
    for item in items:
        it = item["quantity"] * item["price_at_moment"]
        text += (
            _(
                lang,
                "cart_item",
                name=item["name"],
                qty=item["quantity"],
                price=item["price_at_moment"],
                total=it,
            )
            + "\n"
        )
    text += f"\n💰 <b>Итого к оплате: {order['total_amount']:.0f} ₸</b>\n"
    text += _(lang, "confirm_address", address=order["address"]) + "\n"
    text += _(lang, "confirm_time", time=order["delivery_time"]) + "\n"
    text += (
        _(
            lang,
            "confirm_payment",
            payment=PAYMENT_METHODS.get(
                order["payment_method"], order["payment_method"]
            ),
        )
        + "\n"
    )
    if order["comment"]:
        text += _(lang, "confirm_comment", comment=order["comment"]) + "\n"
    return text


def format_admin_order_text(order: dict, items: list, user_name: str) -> str:
    """Форматирование заказа для админа (только русский)."""
    status = ORDER_STATUSES.get(order["status"], order["status"])
    status_emoji = status.split()[0] if status else "📦"
    text = f"{status_emoji} <b>Заказ #{order['id']}</b>\n"
    text += f"📊 <b>Статус:</b> {status}\n\n"
    text += f"👤 <b>Клиент:</b> {user_name}\n"
    text += f"📍 <b>Адрес:</b> {order['address']}\n"
    text += f"📞 <b>Телефон:</b> <code>{order['phone']}</code>\n"
    text += f"💰 <b>Сумма к оплате:</b> {order['total_amount']:.0f} ₸\n"
    text += f"⏰ <b>Время:</b> {order['delivery_time']}\n"
    text += f"💳 <b>Оплата:</b> {PAYMENT_METHODS.get(order['payment_method'], order['payment_method'])}\n"
    if order["comment"]:
        text += f"📝 <b>Комментарий:</b> {order['comment']}\n"
    text += f"\n📋 <b>Товары:</b>\n"
    for item in items:
        text += f"• {item['name']} — {item['quantity']} шт.\n"
    return text


async def _refresh_cart_view(callback: CallbackQuery, lang: str):
    """Обновить отображение корзины (DRY)"""
    user = await get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer(_(lang, "error_user_not_found"), show_alert=True)
        return
    cart_items = await get_cart_items(user["id"])
    total = await get_cart_total(user["id"])
    if not cart_items:
        await callback.message.edit_text(
            _(lang, "cart_empty"),
            reply_markup=empty_cart_keyboard(lang),
            parse_mode="HTML",
        )
    else:
        await callback.message.edit_text(
            format_cart_text(cart_items, total, lang),
            reply_markup=cart_keyboard(cart_items, lang),
            parse_mode="HTML",
        )


# ==================== Язык и старт ====================


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext, command: CommandObject):
    """/start — проверяем сохранённые настройки и реферальный код"""
    user = await get_or_create_user(
        telegram_id=message.from_user.id,
        first_name=message.from_user.first_name,
        last_name=message.from_user.last_name,
    )
    # Реферальная программа
    if command.args and command.args.startswith("ref"):
        code = command.args
        referrer = await get_user_by_referral_code(code)
        if referrer and referrer["id"] != user["id"] and not user.get("referred_by"):
            await apply_referral(user["id"], code)
            try:
                await message.bot.send_message(
                    referrer["telegram_id"],
                    f"🎉 У вас новый реферал! +{REFERRAL_REWARD} ₸ на бонусный счёт.",
                )
            except Exception:
                pass
            await message.answer(
                f"🎉 Вы получили {REFERRAL_REWARD} ₸ на бонусный счёт за регистрацию по приглашению!"
            )
    await state.update_data(last_category_id=None)
    if user.get("language"):
        lang = user["language"]
        await message.answer(
            _(lang, "welcome"), reply_markup=main_menu_keyboard(lang), parse_mode="HTML"
        )
        return
    await message.answer(
        _("ru", "choose_language"), reply_markup=language_keyboard(), parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("lang_"))
async def process_language(callback: CallbackQuery):
    """Выбор языка"""
    action, args = parse_callback(callback.data)
    lang = args[0]
    await update_user_language(callback.from_user.id, lang)
    await callback.message.edit_text(_(lang, "language_changed"), parse_mode="HTML")
    await callback.message.answer(
        _(lang, "welcome"), reply_markup=main_menu_keyboard(lang), parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "language")
async def process_change_language(callback: CallbackQuery):
    """Сменить язык"""
    await callback.message.edit_text(
        _("ru", "choose_language"), reply_markup=language_keyboard(), parse_mode="HTML"
    )
    await callback.answer()


# ==================== Главное меню ====================


@router.callback_query(F.data == "main_menu")
async def process_main_menu(callback: CallbackQuery, state: FSMContext):
    """Возврат в главное меню"""
    lang = await get_user_language(callback.from_user.id)
    await state.update_data(last_category_id=None)
    await callback.message.edit_text(
        _(lang, "main_menu"), reply_markup=main_menu_keyboard(lang), parse_mode="HTML"
    )
    await callback.answer()


# ==================== Каталог ====================


@router.callback_query(F.data == "catalog")
async def process_catalog(callback: CallbackQuery, state: FSMContext):
    """Показать категории"""
    lang = await get_user_language(callback.from_user.id)
    await state.update_data(last_category_id=None)
    categories = await get_categories()
    await callback.message.edit_text(
        _(lang, "catalog"),
        reply_markup=categories_keyboard(categories, lang),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("category_"))
async def process_category(callback: CallbackQuery, state: FSMContext):
    """Показать товары категории"""
    lang = await get_user_language(callback.from_user.id)
    action, args = parse_callback(callback.data)
    category_id = int(args[0])
    await state.update_data(last_category_id=category_id)
    products = await get_products_by_category(category_id)
    if not products:
        await callback.answer(_(lang, "error_category_empty"), show_alert=True)
        return
    await callback.message.edit_text(
        _(lang, "choose_product"),
        reply_markup=products_keyboard(products, category_id, lang),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("product_"))
async def process_product(callback: CallbackQuery, state: FSMContext):
    """Показать детали товара (с фото если есть)"""
    lang = await get_user_language(callback.from_user.id)
    action, args = parse_callback(callback.data)
    product_id = int(args[0])
    product = await get_product(product_id)
    if not product:
        await callback.answer(_(lang, "error_product_not_found"), show_alert=True)
        return
    user = await get_user_by_telegram_id(callback.from_user.id)
    cart_items = await get_cart_items(user["id"]) if user else []
    in_cart = any(item["product_id"] == product_id for item in cart_items)
    text = _(
        lang, "product_detail", emoji="", name=product["name"], price=product["price"]
    )
    if product["description"]:
        text += "\n" + _(lang, "description", desc=product["description"])
    kb = product_detail_keyboard(product_id, in_cart, lang)
    if product.get("photo_file_id"):
        try:
            await callback.message.delete()
            await callback.message.answer_photo(
                photo=product["photo_file_id"],
                caption=text,
                reply_markup=kb,
                parse_mode="HTML",
            )
        except Exception as e:
            logger.error(f"Ошибка отправки фото товара: {e}")
            await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    else:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "back_to_products")
async def process_back_to_products(callback: CallbackQuery, state: FSMContext):
    """Вернуться к товарам последней категории"""
    lang = await get_user_language(callback.from_user.id)
    data = await state.get_data()
    category_id = data.get("last_category_id")
    if category_id:
        products = await get_products_by_category(category_id)
        if products:
            await callback.message.edit_text(
                _(lang, "choose_product"),
                reply_markup=products_keyboard(products, category_id, lang),
                parse_mode="HTML",
            )
            await callback.answer()
            return
    categories = await get_categories()
    await callback.message.edit_text(
        _(lang, "catalog"),
        reply_markup=categories_keyboard(categories, lang),
        parse_mode="HTML",
    )
    await callback.answer()


# ==================== Корзина ====================


@router.callback_query(F.data.startswith("add_to_cart_"))
async def process_add_to_cart(callback: CallbackQuery, state: FSMContext):
    """Добавить товар в корзину"""
    lang = await get_user_language(callback.from_user.id)
    action, args = parse_callback(callback.data)
    product_id = int(args[0])
    user = await get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer(_(lang, "error_user_not_found"), show_alert=True)
        return
    ok = await add_to_cart(user["id"], product_id, 1)
    if not ok:
        await callback.answer("❌ Недостаточно на складе!", show_alert=True)
        return
    total = await get_cart_total(user["id"])
    await callback.answer(_(lang, "added_to_cart"))
    product = await get_product(product_id)
    text = _(
        lang, "product_detail", emoji="", name=product["name"], price=product["price"]
    )
    text += "\n" + _(lang, "added_to_cart") + "\n"
    text += _(lang, "in_cart_total", total=total)
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=_(lang, "go_to_cart"), callback_data="cart"))
    builder.row(
        InlineKeyboardButton(
            text=_(lang, "add_more"), callback_data=f"add_to_cart_{product_id}"
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=_(lang, "back_to_products"), callback_data="back_to_products"
        )
    )
    await callback.message.edit_text(
        text, reply_markup=builder.as_markup(), parse_mode="HTML"
    )


@router.callback_query(F.data == "cart")
async def process_cart(callback: CallbackQuery):
    """Показать корзину"""
    lang = await get_user_language(callback.from_user.id)
    await _refresh_cart_view(callback, lang)
    await callback.answer()


@router.callback_query(F.data.startswith("cart_plus_"))
async def process_cart_plus(callback: CallbackQuery):
    """Увеличить количество"""
    lang = await get_user_language(callback.from_user.id)
    action, args = parse_callback(callback.data)
    cart_item_id = int(args[0])
    user = await get_user_by_telegram_id(callback.from_user.id)
    cart_items = await get_cart_items(user["id"])
    for item in cart_items:
        if item["id"] == cart_item_id:
            await update_cart_quantity(cart_item_id, item["quantity"] + 1)
            break
    await _refresh_cart_view(callback, lang)
    await callback.answer()


@router.callback_query(F.data.startswith("cart_minus_"))
async def process_cart_minus(callback: CallbackQuery):
    """Уменьшить количество"""
    lang = await get_user_language(callback.from_user.id)
    action, args = parse_callback(callback.data)
    cart_item_id = int(args[0])
    user = await get_user_by_telegram_id(callback.from_user.id)
    cart_items = await get_cart_items(user["id"])
    for item in cart_items:
        if item["id"] == cart_item_id:
            await update_cart_quantity(cart_item_id, item["quantity"] - 1)
            break
    await _refresh_cart_view(callback, lang)
    await callback.answer()


@router.callback_query(F.data == "clear_cart")
async def process_clear_cart(callback: CallbackQuery):
    """Очистить корзину"""
    lang = await get_user_language(callback.from_user.id)
    user = await get_user_by_telegram_id(callback.from_user.id)
    await clear_cart(user["id"])
    await callback.message.edit_text(
        _(lang, "cart_cleared"),
        reply_markup=empty_cart_keyboard(lang),
        parse_mode="HTML",
    )
    await callback.answer(_(lang, "cart_cleared"))


# ==================== Оформление заказа ====================


@router.callback_query(F.data == "checkout")
async def process_checkout(callback: CallbackQuery, state: FSMContext):
    """Начало оформления заказа"""
    lang = await get_user_language(callback.from_user.id)

    # Автопауза: проверка графика работы
    if not is_working_hours():
        await callback.message.edit_text(
            _(lang, "closed", start=WORKING_HOURS_START, end=WORKING_HOURS_END),
            reply_markup=back_to_main_keyboard(lang),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    user = await get_user_by_telegram_id(callback.from_user.id)
    cart_items = await get_cart_items(user["id"])
    if not cart_items:
        await callback.answer(_(lang, "error_empty_cart"), show_alert=True)
        return
    total = await get_cart_total(user["id"])
    final_total, fee, dtype = calculate_delivery(total)
    await state.update_data(
        user_id=user["id"],
        phone=user["phone"],
        address=user["address"],
        cart_total=total,
        delivery_fee=fee,
    )
    if user["address"]:
        await callback.message.edit_text(
            _(lang, "address", address=user["address"]),
            reply_markup=address_keyboard(has_address=True, lang=lang),
            parse_mode="HTML",
        )
    else:
        await callback.message.edit_text(
            _(lang, "enter_address"),
            reply_markup=address_keyboard(has_address=False, lang=lang),
            parse_mode="HTML",
        )
        await state.set_state(CheckoutState.waiting_address)
    await callback.answer()


@router.callback_query(F.data == "use_saved_address")
async def process_use_saved_address(callback: CallbackQuery, state: FSMContext):
    """Использовать сохраненный адрес"""
    lang = await get_user_language(callback.from_user.id)
    data = await state.get_data()
    address = data.get("address")
    await state.update_data(delivery_address=address)
    phone = data.get("phone")
    if phone:
        await state.update_data(delivery_phone=phone)
        await callback.message.edit_text(
            _(lang, "delivery_time"),
            reply_markup=delivery_time_keyboard(lang),
            parse_mode="HTML",
        )
        await state.set_state(CheckoutState.waiting_delivery_time)
    else:
        await callback.message.edit_text(_(lang, "phone"), parse_mode="HTML")
        await state.set_state(CheckoutState.waiting_phone)
    await callback.answer()


@router.callback_query(F.data == "enter_new_address")
async def process_enter_new_address(callback: CallbackQuery, state: FSMContext):
    """Ввести новый адрес"""
    lang = await get_user_language(callback.from_user.id)
    await callback.message.edit_text(_(lang, "enter_address"), parse_mode="HTML")
    await state.set_state(CheckoutState.waiting_address)
    await callback.answer()


@router.message(CheckoutState.waiting_address)
async def process_address_input(message: Message, state: FSMContext):
    """Обработка ввода адреса с валидацией"""
    lang = await get_user_language(message.from_user.id)
    address = message.text.strip()
    if not validate_address(address):
        await message.answer(
            "❌ Адрес слишком короткий (минимум 5 символов)", parse_mode="HTML"
        )
        return
    await state.update_data(delivery_address=address)
    data = await state.get_data()
    user_id = data["user_id"]
    await update_user_profile(user_id, address=address)
    phone = data.get("phone")
    if phone:
        await state.update_data(delivery_phone=phone)
        await message.answer(
            _(lang, "delivery_time"),
            reply_markup=delivery_time_keyboard(lang),
            parse_mode="HTML",
        )
        await state.set_state(CheckoutState.waiting_delivery_time)
    else:
        await message.answer(_(lang, "phone"), parse_mode="HTML")
        await state.set_state(CheckoutState.waiting_phone)


@router.message(CheckoutState.waiting_phone)
async def process_phone_input(message: Message, state: FSMContext):
    """Обработка ввода телефона с валидацией"""
    lang = await get_user_language(message.from_user.id)
    phone = message.text.strip()
    if not validate_phone(phone):
        await message.answer(
            "❌ Введите номер телефона (минимум 10 цифр).\nПримеры: +7 707 123 45 67, 87071234567, 7071234567",
            parse_mode="HTML",
        )
        return
    await state.update_data(delivery_phone=phone)
    data = await state.get_data()
    user_id = data["user_id"]
    await update_user_profile(user_id, phone=phone)
    await message.answer(
        _(lang, "delivery_time"),
        reply_markup=delivery_time_keyboard(lang),
        parse_mode="HTML",
    )
    await state.set_state(CheckoutState.waiting_delivery_time)


@router.callback_query(F.data.startswith("time_"), CheckoutState.waiting_delivery_time)
async def process_time_selection(callback: CallbackQuery, state: FSMContext):
    """Выбор времени доставки"""
    lang = await get_user_language(callback.from_user.id)
    action, args = parse_callback(callback.data)
    time_data = "_".join(args)
    if time_data == "late":
        await callback.answer("Выберите время на завтра", show_alert=True)
        return
    if time_data == "asap":
        delivery_time = get_next_delivery_time()
    else:
        delivery_time = time_data
    await state.update_data(delivery_time=delivery_time)
    await callback.message.edit_text(
        _(lang, "payment"), reply_markup=payment_keyboard(lang), parse_mode="HTML"
    )
    await state.set_state(CheckoutState.waiting_payment)
    await callback.answer()


@router.callback_query(F.data.startswith("pay_"), CheckoutState.waiting_payment)
async def process_payment_selection(callback: CallbackQuery, state: FSMContext):
    """Выбор способа оплаты"""
    lang = await get_user_language(callback.from_user.id)
    action, args = parse_callback(callback.data)
    payment_method = args[0]
    await state.update_data(payment_method=payment_method)
    await callback.message.edit_text(
        _(lang, "comment"),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=_(lang, "skip"), callback_data="skip_comment"
                    )
                ]
            ]
        ),
        parse_mode="HTML",
    )
    await state.set_state(CheckoutState.waiting_comment)
    await callback.answer()


@router.callback_query(F.data == "skip_comment", CheckoutState.waiting_comment)
async def process_skip_comment(callback: CallbackQuery, state: FSMContext):
    """Пропустить комментарий"""
    await state.update_data(comment="")
    await show_order_confirmation(callback.message, state)
    await callback.answer()


@router.message(CheckoutState.waiting_comment)
async def process_comment_input(message: Message, state: FSMContext):
    """Обработка комментария"""
    comment = message.text.strip()
    await state.update_data(comment=comment)
    await show_order_confirmation(message, state)


async def show_order_confirmation(message_or_callback, state: FSMContext):
    """Показать подтверждение заказа"""
    tg_id = (
        message_or_callback.from_user.id
        if hasattr(message_or_callback, "from_user")
        else message_or_callback.chat.id
    )
    lang = await get_user_language(tg_id)
    data = await state.get_data()
    user_id = data["user_id"]
    user = await get_user_by_telegram_id(tg_id)
    cart_items = await get_cart_items(user_id)
    total = await get_cart_total(user_id)

    # Применение реферального баланса
    discount = 0.0
    if user and user.get("referral_balance", 0) > 0:
        discount = min(user["referral_balance"], total)

    base_total = total - discount
    final_total, fee, dtype = calculate_delivery(base_total)

    await state.update_data(
        discount=discount, final_total=final_total, delivery_fee=fee
    )

    text = (
        _(lang, "confirm_order")
        + "\n\n"
        + _(lang, "confirm_address", address=data["delivery_address"])
        + "\n"
        + _(lang, "confirm_phone", phone=data["delivery_phone"])
        + "\n"
        + _(lang, "confirm_time", time=data["delivery_time"])
        + "\n"
        + _(
            lang,
            "confirm_payment",
            payment=PAYMENT_METHODS.get(data["payment_method"], data["payment_method"]),
        )
        + "\n"
    )
    if data.get("comment"):
        text += _(lang, "confirm_comment", comment=data["comment"]) + "\n"
    if discount > 0:
        text += _(lang, "discount_applied", discount=discount) + "\n"
    text += "\n" + _(lang, "confirm_items") + "\n"
    for item in cart_items:
        it = item["quantity"] * item["price"]
        text += (
            _(
                lang,
                "cart_item",
                name=item["name"],
                qty=item["quantity"],
                price=item["price"],
                total=it,
            )
            + "\n"
        )
    text += "\n" + _(lang, "cart_total", total=total)
    if discount > 0:
        text += "\n" + _(lang, "discount_applied", discount=discount)
    if dtype == "paid":
        text += "\n" + _(lang, "delivery_fee", fee=fee, min=MINIMUM_ORDER_AMOUNT)
    else:
        text += "\n" + _(lang, "free_delivery", min=MINIMUM_ORDER_AMOUNT)
    text += "\n" + _(lang, "confirm_total", total=final_total)
    await message_or_callback.answer(
        text, reply_markup=confirm_order_keyboard(lang), parse_mode="HTML"
    )
    await state.set_state(CheckoutState.confirm_order)


@router.callback_query(F.data == "confirm_order", CheckoutState.confirm_order)
async def process_confirm_order(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Подтверждение и создание заказа"""
    lang = await get_user_language(callback.from_user.id)

    # Дополнительная проверка графика работы
    if not is_working_hours():
        await callback.message.edit_text(
            _(lang, "closed", start=WORKING_HOURS_START, end=WORKING_HOURS_END),
            reply_markup=back_to_main_keyboard(lang),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    data = await state.get_data()
    user_id = data["user_id"]
    cart_items = await get_cart_items(user_id)
    total = await get_cart_total(user_id)
    if not cart_items:
        await callback.answer(_(lang, "error_empty_cart"), show_alert=True)
        return
    final_total = data.get("final_total", total)
    order_id = await create_order(
        user_id=user_id,
        total_amount=final_total,
        delivery_time=data["delivery_time"],
        payment_method=data["payment_method"],
        comment=data.get("comment", ""),
        address=data["delivery_address"],
        phone=data["delivery_phone"],
    )
    order_items_data = [
        {
            "product_id": item["product_id"],
            "quantity": item["quantity"],
            "price": item["price"],
        }
        for item in cart_items
    ]
    await add_order_items(order_id, order_items_data)

    # Списание бонусов
    discount = data.get("discount", 0)
    if discount > 0:
        await use_referral_balance(user_id, discount)

    await clear_cart(user_id)
    order = await get_order(order_id)
    items = await get_order_items(order_id)
    await callback.message.edit_text(
        _(lang, "order_accepted", id=order_id, total=final_total),
        reply_markup=back_to_main_keyboard(lang),
        parse_mode="HTML",
    )
    user = await get_user_by_telegram_id(callback.from_user.id)
    user_name = (
        f"@{callback.from_user.username}"
        if callback.from_user.username
        else f"{callback.from_user.first_name}"
    )
    admin_text = format_admin_order_text(order, items, user_name)
    try:
        await bot.send_message(
            ADMIN_ID,
            admin_text,
            reply_markup=admin_order_keyboard(order_id),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error(f"Ошибка отправки уведомления админу: {e}")
    await state.clear()
    await callback.answer(_(lang, "thank_you"))


# ==================== Профиль ====================


@router.callback_query(F.data == "profile")
async def process_profile(callback: CallbackQuery, bot: Bot):
    """Показать профиль"""
    lang = await get_user_language(callback.from_user.id)
    user = await get_user_by_telegram_id(callback.from_user.id)
    bot_info = await bot.get_me()
    referral_link = f"https://t.me/{bot_info.username}?start={user['referral_code']}"
    text = _(
        lang,
        "profile",
        address=user["address"] or _(lang, "no_address"),
        phone=user["phone"] or _(lang, "no_phone"),
    )
    text += "\n\n" + _(
        lang, "referral_balance", balance=user.get("referral_balance", 0)
    )
    text += "\n" + _(lang, "referral_link", link=referral_link, reward=REFERRAL_REWARD)
    await callback.message.edit_text(
        text, reply_markup=profile_keyboard(lang), parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "referral")
async def process_referral(callback: CallbackQuery, bot: Bot):
    """Показать реферальную программу"""
    lang = await get_user_language(callback.from_user.id)
    user = await get_user_by_telegram_id(callback.from_user.id)
    bot_info = await bot.get_me()
    link = f"https://t.me/{bot_info.username}?start={user['referral_code']}"
    text = _(
        lang,
        "referral_text",
        link=link,
        reward=REFERRAL_REWARD,
        balance=user.get("referral_balance", 0),
    )
    await callback.message.edit_text(
        text, reply_markup=profile_keyboard(lang), parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "edit_address")
async def process_edit_address(callback: CallbackQuery, state: FSMContext):
    """Редактировать адрес"""
    lang = await get_user_language(callback.from_user.id)
    await callback.message.edit_text(_(lang, "enter_address"), parse_mode="HTML")
    await state.set_state(ProfileState.waiting_address)
    await callback.answer()


@router.message(ProfileState.waiting_address)
async def process_new_address(message: Message, state: FSMContext):
    """Сохранить новый адрес с валидацией"""
    lang = await get_user_language(message.from_user.id)
    address = message.text.strip()
    if not validate_address(address):
        await message.answer(
            "❌ Адрес слишком короткий (минимум 5 символов)", parse_mode="HTML"
        )
        return
    user = await get_user_by_telegram_id(message.from_user.id)
    await update_user_profile(user["id"], address=address)
    await message.answer(
        _(lang, "address_updated"),
        reply_markup=back_to_main_keyboard(lang),
        parse_mode="HTML",
    )
    await state.clear()


@router.callback_query(F.data == "edit_phone")
async def process_edit_phone(callback: CallbackQuery, state: FSMContext):
    """Редактировать телефон"""
    lang = await get_user_language(callback.from_user.id)
    await callback.message.edit_text(_(lang, "phone"), parse_mode="HTML")
    await state.set_state(ProfileState.waiting_phone)
    await callback.answer()


@router.message(ProfileState.waiting_phone)
async def process_new_phone(message: Message, state: FSMContext):
    """Сохранить новый телефон с валидацией"""
    lang = await get_user_language(message.from_user.id)
    phone = message.text.strip()
    if not validate_phone(phone):
        await message.answer(
            "❌ Введите номер телефона (минимум 10 цифр).\nПримеры: +7 707 123 45 67, 87071234567, 7071234567",
            parse_mode="HTML",
        )
        return
    user = await get_user_by_telegram_id(message.from_user.id)
    await update_user_profile(user["id"], phone=phone)
    await message.answer(
        _(lang, "phone_updated"),
        reply_markup=back_to_main_keyboard(lang),
        parse_mode="HTML",
    )
    await state.clear()


# ==================== История + Отмена + Повтор ====================


@router.callback_query(F.data == "history")
async def process_history(callback: CallbackQuery):
    """Показать историю заказов"""
    lang = await get_user_language(callback.from_user.id)
    user = await get_user_by_telegram_id(callback.from_user.id)
    orders = await get_user_orders(user["id"], limit=5)
    if not orders:
        await callback.message.edit_text(
            _(lang, "no_orders"),
            reply_markup=back_to_main_keyboard(lang),
            parse_mode="HTML",
        )
    else:
        text = _(lang, "history") + "\n\n"
        for order in orders:
            status = ORDER_STATUSES.get(order["status"], order["status"])
            text += (
                _(
                    lang,
                    "order_line",
                    id=order["id"],
                    status=status,
                    total=order["total_amount"],
                )
                + "\n"
            )
            text += _(lang, "order_date", date=order["created_at"]) + "\n\n"
        await callback.message.edit_text(
            text, reply_markup=back_to_main_keyboard(lang), parse_mode="HTML"
        )
    await callback.answer()


@router.message(Command("history"))
async def cmd_history(message: Message):
    """/history с кнопками отмены и повтора"""
    lang = await get_user_language(message.from_user.id)
    user = await get_user_by_telegram_id(message.from_user.id)
    if not user:
        await message.answer(_(lang, "start_first"))
        return
    orders = await get_user_orders(user["id"], limit=5)
    if not orders:
        await message.answer(
            _(lang, "no_orders"),
            reply_markup=back_to_main_keyboard(lang),
            parse_mode="HTML",
        )
        return
    for order in orders:
        status = ORDER_STATUSES.get(order["status"], order["status"])
        text = f"📦 <b>Заказ #{order['id']}</b> — {status}\n"
        text += f"💰 {order['total_amount']:.0f} ₸ | {order['created_at']}\n"
        builder = InlineKeyboardBuilder()
        if order["status"] == "new":
            builder.row(
                InlineKeyboardButton(
                    text="❌ Отменить", callback_data=f"user_cancel_{order['id']}"
                )
            )
        builder.row(
            InlineKeyboardButton(
                text="🔄 Заказать снова", callback_data=f"reorder_{order['id']}"
            )
        )
        await message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")


@router.callback_query(F.data.startswith("user_cancel_"))
async def process_user_cancel(callback: CallbackQuery):
    """Отмена заказа пользователем"""
    lang = await get_user_language(callback.from_user.id)
    action, args = parse_callback(callback.data)
    order_id = int(args[0])
    user = await get_user_by_telegram_id(callback.from_user.id)
    ok = await cancel_order_user(order_id, user["id"])
    if ok:
        await callback.message.edit_text(
            f"❌ <b>Заказ #{order_id} отменён</b>", parse_mode="HTML"
        )
        await callback.answer("Заказ отменён")
    else:
        await callback.answer("❌ Нельзя отменить этот заказ", show_alert=True)


@router.callback_query(F.data.startswith("reorder_"))
async def process_reorder(callback: CallbackQuery):
    """Заказать снова"""
    lang = await get_user_language(callback.from_user.id)
    action, args = parse_callback(callback.data)
    order_id = int(args[0])
    user = await get_user_by_telegram_id(callback.from_user.id)
    ok = await reorder(order_id, user["id"])
    if ok:
        await callback.answer(_(lang, "added_to_cart"))
        await _refresh_cart_view(callback, lang)
    else:
        await callback.answer("❌ Ошибка", show_alert=True)


# ==================== Поддержка ====================


@router.callback_query(F.data == "support")
async def process_support(callback: CallbackQuery, state: FSMContext):
    """Начать диалог с поддержкой"""
    lang = await get_user_language(callback.from_user.id)
    await callback.message.edit_text(
        _(lang, "support_prompt"),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=_(lang, "cancel"), callback_data="main_menu"
                    )
                ]
            ]
        ),
        parse_mode="HTML",
    )
    await state.set_state(SupportState.waiting_message)
    await callback.answer()


@router.message(SupportState.waiting_message)
async def process_support_message(message: Message, state: FSMContext):
    """Переслать сообщение в поддержку"""
    lang = await get_user_language(message.from_user.id)
    user = await get_user_by_telegram_id(message.from_user.id)
    if not user:
        await message.answer(_(lang, "error_user_not_found"))
        await state.clear()
        return
    if not SUPPORT_GROUP_ID:
        await message.answer("❌ Служба поддержки не настроена.")
        await state.clear()
        return
    try:
        text = f"💬 <b>Сообщение от пользователя</b>\n"
        text += f"👤 {message.from_user.full_name} (ID: <code>{message.from_user.id}</code>)\n"
        if message.text:
            text += f"\n📝 {message.text}"
        elif message.caption:
            text += f"\n📝 {message.caption}"
        sent = await message.bot.send_message(
            SUPPORT_GROUP_ID,
            text,
            parse_mode="HTML",
        )
        await save_support_message(
            user_id=user["id"],
            user_telegram_id=message.from_user.id,
            user_message_id=message.message_id,
            support_chat_id=SUPPORT_GROUP_ID,
            support_message_id=sent.message_id,
        )
        await message.answer(
            _(lang, "support_sent"),
            reply_markup=back_to_main_keyboard(lang),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error(f"Ошибка отправки в поддержку: {e}")
        await message.answer("❌ Ошибка отправки. Попробуйте позже.")
    await state.clear()


@router.message(F.chat.id == SUPPORT_GROUP_ID, F.reply_to_message)
async def process_support_reply(message: Message):
    """Ответ поддержки из группы"""
    if message.from_user.id != ADMIN_ID:
        return
    support_msg_id = message.reply_to_message.message_id
    record = await get_support_message_by_support_id(support_msg_id)
    if not record:
        return
    try:
        await message.bot.send_message(
            record["user_telegram_id"],
            f"💬 <b>Ответ поддержки:</b>\n\n{message.text}",
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error(f"Ошибка ответа пользователю: {e}")


# ==================== Админ панель (только русский) ====================


@router.message(Command("admin"))
async def cmd_admin(message: Message):
    """Панель администратора"""
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ У вас нет доступа к админ-панели.")
        return
    await message.answer(
        "🔧 <b>Панель администратора</b>\n\nВыберите раздел:",
        reply_markup=admin_main_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin_orders")
async def process_admin_all_orders(callback: CallbackQuery):
    """Все заказы — каждый заказ это кнопка, по нажатию открывается детали заказа."""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа", show_alert=True)
        return
    orders = await get_all_orders(limit=50)
    if not orders:
        await callback.message.edit_text(
            "📋 <b>Заказов пока нет</b>",
            reply_markup=admin_main_keyboard(),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    builder = InlineKeyboardBuilder()
    for order in orders:
        status_short = ORDER_STATUSES.get(order["status"], order["status"])
        user_name = order.get("first_name") or "Клиент"
        btn_text = f"📦 #{order['id']} • {order['total_amount']:.0f}₸ • {user_name} • {status_short}"
        if len(btn_text) > 60:
            user_name = user_name[:12] + "…"
            btn_text = f"📦 #{order['id']} • {order['total_amount']:.0f}₸ • {user_name} • {status_short}"
        builder.row(
            InlineKeyboardButton(
                text=btn_text, callback_data=f"admin_view_{order['id']}"
            )
        )
    builder.row(
        InlineKeyboardButton(text="◀️ В админ-панель", callback_data="admin_back")
    )

    await callback.message.edit_text(
        "📋 <b>Все заказы</b>\n\n<i>Нажмите на заказ, чтобы открыть детали и управлять статусом.</i>\n\n"
        "⏰ <i>Заказы со статусом «Отправлен» и «Доставлен» старше 24 часов "
        "автоматически скрываются (но остаются в базе данных).</i>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_orders_"))
async def process_admin_orders_by_status(callback: CallbackQuery):
    """Заказы по статусу — каждый заказ это кнопка для управления."""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа", show_alert=True)
        return
    action, args = parse_callback(callback.data)
    status = args[0]
    orders = await get_all_orders(status=status, limit=50)
    if not orders:
        await callback.message.edit_text(
            f"📋 <b>Заказов со статусом '{ORDER_STATUSES.get(status, status)}' нет</b>",
            reply_markup=admin_main_keyboard(),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    builder = InlineKeyboardBuilder()
    for order in orders:
        user_name = order.get("first_name") or "Клиент"
        created = order["created_at"][:16] if order.get("created_at") else ""
        btn_text = f"📦 #{order['id']} • {order['total_amount']:.0f}₸ • {user_name} • {created}"
        if len(btn_text) > 60:
            user_name = user_name[:10] + "…"
            btn_text = f"📦 #{order['id']} • {order['total_amount']:.0f}₸ • {user_name} • {created}"
        builder.row(
            InlineKeyboardButton(
                text=btn_text, callback_data=f"admin_view_{order['id']}"
            )
        )
    builder.row(
        InlineKeyboardButton(text="◀️ В админ-панель", callback_data="admin_back")
    )

    await callback.message.edit_text(
        f"📋 <b>Заказы: {ORDER_STATUSES.get(status, status)}</b>\n\n"
        "<i>Нажмите на заказ, чтобы открыть детали и управлять статусом.</i>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_view_"))
async def process_admin_view_order(callback: CallbackQuery, bot: Bot):
    """Просмотр заказа админом из списка — открывает карточку с кнопками управления статусом."""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа", show_alert=True)
        return
    action, args = parse_callback(callback.data)
    order_id = int(args[0])
    order = await get_order(order_id)
    if not order:
        await callback.answer("Заказ не найден", show_alert=True)
        return
    items = await get_order_items(order_id)
    user_name = f"@{order.get('first_name', 'Клиент')}"
    text = format_admin_order_text(order, items, user_name)
    await callback.message.edit_text(
        text,
        reply_markup=admin_order_status_keyboard(order_id, order["status"]),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_process_"))
async def process_admin_take_order(callback: CallbackQuery, bot: Bot):
    """Взять заказ в работу"""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа", show_alert=True)
        return
    action, args = parse_callback(callback.data)
    order_id = int(args[0])
    await update_order_status(order_id, "processing")
    order = await get_order(order_id)
    items = await get_order_items(order_id)
    try:
        await bot.send_message(
            order["telegram_id"],
            f"📦 <b>Заказ #{order_id}</b>\n\nВаш заказ принят в работу и собирается!",
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error(f"Ошибка уведомления клиента: {e}")
    user_name = f"@{order.get('username', order.get('first_name', 'Клиент'))}"
    text = format_admin_order_text(order, items, user_name)
    await callback.message.edit_text(
        text,
        reply_markup=admin_order_status_keyboard(order_id, "processing"),
        parse_mode="HTML",
    )
    await callback.answer("Заказ в работе")


@router.callback_query(F.data.startswith("admin_cancel_"))
async def process_admin_cancel_order(callback: CallbackQuery, bot: Bot):
    """Отменить заказ (админ)"""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа", show_alert=True)
        return
    action, args = parse_callback(callback.data)
    order_id = int(args[0])
    await update_order_status(order_id, "cancelled")
    order = await get_order(order_id)
    try:
        await bot.send_message(
            order["telegram_id"],
            f"❌ <b>Заказ #{order_id}</b>\n\nК сожалению, ваш заказ был отменён.\nСвяжитесь с нами для уточнения.",
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error(f"Ошибка уведомления клиента: {e}")
    await callback.message.edit_text(
        f"❌ <b>Заказ #{order_id} отменён</b>",
        reply_markup=admin_main_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer("Заказ отменён")


@router.callback_query(F.data.startswith("admin_status_"))
async def process_admin_change_status(callback: CallbackQuery, bot: Bot):
    """Изменить статус заказа"""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа", show_alert=True)
        return
    action, args = parse_callback(callback.data)
    order_id = int(args[0])
    new_status = args[1]
    await update_order_status(order_id, new_status)
    order = await get_order(order_id)
    items = await get_order_items(order_id)
    status_messages = {
        "sent": f"🚚 <b>Заказ #{order_id}</b>\n\nВаш заказ отправлен курьером!",
        "delivered": f"✅ <b>Заказ #{order_id}</b>\n\nВаш заказ доставлен! Приятного аппетита!",
        "cancelled": f"❌ <b>Заказ #{order_id}</b>\n\nЗаказ отменён.",
    }
    if new_status in status_messages:
        try:
            await bot.send_message(
                order["telegram_id"], status_messages[new_status], parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Ошибка уведомления клиента: {e}")
    user_name = f"@{order.get('username', order.get('first_name', 'Клиент'))}"
    text = format_admin_order_text(order, items, user_name)
    await callback.message.edit_text(
        text,
        reply_markup=admin_order_status_keyboard(order_id, new_status),
        parse_mode="HTML",
    )
    await callback.answer(
        f"Статус обновлён: {ORDER_STATUSES.get(new_status, new_status)}"
    )


# ==================== Админ: статистика ====================


@router.callback_query(F.data == "admin_stats")
async def process_admin_stats(callback: CallbackQuery):
    """Меню статистики"""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа", show_alert=True)
        return
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📅 За сегодня", callback_data="admin_stats_day")
    )
    builder.row(
        InlineKeyboardButton(text="📅 За неделю", callback_data="admin_stats_week")
    )
    builder.row(
        InlineKeyboardButton(text="◀️ В админ-панель", callback_data="admin_back")
    )
    await callback.message.edit_text(
        "📊 <b>Статистика</b>\n\nВыберите период:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "admin_stats_day")
async def process_admin_stats_day(callback: CallbackQuery):
    """Статистика за день"""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа", show_alert=True)
        return
    stats = await get_stats_day()
    top = await get_top_products("day", 3)
    text = "📊 <b>Статистика за сегодня</b>\n\n"
    text += f"📦 Заказов: <b>{stats['orders']}</b>\n"
    text += f"💰 Выручка: <b>{stats['revenue']:.0f} ₸</b>\n"
    text += f"📈 Средний чек: <b>{stats['avg_check']:.0f} ₸</b>\n"
    text += f"❌ Отмен: <b>{stats['cancelled']}</b>\n\n"
    if top:
        text += "🔥 <b>Топ-3 товара:</b>\n"
        for i, p in enumerate(top, 1):
            text += f"{i}. {p['name']} — {p['qty']} шт. ({p['revenue']:.0f} ₸)\n"
    else:
        text += "🔥 Топ товаров пока нет."
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="admin_stats"))
    await callback.message.edit_text(
        text, reply_markup=builder.as_markup(), parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "admin_stats_week")
async def process_admin_stats_week(callback: CallbackQuery):
    """Статистика за неделю"""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа", show_alert=True)
        return
    stats = await get_stats_week()
    top = await get_top_products("week", 3)
    text = "📊 <b>Статистика за неделю</b>\n\n"
    text += f"📦 Заказов: <b>{stats['orders']}</b>\n"
    text += f"💰 Выручка: <b>{stats['revenue']:.0f} ₸</b>\n"
    text += f"📈 Средний чек: <b>{stats['avg_check']:.0f} ₸</b>\n"
    text += f"❌ Отмен: <b>{stats['cancelled']}</b>\n\n"
    if top:
        text += "🔥 <b>Топ-3 товара:</b>\n"
        for i, p in enumerate(top, 1):
            text += f"{i}. {p['name']} — {p['qty']} шт. ({p['revenue']:.0f} ₸)\n"
    else:
        text += "🔥 Топ товаров пока нет."
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="admin_stats"))
    await callback.message.edit_text(
        text, reply_markup=builder.as_markup(), parse_mode="HTML"
    )
    await callback.answer()


# ==================== Админ: управление товарами ====================


@router.callback_query(F.data == "admin_products")
async def process_admin_products(callback: CallbackQuery):
    """Панель управления товарами"""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.message.edit_text(
        "🛠 <b>Управление товарами</b>\n\nВыберите действие:",
        reply_markup=admin_products_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "admin_edit_product")
async def process_admin_edit_product(callback: CallbackQuery, state: FSMContext):
    """Редактировать товар — выбор категории"""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа", show_alert=True)
        return

    categories = await get_categories()
    builder = InlineKeyboardBuilder()
    for cat in categories:
        builder.row(
            InlineKeyboardButton(
                text=f"{cat['emoji']} {cat['name']}",
                callback_data=f"admin_edit_cat_{cat['id']}",
            )
        )
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="admin_products"))

    await callback.message.edit_text(
        "📝 <b>Выберите категорию для редактирования:</b>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_edit_cat_"))
async def process_admin_edit_cat(callback: CallbackQuery, state: FSMContext):
    """Показать товары категории для редактирования"""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа", show_alert=True)
        return

    action, args = parse_callback(callback.data)
    category_id = int(args[0])
    products = await get_products_by_category(category_id)

    if not products:
        await callback.answer("В этой категории нет товаров", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    for p in products:
        builder.row(
            InlineKeyboardButton(
                text=f"✏️ {p['name']} — {p['price']:.0f} ₸",
                callback_data=f"admin_edit_item_{p['id']}",
            )
        )
    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="admin_edit_product")
    )

    await callback.message.edit_text(
        "📝 <b>Выберите товар для редактирования:</b>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_edit_item_"))
async def process_admin_edit_item(callback: CallbackQuery, state: FSMContext):
    """Показать поля для редактирования товара"""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа", show_alert=True)
        return

    action, args = parse_callback(callback.data)
    product_id = int(args[0])
    product = await get_product(product_id)

    if not product:
        await callback.answer("Товар не найден", show_alert=True)
        return

    await state.update_data(edit_product_id=product_id)

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🏷 Название", callback_data="admin_edit_field_name")
    )
    builder.row(
        InlineKeyboardButton(text="💰 Цена", callback_data="admin_edit_field_price")
    )
    builder.row(
        InlineKeyboardButton(text="📝 Описание", callback_data="admin_edit_field_desc")
    )
    builder.row(
        InlineKeyboardButton(text="📸 Фото", callback_data="admin_edit_field_photo")
    )
    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="admin_edit_product")
    )

    text = (
        f"📋 <b>Текущие данные товара:</b>\n\n"
        f"ID: {product['id']}\n"
        f"🏷 Название: {product['name']}\n"
        f"💰 Цена: {product['price']:.0f} ₸\n"
        f"📝 Описание: {product.get('description') or 'Нет'}\n"
        f"📸 Фото: {'Есть' if product.get('photo_file_id') else 'Нет'}\n\n"
        f"Выберите что редактировать:"
    )

    await callback.message.edit_text(
        text, reply_markup=builder.as_markup(), parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "admin_edit_field_name")
async def process_admin_edit_name(callback: CallbackQuery, state: FSMContext):
    """Редактировать название"""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.message.edit_text(
        "✏️ <b>Введите новое название товара:</b>",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_cancel")]
            ]
        ),
        parse_mode="HTML",
    )
    await state.set_state(AdminProductState.waiting_name)
    await callback.answer()


@router.callback_query(F.data == "admin_edit_field_price")
async def process_admin_edit_price(callback: CallbackQuery, state: FSMContext):
    """Редактировать цену"""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.message.edit_text(
        "💰 <b>Введите новую цену (в тенге):</b>",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_cancel")]
            ]
        ),
        parse_mode="HTML",
    )
    await state.set_state(AdminProductState.waiting_price)
    await callback.answer()


@router.callback_query(F.data == "admin_edit_field_desc")
async def process_admin_edit_desc(callback: CallbackQuery, state: FSMContext):
    """Редактировать описание"""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.message.edit_text(
        "📝 <b>Введите новое описание:</b>",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_cancel")]
            ]
        ),
        parse_mode="HTML",
    )
    await state.set_state(AdminProductState.waiting_description)
    await callback.answer()


@router.callback_query(F.data == "admin_edit_field_photo")
async def process_admin_edit_photo(callback: CallbackQuery, state: FSMContext):
    """Редактировать фото"""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.message.edit_text(
        "📸 <b>Отправьте новое фото:</b>",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_cancel")]
            ]
        ),
        parse_mode="HTML",
    )
    await state.set_state(AdminProductState.waiting_image)
    await callback.answer()


@router.message(AdminProductState.waiting_name)
async def process_edit_name_save(message: Message, state: FSMContext):
    """Сохранить новое название"""
    data = await state.get_data()
    product_id = data.get("edit_product_id")
    if product_id:
        from database import update_product

        await update_product(product_id, name=message.text.strip())
        await message.answer(
            "✅ <b>Название обновлено!</b>",
            reply_markup=admin_main_keyboard(),
            parse_mode="HTML",
        )
    await state.clear()


@router.message(AdminProductState.waiting_price)
async def process_edit_price_save(message: Message, state: FSMContext):
    """Сохранить новую цену"""
    price = validate_price(message.text)
    if price is None:
        await message.answer(
            "❌ <b>Неверная цена!</b>\n\nВведите положительное число, например: 890",
            parse_mode="HTML",
        )
        return
    data = await state.get_data()
    product_id = data.get("edit_product_id")
    if product_id:
        from database import update_product

        await update_product(product_id, price=price)
        await message.answer(
            "✅ <b>Цена обновлена!</b>",
            reply_markup=admin_main_keyboard(),
            parse_mode="HTML",
        )
    await state.clear()


@router.message(AdminProductState.waiting_description)
async def process_edit_desc_save(message: Message, state: FSMContext):
    """Сохранить новое описание"""
    data = await state.get_data()
    product_id = data.get("edit_product_id")
    if product_id:
        from database import update_product

        await update_product(product_id, description=message.text.strip())
        await message.answer(
            "✅ <b>Описание обновлено!</b>",
            reply_markup=admin_main_keyboard(),
            parse_mode="HTML",
        )
    await state.clear()


@router.message(AdminProductState.waiting_image)
async def process_edit_photo_save(message: Message, state: FSMContext):
    """Сохранить новое фото"""
    if not message.photo:
        await message.answer("❌ <b>Отправьте фото</b>", parse_mode="HTML")
        return
    data = await state.get_data()
    product_id = data.get("edit_product_id")
    if product_id:
        from database import update_product

        photo = message.photo[-1]
        await update_product(product_id, photo_file_id=photo.file_id)
        await message.answer(
            "✅ <b>Фото обновлено!</b>",
            reply_markup=admin_main_keyboard(),
            parse_mode="HTML",
        )
    await state.clear()


@router.callback_query(F.data == "admin_delete_product")
async def process_admin_delete_product(callback: CallbackQuery, state: FSMContext):
    """Удалить товар — выбор категории"""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа", show_alert=True)
        return

    categories = await get_categories()
    builder = InlineKeyboardBuilder()
    for cat in categories:
        builder.row(
            InlineKeyboardButton(
                text=f"{cat['emoji']} {cat['name']}",
                callback_data=f"admin_del_cat_{cat['id']}",
            )
        )
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="admin_products"))

    await callback.message.edit_text(
        "🗑 <b>Выберите категорию для удаления товаров:</b>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_del_cat_"))
async def process_admin_del_cat(callback: CallbackQuery, state: FSMContext):
    """Показать товары категории для удаления"""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа", show_alert=True)
        return

    action, args = parse_callback(callback.data)
    category_id = int(args[0])
    products = await get_products_by_category(category_id)

    if not products:
        await callback.answer("В этой категории нет товаров", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    for p in products:
        builder.row(
            InlineKeyboardButton(
                text=f"🗑 {p['name']} — {p['price']:.0f} ₸",
                callback_data=f"admin_del_item_{p['id']}",
            )
        )
    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="admin_delete_product")
    )

    await callback.message.edit_text(
        "🗑 <b>Выберите товар для удаления:</b>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_del_item_"))
async def process_admin_del_item(callback: CallbackQuery, state: FSMContext):
    """Подтвердить удаление товара"""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа", show_alert=True)
        return

    action, args = parse_callback(callback.data)
    product_id = int(args[0])
    product = await get_product(product_id)

    if not product:
        await callback.answer("Товар не найден", show_alert=True)
        return

    await state.update_data(delete_product_id=product_id)

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="✅ Да, удалить", callback_data="admin_confirm_delete"
        )
    )
    builder.row(
        InlineKeyboardButton(text="❌ Отмена", callback_data="admin_delete_product")
    )

    await callback.message.edit_text(
        f"🗑 <b>Удалить товар?</b>\n\n"
        f"🏷 {product['name']}\n"
        f"💰 {product['price']:.0f} ₸\n\n"
        f"Товар будет скрыт из каталога.",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "admin_confirm_delete")
async def process_admin_confirm_delete(callback: CallbackQuery, state: FSMContext):
    """Подтвердить удаление"""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа", show_alert=True)
        return

    data = await state.get_data()
    product_id = data.get("delete_product_id")

    if product_id:
        from database import delete_product

        await delete_product(product_id)
        await callback.message.edit_text(
            "✅ <b>Товар удалён!</b>",
            reply_markup=admin_main_keyboard(),
            parse_mode="HTML",
        )
    else:
        await callback.answer("Ошибка", show_alert=True)

    await state.clear()
    await callback.answer()


@router.callback_query(F.data == "admin_add_product")
async def process_admin_add_product(callback: CallbackQuery, state: FSMContext):
    """Начать добавление товара"""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа", show_alert=True)
        return
    categories = await get_categories()
    await callback.message.edit_text(
        "➕ <b>Добавление нового товара</b>\n\nВыберите категорию:",
        reply_markup=admin_categories_for_product_keyboard(categories),
        parse_mode="HTML",
    )
    await state.set_state(AdminProductState.waiting_category)
    await callback.answer()


@router.callback_query(
    F.data.startswith("admin_cat_"), AdminProductState.waiting_category
)
async def process_admin_select_category(callback: CallbackQuery, state: FSMContext):
    """Выбор категории для товара"""
    action, args = parse_callback(callback.data)
    category_id = int(args[0])
    await state.update_data(category_id=category_id)
    await callback.message.edit_text(
        "✏️ <b>Введите название товара:</b>\n\nНапример: Молоко 3.2% 1л",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_cancel")]
            ]
        ),
        parse_mode="HTML",
    )
    await state.set_state(AdminProductState.waiting_name)
    await callback.answer()


@router.message(AdminProductState.waiting_name)
async def process_admin_product_name(message: Message, state: FSMContext):
    """Сохранить название товара"""
    await state.update_data(product_name=message.text.strip())
    await message.answer(
        "💰 <b>Введите цену товара (в тенге):</b>\n\nНапример: 890",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_cancel")]
            ]
        ),
        parse_mode="HTML",
    )
    await state.set_state(AdminProductState.waiting_price)


@router.message(AdminProductState.waiting_price)
async def process_admin_product_price(message: Message, state: FSMContext):
    """Сохранить цену товара с валидацией"""
    price = validate_price(message.text)
    if price is None:
        await message.answer(
            "❌ <b>Неверная цена!</b>\n\nВведите положительное число, например: 890",
            parse_mode="HTML",
        )
        return
    await state.update_data(product_price=price)
    await message.answer(
        "📝 <b>Введите описание товара:</b>\n\nИли нажмите 'Пропустить':",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="⏭ Пропустить", callback_data="admin_skip_desc"
                    )
                ],
                [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_cancel")],
            ]
        ),
        parse_mode="HTML",
    )
    await state.set_state(AdminProductState.waiting_description)


@router.callback_query(
    F.data == "admin_skip_desc", AdminProductState.waiting_description
)
async def process_admin_skip_desc(callback: CallbackQuery, state: FSMContext):
    """Пропустить описание"""
    await state.update_data(product_description="")
    await show_admin_photo_prompt(callback.message, state)
    await callback.answer()


@router.message(AdminProductState.waiting_description)
async def process_admin_product_desc(message: Message, state: FSMContext):
    """Сохранить описание"""
    await state.update_data(product_description=message.text.strip())
    await show_admin_photo_prompt(message, state)


async def show_admin_photo_prompt(message_or_callback, state: FSMContext):
    """Показать запрос фото"""
    await message_or_callback.answer(
        "📸 <b>Отправьте фото товара</b>\n\nИли нажмите 'Пропустить':",
        reply_markup=admin_skip_photo_keyboard(),
        parse_mode="HTML",
    )
    await state.set_state(AdminProductState.waiting_image)


@router.callback_query(F.data == "admin_skip_photo", AdminProductState.waiting_image)
async def process_admin_skip_photo(callback: CallbackQuery, state: FSMContext):
    """Пропустить фото"""
    await state.update_data(product_image=None)
    await show_admin_product_preview(callback.message, state)
    await callback.answer()


@router.message(AdminProductState.waiting_image)
async def process_admin_product_photo(message: Message, state: FSMContext):
    """Сохранить фото"""
    if not message.photo:
        await message.answer(
            "❌ <b>Отправьте фото или нажмите 'Пропустить'</b>",
            reply_markup=admin_skip_photo_keyboard(),
            parse_mode="HTML",
        )
        return
    photo = message.photo[-1]
    await state.update_data(product_image=photo.file_id)
    await show_admin_product_preview(message, state)


async def show_admin_product_preview(message_or_callback, state: FSMContext):
    """Показать превью товара"""
    data = await state.get_data()
    text = (
        f"📋 <b>Проверьте данные товара:</b>\n\n"
        f"📦 <b>Категория ID:</b> {data['category_id']}\n"
        f"🏷 <b>Название:</b> {data['product_name']}\n"
        f"💰 <b>Цена:</b> {data['product_price']:.0f} ₸\n"
        f"📝 <b>Описание:</b> {data.get('product_description', 'Нет') or 'Нет'}\n"
        f"📸 <b>Фото:</b> {'Есть' if data.get('product_image') else 'Нет'}\n"
    )
    await message_or_callback.answer(
        text, reply_markup=admin_confirm_product_keyboard(), parse_mode="HTML"
    )
    await state.set_state(AdminProductState.confirm)


@router.callback_query(F.data == "admin_save_product", AdminProductState.confirm)
async def process_admin_save_product(callback: CallbackQuery, state: FSMContext):
    """Сохранить товар"""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа", show_alert=True)
        return
    data = await state.get_data()
    product_id = await add_product(
        category_id=data["category_id"],
        name=data["product_name"],
        price=data["product_price"],
        description=data.get("product_description") or None,
        photo_file_id=data.get("product_image") or None,
    )
    await callback.message.edit_text(
        f"✅ <b>Товар добавлен!</b>\n\n"
        f"ID: {product_id}\n"
        f"Название: {data['product_name']}\n"
        f"Цена: {data['product_price']:.0f} ₸",
        reply_markup=admin_main_keyboard(),
        parse_mode="HTML",
    )
    await state.clear()
    await callback.answer("Товар сохранён!")


@router.callback_query(F.data == "admin_change_product", AdminProductState.confirm)
async def process_admin_change_product(callback: CallbackQuery, state: FSMContext):
    """Изменить товар — начать заново"""
    await state.set_state(AdminProductState.waiting_category)
    categories = await get_categories()
    await callback.message.edit_text(
        "➕ <b>Добавление нового товара</b>\n\nВыберите категорию:",
        reply_markup=admin_categories_for_product_keyboard(categories),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "admin_cancel")
async def process_admin_cancel(callback: CallbackQuery, state: FSMContext):
    """Отмена операции админа"""
    await state.clear()
    await callback.message.edit_text(
        "❌ <b>Операция отменена</b>",
        reply_markup=admin_main_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "admin_back")
async def process_admin_back(callback: CallbackQuery):
    """Назад в админ-панель"""
    await callback.message.edit_text(
        "🔧 <b>Панель администратора</b>\n\nВыберите раздел:",
        reply_markup=admin_main_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "admin_add_category")
async def process_admin_add_category(callback: CallbackQuery, state: FSMContext):
    """Добавить категорию"""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.message.edit_text(
        "➕ <b>Добавление категории</b>\n\n"
        "Введите название категории и эмодзи через запятую:\n"
        "Например: Молочное, 🥛",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_cancel")]
            ]
        ),
        parse_mode="HTML",
    )
    await state.set_state(AdminProductState.waiting_category)
    await callback.answer()


@router.message(AdminProductState.waiting_category)
async def process_admin_new_category(message: Message, state: FSMContext):
    """Сохранить новую категорию"""
    parts = message.text.strip().split(",")
    if len(parts) >= 2:
        name = parts[0].strip()
        emoji = parts[1].strip()
    else:
        name = parts[0].strip()
        emoji = "📦"
    cat_id = await add_category(name, emoji)
    await message.answer(
        f"✅ <b>Категория добавлена!</b>\n\n"
        f"ID: {cat_id}\n"
        f"Название: {name}\n"
        f"Эмодзи: {emoji}",
        reply_markup=admin_main_keyboard(),
        parse_mode="HTML",
    )
    await state.clear()


# ==================== Обработка ошибок ====================


@router.errors()
async def process_errors(exception):
    """Обработка ошибок"""
    logger.error(f"Ошибка: {exception}")
