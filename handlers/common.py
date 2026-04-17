import redis
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message
from config import REDIS_URL

r = redis.from_url(REDIS_URL, decode_responses=True)
router = Router()


@router.message(Command("start"))
async def start_command(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    
    if await is_blocked(user_id):
        await safe_send_message(user_id, "⛔ Ваш аккаунт заблокирован.")
        return
    
    if await is_doctor(user_id):
        await safe_send_message(
            user_id,
            "👨‍⚕️ <b>Панель врача</b>\n\n"
            "Используйте кнопки ниже или команды:\n"
            "• /online — стать онлайн\n"
            "• /offline — стать офлайн\n"
            "• /status — мой статус\n"
            "• /next — взять следующего клиента\n"
            "• /clients — текущий клиент",
            reply_markup=get_doctor_main_keyboard(),
            parse_mode="HTML"
        )
    else:
        await save_user_if_new(user_id, message.from_user.username, message.from_user.first_name, message.from_user.last_name)
        await safe_send_message(
            user_id,
            "🐾 Добро пожаловать в онлайн-консультации ветклиники!\n\nВыберите специалиста:",
            reply_markup=get_client_main_keyboard()
        )

