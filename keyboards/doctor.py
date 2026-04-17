from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def get_doctor_main_keyboard():
    """Главная панель врача"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🟢 Стать онлайн", callback_data="doctor_online")],
        [InlineKeyboardButton(text="🔴 Стать офлайн", callback_data="doctor_offline")],
        [InlineKeyboardButton(text="📋 Очередь", callback_data="view_queue")],
        [InlineKeyboardButton(text="📊 Статус", callback_data="show_status")]
    ])

def get_doctor_status_keyboard():
    """Клавиатура для просмотра статуса"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Очередь", callback_data="view_queue")],
        [InlineKeyboardButton(text="❌ Завершить текущего", callback_data="end_current")],
    ])

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