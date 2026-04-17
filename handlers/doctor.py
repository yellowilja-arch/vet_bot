import redis
from config import REDIS_URL

r = redis.from_url(REDIS_URL, decode_responses=True)

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from config import TOPICS
from services.validators import is_doctor, get_doctor_status, get_current_client, set_doctor_status, set_current_client, update_doctor_activity, clear_session
from services.routing import get_doctor
from database.queue import add_to_queue, pop_from_queue, get_queue_length, confirm_queue_processed
from database.consultations import save_consultation_start, save_consultation_end, update_consultation_doctor, get_user_consultations
from database.payments import confirm_payment, get_pending_payment
from database.doctors import get_doctor_name
from utils.helpers import safe_send_message, get_anonymous_id
from keyboards.doctor import get_doctor_main_keyboard, get_doctor_status_keyboard, get_doctor_actions_keyboard, get_end_confirmation_keyboard, get_transfer_menu_keyboard
from states.forms import PaymentState

router = Router()


# ДИАГНОСТИКА: ловит все сообщения в этом роутере
@router.message()
async def catch_all_doctor(message: Message):
    print(f"🔍 doctor catch_all: {message.text}")
    await message.answer(f"doctor catch_all: {message.text}")


@router.message(Command("testdoc"))
async def test_doctor(message: Message):
    await message.answer("doctor router works!")


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
    
    topic = r.get(f"doctor:{user_id}:topic")
    current = get_current_client(user_id)
    queue_len = await get_queue_length(topic) if topic else 0
    
    text = f"📊 Статус: {get_doctor_status(user_id)}\nСпециализация: {TOPICS.get(topic, '?')}\n"
    text += f"👤 Текущий клиент: {current or 'нет'}\n📋 Очередь: {queue_len}"
    await safe_send_message(user_id, text, reply_markup=get_doctor_status_keyboard())


@router.message(Command("next"))
async def next_command(message: Message):
    user_id = message.from_user.id
    if not await is_doctor(user_id):
        return
    
    if get_current_client(user_id):
        await safe_send_message(user_id, "⚠️ У вас уже есть активный клиент.")
        return
    
    topic = r.get(f"doctor:{user_id}:topic")
    if not topic:
        await safe_send_message(user_id, "❌ Не удалось определить специализацию.")
        return
    
    doctor_lock = f"lock:doctor_pick:{topic}"
    if not r.set(doctor_lock, "1", nx=True, ex=2):
        await safe_send_message(user_id, "⏳ Подождите секунду, обрабатываю...")
        return
    
    try:
        while True:
            client_id, anonymous_id, queue_id = await pop_from_queue(topic)
            if not client_id:
                break
            
            client_lock = f"lock:client_pick:{client_id}"
            if not r.set(client_lock, "1", nx=True, ex=5):
                from database.db import get_db
                db = await get_db()
                await db.execute('UPDATE queue SET status = "waiting" WHERE id = ?', (queue_id,))
                r.rpush(f"queue:{topic}", f"{client_id}:{anonymous_id}:{queue_id}")
                r.sadd(f"queue_set:{topic}", client_id)
                continue
            
            try:
                from services.validators import is_payment_confirmed
                from database.consultations import get_user_consultations
                
                consultation_id = None
                from database.db import get_db
                db = await get_db()
                cursor = await db.execute('''
                    SELECT id FROM consultations 
                    WHERE client_id = ? AND status IN ('waiting_payment', 'paid')
                    ORDER BY id DESC LIMIT 1
                ''', (client_id,))
                row = await cursor.fetchone()
                if row:
                    consultation_id = row[0]
                
                if not consultation_id or not await is_payment_confirmed(consultation_id):
                    await db.execute('UPDATE queue SET status = "waiting" WHERE id = ?', (queue_id,))
                    r.rpush(f"queue:{topic}", f"{client_id}:{anonymous_id}:{queue_id}")
                    r.sadd(f"queue_set:{topic}", client_id)
                    continue
                
                doctor_name = await get_doctor_name(user_id)
                await update_consultation_doctor(consultation_id, user_id, doctor_name)
                
                set_current_client(user_id, client_id)
                r.set(f"client:{client_id}:doctor", user_id)
                
                # ✅ ПОДТВЕРЖДАЕМ УСПЕШНУЮ ОБРАБОТКУ
                await confirm_queue_processed(queue_id)
                
                await safe_send_message(client_id, f"✅ Врач принял заявку! Ваш ID: {anonymous_id}")
                await safe_send_message(user_id, f"✅ Клиент {anonymous_id} принят")
                update_doctor_activity(user_id)
                return
            finally:
                r.delete(client_lock)
        
        await safe_send_message(user_id, "📭 Нет клиентов с подтверждённой оплатой")
    finally:
        r.delete(doctor_lock)


@router.message(Command("end"))
async def end_command(message: Message):
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
    topic = r.get(f"doctor:{doctor_id}:topic")
    if not topic:
        await safe_send_message(doctor_id, "❌ Не удалось определить специализацию.")
        await call.answer()
        return
    queue_len = await get_queue_length(topic)
    if queue_len == 0:
        await safe_send_message(doctor_id, "📭 Очередь пуста.")
    else:
        queue_items = r.lrange(f"queue:{topic}", 0, 9)
        text = f"📋 ОЧЕРЕДЬ ({queue_len}):\n\n"
        for i, item in enumerate(queue_items):
            parts = item.split(":")
            anonymous_id = parts[1] if len(parts) > 1 else "???"
            text += f"{i+1}. {anonymous_id}\n"
        await safe_send_message(doctor_id, text)
    await call.answer()


@router.callback_query(lambda c: c.data == "show_status")
async def show_status_callback(call: CallbackQuery):
    doctor_id = call.from_user.id
    if not await is_doctor(doctor_id):
        await call.answer("⛔ Только для врачей")
        return
    topic = r.get(f"doctor:{doctor_id}:topic")
    current = get_current_client(doctor_id)
    queue_len = await get_queue_length(topic) if topic else 0
    text = f"📊 Статус: {get_doctor_status(doctor_id)}\nСпециализация: {TOPICS.get(topic, '?')}\n"
    text += f"👤 Текущий клиент: {current or 'нет'}\n📋 Очередь: {queue_len}"
    await call.message.edit_text(text, reply_markup=get_doctor_status_keyboard())
    await call.answer()