from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

def get_admin_main_keyboard():
    """Главная панель администратора"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Статистика"), KeyboardButton(text="🩺 Здоровье")],
            [KeyboardButton(text="🚫 Заблокировать"), KeyboardButton(text="✅ Разблокировать")],
            [KeyboardButton(text="➕ Добавить врача"), KeyboardButton(text="➖ Удалить врача")],
            [KeyboardButton(text="🔄 Сброс состояний"), KeyboardButton(text="💾 Бэкап")],
        ],
        resize_keyboard=True
    )


def get_admin_support_keyboard(request_id, user_id):
    """Клавиатура для обработки обращений в поддержку"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Отмечено", callback_data=f"support_done:{request_id}")],
        [InlineKeyboardButton(text="📝 Ответить", callback_data=f"support_reply:{user_id}:{request_id}")],
    ])