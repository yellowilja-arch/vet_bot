from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def get_doctor_main_keyboard():
    """Главная панель врача"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🟢 Стать онлайн", callback_data="doctor_online")],
        [InlineKeyboardButton(text="🔴 Стать офлайн", callback_data="doctor_offline")],
        [InlineKeyboardButton(text="📋 Очередь", callback_data="view_queue")],
        [InlineKeyboardButton(text="📊 Статус", callback_data="show_status")],
        [InlineKeyboardButton(text="▶️ Следующий клиент (/next)", callback_data="doctor_next")],
    ])


def get_confirm_payment_inline_keyboard(client_user_id: int):
    """Под фото чека — подтверждение оплаты без ввода команды."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Оплата подтверждена", callback_data=f"cfm_pay:{client_user_id}")]
    ])


def get_start_consultation_keyboard(client_user_id: int, consultation_id: int):
    """Под анкетой — взять этого клиента в работу."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="▶️ Начать консультацию", callback_data=f"take_cn:{client_user_id}:{consultation_id}")]
    ])

def get_doctor_status_keyboard(has_active_client: bool = False):
    """Клавиатура для просмотра статуса"""
    buttons = [[InlineKeyboardButton(text="📋 Очередь", callback_data="view_queue")]]
    if has_active_client:
        buttons.append([InlineKeyboardButton(text="❌ Завершить текущего", callback_data="end_current")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_doctor_actions_keyboard(user_id):
    """Клавиатура для действий врача во время консультации"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Завершить", callback_data=f"end_confirm:{user_id}")],
        [InlineKeyboardButton(text="🔄 Перенаправить", callback_data=f"transfer_confirm:{user_id}")],
        [InlineKeyboardButton(text="📋 Очередь", callback_data="view_queue")],
    ])

def get_end_confirmation_keyboard(user_id):
    """Клавиатура для подтверждения завершения"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, завершить", callback_data=f"end:{user_id}")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]
    ])

def get_transfer_menu_keyboard(user_id):
    """Клавиатура для перенаправления клиента"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🦷 Стоматолог", callback_data=f"to:dentistry:{user_id}")],
        [InlineKeyboardButton(text="🔪 Хирург", callback_data=f"to:surgery:{user_id}")],
        [InlineKeyboardButton(text="💊 Терапевт", callback_data=f"to:therapy:{user_id}")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]
    ])