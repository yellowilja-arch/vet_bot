import asyncio
import logging
import os
import redis
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ============================================
# НАСТРОЙКИ
# ============================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
GROUP_ID = os.getenv("GROUP_ID")
ADMIN_IDS = os.getenv("ADMIN_IDS")
PHONE_NUMBER = os.getenv("PHONE_NUMBER", "+79256530940")

print("=" * 50)
print("ПРОВЕРКА ПЕРЕМЕННЫХ ОКРУЖЕНИЯ:")
print(f"BOT_TOKEN: {'✅ НАЙДЕН' if BOT_TOKEN else '❌ ОТСУТСТВУЕТ'}")
print(f"GROUP_ID: {GROUP_ID if GROUP_ID else '❌ ОТСУТСТВУЕТ'}")
print(f"ADMIN_IDS: {ADMIN_IDS if ADMIN_IDS else '❌ ОТСУТСТВУЕТ'}")
print(f"PHONE_NUMBER: {PHONE_NUMBER}")
print("=" * 50)

if not BOT_TOKEN:
    print("❌ КРИТИЧЕСКАЯ ОШИБКА: BOT_TOKEN не найден!")
    exit(1)

GROUP_ID = int(GROUP_ID) if GROUP_ID else None
ADMIN_IDS = [int(x.strip()) for x in ADMIN_IDS.split(",")] if ADMIN_IDS else []

redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
r = redis.from_url(redis_url, decode_responses=True)

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

logging.basicConfig(level=logging.INFO)

# ============================================
# НАСТРОЙКИ ВРАЧЕЙ
# ============================================

TOPICS = {
    "dentistry": "Стоматолог",
    "surgery": "Хирург",
    "therapy": "Терапевт"
}

DOCTORS = {
    "dentistry": [1092230808],
    "surgery": [222222222],
    "therapy": [1906114179]
}

# ============================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================

def get_anonymous_id(topic, user_id):
    short_id = str(user_id)[-4:]
    prefix_map = {"dentistry": "ST", "surgery": "SR", "therapy": "TP"}
    prefix = prefix_map.get(topic, "CL")
    return f"{prefix}{short_id}"

def get_doctor(topic):
    if topic == "therapy":
        current_idx = int(r.get("therapy_round_robin_idx") or 0)
        doctor_id = DOCTORS["therapy"][current_idx % len(DOCTORS["therapy"])]
        r.set("therapy_round_robin_idx", current_idx + 1)
        return doctor_id
    return DOCTORS[topic][0]

def set_doctor_status(doctor_id, status):
    """status: 'online', 'offline', 'busy', 'waiting'"""
    r.set(f"doctor:{doctor_id}:status", status)

def get_doctor_status(doctor_id):
    return r.get(f"doctor:{doctor_id}:status") or "offline"

def get_current_client(doctor_id):
    return r.get(f"doctor:{doctor_id}:current_client")

def set_current_client(doctor_id, user_id):
    if user_id:
        r.set(f"doctor:{doctor_id}:current_client", user_id)
    else:
        r.delete(f"doctor:{doctor_id}:current_client")

def get_queue(topic):
    queue_key = f"queue:{topic}"
    return r.llen(queue_key)

def add_to_queue(topic, user_id, anonymous_id):
    queue_key = f"queue:{topic}"
    r.rpush(queue_key, f"{user_id}:{anonymous_id}")
    return r.llen(queue_key)

def get_queue_position(topic, user_id):
    queue_key = f"queue:{topic}"
    queue = r.lrange(queue_key, 0, -1)
    for i, item in enumerate(queue):
        if item.startswith(f"{user_id}:"):
            return i + 1
    return None

def remove_from_queue(topic, user_id):
    queue_key = f"queue:{topic}"
    queue = r.lrange(queue_key, 0, -1)
    for i, item in enumerate(queue):
        if item.startswith(f"{user_id}:"):
            r.lrem(queue_key, 1, item)
            return True
    return False

def get_next_from_queue(topic):
    queue_key = f"queue:{topic}"
    next_client = r.lpop(queue_key)
    if next_client:
        user_id, anonymous_id = next_client.split(":")
        return int(user_id), anonymous_id
    return None, None

def notify_queue_position(user_id, topic):
    position = get_queue_position(topic, user_id)
    if position:
        asyncio.create_task(bot.send_message(
            user_id,
            f"⏳ Ваша очередь: {position} позиция.\n"
            f"Как только врач освободится, вы получите уведомление."
        ))

def notify_queue_update(topic, doctor_id):
    queue_length = get_queue(topic)
    if queue_length > 0:
        asyncio.create_task(bot.send_message(
            doctor_id,
            f"📋 В очереди {queue_length} клиент(ов).\n"
            f"Используйте /next, чтобы взять следующего."
        ))

# ============================================
# КЛАВИАТУРЫ
# ============================================

def get_main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=TOPICS[t])] for t in TOPICS],
        resize_keyboard=True
    )

def get_doctor_status_keyboard(doctor_id):
    status = get_doctor_status(doctor_id)
    if status == "online":
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🟢 В сети", callback_data="status_online")],
            [InlineKeyboardButton(text="🔴 Уйти офлайн", callback_data="status_offline")],
            [InlineKeyboardButton(text="📋 Очередь", callback_data="view_queue")],
            [InlineKeyboardButton(text="❌ Завершить", callback_data="end_current")],
        ])
    else:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⚫ Не в сети", callback_data="status_offline")],
            [InlineKeyboardButton(text="🟢 Стать онлайн", callback_data="status_online")],
        ])

def get_doctor_actions_keyboard(user_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Завершить", callback_data=f"end_confirm:{user_id}")],
        [InlineKeyboardButton(text="🔄 Перенаправить", callback_data=f"transfer_confirm:{user_id}")],
        [InlineKeyboardButton(text="⏳ Врач занят", callback_data=f"busy:{user_id}")],
        [InlineKeyboardButton(text="📋 Очередь", callback_data="view_queue")],
    ])

# ============================================
# FSM СОСТОЯНИЯ
# ============================================

class PaymentState(StatesGroup):
    waiting_payment = State()
    waiting_receipt = State()

class WaitingState(StatesGroup):
    waiting_for_doctor = State()

# ============================================
# КОМАНДЫ
# ============================================

@dp.message(Command("start"))
async def start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "🐾 Добро пожаловать в онлайн-консультации ветклиники!\n\nВыберите специалиста:",
        reply_markup=get_main_keyboard()
    )

@dp.message(Command("clients"))
async def list_active_clients_command(message: types.Message):
    doctor_id = message.from_user.id
    active_clients = r.smembers(f"doctor:{doctor_id}:active_clients")
    if not active_clients:
        await message.answer("📭 Нет активных консультаций.")
        return
    text = "📋 <b>Ваши активные клиенты:</b>\n\n"
    for client_id in active_clients:
        anonymous_id = r.get(f"user:{int(client_id)}:anonymous_id") or "клиент"
        text += f"• {anonymous_id}\n"
    await message.answer(text, parse_mode="HTML")

@dp.message(Command("online"))
async def go_online(message: types.Message):
    doctor_id = message.from_user.id
    set_doctor_status(doctor_id, "online")
    await message.answer("🟢 Вы стали онлайн. Клиенты смогут записываться к вам.", reply_markup=get_doctor_status_keyboard(doctor_id))

@dp.message(Command("offline"))
async def go_offline(message: types.Message):
    doctor_id = message.from_user.id
    set_doctor_status(doctor_id, "offline")
    await message.answer("🔴 Вы стали офлайн. Клиенты не будут направляться к вам.", reply_markup=get_doctor_status_keyboard(doctor_id))

@dp.message(Command("next"))
async def take_next_client(message: types.Message):
    doctor_id = message.from_user.id
    topic = r.get(f"doctor:{doctor_id}:topic")
    if not topic:
        await message.answer("❌ Не удалось определить вашу специализацию.")
        return
    
    next_client_id, next_anonymous_id = get_next_from_queue(topic)
    if next_client_id:
        set_current_client(doctor_id, next_client_id)
        r.sadd(f"doctor:{doctor_id}:active_clients", next_client_id)
        r.set(f"client:{next_client_id}:doctor", doctor_id)
        r.set(f"user:{next_client_id}:active", 1)
        
        await bot.send_message(
            next_client_id,
            f"✅ Врач принял вашу заявку! Консультация начинается.\nВаш ID: {next_anonymous_id}"
        )
        await message.answer(f"✅ Клиент {next_anonymous_id} принят. Напишите сообщение.")
        
        queue_length = get_queue(topic)
        if queue_length > 0:
            await message.answer(f"📋 В очереди осталось {queue_length} клиент(ов).")
    else:
        await message.answer("📭 Очередь пуста.")

@dp.message(Command("status"))
async def show_status(message: types.Message):
    doctor_id = message.from_user.id
    status = get_doctor_status(doctor_id)
    current_client = get_current_client(doctor_id)
    topic = r.get(f"doctor:{doctor_id}:topic")
    queue_length = get_queue(topic) if topic else 0
    
    text = f"📊 <b>Ваш статус:</b>\n\n"
    text += f"🟢 Статус: {'Онлайн' if status == 'online' else 'Офлайн'}\n"
    if current_client:
        anonymous_id = r.get(f"user:{int(current_client)}:anonymous_id") or "клиент"
        text += f"👤 Текущий клиент: {anonymous_id}\n"
    else:
        text += f"👤 Текущий клиент: нет\n"
    text += f"📋 В очереди: {queue_length}\n"
    
    await message.answer(text, parse_mode="HTML", reply_markup=get_doctor_status_keyboard(doctor_id))

# ============================================
# ВЫБОР СПЕЦИАЛИСТА
# ============================================

@dp.message(F.text.in_(list(TOPICS.values())))
async def choose_topic(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    topic_key = None
    for k, v in TOPICS.items():
        if v == message.text:
            topic_key = k
            break
    
    doctor_id = get_doctor(topic_key)
    doctor_status = get_doctor_status(doctor_id)
    
    if doctor_status != "online":
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, я готов ждать", callback_data=f"wait:{topic_key}")],
            [InlineKeyboardButton(text="🔙 Выбрать другого врача", callback_data="back_to_menu")]
        ])
        await message.answer(
            f"⚠️ {TOPICS[topic_key]} сейчас не может ответить.\n\n"
            f"Вы можете:\n"
            f"• Подождать — мы уведомим вас, когда врач освободится\n"
            f"• Выбрать другого специалиста\n\n"
            f"Ждать консультации?",
            reply_markup=kb
        )
        await state.update_data(topic=topic_key, topic_name=message.text)
        await state.set_state(WaitingState.waiting_for_doctor)
        return
    
    anonymous_id = get_anonymous_id(topic_key, user_id)
    r.set(f"user:{user_id}:topic", topic_key)
    r.set(f"user:{user_id}:anonymous_id", anonymous_id)
    await state.update_data(topic=message.text, anonymous_id=anonymous_id)
    
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="✅ Я оплатил")]], resize_keyboard=True)
    await message.answer(
        f"💰 Консультация {message.text} — 500 ₽\n\n"
        f"📞 Оплата по номеру телефона (СБП):\n<code>{PHONE_NUMBER}</code>\n\n"
        f"Ваш ID для консультации: <b>{anonymous_id}</b>\n\n"
        f"После оплаты нажмите кнопку ниже и отправьте чек.",
        reply_markup=kb, parse_mode="HTML"
    )
    await state.set_state(PaymentState.waiting_payment)

# ============================================
# ОЖИДАНИЕ ВРАЧА
# ============================================

@dp.callback_query(lambda c: c.data.startswith("wait:"))
async def wait_for_doctor(call: types.CallbackQuery, state: FSMContext):
    topic_key = call.data.split(":")[1]
    user_id = call.from_user.id
    anonymous_id = get_anonymous_id(topic_key, user_id)
    
    position = add_to_queue(topic_key, user_id, anonymous_id)
    r.set(f"user:{user_id}:topic", topic_key)
    r.set(f"user:{user_id}:anonymous_id", anonymous_id)
    r.set(f"user:{user_id}:payment_status", "queued")
    
    await call.message.edit_text(
        f"⏳ Вы добавлены в очередь к {TOPICS[topic_key]}.\n"
        f"Ваша позиция: {position}\n\n"
        f"Как только врач освободится, мы уведомим вас.\n"
        f"После уведомления нужно будет оплатить консультацию."
    )
    
    # Уведомляем врача о новом клиенте в очереди
    doctor_id = get_doctor(topic_key)
    await bot.send_message(
        doctor_id,
        f"🆕 Новый клиент в очереди к {TOPICS[topic_key]}!\n"
        f"Всего в очереди: {get_queue(topic_key)}.\n"
        f"Используйте /next, чтобы взять следующего.",
        reply_markup=get_doctor_status_keyboard(doctor_id)
    )
    
    await state.clear()
    await call.answer()

@dp.callback_query(lambda c: c.data == "back_to_menu")
async def back_to_menu(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("🐾 Выберите специалиста:", reply_markup=get_main_keyboard())
    await call.answer()

# ============================================
# ОПЛАТА
# ============================================

@dp.message(F.text == "✅ Я оплатил", PaymentState.waiting_payment)
async def paid_button(message: types.Message, state: FSMContext):
    await message.answer("📎 Отправьте скриншот или фото чека.")
    await state.set_state(PaymentState.waiting_receipt)

@dp.message(PaymentState.waiting_receipt, F.photo)
async def handle_receipt(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    topic_key = r.get(f"user:{user_id}:topic")
    anonymous_id = r.get(f"user:{user_id}:anonymous_id")
    doctor_id = get_doctor(topic_key)
    
    # Отправляем чек врачу
    await bot.send_photo(
        doctor_id,
        message.photo[-1].file_id,
        caption=f"🧾 НОВЫЙ ЧЕК\n👤 Клиент: {anonymous_id}\n📂 Тема: {TOPICS[topic_key]}\n\n💰 Сумма: 500 ₽\n✅ Требуется подтверждение.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Принять оплату", callback_data=f"accept_payment:{user_id}")],
            [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_payment:{user_id}")]
        ])
    )
    
    await message.answer("✅ Чек отправлен врачу. Ожидайте подтверждения оплаты.")
    await state.clear()

# ============================================
# ПОДТВЕРЖДЕНИЕ ОПЛАТЫ ВРАЧОМ
# ============================================

@dp.callback_query(lambda c: c.data.startswith("accept_payment:"))
async def accept_payment(call: types.CallbackQuery):
    user_id = int(call.data.split(":")[1])
    doctor_id = call.from_user.id
    topic_key = r.get(f"user:{user_id}:topic")
    anonymous_id = r.get(f"user:{user_id}:anonymous_id")
    
    # Проверяем, свободен ли врач
    current_client = get_current_client(doctor_id)
    if current_client:
        await call.message.answer("⚠️ У вас уже есть активный клиент. Завершите текущую консультацию сначала.")
        await call.answer()
        return
    
    # Подключаем клиента
    set_current_client(doctor_id, user_id)
    r.sadd(f"doctor:{doctor_id}:active_clients", user_id)
    r.set(f"client:{user_id}:doctor", doctor_id)
    r.set(f"user:{user_id}:active", 1)
    r.set(f"user:{user_id}:payment_status", "paid")
    
    await bot.send_message(
        user_id,
        f"✅ Оплата подтверждена! Врач принял вашу заявку.\nВаш ID: {anonymous_id}\n\nВрач скоро свяжется с вами."
    )
    
    await call.message.edit_text(
        f"✅ Оплата клиента {anonymous_id} подтверждена.\n"
        f"Клиент подключён. Напишите сообщение."
    )
    await call.answer()

@dp.callback_query(lambda c: c.data.startswith("reject_payment:"))
async def reject_payment(call: types.CallbackQuery):
    user_id = int(call.data.split(":")[1])
    await bot.send_message(user_id, "❌ Оплата не подтверждена. Пожалуйста, проверьте чек и попробуйте снова.")
    await call.message.edit_text("❌ Оплата отклонена.")
    await call.answer()

# ============================================
# УПРАВЛЕНИЕ СТАТУСОМ ВРАЧА
# ============================================

@dp.callback_query(lambda c: c.data == "status_online")
async def set_online(call: types.CallbackQuery):
    doctor_id = call.from_user.id
    set_doctor_status(doctor_id, "online")
    await call.message.edit_text("🟢 Вы онлайн.", reply_markup=get_doctor_status_keyboard(doctor_id))
    await call.answer()

@dp.callback_query(lambda c: c.data == "status_offline")
async def set_offline(call: types.CallbackQuery):
    doctor_id = call.from_user.id
    set_doctor_status(doctor_id, "offline")
    await call.message.edit_text("🔴 Вы офлайн.", reply_markup=get_doctor_status_keyboard(doctor_id))
    await call.answer()

@dp.callback_query(lambda c: c.data == "view_queue")
async def view_queue(call: types.CallbackQuery):
    doctor_id = call.from_user.id
    topic = r.get(f"doctor:{doctor_id}:topic")
    if not topic:
        await call.message.answer("❌ Не удалось определить вашу специализацию.")
        await call.answer()
        return
    
    queue_length = get_queue(topic)
    if queue_length == 0:
        await call.message.answer("📭 Очередь пуста.")
    else:
        queue_items = r.lrange(f"queue:{topic}", 0, 9)
        text = f"📋 ОЧЕРЕДЬ ({queue_length}):\n\n"
        for i, item in enumerate(queue_items):
            _, anonymous_id = item.split(":")
            text += f"{i+1}. {anonymous_id}\n"
        await call.message.answer(text)
    await call.answer()

@dp.callback_query(lambda c: c.data == "end_current")
async def end_current_prompt(call: types.CallbackQuery):
    doctor_id = call.from_user.id
    current_client = get_current_client(doctor_id)
    if not current_client:
        await call.message.answer("⚠️ Нет активного клиента.")
        await call.answer()
        return
    
    anonymous_id = r.get(f"user:{int(current_client)}:anonymous_id") or "клиент"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, завершить", callback_data="end_confirm")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]
    ])
    await call.message.answer(f"⚠️ Завершить консультацию с {anonymous_id}?", reply_markup=kb)
    await call.answer()

@dp.callback_query(lambda c: c.data == "end_confirm")
async def end_current_consultation(call: types.CallbackQuery):
    doctor_id = call.from_user.id
    current_client = get_current_client(doctor_id)
    
    if current_client:
        anonymous_id = r.get(f"user:{int(current_client)}:anonymous_id") or "клиент"
        
        # Очищаем данные
        r.srem(f"doctor:{doctor_id}:active_clients", current_client)
        r.delete(f"client:{current_client}:doctor")
        r.delete(f"user:{current_client}:active")
        set_current_client(doctor_id, None)
        
        await bot.send_message(int(current_client), "🏁 Консультация завершена. Спасибо, что обратились к нам!")
        
        # Проверяем очередь
        topic = r.get(f"doctor:{doctor_id}:topic")
        if topic:
            queue_length = get_queue(topic)
            if queue_length > 0:
                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="✅ Взять следующего", callback_data="take_next")]
                ])
                await call.message.answer(
                    f"✅ Консультация с {anonymous_id} завершена.\n"
                    f"📋 В очереди {queue_length} клиент(ов).\n"
                    f"Взять следующего?",
                    reply_markup=kb
                )
            else:
                await call.message.answer(f"✅ Консультация с {anonymous_id} завершена. Очередь пуста.")
    
    await call.answer()

@dp.callback_query(lambda c: c.data == "take_next")
async def take_next_after_end(call: types.CallbackQuery):
    doctor_id = call.from_user.id
    topic = r.get(f"doctor:{doctor_id}:topic")
    
    next_client_id, next_anonymous_id = get_next_from_queue(topic)
    if next_client_id:
        set_current_client(doctor_id, next_client_id)
        r.sadd(f"doctor:{doctor_id}:active_clients", next_client_id)
        r.set(f"client:{next_client_id}:doctor", doctor_id)
        r.set(f"user:{next_client_id}:active", 1)
        
        await bot.send_message(
            next_client_id,
            f"✅ Врач принял вашу заявку! Консультация начинается.\nВаш ID: {next_anonymous_id}"
        )
        await call.message.answer(f"✅ Клиент {next_anonymous_id} принят. Напишите сообщение.")
    else:
        await call.message.answer("📭 Очередь пуста.")
    
    await call.answer()

# ============================================
# ЧАТ
# ============================================

@dp.message()
async def chat_messages(message: types.Message):
    user_id = message.from_user.id
    
    if message.text in ["✅ Я оплатил"] + list(TOPICS.values()):
        return
    
    # Клиент → Врач
    if r.get(f"user:{user_id}:active"):
        doctor_id = r.get(f"client:{user_id}:doctor")
        anonymous_id = r.get(f"user:{user_id}:anonymous_id") or "клиент"
        if doctor_id:
            await bot.send_message(
                int(doctor_id),
                f"👤 {anonymous_id}: {message.text}",
                reply_markup=get_doctor_actions_keyboard(user_id)
            )
    
    # Врач → Клиент
    elif r.get(f"doctor:{user_id}:current_client"):
        client_id = r.get(f"doctor:{user_id}:current_client")
        if client_id:
            await bot.send_message(
                int(client_id),
                f"👨‍⚕️ Врач: {message.text}"
            )

# ============================================
# ЗАПУСК
# ============================================

async def set_commands():
    await bot.set_my_commands([
        BotCommand(command="start", description="Начать консультацию"),
        BotCommand(command="status", description="Мой статус"),
        BotCommand(command="online", description="Стать онлайн"),
        BotCommand(command="offline", description="Стать офлайн"),
        BotCommand(command="next", description="Взять следующего клиента"),
    ])

async def main():
    await set_commands()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())