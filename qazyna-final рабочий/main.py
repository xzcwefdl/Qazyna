"""QazynaDelivery bot — единый файл хендлеров, без наворотов.

Главное: добавление товара работает (3 раздельных StateGroup).
"""

import asyncio
import logging
import re
import sys
from datetime import datetime

from aiogram import Bot, Dispatcher, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import BaseFilter, Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import (
    ADMIN_ID,
    BOT_TOKEN,
    DELIVERY_FEE,
    MINIMUM_ORDER_AMOUNT,
    ORDER_STATUSES,
    PAYMENT_METHODS,
    REFERRAL_REWARD,
    SUPPORT_GROUP_ID,
    WORKING_HOURS_END,
    WORKING_HOURS_START,
)
from database import *
from keyboards import *
from locales import t
from states import (
    AdminAddCategoryState,
    AdminAddProductState,
    AdminEditProductState,
    CheckoutState,
    ProfileState,
    SupportState,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

router = Router()


async def resend(target, text, reply_markup=None, parse_mode="HTML"):
    """edit_text с fallback'ом на edit_caption / answer.

    Telegram не даёт edit_text сообщению, у которого нет текста (например,
    если раньше отправили фото с caption). Этот хелпер:
    1) пробует edit_text;
    2) если BadRequest "no text" — пробует edit_caption;
    3) если не вышло — шлёт новое сообщение answer.
    """
    try:
        await target.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
        return
    except TelegramBadRequest as e:
        if "no text" not in str(e).lower():
            raise
    # fallback: edit_caption (для фото/видео)
    try:
        await target.edit_caption(text, reply_markup=reply_markup, parse_mode=parse_mode)
        return
    except Exception:
        pass
    # последний шанс: новое сообщение
    await target.answer(text, reply_markup=reply_markup, parse_mode=parse_mode)


async def resend(target, text, reply_markup=None, parse_mode="HTML"):
    """Удаляет target-сообщение и шлёт новое.

    Используется после показа фото: edit_caption часто делает caption
    визуально невидимым (особенно на мобильных клиентах с большим фото),
    поэтому надёжнее удалить старое сообщение и прислать новое с текстом.
    """
    try:
        await target.delete()
    except Exception:
        pass
    await target.answer(text, reply_markup=reply_markup, parse_mode=parse_mode)


# ==================== Фильтр: только админ ====================


class IsAdmin(BaseFilter):
    async def __call__(self, event):
        return getattr(event.from_user, "id", None) == ADMIN_ID


# ==================== Хелперы ====================


def parse_cb(data: str):
    """Парсинг callback: ('admin_view', ['5']) для 'admin_view_5'."""
    for prefix in [
        "add_to_cart", "cart_plus", "cart_minus",
        "admin_view", "admin_process", "admin_cancel", "admin_status",
        "admin_orders", "admin_cat", "admin_edit_cat", "admin_edit_item",
        "admin_del_cat", "admin_del_item", "user_cancel", "reorder",
    ]:
        if data.startswith(prefix + "_"):
            rest = data[len(prefix) + 1:]
            return prefix, rest.split("_") if rest else []
    parts = data.split("_")
    return parts[0], parts[1:]


def is_working():
    return WORKING_HOURS_START <= datetime.now().hour < WORKING_HOURS_END


def calc_delivery(total):
    if total >= MINIMUM_ORDER_AMOUNT:
        return total, 0, "free"
    return total + DELIVERY_FEE, DELIVERY_FEE, "paid"


def next_delivery_time():
    now = datetime.now()
    if now.hour >= 23:
        return "08:00–10:00"
    for s in [8, 10, 12, 14, 16, 18, 20]:
        if now.hour < s:
            return f"{s:02d}:00–{s + 2:02d}:00"
    return "08:00–10:00"


def format_cart(cart, total, lang):
    if not cart:
        return t(lang, "cart_empty")
    text = t(lang, "cart") + "\n\n"
    for item in cart:
        it = item["quantity"] * item["price"]
        text += t(lang, "cart_item", name=item["name"], qty=item["quantity"],
                  price=item["price"], total=it) + "\n"
    final, fee, dtype = calc_delivery(total)
    text += "\n" + t(lang, "cart_total", total=total)
    if dtype == "paid":
        text += "\n" + t(lang, "delivery_fee", fee=fee, min=MINIMUM_ORDER_AMOUNT)
        text += "\n" + t(lang, "total_with_delivery", total=final)
    else:
        text += "\n" + t(lang, "free_delivery", min=MINIMUM_ORDER_AMOUNT)
        text += "\n" + t(lang, "total_free_delivery", total=final)
    return text


def format_admin_order(order, items, user_name):
    status = ORDER_STATUSES.get(order["status"], order["status"])
    text = f"📦 <b>Заказ #{order['id']}</b>\n"
    text += f"Статус: {status}\n\n"
    text += f"👤 <b>Клиент:</b> {user_name}\n"
    text += f"📍 <b>Адрес:</b> {order['address']}\n"
    text += f"📞 <b>Телефон:</b> <code>{order['phone']}</code>\n"
    text += f"💰 <b>Сумма:</b> {order['total_amount']:.0f} ₸\n"
    text += f"⏰ <b>Время:</b> {order['delivery_time']}\n"
    text += f"💳 <b>Оплата:</b> {PAYMENT_METHODS.get(order['payment_method'], order['payment_method'])}\n"
    if order["comment"]:
        text += f"📝 <b>Комментарий:</b> {order['comment']}\n"
    text += f"\n📋 <b>Товары:</b>\n"
    for item in items:
        text += f"• {item['name']} — {item['quantity']} шт.\n"
    return text


async def refresh_cart_view(callback, lang):
    user = await get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer(t(lang, "error_user_not_found"), show_alert=True)
        return
    items = await get_cart_items(user["id"])
    total = await get_cart_total(user["id"])
    if not items:
        await resend(callback.message, 
            t(lang, "cart_empty"), reply_markup=empty_cart_keyboard(lang), parse_mode="HTML",
        )
    else:
        await resend(callback.message, 
            format_cart(items, total, lang), reply_markup=cart_keyboard(items, lang), parse_mode="HTML",
        )


# ============================================================
#   /start, язык, главное меню, профиль
# ============================================================


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext, command: CommandObject):
    user = await get_or_create_user(
        telegram_id=message.from_user.id,
        first_name=message.from_user.first_name,
        last_name=message.from_user.last_name,
    )
    if command.args and command.args.startswith("ref"):
        code = command.args
        referrer = await get_user_by_referral_code(code)
        if referrer and referrer["id"] != user["id"] and not user.get("referred_by"):
            applied = await apply_referral(user["id"], code)
            if applied:
                try:
                    await message.bot.send_message(
                        referrer["telegram_id"],
                        f"🎉 Новый реферал! +{REFERRAL_REWARD} ₸",
                    )
                except Exception:
                    pass
                await message.answer(f"🎉 +{REFERRAL_REWARD} ₸ на бонусный счёт!")
    await state.update_data(last_category_id=None)
    lang = user.get("language") or "ru"
    if user.get("language"):
        await message.answer(t(lang, "welcome"), reply_markup=main_menu_keyboard(lang), parse_mode="HTML")
        return
    await message.answer(t("ru", "choose_language"), reply_markup=language_keyboard(), parse_mode="HTML")


@router.callback_query(F.data.startswith("lang_"))
async def process_language(callback: CallbackQuery):
    _, args = parse_cb(callback.data)
    lang = args[0]
    await update_user_language(callback.from_user.id, lang)
    await resend(callback.message, t(lang, "language_changed"), parse_mode="HTML")
    await callback.message.answer(t(lang, "welcome"), reply_markup=main_menu_keyboard(lang), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "language")
async def process_change_language(callback: CallbackQuery):
    await resend(callback.message, t("ru", "choose_language"), reply_markup=language_keyboard(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "main_menu")
async def process_main_menu(callback: CallbackQuery, state: FSMContext):
    lang = await get_user_language(callback.from_user.id)
    await state.update_data(last_category_id=None)
    await resend(callback.message, t(lang, "main_menu"), reply_markup=main_menu_keyboard(lang), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "profile")
async def process_profile(callback: CallbackQuery, bot: Bot):
    lang = await get_user_language(callback.from_user.id)
    user = await get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer(t(lang, "error_user_not_found"), show_alert=True)
        return
    bot_info = await bot.get_me()
    link = f"https://t.me/{bot_info.username}?start={user['referral_code']}"
    text = t(lang, "profile",
             address=user["address"] or t(lang, "no_address"),
             phone=user["phone"] or t(lang, "no_phone"))
    text += "\n\n" + t(lang, "referral_balance", balance=user.get("referral_balance", 0))
    text += "\n" + t(lang, "referral_link", link=link)
    await resend(callback.message, text, reply_markup=profile_keyboard(lang), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "referral")
async def process_referral(callback: CallbackQuery, bot: Bot):
    lang = await get_user_language(callback.from_user.id)
    user = await get_user_by_telegram_id(callback.from_user.id)
    bot_info = await bot.get_me()
    link = f"https://t.me/{bot_info.username}?start={user['referral_code']}"
    text = t(lang, "referral_text", link=link, reward=REFERRAL_REWARD, balance=user.get("referral_balance", 0))
    await resend(callback.message, text, reply_markup=profile_keyboard(lang), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "edit_address")
async def process_edit_address(callback: CallbackQuery, state: FSMContext):
    lang = await get_user_language(callback.from_user.id)
    await resend(callback.message, t(lang, "enter_address"), parse_mode="HTML")
    await state.set_state(ProfileState.waiting_address)
    await callback.answer()


@router.message(ProfileState.waiting_address)
async def process_new_address(message: Message, state: FSMContext):
    lang = await get_user_language(message.from_user.id)
    address = message.text.strip()
    if not validate_address(address):
        await message.answer("❌ Адрес слишком короткий (минимум 5 символов)", parse_mode="HTML")
        return
    user = await get_user_by_telegram_id(message.from_user.id)
    await update_user_profile(user["id"], address=address)
    await message.answer(t(lang, "address_updated"), reply_markup=back_to_main_keyboard(lang), parse_mode="HTML")
    await state.clear()


@router.callback_query(F.data == "edit_phone")
async def process_edit_phone(callback: CallbackQuery, state: FSMContext):
    lang = await get_user_language(callback.from_user.id)
    await resend(callback.message, t(lang, "phone"), parse_mode="HTML")
    await state.set_state(ProfileState.waiting_phone)
    await callback.answer()


@router.message(ProfileState.waiting_phone)
async def process_new_phone(message: Message, state: FSMContext):
    lang = await get_user_language(message.from_user.id)
    phone = message.text.strip()
    if not validate_phone(phone):
        await message.answer(
            "❌ Введите телефон (минимум 10 цифр).\nПримеры: +7 707 123 45 67, 87071234567",
            parse_mode="HTML",
        )
        return
    user = await get_user_by_telegram_id(message.from_user.id)
    await update_user_profile(user["id"], phone=phone)
    await message.answer(t(lang, "phone_updated"), reply_markup=back_to_main_keyboard(lang), parse_mode="HTML")
    await state.clear()


# ============================================================
#   Каталог и корзина
# ============================================================


@router.callback_query(F.data == "catalog")
async def process_catalog(callback: CallbackQuery, state: FSMContext):
    lang = await get_user_language(callback.from_user.id)
    await state.update_data(last_category_id=None)
    cats = await get_categories()
    await resend(callback.message, t(lang, "catalog"), reply_markup=categories_keyboard(cats, lang), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("category_"))
async def process_category(callback: CallbackQuery, state: FSMContext):
    lang = await get_user_language(callback.from_user.id)
    _, args = parse_cb(callback.data)
    cat_id = int(args[0])
    await state.update_data(last_category_id=cat_id)
    products = await get_products_by_category(cat_id)
    if not products:
        await callback.answer(t(lang, "error_category_empty"), show_alert=True)
        return
    await resend(callback.message, 
        t(lang, "choose_product"), reply_markup=products_keyboard(products, cat_id, lang), parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("product_"))
async def process_product(callback: CallbackQuery):
    lang = await get_user_language(callback.from_user.id)
    _, args = parse_cb(callback.data)
    pid = int(args[0])
    product = await get_product(pid)
    if not product:
        await callback.answer(t(lang, "error_product_not_found"), show_alert=True)
        return
    user = await get_user_by_telegram_id(callback.from_user.id)
    items = await get_cart_items(user["id"]) if user else []
    in_cart = any(i["product_id"] == pid for i in items)
    text = t(lang, "product_detail", emoji="", name=product["name"], price=product["price"])
    if product["description"]:
        text += "\n" + t(lang, "description", desc=product["description"])
    kb = product_detail_keyboard(pid, in_cart, lang)
    if product.get("photo_file_id"):
        try:
            await callback.message.delete()
            await callback.message.answer_photo(
                photo=product["photo_file_id"], caption=text, reply_markup=kb, parse_mode="HTML",
            )
        except Exception:
            await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
    else:
        await resend(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "back_to_products")
async def process_back_to_products(callback: CallbackQuery, state: FSMContext):
    lang = await get_user_language(callback.from_user.id)
    data = await state.get_data()
    cat_id = data.get("last_category_id")
    if cat_id:
        products = await get_products_by_category(cat_id)
        if products:
            await resend(callback.message, 
                t(lang, "choose_product"), reply_markup=products_keyboard(products, cat_id, lang), parse_mode="HTML",
            )
            await callback.answer()
            return
    cats = await get_categories()
    await resend(callback.message, t(lang, "catalog"), reply_markup=categories_keyboard(cats, lang), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("add_to_cart_"))
async def process_add_to_cart(callback: CallbackQuery):
    lang = await get_user_language(callback.from_user.id)
    _, args = parse_cb(callback.data)
    pid = int(args[0])
    user = await get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer(t(lang, "error_user_not_found"), show_alert=True)
        return
    await add_to_cart(user["id"], pid, 1)
    total = await get_cart_total(user["id"])
    await callback.answer(t(lang, "added_to_cart"))
    product = await get_product(pid)
    text = t(lang, "product_detail", emoji="", name=product["name"], price=product["price"])
    text += "\n" + t(lang, "added_to_cart") + "\n"
    text += t(lang, "in_cart_total", total=total)
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text=t(lang, "go_to_cart"), callback_data="cart"))
    b.row(InlineKeyboardButton(text=t(lang, "add_more"), callback_data=f"add_to_cart_{pid}"))
    b.row(InlineKeyboardButton(text=t(lang, "back_to_products"), callback_data="back_to_products"))
    await resend(callback.message, text, reply_markup=b.as_markup(), parse_mode="HTML")


@router.callback_query(F.data == "cart")
async def process_cart(callback: CallbackQuery):
    lang = await get_user_language(callback.from_user.id)
    await refresh_cart_view(callback, lang)
    await callback.answer()


@router.callback_query(F.data.startswith("cart_plus_"))
async def process_cart_plus(callback: CallbackQuery):
    lang = await get_user_language(callback.from_user.id)
    _, args = parse_cb(callback.data)
    cid = int(args[0])
    user = await get_user_by_telegram_id(callback.from_user.id)
    items = await get_cart_items(user["id"])
    for item in items:
        if item["id"] == cid:
            await update_cart_quantity(cid, item["quantity"] + 1)
            break
    await refresh_cart_view(callback, lang)
    await callback.answer()


@router.callback_query(F.data.startswith("cart_minus_"))
async def process_cart_minus(callback: CallbackQuery):
    lang = await get_user_language(callback.from_user.id)
    _, args = parse_cb(callback.data)
    cid = int(args[0])
    user = await get_user_by_telegram_id(callback.from_user.id)
    items = await get_cart_items(user["id"])
    for item in items:
        if item["id"] == cid:
            await update_cart_quantity(cid, item["quantity"] - 1)
            break
    await refresh_cart_view(callback, lang)
    await callback.answer()


@router.callback_query(F.data == "clear_cart")
async def process_clear_cart(callback: CallbackQuery):
    lang = await get_user_language(callback.from_user.id)
    user = await get_user_by_telegram_id(callback.from_user.id)
    await clear_cart(user["id"])
    await resend(callback.message, 
        t(lang, "cart_cleared"), reply_markup=empty_cart_keyboard(lang), parse_mode="HTML",
    )
    await callback.answer()


# ============================================================
#   Оформление заказа
# ============================================================


@router.callback_query(F.data == "checkout")
async def process_checkout(callback: CallbackQuery, state: FSMContext):
    lang = await get_user_language(callback.from_user.id)
    if not is_working():
        await resend(callback.message, 
            t(lang, "closed", start=WORKING_HOURS_START, end=WORKING_HOURS_END),
            reply_markup=back_to_main_keyboard(lang), parse_mode="HTML",
        )
        await callback.answer()
        return
    user = await get_user_by_telegram_id(callback.from_user.id)
    items = await get_cart_items(user["id"])
    if not items:
        await callback.answer(t(lang, "error_empty_cart"), show_alert=True)
        return
    total = await get_cart_total(user["id"])
    await state.update_data(
        user_id=user["id"], phone=user["phone"], address=user["address"], cart_total=total,
    )
    if user["address"]:
        await resend(callback.message, 
            t(lang, "address", address=user["address"]),
            reply_markup=address_keyboard(has_address=True, lang=lang), parse_mode="HTML",
        )
    else:
        await resend(callback.message, 
            t(lang, "enter_address"),
            reply_markup=address_keyboard(has_address=False, lang=lang), parse_mode="HTML",
        )
        await state.set_state(CheckoutState.waiting_address)
    await callback.answer()


@router.callback_query(F.data == "use_saved_address")
async def process_use_saved_address(callback: CallbackQuery, state: FSMContext):
    lang = await get_user_language(callback.from_user.id)
    data = await state.get_data()
    await state.update_data(delivery_address=data.get("address"))
    phone = data.get("phone")
    if phone:
        await state.update_data(delivery_phone=phone)
        await resend(callback.message, 
            t(lang, "delivery_time"), reply_markup=delivery_time_keyboard(lang), parse_mode="HTML",
        )
        await state.set_state(CheckoutState.waiting_delivery_time)
    else:
        await resend(callback.message, t(lang, "phone"), parse_mode="HTML")
        await state.set_state(CheckoutState.waiting_phone)
    await callback.answer()


@router.callback_query(F.data == "enter_new_address")
async def process_enter_new_address(callback: CallbackQuery, state: FSMContext):
    lang = await get_user_language(callback.from_user.id)
    await resend(callback.message, t(lang, "enter_address"), parse_mode="HTML")
    await state.set_state(CheckoutState.waiting_address)
    await callback.answer()


@router.message(CheckoutState.waiting_address)
async def process_address_input(message: Message, state: FSMContext):
    lang = await get_user_language(message.from_user.id)
    address = message.text.strip()
    if not validate_address(address):
        await message.answer("❌ Адрес слишком короткий (минимум 5 символов)", parse_mode="HTML")
        return
    await state.update_data(delivery_address=address)
    data = await state.get_data()
    await update_user_profile(data["user_id"], address=address)
    phone = data.get("phone")
    if phone:
        await state.update_data(delivery_phone=phone)
        await message.answer(t(lang, "delivery_time"), reply_markup=delivery_time_keyboard(lang), parse_mode="HTML")
        await state.set_state(CheckoutState.waiting_delivery_time)
    else:
        await message.answer(t(lang, "phone"), parse_mode="HTML")
        await state.set_state(CheckoutState.waiting_phone)


@router.message(CheckoutState.waiting_phone)
async def process_phone_input(message: Message, state: FSMContext):
    lang = await get_user_language(message.from_user.id)
    phone = message.text.strip()
    if not validate_phone(phone):
        await message.answer("❌ Введите телефон (минимум 10 цифр).", parse_mode="HTML")
        return
    await state.update_data(delivery_phone=phone)
    data = await state.get_data()
    await update_user_profile(data["user_id"], phone=phone)
    await message.answer(t(lang, "delivery_time"), reply_markup=delivery_time_keyboard(lang), parse_mode="HTML")
    await state.set_state(CheckoutState.waiting_delivery_time)


@router.callback_query(F.data.startswith("time_"), CheckoutState.waiting_delivery_time)
async def process_time_selection(callback: CallbackQuery, state: FSMContext):
    lang = await get_user_language(callback.from_user.id)
    _, args = parse_cb(callback.data)
    time_data = "_".join(args)
    if time_data == "late":
        await callback.answer("Выберите время на завтра", show_alert=True)
        return
    delivery_time = next_delivery_time() if time_data == "asap" else time_data
    await state.update_data(delivery_time=delivery_time)
    await resend(callback.message, t(lang, "payment"), reply_markup=payment_keyboard(lang), parse_mode="HTML")
    await state.set_state(CheckoutState.waiting_payment)
    await callback.answer()


@router.callback_query(F.data.startswith("pay_"), CheckoutState.waiting_payment)
async def process_payment_selection(callback: CallbackQuery, state: FSMContext):
    lang = await get_user_language(callback.from_user.id)
    _, args = parse_cb(callback.data)
    payment_method = args[0]
    await state.update_data(payment_method=payment_method)
    await resend(callback.message, 
        t(lang, "comment"),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, "skip"), callback_data="skip_comment")]
        ]),
        parse_mode="HTML",
    )
    await state.set_state(CheckoutState.waiting_comment)
    await callback.answer()


@router.callback_query(F.data == "skip_comment", CheckoutState.waiting_comment)
async def process_skip_comment(callback: CallbackQuery, state: FSMContext):
    await state.update_data(comment="")
    await show_order_confirmation(callback.message, state)
    await callback.answer()


@router.message(CheckoutState.waiting_comment)
async def process_comment_input(message: Message, state: FSMContext):
    await state.update_data(comment=message.text.strip())
    await show_order_confirmation(message, state)


async def show_order_confirmation(target, state: FSMContext):
    tg_id = target.from_user.id if hasattr(target, "from_user") else target.chat.id
    lang = await get_user_language(tg_id)
    data = await state.get_data()
    user = await get_user_by_telegram_id(tg_id)
    items = await get_cart_items(data["user_id"])
    total = await get_cart_total(data["user_id"])

    discount = 0.0
    if user and user.get("referral_balance", 0) > 0:
        discount = min(user["referral_balance"], total)

    base_total = total - discount
    final, fee, dtype = calc_delivery(base_total)
    await state.update_data(discount=discount, final_total=final, delivery_fee=fee)

    text = t(lang, "confirm_order") + "\n\n"
    text += t(lang, "confirm_address", address=data["delivery_address"]) + "\n"
    text += t(lang, "confirm_phone", phone=data["delivery_phone"]) + "\n"
    text += t(lang, "confirm_time", time=data["delivery_time"]) + "\n"
    text += t(lang, "confirm_payment",
              payment=PAYMENT_METHODS.get(data["payment_method"], data["payment_method"])) + "\n"
    if data.get("comment"):
        text += t(lang, "confirm_comment", comment=data["comment"]) + "\n"
    if discount > 0:
        text += t(lang, "discount_applied", discount=discount) + "\n"
    text += "\n" + t(lang, "confirm_items") + "\n"
    for item in items:
        it = item["quantity"] * item["price"]
        text += t(lang, "cart_item", name=item["name"], qty=item["quantity"],
                  price=item["price"], total=it) + "\n"
    text += "\n" + t(lang, "cart_total", total=total)
    if dtype == "paid":
        text += "\n" + t(lang, "delivery_fee", fee=fee, min=MINIMUM_ORDER_AMOUNT)
    else:
        text += "\n" + t(lang, "free_delivery", min=MINIMUM_ORDER_AMOUNT)
    text += "\n" + t(lang, "confirm_total", total=final)
    await target.answer(text, reply_markup=confirm_order_keyboard(lang), parse_mode="HTML")
    await state.set_state(CheckoutState.confirm_order)


@router.callback_query(F.data == "confirm_order", CheckoutState.confirm_order)
async def process_confirm_order(callback: CallbackQuery, state: FSMContext, bot: Bot):
    lang = await get_user_language(callback.from_user.id)
    if not is_working():
        await resend(callback.message, 
            t(lang, "closed", start=WORKING_HOURS_START, end=WORKING_HOURS_END),
            reply_markup=back_to_main_keyboard(lang), parse_mode="HTML",
        )
        await callback.answer()
        return
    data = await state.get_data()
    items = await get_cart_items(data["user_id"])
    if not items:
        await callback.answer(t(lang, "error_empty_cart"), show_alert=True)
        return
    final = data.get("final_total", await get_cart_total(data["user_id"]))
    order_id = await create_order(
        user_id=data["user_id"], total_amount=final,
        delivery_time=data["delivery_time"], payment_method=data["payment_method"],
        comment=data.get("comment", ""), address=data["delivery_address"],
        phone=data["delivery_phone"],
    )
    await add_order_items(order_id, [
        {"product_id": i["product_id"], "quantity": i["quantity"], "price": i["price"]}
        for i in items
    ])
    if data.get("discount", 0) > 0:
        await use_referral_balance(data["user_id"], data["discount"])
    await clear_cart(data["user_id"])
    order = await get_order(order_id)
    oitems = await get_order_items(order_id)
    await resend(callback.message, 
        t(lang, "order_accepted", id=order_id, total=final),
        reply_markup=back_to_main_keyboard(lang), parse_mode="HTML",
    )
    user_name = order.get("first_name") or "Клиент"
    try:
        await bot.send_message(
            ADMIN_ID, format_admin_order(order, oitems, user_name),
            reply_markup=admin_order_status_keyboard(order_id, order["status"]),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error(f"admin notify failed: {e}")
    await state.clear()
    await callback.answer(t(lang, "thank_you"))


# ============================================================
#   История заказов
# ============================================================


@router.callback_query(F.data == "history")
async def process_history(callback: CallbackQuery):
    lang = await get_user_language(callback.from_user.id)
    user = await get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer(t(lang, "error_user_not_found"), show_alert=True)
        return
    orders = await get_user_orders(user["id"], limit=5)
    if not orders:
        await resend(callback.message, 
            t(lang, "no_orders"), reply_markup=back_to_main_keyboard(lang), parse_mode="HTML",
        )
    else:
        text = t(lang, "history") + "\n\n"
        for o in orders:
            status = ORDER_STATUSES.get(o["status"], o["status"])
            text += t(lang, "order_line", id=o["id"], status=status, total=o["total_amount"]) + "\n"
            text += t(lang, "order_date", date=o["created_at"]) + "\n\n"
        await resend(callback.message, 
            text, reply_markup=back_to_main_keyboard(lang), parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data.startswith("user_cancel_"))
async def process_user_cancel(callback: CallbackQuery):
    lang = await get_user_language(callback.from_user.id)
    _, args = parse_cb(callback.data)
    oid = int(args[0])
    user = await get_user_by_telegram_id(callback.from_user.id)
    ok = await cancel_order_user(oid, user["id"])
    if ok:
        await resend(callback.message, f"❌ <b>Заказ #{oid} отменён</b>", parse_mode="HTML")
        await callback.answer("Заказ отменён")
    else:
        await callback.answer("❌ Нельзя отменить этот заказ", show_alert=True)


@router.callback_query(F.data.startswith("reorder_"))
async def process_reorder(callback: CallbackQuery):
    lang = await get_user_language(callback.from_user.id)
    _, args = parse_cb(callback.data)
    oid = int(args[0])
    user = await get_user_by_telegram_id(callback.from_user.id)
    ok = await reorder(oid, user["id"])
    if ok:
        await callback.answer(t(lang, "added_to_cart"))
        await refresh_cart_view(callback, lang)
    else:
        await callback.answer("❌ Ошибка", show_alert=True)


# ============================================================
#   Поддержка
# ============================================================


@router.callback_query(F.data == "support")
async def process_support(callback: CallbackQuery, state: FSMContext):
    lang = await get_user_language(callback.from_user.id)
    await resend(callback.message, 
        t(lang, "support_prompt"),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, "cancel"), callback_data="main_menu")]
        ]),
        parse_mode="HTML",
    )
    await state.set_state(SupportState.waiting_message)
    await callback.answer()


@router.message(SupportState.waiting_message)
async def process_support_message(message: Message, state: FSMContext):
    lang = await get_user_language(message.from_user.id)
    user = await get_user_by_telegram_id(message.from_user.id)
    if not user:
        await message.answer(t(lang, "error_user_not_found"))
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
        sent = await message.bot.send_message(SUPPORT_GROUP_ID, text, parse_mode="HTML")
        await save_support_message(
            user_id=user["id"], user_telegram_id=message.from_user.id,
            user_message_id=message.message_id, support_chat_id=SUPPORT_GROUP_ID,
            support_message_id=sent.message_id,
        )
        await message.answer(t(lang, "support_sent"), reply_markup=back_to_main_keyboard(lang), parse_mode="HTML")
    except Exception as e:
        logger.error(f"support send failed: {e}")
        await message.answer("❌ Ошибка отправки. Попробуйте позже.")
    await state.clear()


@router.message(F.chat.id == SUPPORT_GROUP_ID, F.reply_to_message)
async def process_support_reply(message: Message):
    if not SUPPORT_GROUP_ID or message.from_user.id != ADMIN_ID:
        return
    record = await get_support_message_by_support_id(message.reply_to_message.message_id)
    if not record:
        return
    try:
        await message.bot.send_message(
            record["user_telegram_id"],
            f"💬 <b>Ответ поддержки:</b>\n\n{message.text}",
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error(f"support reply failed: {e}")


# ============================================================
#   АДМИН-ПАНЕЛЬ
# ============================================================


@router.message(Command("admin"), IsAdmin())
async def cmd_admin(message: Message):
    await message.answer(
        "🔧 <b>Панель администратора</b>\n\nВыберите раздел:",
        reply_markup=admin_main_keyboard(), parse_mode="HTML",
    )


@router.callback_query(F.data == "admin_back", IsAdmin())
async def process_admin_back(callback: CallbackQuery):
    await resend(callback.message, 
        "🔧 <b>Панель администратора</b>\n\nВыберите раздел:",
        reply_markup=admin_main_keyboard(), parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "admin_products", IsAdmin())
async def process_admin_products(callback: CallbackQuery):
    await resend(callback.message, 
        "🛠 <b>Управление товарами</b>\n\nВыберите действие:",
        reply_markup=admin_products_keyboard(), parse_mode="HTML",
    )
    await callback.answer()


# --- Заказы ---

def _order_btn_text(order):
    user_name = order.get("first_name") or "Клиент"
    status_short = ORDER_STATUSES.get(order["status"], order["status"])
    text = f"📦 #{order['id']} • {order['total_amount']:.0f}₸ • {user_name} • {status_short}"
    if len(text) > 60:
        user_name = user_name[:10] + "…"
        text = f"📦 #{order['id']} • {order['total_amount']:.0f}₸ • {user_name} • {status_short}"
    return text


@router.callback_query(F.data == "admin_orders", IsAdmin())
async def process_admin_all_orders(callback: CallbackQuery):
    orders = await get_all_orders(limit=50)
    if not orders:
        await resend(callback.message, 
            "📋 <b>Заказов пока нет</b>",
            reply_markup=admin_main_keyboard(), parse_mode="HTML",
        )
        await callback.answer()
        return
    b = InlineKeyboardBuilder()
    for o in orders:
        b.row(InlineKeyboardButton(text=_order_btn_text(o), callback_data=f"admin_view_{o['id']}"))
    b.row(InlineKeyboardButton(text="◀️ В админ-панель", callback_data="admin_back"))
    await resend(callback.message, 
        "📋 <b>Все заказы</b>\n\n<i>Нажмите на заказ для управления.</i>",
        reply_markup=b.as_markup(), parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_orders_"), IsAdmin())
async def process_admin_orders_by_status(callback: CallbackQuery):
    _, args = parse_cb(callback.data)
    status = args[0]
    orders = await get_all_orders(status=status, limit=50)
    if not orders:
        await resend(callback.message, 
            f"📋 <b>Нет заказов со статусом '{ORDER_STATUSES.get(status, status)}'</b>",
            reply_markup=admin_main_keyboard(), parse_mode="HTML",
        )
        await callback.answer()
        return
    b = InlineKeyboardBuilder()
    for o in orders:
        user_name = o.get("first_name") or "Клиент"
        created = o["created_at"][:16] if o.get("created_at") else ""
        text = f"📦 #{o['id']} • {o['total_amount']:.0f}₸ • {user_name} • {created}"
        if len(text) > 60:
            user_name = user_name[:10] + "…"
            text = f"📦 #{o['id']} • {o['total_amount']:.0f}₸ • {user_name} • {created}"
        b.row(InlineKeyboardButton(text=text, callback_data=f"admin_view_{o['id']}"))
    b.row(InlineKeyboardButton(text="◀️ В админ-панель", callback_data="admin_back"))
    await resend(callback.message, 
        f"📋 <b>Заказы: {ORDER_STATUSES.get(status, status)}</b>\n\n"
        "<i>Нажмите на заказ для управления.</i>",
        reply_markup=b.as_markup(), parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_view_"), IsAdmin())
async def process_admin_view_order(callback: CallbackQuery):
    _, args = parse_cb(callback.data)
    oid = int(args[0])
    order = await get_order(oid)
    if not order:
        await callback.answer("Заказ не найден", show_alert=True)
        return
    items = await get_order_items(oid)
    user_name = order.get("first_name") or "Клиент"
    await resend(callback.message, 
        format_admin_order(order, items, user_name),
        reply_markup=admin_order_status_keyboard(oid, order["status"]),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_status_"), IsAdmin())
async def process_admin_change_status(callback: CallbackQuery, bot: Bot):
    _, args = parse_cb(callback.data)
    oid = int(args[0])
    new_status = args[1]
    await update_order_status(oid, new_status)
    order = await get_order(oid)
    items = await get_order_items(oid)
    msgs = {
        "sent": f"🚚 <b>Заказ #{oid}</b>\n\nВаш заказ отправлен курьером!",
        "delivered": f"✅ <b>Заказ #{oid}</b>\n\nДоставлен! Приятного аппетита!",
        "cancelled": f"❌ <b>Заказ #{oid}</b>\n\nЗаказ отменён.",
    }
    if new_status in msgs:
        try:
            await bot.send_message(order["telegram_id"], msgs[new_status], parse_mode="HTML")
        except Exception:
            pass
    user_name = order.get("first_name") or "Клиент"
    await resend(callback.message, 
        format_admin_order(order, items, user_name),
        reply_markup=admin_order_status_keyboard(oid, new_status),
        parse_mode="HTML",
    )
    await callback.answer(f"Статус: {ORDER_STATUSES.get(new_status, new_status)}")


# --- Статистика ---

@router.callback_query(F.data == "admin_stats", IsAdmin())
async def process_admin_stats(callback: CallbackQuery):
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="📅 За сегодня", callback_data="admin_stats_day"))
    b.row(InlineKeyboardButton(text="📅 За неделю", callback_data="admin_stats_week"))
    b.row(InlineKeyboardButton(text="◀️ В админ-панель", callback_data="admin_back"))
    await resend(callback.message, 
        "📊 <b>Статистика</b>\n\nВыберите период:",
        reply_markup=b.as_markup(), parse_mode="HTML",
    )
    await callback.answer()


async def _stats_text(period):
    stats = await get_stats_day() if period == "day" else await get_stats_week()
    top = await get_top_products(period, 3)
    label = "сегодня" if period == "day" else "неделю"
    text = f"📊 <b>Статистика за {label}</b>\n\n"
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
    return text


@router.callback_query(F.data == "admin_stats_day", IsAdmin())
async def process_admin_stats_day(callback: CallbackQuery):
    text = await _stats_text("day")
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="◀️ Назад", callback_data="admin_stats"))
    await resend(callback.message, text, reply_markup=b.as_markup(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "admin_stats_week", IsAdmin())
async def process_admin_stats_week(callback: CallbackQuery):
    text = await _stats_text("week")
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="◀️ Назад", callback_data="admin_stats"))
    await resend(callback.message, text, reply_markup=b.as_markup(), parse_mode="HTML")
    await callback.answer()


# ============================================================
#   ДОБАВЛЕНИЕ ТОВАРА (AdminAddProductState) — ГЛАВНЫЙ ФИКС
# ============================================================


@router.callback_query(F.data == "admin_add_product", IsAdmin())
async def process_admin_add_product(callback: CallbackQuery, state: FSMContext):
    cats = await get_categories()
    await resend(callback.message, 
        "➕ <b>Добавление нового товара</b>\n\nВыберите категорию:",
        reply_markup=admin_categories_for_product_keyboard(cats), parse_mode="HTML",
    )
    await state.set_state(AdminAddProductState.waiting_category)
    await callback.answer()


@router.callback_query(
    F.data.startswith("admin_cat_"), IsAdmin(), AdminAddProductState.waiting_category
)
async def process_admin_select_category(callback: CallbackQuery, state: FSMContext):
    _, args = parse_cb(callback.data)
    cat_id = int(args[0])
    await state.update_data(category_id=cat_id)
    await resend(callback.message, 
        "✏️ <b>Введите название товара:</b>\n\nНапример: Молоко 3.2% 1л",
        reply_markup=admin_cancel_kb(), parse_mode="HTML",
    )
    await state.set_state(AdminAddProductState.waiting_name)
    await callback.answer()


@router.message(AdminAddProductState.waiting_name, IsAdmin())
async def process_admin_product_name(message: Message, state: FSMContext):
    await state.update_data(product_name=message.text.strip())
    await message.answer(
        "💰 <b>Введите цену товара (в тенге):</b>\n\nНапример: 890",
        reply_markup=admin_cancel_kb(), parse_mode="HTML",
    )
    await state.set_state(AdminAddProductState.waiting_price)


@router.message(AdminAddProductState.waiting_price, IsAdmin())
async def process_admin_product_price(message: Message, state: FSMContext):
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
        reply_markup=admin_skip_desc_kb(), parse_mode="HTML",
    )
    await state.set_state(AdminAddProductState.waiting_description)


@router.callback_query(
    F.data == "admin_skip_desc", IsAdmin(), AdminAddProductState.waiting_description
)
async def process_admin_skip_desc(callback: CallbackQuery, state: FSMContext):
    await state.update_data(product_description="")
    await callback.message.answer(
        "📸 <b>Отправьте фото товара</b>\n\nИли нажмите 'Пропустить':",
        reply_markup=admin_skip_photo_keyboard(), parse_mode="HTML",
    )
    await state.set_state(AdminAddProductState.waiting_image)
    await callback.answer()


@router.message(AdminAddProductState.waiting_description, IsAdmin())
async def process_admin_product_desc(message: Message, state: FSMContext):
    await state.update_data(product_description=message.text.strip())
    await message.answer(
        "📸 <b>Отправьте фото товара</b>\n\nИли нажмите 'Пропустить':",
        reply_markup=admin_skip_photo_keyboard(), parse_mode="HTML",
    )
    await state.set_state(AdminAddProductState.waiting_image)


@router.callback_query(
    F.data == "admin_skip_photo", IsAdmin(), AdminAddProductState.waiting_image
)
async def process_admin_skip_photo(callback: CallbackQuery, state: FSMContext):
    await state.update_data(product_image=None)
    await show_admin_product_preview(callback.message, state)
    await callback.answer()


@router.message(AdminAddProductState.waiting_image, IsAdmin())
async def process_admin_product_photo(message: Message, state: FSMContext):
    if not message.photo:
        await message.answer(
            "❌ <b>Отправьте фото или нажмите 'Пропустить'</b>",
            reply_markup=admin_skip_photo_keyboard(), parse_mode="HTML",
        )
        return
    photo = message.photo[-1]
    await state.update_data(product_image=photo.file_id)
    await show_admin_product_preview(message, state)


async def show_admin_product_preview(target, state: FSMContext):
    data = await state.get_data()
    text = (
        f"📋 <b>Проверьте данные товара:</b>\n\n"
        f"📦 <b>Категория ID:</b> {data['category_id']}\n"
        f"🏷 <b>Название:</b> {data['product_name']}\n"
        f"💰 <b>Цена:</b> {data['product_price']:.0f} ₸\n"
        f"📝 <b>Описание:</b> {data.get('product_description', 'Нет') or 'Нет'}\n"
        f"📸 <b>Фото:</b> {'Есть' if data.get('product_image') else 'Нет'}\n"
    )
    await target.answer(text, reply_markup=admin_confirm_product_keyboard(), parse_mode="HTML")
    await state.set_state(AdminAddProductState.confirm)


@router.callback_query(
    F.data == "admin_save_product", IsAdmin(), AdminAddProductState.confirm
)
async def process_admin_save_product(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    pid = await add_product(
        category_id=data["category_id"], name=data["product_name"], price=data["product_price"],
        description=data.get("product_description") or None,
        photo_file_id=data.get("product_image") or None,
    )
    await resend(callback.message, 
        f"✅ <b>Товар добавлен!</b>\n\nID: {pid}\nНазвание: {data['product_name']}\n"
        f"Цена: {data['product_price']:.0f} ₸",
        reply_markup=admin_main_keyboard(), parse_mode="HTML",
    )
    await state.clear()
    await callback.answer("Товар сохранён!")


@router.callback_query(
    F.data == "admin_change_product", IsAdmin(), AdminAddProductState.confirm
)
async def process_admin_change_product(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminAddProductState.waiting_category)
    cats = await get_categories()
    await resend(callback.message, 
        "➕ <b>Добавление нового товара</b>\n\nВыберите категорию:",
        reply_markup=admin_categories_for_product_keyboard(cats), parse_mode="HTML",
    )
    await callback.answer()


# ============================================================
#   РЕДАКТИРОВАНИЕ ТОВАРА (AdminEditProductState)
# ============================================================


@router.callback_query(F.data == "admin_edit_product", IsAdmin())
async def process_admin_edit_product(callback: CallbackQuery):
    cats = await get_categories()
    b = InlineKeyboardBuilder()
    for cat in cats:
        b.row(InlineKeyboardButton(
            text=f"{cat['emoji']} {cat['name']}", callback_data=f"admin_edit_cat_{cat['id']}",
        ))
    b.row(InlineKeyboardButton(text="◀️ Назад", callback_data="admin_products"))
    await resend(callback.message, 
        "📝 <b>Выберите категорию для редактирования:</b>",
        reply_markup=b.as_markup(), parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_edit_cat_"), IsAdmin())
async def process_admin_edit_cat(callback: CallbackQuery):
    _, args = parse_cb(callback.data)
    cat_id = int(args[0])
    products = await get_products_by_category(cat_id)
    if not products:
        await callback.answer("В этой категории нет товаров", show_alert=True)
        return
    b = InlineKeyboardBuilder()
    for p in products:
        b.row(InlineKeyboardButton(
            text=f"✏️ {p['name']} — {p['price']:.0f} ₸",
            callback_data=f"admin_edit_item_{p['id']}",
        ))
    b.row(InlineKeyboardButton(text="◀️ Назад", callback_data="admin_edit_product"))
    await resend(callback.message, 
        "📝 <b>Выберите товар для редактирования:</b>",
        reply_markup=b.as_markup(), parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_edit_item_"), IsAdmin())
async def process_admin_edit_item(callback: CallbackQuery, state: FSMContext):
    _, args = parse_cb(callback.data)
    pid = int(args[0])
    product = await get_product(pid)
    if not product:
        await callback.answer("Товар не найден", show_alert=True)
        return
    await state.update_data(edit_product_id=pid)
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🏷 Название", callback_data="admin_edit_field_name"))
    b.row(InlineKeyboardButton(text="💰 Цена", callback_data="admin_edit_field_price"))
    b.row(InlineKeyboardButton(text="📝 Описание", callback_data="admin_edit_field_desc"))
    b.row(InlineKeyboardButton(text="📸 Фото", callback_data="admin_edit_field_photo"))
    b.row(InlineKeyboardButton(text="◀️ Назад", callback_data="admin_edit_product"))
    text = (
        f"📋 <b>Текущие данные товара:</b>\n\n"
        f"ID: {product['id']}\n🏷 Название: {product['name']}\n"
        f"💰 Цена: {product['price']:.0f} ₸\n"
        f"📝 Описание: {product.get('description') or 'Нет'}\n"
        f"📸 Фото: {'Есть' if product.get('photo_file_id') else 'Нет'}\n\n"
        f"Выберите что редактировать:"
    )
    await resend(callback.message, text, reply_markup=b.as_markup(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "admin_edit_field_name", IsAdmin())
async def process_admin_edit_name(callback: CallbackQuery, state: FSMContext):
    await resend(callback.message, 
        "✏️ <b>Введите новое название товара:</b>",
        reply_markup=admin_cancel_kb(), parse_mode="HTML",
    )
    await state.set_state(AdminEditProductState.waiting_name)
    await callback.answer()


@router.callback_query(F.data == "admin_edit_field_price", IsAdmin())
async def process_admin_edit_price(callback: CallbackQuery, state: FSMContext):
    await resend(callback.message, 
        "💰 <b>Введите новую цену (в тенге):</b>",
        reply_markup=admin_cancel_kb(), parse_mode="HTML",
    )
    await state.set_state(AdminEditProductState.waiting_price)
    await callback.answer()


@router.callback_query(F.data == "admin_edit_field_desc", IsAdmin())
async def process_admin_edit_desc(callback: CallbackQuery, state: FSMContext):
    await resend(callback.message, 
        "📝 <b>Введите новое описание:</b>",
        reply_markup=admin_cancel_kb(), parse_mode="HTML",
    )
    await state.set_state(AdminEditProductState.waiting_description)
    await callback.answer()


@router.callback_query(F.data == "admin_edit_field_photo", IsAdmin())
async def process_admin_edit_photo(callback: CallbackQuery, state: FSMContext):
    await resend(callback.message, 
        "📸 <b>Отправьте новое фото:</b>",
        reply_markup=admin_cancel_kb(), parse_mode="HTML",
    )
    await state.set_state(AdminEditProductState.waiting_image)
    await callback.answer()


@router.message(AdminEditProductState.waiting_name, IsAdmin())
async def process_edit_name_save(message: Message, state: FSMContext):
    data = await state.get_data()
    pid = data.get("edit_product_id")
    if pid:
        await update_product(pid, name=message.text.strip())
        await message.answer("✅ <b>Название обновлено!</b>", reply_markup=admin_main_keyboard(), parse_mode="HTML")
    await state.clear()


@router.message(AdminEditProductState.waiting_price, IsAdmin())
async def process_edit_price_save(message: Message, state: FSMContext):
    price = validate_price(message.text)
    if price is None:
        await message.answer(
            "❌ <b>Неверная цена!</b>\n\nВведите положительное число, например: 890",
            parse_mode="HTML",
        )
        return
    data = await state.get_data()
    pid = data.get("edit_product_id")
    if pid:
        await update_product(pid, price=price)
        await message.answer("✅ <b>Цена обновлена!</b>", reply_markup=admin_main_keyboard(), parse_mode="HTML")
    await state.clear()


@router.message(AdminEditProductState.waiting_description, IsAdmin())
async def process_edit_desc_save(message: Message, state: FSMContext):
    data = await state.get_data()
    pid = data.get("edit_product_id")
    if pid:
        await update_product(pid, description=message.text.strip())
        await message.answer("✅ <b>Описание обновлено!</b>", reply_markup=admin_main_keyboard(), parse_mode="HTML")
    await state.clear()


@router.message(AdminEditProductState.waiting_image, IsAdmin())
async def process_edit_photo_save(message: Message, state: FSMContext):
    if not message.photo:
        await message.answer("❌ <b>Отправьте фото</b>", parse_mode="HTML")
        return
    data = await state.get_data()
    pid = data.get("edit_product_id")
    if pid:
        photo = message.photo[-1]
        await update_product(pid, photo_file_id=photo.file_id)
        await message.answer("✅ <b>Фото обновлено!</b>", reply_markup=admin_main_keyboard(), parse_mode="HTML")
    await state.clear()


# ============================================================
#   УДАЛЕНИЕ ТОВАРА
# ============================================================


@router.callback_query(F.data == "admin_delete_product", IsAdmin())
async def process_admin_delete_product(callback: CallbackQuery):
    cats = await get_categories()
    b = InlineKeyboardBuilder()
    for cat in cats:
        b.row(InlineKeyboardButton(
            text=f"{cat['emoji']} {cat['name']}", callback_data=f"admin_del_cat_{cat['id']}",
        ))
    b.row(InlineKeyboardButton(text="◀️ Назад", callback_data="admin_products"))
    await resend(callback.message, 
        "🗑 <b>Выберите категорию для удаления товаров:</b>",
        reply_markup=b.as_markup(), parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_del_cat_"), IsAdmin())
async def process_admin_del_cat(callback: CallbackQuery):
    _, args = parse_cb(callback.data)
    cat_id = int(args[0])
    products = await get_products_by_category(cat_id)
    if not products:
        await callback.answer("В этой категории нет товаров", show_alert=True)
        return
    b = InlineKeyboardBuilder()
    for p in products:
        b.row(InlineKeyboardButton(
            text=f"🗑 {p['name']} — {p['price']:.0f} ₸",
            callback_data=f"admin_del_item_{p['id']}",
        ))
    b.row(InlineKeyboardButton(text="◀️ Назад", callback_data="admin_delete_product"))
    await resend(callback.message, 
        "🗑 <b>Выберите товар для удаления:</b>",
        reply_markup=b.as_markup(), parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_del_item_"), IsAdmin())
async def process_admin_del_item(callback: CallbackQuery, state: FSMContext):
    _, args = parse_cb(callback.data)
    pid = int(args[0])
    product = await get_product(pid)
    if not product:
        await callback.answer("Товар не найден", show_alert=True)
        return
    await state.update_data(delete_product_id=pid)
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="✅ Да, удалить", callback_data="admin_confirm_delete"))
    b.row(InlineKeyboardButton(text="❌ Отмена", callback_data="admin_delete_product"))
    await resend(callback.message, 
        f"🗑 <b>Удалить товар?</b>\n\n🏷 {product['name']}\n💰 {product['price']:.0f} ₸\n\n"
        f"Товар будет скрыт из каталога.",
        reply_markup=b.as_markup(), parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "admin_confirm_delete", IsAdmin())
async def process_admin_confirm_delete(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    pid = data.get("delete_product_id")
    if pid:
        await delete_product(pid)
        await resend(callback.message, 
            "✅ <b>Товар удалён!</b>", reply_markup=admin_main_keyboard(), parse_mode="HTML",
        )
    else:
        await callback.answer("Ошибка", show_alert=True)
    await state.clear()
    await callback.answer()


# ============================================================
#   ДОБАВЛЕНИЕ КАТЕГОРИИ (AdminAddCategoryState)
# ============================================================


@router.callback_query(F.data == "admin_add_category", IsAdmin())
async def process_admin_add_category(callback: CallbackQuery, state: FSMContext):
    await resend(callback.message, 
        "➕ <b>Добавление категории</b>\n\n"
        "Введите название и эмодзи через запятую:\nНапример: Молочное, 🥛",
        reply_markup=admin_cancel_kb(), parse_mode="HTML",
    )
    await state.set_state(AdminAddCategoryState.waiting_name)
    await callback.answer()


@router.message(AdminAddCategoryState.waiting_name, IsAdmin())
async def process_admin_new_category(message: Message, state: FSMContext):
    parts = message.text.strip().split(",")
    if len(parts) >= 2:
        name = parts[0].strip()
        emoji = parts[1].strip()
    else:
        name = parts[0].strip()
        emoji = "📦"
    cid = await add_category(name, emoji)
    await message.answer(
        f"✅ <b>Категория добавлена!</b>\n\nID: {cid}\nНазвание: {name}\nЭмодзи: {emoji}",
        reply_markup=admin_main_keyboard(), parse_mode="HTML",
    )
    await state.clear()


@router.callback_query(F.data == "admin_cancel", IsAdmin())
async def process_admin_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await resend(callback.message, 
        "❌ <b>Операция отменена</b>",
        reply_markup=admin_main_keyboard(), parse_mode="HTML",
    )
    await callback.answer()


# ============================================================
#   Запуск
# ============================================================


async def main():
    await init_db()
    logger.info("Database initialized")

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    logger.info("Bot started")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        logger.info("Bot stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
