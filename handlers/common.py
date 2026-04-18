import redis
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext
from config import REDIS_URL, ADMIN_IDS
from services.validators import is_blocked, is_doctor, is_admin, get_doctor_status, get_current_client, set_doctor_status, update_doctor_activity
from database.doctors import get_all_doctors
from database.queue import get_queue_length
from database.users import save_user_if_new
from utils.helpers import safe_send_message, safe_send_photo, get_anonymous_id
from keyboards.client import get_main_keyboard
from keyboards.doctor import get_doctor_main_keyboard, get_doctor_status_keyboard
from keyboards.admin import get_admin_main_keyboard
from states.forms import PaymentState

r = redis.from_url(REDIS_URL, decode_responses=True)
router = Router()


@router.message(Command("reset_state"))
async def reset_state(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("✅ Состояние сброшено. Напишите /start")


@router.message(Command("start"))
async def start_command(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    
    if await is_blocked(user_id):
        await safe_send_message(user_id, "⛔ Ваш аккаунт заблокирован.")
        return
    
    await message.answer("✅ Обновление панели", reply_markup=ReplyKeyboardRemove())
    
    if await is_admin(user_id):
        await safe_send_message(
            user_id,
            "👨‍💼 <b>Панель администратора</b>\n\n"
            "Доступные команды:\n"
            "• /stats — статистика\n"
            "• /health — здоровье бота\n"
            "• /ban, /unban — чёрный список\n"
            "• /adddoctor, /removedoctor — управление врачами\n"
            "• /resetuser, /resetall, /closestuck, /unlockdoctors — восстановление\n"
            "• /backup — ручной бэкап\n"
            "• /user — информация о пользователе",
            reply_markup=get_admin_main_keyboard(),
            parse_mode="HTML"
        )
    elif await is_doctor(user_id):
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
            "🐾 Добро пожаловать в онлайн-консультации ветклиники!\n\nВыберите категорию проблемы:",
            reply_markup=get_main_keyboard(),
            parse_mode="HTML"
        )


print("✅ common.py ЗАГРУЖЕН, router создан")