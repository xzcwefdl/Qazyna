"""Состояния FSM (Finite State Machine)"""
from aiogram.fsm.state import State, StatesGroup



class CheckoutState(StatesGroup):
    """Состояния оформления заказа"""
    waiting_address = State()
    waiting_phone = State()
    waiting_delivery_time = State()
    waiting_payment = State()
    waiting_comment = State()
    confirm_order = State()


class ProfileState(StatesGroup):
    """Состояния редактирования профиля"""
    waiting_address = State()
    waiting_phone = State()


class AdminProductState(StatesGroup):
    """Состояния добавления товара админом"""
    waiting_category = State()
    waiting_name = State()
    waiting_price = State()
    waiting_description = State()
    waiting_image = State()
    confirm = State()


class SupportState(StatesGroup):
    """Состояния обращения в поддержку"""
    waiting_message = State()
