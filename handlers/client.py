from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from config import TOPICS, PHONE_NUMBER
from services.validators import is_blocked, is_doctor, has_active_consultation, get_doctor_status, get_current_client, update_client_activity
from services.routing import get_doctor, get_available_doctors_list
from database.queue import add_to_queue, get_queue_length
from database.consultations import save_consultation_start, save_consultation_end
from database.payments import save_payment, confirm_payment, get_pending_payment
from database.doctors import get_all_doctors, get_doctor_name
from utils.helpers import safe_send_message, safe_send_photo, get_anonymous_id
from keyboards.client import get_client_main_keyboard, get_payment_keyboard, get_waiting_keyboard, get_doctors_list_keyboard, get_support_keyboard, get_rating_keyboard
from states.forms import PaymentState, WaitingState

router = Router()
# ============================================
# ВЫБОР СПЕЦИАЛИСТА
# ============================================

@router.message(F.text.in_(list(TOPICS.values())))
async def select_topic(message: Message, state: FSMContext):
    user_id = message.from_user.id
    
    if await is_blocked(user_id):
        await safe_send_message(user_id, "⛔ Ваш аккаунт заблокирован.")
        return
    
    if await has_active_consultation(user_id):
        await safe_send_message(user_id, "⚠️ У вас уже есть активная консультация!")
        return
    
    topic_key = None
    for key, value in TOPICS.items():
        if value == message.text:
            topic_key = key
            break
    
    anonymous_id = get_anonymous_id(topic_key, user_id)
    queue_position = await add_to_queue(topic_key, user_id, anonymous_id)
    consultation_id = await save_consultation_start(user_id, anonymous_id, None, topic_key)
    
    await safe_send_message(
        user_id,
        f"✅ Вы добавлены в очередь к {message.text}\n"
        f"Ваш ID: {anonymous_id}\n"
        f"Позиция в очереди: {queue_position}\n\n"
        f"💳 Оплата: {PHONE_NUMBER} (СБП/карта)\n"
        f"💰 Стоимость: 500₽\n\n"
        f"После оплаты нажмите кнопку ниже:",
        reply_markup=get_payment_keyboard(topic_key)
    )
    await state.set_state(PaymentState.waiting_payment)

# ============================================
# ВЫБОР КОНКРЕТНОГО ВРАЧА
# ============================================

@router.message(F.text == "👨‍⚕️ Выбрать врача")
async def choose_doctor_menu(message: Message):
    user_id = message.from_user.id
    if await is_doctor(user_id):
        await safe_send_message(user_id, "👨‍⚕️ Вы врач. Используйте /start для панели управления.")
        return
    
    doctors = await get_all_doctors()
    if not doctors:
        await safe_send_message(user_id, "❌ В данный момент нет доступных врачей.")
        return
    
    # Группируем и показываем список
    from config import TOPICS
    kb = get_doctors_list_keyboard(doctors)
    
    await safe_send_message(
        user_id,
        "👨‍⚕️ <b>Выберите врача</b>\n\n🟢 — онлайн, 🔴 — офлайн",
        reply_markup=kb,
        parse_mode="HTML"
    )

@router.callback_query(lambda c: c.data.startswith("select_doctor:"))
async def select_specific_doctor(call: CallbackQuery, state: FSMContext):
    user_id = call.from_user.id
    doctor_id = int(call.data.split(":")[1])
    
    doctors = await get_all_doctors()
    selected_doctor = None
    for doc in doctors:
        if doc[0] == doctor_id:
            selected_doctor = doc
            break
    
    if not selected_doctor:
        await call.message.edit_text("❌ Врач не найден.")
        await call.answer()
        return
    
    doctor_name, topic_key = selected_doctor[1], selected_doctor[2]
    doctor_status = get_doctor_status(doctor_id)
    
    if doctor_status != "online" or get_current_client(doctor_id):
        kb = get_waiting_keyboard(topic_key)
        await call.message.edit_text(
            f"⚠️ {doctor_name} сейчас не в сети.\n\n"
            f"Вы можете подождать или выбрать другого врача.",
            reply_markup=kb
        )
        await state.update_data(waiting_doctor_id=doctor_id, waiting_doctor_name=doctor_name, waiting_topic=topic_key)
        await state.set_state(WaitingState.waiting_for_specific_doctor)
        await call.answer()
        return
    
    anonymous_id = get_anonymous_id(topic_key, user_id)
    consultation_id = await save_consultation_start(user_id, anonymous_id, doctor_id, topic_key)
    
    if consultation_id:
        await safe_send_message(
            user_id,
            f"💰 Консультация с {doctor_name} ({TOPICS[topic_key]}) — 500 ₽\n\n"
            f"📞 Оплата: {PHONE_NUMBER} (СБП/карта)\n"
            f"Ваш ID: {anonymous_id}\n\n"
            f"После оплаты нажмите кнопку ниже:",
            reply_markup=get_payment_keyboard(topic_key)
        )
        await state.set_state(PaymentState.waiting_payment)
    
    await call.answer()

# ============================================
# ОПЛАТА
# ============================================

@router.callback_query(lambda c: c.data.startswith("paid_"))
async def process_payment_button(call: CallbackQuery, state: FSMContext):
    topic_key = call.data.split("_")[1]
    user_id = call.from_user.id
    
    await safe_send_message(user_id, "📎 Отправьте скриншот или фото чека.")
    await state.update_data(payment_topic=topic_key)
    await state.set_state(PaymentState.waiting_receipt)
    await call.answer()

@router.message(PaymentState.waiting_receipt, F.photo)
async def handle_receipt(message: Message, state: FSMContext):
    user_id = message.from_user.id
    data = await state.get_data()
    topic_key = data.get("payment_topic")
    
    if not topic_key:
        await safe_send_message(user_id, "❌ Ошибка: не выбрана тема. Начните заново с /start")
        await state.clear()
        return
    
    from database.db import get_db
    db = await get_db()
    cursor = await db.execute('''
        SELECT id FROM consultations 
        WHERE client_id = ? AND status IN ('waiting_payment', 'paid')
        ORDER BY id DESC LIMIT 1
    ''', (user_id,))
    row = await cursor.fetchone()
    consultation_id = row[0] if row else None
    
    if not consultation_id:
        await safe_send_message(user_id, "❌ Ошибка: консультация не найдена.")
        await state.clear()
        return
    
    anonymous_id = get_anonymous_id(topic_key, user_id)
    await save_payment(user_id, consultation_id, message.photo[-1].file_id)
    
    from keyboards.doctor import get_doctor_main_keyboard
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"confirm_payment:{user_id}"),
         InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_payment:{user_id}")]
    ])
    
    doctor_id = get_doctor(topic_key)
    if doctor_id:
        await safe_send_photo(
            doctor_id,
            message.photo[-1].file_id,
            caption=f"🧾 Чек от клиента {anonymous_id}\nТема: {TOPICS[topic_key]}",
            reply_markup=keyboard
        )
    
    await safe_send_message(user_id, "✅ Чек отправлен врачу. Ожидайте подтверждения.")
    await state.clear()

# ============================================
# ПОДТВЕРЖДЕНИЕ ОПЛАТЫ ВРАЧОМ
# ============================================

@router.callback_query(lambda c: c.data.startswith("confirm_payment:"))
async def confirm_payment_callback(call: CallbackQuery):
    doctor_id = call.from_user.id
    if not await is_doctor(doctor_id):
        return await call.answer("⛔ Только для врачей")
    
    client_id = int(call.data.split(":")[1])
    
    from database.db import get_db
    db = await get_db()
    cursor = await db.execute('''
        SELECT consultation_id FROM payments
        WHERE client_id = ? AND status = "pending"
        ORDER BY id DESC LIMIT 1
    ''', (client_id,))
    row = await cursor.fetchone()
    
    if not row:
        return await call.answer("Платёж не найден")
    
    consultation_id = row[0]
    
    if await confirm_payment(client_id, consultation_id):
        await safe_send_message(client_id, "✅ Оплата подтверждена! Ожидайте врача.")
        await call.message.edit_caption(call.message.caption + "\n\n✅ Оплата подтверждена")
        await call.answer("Подтверждено")
    else:
        await call.answer("Оплата уже подтверждена")

@router.callback_query(lambda c: c.data.startswith("reject_payment:"))
async def reject_payment_callback(call: CallbackQuery):
    doctor_id = call.from_user.id
    if not await is_doctor(doctor_id):
        return await call.answer("⛔ Только для врачей")
    
    client_id = int(call.data.split(":")[1])
    
    from database.db import get_db
    db = await get_db()
    await db.execute('''
        UPDATE payments SET status = "rejected"
        WHERE client_id = ? AND status = "pending"
    ''', (client_id,))
    await db.commit()
    
    await safe_send_message(client_id, "❌ Оплата отклонена. Попробуйте снова.")
    await call.message.edit_caption(call.message.caption + "\n\n❌ Оплата отклонена")
    await call.answer("Отклонено")

# ============================================
# ОЖИДАНИЕ ВРАЧА
# ============================================

@router.callback_query(lambda c: c.data.startswith("wait:"))
async def wait_for_doctor(call: CallbackQuery, state: FSMContext):
    topic_key = call.data.split(":")[1]
    user_id = call.from_user.id
    anonymous_id = get_anonymous_id(topic_key, user_id)
    
    position = await add_to_queue(topic_key, user_id, anonymous_id)
    
    await call.message.edit_text(
        f"⏳ Вы добавлены в очередь к {TOPICS[topic_key]}.\n"
        f"Ваша позиция: {position}\n\n"
        f"Как только врач освободится, мы уведомим вас.\n"
        f"После уведомления нужно будет оплатить консультацию."
    )
    
    from services.notifications import notify_new_queue_client
    doctor_id = get_doctor(topic_key)
    if doctor_id:
        await notify_new_queue_client(doctor_id, TOPICS[topic_key], position)
    
    await state.clear()
    await call.answer()

@router.callback_query(lambda c: c.data == "back_to_menu")
async def back_to_menu(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("🐾 Выберите специалиста:", reply_markup=get_client_main_keyboard())
    await call.answer()