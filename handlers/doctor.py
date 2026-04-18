import redis
from config import REDIS_URL

r = redis.from_url(REDIS_URL, decode_responses=True)

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from config import SPECIALISTS
from services.validators import is_doctor, get_doctor_status, get_current_client, set_doctor_status, set_current_client, update_doctor_activity, clear_session
from services.routing import get_doctor_by_specialization
from database.queue import pop_from_queue, get_queue_length, confirm_queue_processed
from database.consultations import update_consultation_doctor, save_consultation_end
from database.payments import confirm_payment, get_pending_payment
from database.doctors import get_doctor_name
from utils.helpers import safe_send_message, get_anonymous_id
from keyboards.doctor import get_doctor_main_keyboard, get_doctor_status_keyboard, get_doctor_actions_keyboard
from states.forms import QuestionnaireState

router = Router()


@router.message(Command("online"))
async def go_online(message: Message):
    user_id = message.from_user.id
    if await is_doctor(user_id):
        set_doctor_status(user_id, "online")
        await safe_send_message(user_id, "🟢 Вы онлайн", reply_markup=get_doctor_main_keyboard())


@router.message(Command("offline"))
async def go_offline(message: Message):
    user_id = message.from_user.id
    if await is_doctor(user_id):
        set_doctor_status(user_id, "offline")
        await safe_send_message(user_id, "🔴 Вы офлайн", reply_markup=get_doctor_main_keyboard())


@router.message(Command("status"))
async def show_status(message: Message):
    user_id = message.from_user.id
    if not await is_doctor(user_id):
        return
    
    current = get_current_client(user_id)
    queue_len = await get_queue_length("all")
    
    text = f"📊 Статус: {get_doctor_status(user_id)}\n"
    text += f"👤 Текущий клиент: {current or 'нет'}\n📋 В очереди: {queue_len}"
    
    has_client = current is not None
    await safe_send_message(user_id, text, reply_markup=get_doctor_status_keyboard(has_client))


@router.message(Command("confirm_payment"))
async def confirm_payment_command(message: Message, state: FSMContext):
    """Врач подтверждает оплату клиента"""
    doctor_id = message.from_user.id
    if not await is_doctor(doctor_id):
        await safe_send_message(doctor_id, "⛔ Только для врачей")
        return
    
    args = message.text.split()
    if len(args) != 2:
        await safe_send_message(doctor_id, "⚠️ Использование: /confirm_payment <user_id>")
        return
    
    client_id = int(args[1])
    
    # Находим платёж
    payment = await get_pending_payment(client_id)
    if not payment:
        await safe_send_message(doctor_id, "❌ Платёж не найден или уже подтверждён")
        return
    
    payment_id, consultation_id = payment
    
    # Подтверждаем оплату
    if await confirm_payment(client_id, consultation_id):
        await safe_send_message(client_id, "✅ Оплата подтверждена!")
        await safe_send_message(doctor_id, "✅ Оплата подтверждена")
        
        # Сохраняем данные для опросника
        await state.update_data(
            consultation_id=consultation_id,
            doctor_id=doctor_id,
            problem_name="Консультация"
        )
        
        # Начинаем опросник
        from keyboards.client import get_species_keyboard
        await state.set_state(QuestionnaireState.waiting_species)
        await safe_send_message(
            client_id,
            "📋 <b>Пожалуйста, заполните информацию о питомце</b>\n\n"
            "Выберите вид животного:",
            reply_markup=get_species_keyboard(),
            parse_mode="HTML"
        )
    else:
        await safe_send_message(doctor_id, "❌ Ошибка подтверждения")
        await safe_send_message(client_id, "❌ Ошибка подтверждения оплаты")


@router.message(Command("next"))
async def next_command(message: Message):
    """Взять следующего клиента из очереди"""
    user_id = message.from_user.id
    if not await is_doctor(user_id):
        return
    
    if get_current_client(user_id):
        await safe_send_message(user_id, "⚠️ У вас уже есть активный клиент. Завершите его сначала.")
        return
    
    # Ищем клиента в очереди
    client_id, anonymous_id, queue_id = await pop_from_queue("all")
    if not client_id:
        await safe_send_message(user_id, "📭 В очереди нет клиентов.")
        return
    
    # Находим консультацию
    from database.db import get_db
    db = await get_db()
    cursor = await db.execute('''
        SELECT id, problem_key FROM consultations 
        WHERE client_id = ? AND status = "paid"
        ORDER BY id DESC LIMIT 1
    ''', (client_id,))
    row = await cursor.fetchone()
    
    if not row:
        await safe_send_message(user_id, "❌ Консультация не найдена")
        return
    
    consultation_id, problem_key = row
    
    # Назначаем врача
    doctor_name = await get_doctor_name(user_id)
    await update_consultation_doctor(consultation_id, user_id, doctor_name)
    
    set_current_client(user_id, client_id)
    r.set(f"client:{client_id}:doctor", user_id)
    
    await confirm_queue_processed(queue_id)
    
    await safe_send_message(client_id, f"✅ Врач принял заявку! Консультация начинается.")
    await safe_send_message(user_id, f"✅ Клиент принят. Напишите сообщение.")
    update_doctor_activity(user_id)


@router.message(Command("end"))
async def end_command(message: Message):
    """Завершить текущую консультацию"""
    user_id = message.from_user.id
    if await is_doctor(user_id):
        current_client = get_current_client(user_id)
        if current_client:
            from database.db import get_db
            db = await get_db()
            cursor = await db.execute('''
                SELECT id FROM consultations 
                WHERE client_id = ? AND status = "active"
            ''', (int(current_client),))
            row = await cursor.fetchone()
            if row:
                consultation_id = row[0]
                await save_consultation_end(consultation_id, "ended_by_doctor")
                from keyboards.client import get_rating_keyboard
                await safe_send_message(int(current_client), "Пожалуйста, оцените консультацию:", reply_markup=get_rating_keyboard(consultation_id, user_id))
            set_current_client(user_id, None)
            clear_session(int(current_client), user_id)
            await safe_send_message(int(current_client), "🔚 Врач завершил консультацию.")
            await safe_send_message(user_id, "✅ Консультация завершена")


@router.callback_query(lambda c: c.data == "doctor_online")
async def doctor_online_callback(call: CallbackQuery):
    doctor_id = call.from_user.id
    if not await is_doctor(doctor_id):
        await call.answer("⛔ Только для врачей")
        return
    set_doctor_status(doctor_id, "online")
    await call.message.edit_text("🟢 Вы стали онлайн.", reply_markup=get_doctor_main_keyboard())
    await call.answer()


@router.callback_query(lambda c: c.data == "doctor_offline")
async def doctor_offline_callback(call: CallbackQuery):
    doctor_id = call.from_user.id
    if not await is_doctor(doctor_id):
        await call.answer("⛔ Только для врачей")
        return
    set_doctor_status(doctor_id, "offline")
    await call.message.edit_text("🔴 Вы стали офлайн.", reply_markup=get_doctor_main_keyboard())
    await call.answer()


@router.callback_query(lambda c: c.data == "view_queue")
async def view_queue_callback(call: CallbackQuery):
    doctor_id = call.from_user.id
    if not await is_doctor(doctor_id):
        await call.answer("⛔ Только для врачей")
        return
    
    queue_len = await get_queue_length("all")
    if queue_len == 0:
        await safe_send_message(doctor_id, "📭 Очередь пуста.")
    else:
        from database.queue import get_queue_items
        items = await get_queue_items("all", limit=10)
        text = f"📋 ОЧЕРЕДЬ ({queue_len}):\n\n"
        for i, (client_id, anonymous_id, queue_id) in enumerate(items):
            text += f"{i+1}. {anonymous_id}\n"
        await safe_send_message(doctor_id, text)
    await call.answer()


@router.callback_query(lambda c: c.data == "show_status")
async def show_status_callback(call: CallbackQuery):
    doctor_id = call.from_user.id
    if not await is_doctor(doctor_id):
        await call.answer("⛔ Только для врачей")
        return
    
    current = get_current_client(doctor_id)
    queue_len = await get_queue_length("all")
    
    text = f"📊 Статус: {get_doctor_status(doctor_id)}\n"
    text += f"👤 Текущий клиент: {current or 'нет'}\n📋 Очередь: {queue_len}"
    
    has_client = current is not None
    await call.message.edit_text(text, reply_markup=get_doctor_status_keyboard(has_client))
    await call.answer()


@router.message()
async def chat_messages(message: Message):
    """Пересылка сообщений между клиентом и врачом"""
    user_id = message.from_user.id
    
    if not await is_doctor(user_id):
        return
    
    current_client = get_current_client(user_id)
    if not current_client:
        return
    
    await safe_send_message(int(current_client), f"👨‍⚕️ Врач: {message.text}")
    update_doctor_activity(user_id)