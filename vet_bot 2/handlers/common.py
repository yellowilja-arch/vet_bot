import redis
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from config import TOPICS, REDIS_URL
from services.validators import is_blocked, is_doctor, get_doctor_status
from database.doctors import get_all_doctors
from database.users import save_user_if_new
from utils.helpers import safe_send_message, safe_send_photo, get_anonymous_id
from keyboards.client import get_client_main_keyboard
from keyboards.doctor import get_doctor_main_keyboard
from states.forms import PaymentState

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


@router.message(Command("doctors"))
async def list_doctors_command(message: Message):
    user_id = message.from_user.id
    if await is_doctor(user_id):
        await safe_send_message(user_id, "⛔ Эта команда только для клиентов.")
        return
    
    doctors = await get_all_doctors()
    if not doctors:
        await safe_send_message(user_id, "❌ В системе пока нет врачей.")
        return
    
    text = "👨‍⚕️ <b>Наши врачи</b>\n\n"
    for doc_id, name, spec in doctors:
        status = get_doctor_status(doc_id)
        status_emoji = "🟢" if status == "online" else "🔴"
        text += f"{status_emoji} <b>{name}</b> — {TOPICS.get(spec, spec)}\n"
    
    await safe_send_message(user_id, text, parse_mode="HTML")


@router.message(Command("my_consultations"))
async def my_consultations_command(message: Message):
    user_id = message.from_user.id
    if await is_doctor(user_id):
        await safe_send_message(user_id, "⛔ Эта команда только для клиентов.")
        return
    
    from database.consultations import get_user_consultations
    consultations = await get_user_consultations(user_id)
    
    if not consultations:
        await safe_send_message(user_id, "📭 У вас пока нет консультаций.")
        return
    
    text = "📋 <b>Ваши консультации</b>\n\n"
    for cons in consultations:
        status_emoji = "✅" if cons[3] == "ended" else "⚠️" if cons[3] == "auto_ended" else "⏳"
        date = cons[4][:10] if cons[4] else "дата неизвестна"
        text += f"{status_emoji} #{cons[0]} — {cons[1] or 'Врач не назначен'} ({cons[2]}) от {date}\n"
    
    await safe_send_message(user_id, text, parse_mode="HTML")


@router.message(F.text == "📋 Мои консультации")
async def my_consultations_button(message: Message):
    await my_consultations_command(message)


@router.message(Command("cancel"))
async def cancel_command(message: Message, state: FSMContext):
    await state.clear()
    await safe_send_message(message.from_user.id, "❌ Действие отменено.")


@router.message()
async def chat_messages(message: Message):
    """Пересылка сообщений между клиентом и врачом"""
    user_id = message.from_user.id
    
    if await is_blocked(user_id):
        return
    
    if message.text in ["✅ Я оплатил"] + list(TOPICS.values()) + ["📋 Мои консультации"]:
        return
    
    from services.validators import is_client_active, get_current_client, update_client_activity, update_doctor_activity
    
    if await is_client_active(user_id):
        # Клиент → Врач
        doctor_id = r.get(f"client:{user_id}:doctor")
        if not doctor_id:
            from database.db import get_db
            db = await get_db()
            cursor = await db.execute('''
                SELECT doctor_id FROM consultations 
                WHERE client_id = ? AND status = "active"
            ''', (user_id,))
            row = await cursor.fetchone()
            if row and row[0]:
                doctor_id = str(row[0])
                r.set(f"client:{user_id}:doctor", doctor_id)
        
        if doctor_id:
            anonymous_id = get_anonymous_id(
                r.get(f"doctor:{int(doctor_id)}:topic") or "therapy",
                user_id
            )
            if message.photo:
                await safe_send_photo(int(doctor_id), message.photo[-1].file_id, caption=f"👤 {anonymous_id}: {message.caption or ''}")
            elif message.video:
                await safe_send_message(int(doctor_id), f"👤 {anonymous_id}: [Видео] {message.caption or ''}")
            elif message.document:
                await safe_send_message(int(doctor_id), f"👤 {anonymous_id}: [Документ] {message.caption or ''}")
            else:
                await safe_send_message(int(doctor_id), f"👤 {anonymous_id}: {message.text}")
            update_client_activity(user_id)
    
    elif await is_doctor(user_id):
        # Врач → Клиент
        current_client = get_current_client(user_id)
        if current_client:
            await safe_send_message(int(current_client), f"👨‍⚕️ Врач: {message.text}")
            update_doctor_activity(user_id)