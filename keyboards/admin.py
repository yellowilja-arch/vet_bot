from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

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