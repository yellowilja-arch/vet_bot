from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def get_admin_support_keyboard(request_id, user_id):
    """Клавиатура для обработки обращений в поддержку"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Отмечено", callback_data=f"support_done:{request_id}")],
        [InlineKeyboardButton(text="📝 Ответить", callback_data=f"support_reply:{user_id}:{request_id}")],
    ])