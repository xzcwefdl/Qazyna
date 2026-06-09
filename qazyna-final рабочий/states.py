"""FSM-состояния. Главное: 3 раздельных группы для админа, чтобы add и edit
не перехватывали друг друга как в исходной версии."""

from aiogram.fsm.state import State, StatesGroup


class CheckoutState(StatesGroup):
    waiting_address = State()
    waiting_phone = State()
    waiting_delivery_time = State()
    waiting_payment = State()
    waiting_comment = State()
    confirm_order = State()


class ProfileState(StatesGroup):
    waiting_address = State()
    waiting_phone = State()


class SupportState(StatesGroup):
    waiting_message = State()


class AdminAddProductState(StatesGroup):
    waiting_category = State()
    waiting_name = State()
    waiting_price = State()
    waiting_description = State()
    waiting_image = State()
    confirm = State()


class AdminEditProductState(StatesGroup):
    waiting_name = State()
    waiting_price = State()
    waiting_description = State()
    waiting_image = State()


class AdminAddCategoryState(StatesGroup):
    waiting_name = State()
