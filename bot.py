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
from aiogram.exceptions import TelegramForbiddenError

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
# БЕЗОПАСНАЯ ОТПРАВКА СООБЩЕНИЙ
# ============================================

async def safe_send_message(chat_id, text, **kwargs):
    """Безопасная отправка сообщения с обработкой блокировки"""
    try:
        return await bot.send_message(chat_id, text, **kwargs)
    except TelegramForbiddenError:
        print(f"⚠️ Пользователь {chat_id} заблокировал бота")
        
        if r.get(f"user:{chat_id}:active"):
            doctor_id = r.get(f"client:{chat_id}:doctor")
            if doctor_id:
                doctor_id = int(doctor_id)
                r.delete(f"client:{chat_id}:doctor")
                r.delete(f"user:{chat_id}:active")
                r.delete(f"user:{chat_id}:payment_status")
                
                if get_current_client(doctor_id) == str(chat_id):
                    set_current_client(doctor_id, None)
                
                await safe_send_message(
                    doctor_id,
                    f"⚠️ Клиент {r.get(f'user:{chat_id}:anonymous_id') or 'ID ' + str(chat_id)} заблокировал бота.\n"
                    f"Консультация автоматически завершена.\n\n"
                    f"Используйте /next для следующего клиента."
                )
                
                topic = r.get(f"doctor:{doctor_id}:topic")
                if topic and get_queue(topic) > 0:
                    await safe_send_message(
                        doctor_id,
                        f"📋 В очереди {get_queue(topic)} клиент(ов). Используйте /next."
                    )
        return None
    except Exception as e:
        print(f"Ошибка при отправке сообщения {chat_id}: {e}")
        return None

async def safe_send_photo(chat_id, photo, caption=None, **kwargs):
    """Безопасная отправка фото с обработкой блокировки"""
    try:
        return await bot.send_photo(chat_id, photo, caption=caption, **kwargs)
    except TelegramForbiddenError:
        print(f"⚠️ Пользователь {chat_id} заблокировал бота (фото)")
        return None
    except Exception as e:
        print(f"Ошибка при отправке фото {chat_id}: {e}")
        return None

# ============================================
# НАСТРОЙКИ ВРАЧЕЙ
# ============================================

TOPICS = {
    "dentistry": "Стоматолог",
    "surgery": "Хирург",
    "therapy": "Терапевт"
}

DOCTORS = {
    "dentistry": [1092230808],   # 👈 ВАШ ID (стоматолог)
    "surgery": [222222222],      # 👈 ЗАМЕНИТЕ на ID хирурга
    "therapy": [1906114179]      # 👈 Терапевт
}

# Автоматически собираем список всех врачей
DOCTOR_IDS = []
for docs in DOCTORS.values():
    DOCTOR_IDS.extend(docs)
DOCTOR_IDS = list(set(DOCTOR_IDS))

def is_doctor(user_id):
    return user_id in DOCTOR_IDS

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

def get_next_from_queue(topic):
    queue_key = f"queue:{topic}"
    next_client = r.lpop(queue_key)
    if next_client:
        user_id, anonymous_id = next_client.split(":")
        return int(user_id), anonymous_id
    return None, None

# ============================================
# АВТОМАТИЧЕСКАЯ НАСТРОЙКА СПЕЦИАЛИЗАЦИИ ВРАЧЕЙ
# ============================================

for topic_name, doctor_ids in DOCTORS.items():
    for doctor_id in doctor_ids:
        if not r.get(f"doctor:{doctor_id}:topic"):
            r.set(f"doctor:{doctor_id}:topic", topic_name)
            print(f"✅ Установлена специализация {TOPICS[topic_name]} для врача {doctor_id}")

print(f"📋 Всего врачей в системе: {len(DOCTOR_IDS)}")
for doctor_id in DOCTOR_IDS:
    topic = r.get(f"doctor:{doctor_id}:topic")
    print(f"   • {doctor_id} → {TOPICS.get(topic, 'не назначена')}")

# ============================================
# КЛАВИАТУРЫ
# ============================================

def get_main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=TOPICS[t])] for t in TOPICS],
        resize_keyboard=True
    )

def get_doctor_main_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🟢 Стать онлайн", callback_data="doctor_online")],
        [InlineKeyboardButton(text="🔴 Стать офлайн", callback_data="doctor_offline")],
        [InlineKeyboardButton(text="📋 Посмотреть очередь", callback_data="view_queue")],
        [InlineKeyboardButton(text="📊 Мой статус", callback_data="show_status")],
    ])

def get_doctor_status_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Очередь", callback_data="view_queue")],
        [InlineKeyboardButton(text="❌ Завершить текущего", callback_data="end_current")],
    ])

def get_doctor_actions_keyboard(user_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Завершить", callback_data=f"end_confirm:{user_id}")],
        [InlineKeyboardButton(text="🔄 Перенаправить", callback_data=f"transfer_confirm:{user_id}")],
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
    user_id = message.from_user.id
    
    if is_doctor(user_id):
        await safe_send_message(
            user_id,
            "👨‍⚕️ <b>Панель управления врача</b>\n\n"
            "Используйте кнопки ниже или команды:\n"
            "• /online — стать онлайн\n"
            "• /offline — стать офлайн\n"
            "• /status — мой статус\n"
            "• /next — взять следующего клиента\n"
            "• /clients — список активных клиентов\n\n"
            "Текущий статус: " + ("🟢 Онлайн" if get_doctor_status(user_id) == "online" else "🔴 Офлайн"),
            reply_markup=get_doctor_main_keyboard(),
            parse_mode="HTML"
        )
    else:
        await safe_send_message(
            user_id,
            "🐾 Добро пожаловать в онлайн-консультации ветклиники!\n\nВыберите специалиста:",
            reply_markup=get_main_keyboard()
        )

@dp.message(Command("online"))
async def go_online(message: types.Message):
    user_id = message.from_user.id
    if not is_doctor(user_id):
        await safe_send_message(user_id, "⛔ Эта команда только для врачей.")
        return
    
    set_doctor_status(user_id, "online")
    await safe_send_message(
        user_id,
        "🟢 Вы стали онлайн. Клиенты могут записываться к вам.",
        reply_markup=get_doctor_main_keyboard()
    )

@dp.message(Command("offline"))
async def go_offline(message: types.Message):
    user_id = message.from_user.id
    if not is_doctor(user_id):
        await safe_send_message(user_id, "⛔ Эта команда только для врачей.")
        return
    
    set_doctor_status(user_id, "offline")
    await safe_send_message(
        user_id,
        "🔴 Вы стали офлайн. Клиенты не будут направляться к вам.",
        reply_markup=get_doctor_main_keyboard()
    )

@dp.message(Command("status"))
async def show_status(message: types.Message):
    user_id = message.from_user.id
    if not is_doctor(user_id):
        await safe_send_message(user_id, "⛔ Эта команда только для врачей.")
        return
    
    status = get_doctor_status(user_id)
    current_client = get_current_client(user_id)
    topic = r.get(f"doctor:{user_id}:topic")
    queue_length = get_queue(topic) if topic else 0
    
    text = f"📊 <b>Ваш статус:</b>\n\n"
    text += f"🟢 Статус: {'Онлайн' if status == 'online' else 'Офлайн'}\n"
    text += f"📂 Специализация: {TOPICS.get(topic, 'Неизвестно')}\n"
    if current_client:
        anonymous_id = r.get(f"user:{int(current_client)}:anonymous_id") or "клиент"
        text += f"👤 Текущий клиент: {anonymous_id}\n"
    else:
        text += f"👤 Текущий клиент: нет\n"
    text += f"📋 В очереди: {queue_length}\n"
    
    await safe_send_message(user_id, text, parse_mode="HTML", reply_markup=get_doctor_status_keyboard())

@dp.message(Command("next"))
async def take_next_client(message: types.Message):
    user_id = message.from_user.id
    if not is_doctor(user_id):
        await safe_send_message(user_id, "⛔ Эта команда только для врачей.")
        return
    
    topic = r.get(f"doctor:{user_id}:topic")
    if not topic:
        await safe_send_message(user_id, "❌ Не удалось определить вашу специализацию.")
        return
    
    next_client_id, next_anonymous_id = get_next_from_queue(topic)
    if next_client_id:
        set_current_client(user_id, next_client_id)
        r.set(f"client:{next_client_id}:doctor", user_id)
        r.set(f"user:{next_client_id}:active", 1)
        
        await safe_send_message(
            next_client_id,
            f"✅ Врач принял вашу заявку! Консультация начинается.\nВаш ID: {next_anonymous_id}"
        )
        await safe_send_message(user_id, f"✅ Клиент {next_anonymous_id} принят. Напишите сообщение.")
    else:
        await safe_send_message(user_id, "📭 Очередь пуста.")

@dp.message(Command("clients"))
async def list_active_clients(message: types.Message):
    user_id = message.from_user.id
    if not is_doctor(user_id):
        await safe_send_message(user_id, "⛔ Эта команда только для врачей.")
        return
    
    current_client = get_current_client(user_id)
    if current_client:
        anonymous_id = r.get(f"user:{int(current_client)}:anonymous_id") or "клиент"
        await safe_send_message(user_id, f"👤 Текущий клиент: {anonymous_id}")
    else:
        await safe_send_message(user_id, "📭 Нет активного клиента.")

# ============================================
# КЛИЕНТ: ВЫБОР СПЕЦИАЛИСТА
# ============================================

@dp.message(F.text.in_(list(TOPICS.values())))
async def choose_topic(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    
    if is_doctor(user_id):
        await safe_send_message(user_id, "👨‍⚕️ Вы врач. Используйте /start для панели управления.")
        return
    
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
        await safe_send_message(
            user_id,
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
    await safe_send_message(
        user_id,
        f"💰 Консультация {message.text} — 500 ₽\n\n"
        f"📞 Оплата по номеру телефона (СБП):\n<code>{PHONE_NUMBER}</code>\n\n"
        f"Ваш ID для консультации: <b>{anonymous_id}</b>\n\n"
        f"После оплаты нажмите кнопку ниже и отправьте чек.",
        reply_markup=kb, parse_mode="HTML"
    )
    await state.set_state(PaymentState.waiting_payment)

# ============================================
# КЛИЕНТ: ОЖИДАНИЕ ВРАЧА
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
    
    doctor_id = get_doctor(topic_key)
    await safe_send_message(
        doctor_id,
        f"🆕 Новый клиент в очереди к {TOPICS[topic_key]}!\n"
        f"Всего в очереди: {get_queue(topic_key)}.\n"
        f"Используйте /next, чтобы взять следующего.",
        reply_markup=get_doctor_main_keyboard()
    )
    
    await state.clear()
    await call.answer()

@dp.callback_query(lambda c: c.data == "back_to_menu")
async def back_to_menu(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("🐾 Выберите специалиста:", reply_markup=get_main_keyboard())
    await call.answer()

# ============================================
# КЛИЕНТ: ОПЛАТА
# ============================================

@dp.message(F.text == "✅ Я оплатил", PaymentState.waiting_payment)
async def paid_button(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    
    if is_doctor(user_id):
        return
    
    await safe_send_message(user_id, "📎 Отправьте скриншот или фото чека.")
    await state.set_state(PaymentState.waiting_receipt)

@dp.message(PaymentState.waiting_receipt, F.photo)
async def handle_receipt(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    
    if is_doctor(user_id):
        return
    
    topic_key = r.get(f"user:{user_id}:topic")
    anonymous_id = r.get(f"user:{user_id}:anonymous_id")
    doctor_id = get_doctor(topic_key)
    
    await safe_send_photo(
        doctor_id,
        message.photo[-1].file_id,
        caption=f"🧾 НОВЫЙ ЧЕК\n👤 Клиент: {anonymous_id}\n📂 Тема: {TOPICS[topic_key]}\n\n💰 Сумма: 500 ₽",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Принять оплату", callback_data=f"accept_payment:{user_id}")],
            [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_payment:{user_id}")]
        ])
    )
    
    await safe_send_message(user_id, "✅ Чек отправлен врачу. Ожидайте подтверждения оплаты.")
    await state.clear()

# ============================================
# ВРАЧ: ПОДТВЕРЖДЕНИЕ ОПЛАТЫ
# ============================================

@dp.callback_query(lambda c: c.data.startswith("accept_payment:"))
async def accept_payment(call: types.CallbackQuery):
    doctor_id = call.from_user.id
    
    if not is_doctor(doctor_id):
        await call.answer("⛔ Только для врачей")
        return
    
    user_id = int(call.data.split(":")[1])
    anonymous_id = r.get(f"user:{user_id}:anonymous_id") or "клиент"
    
    current_client = get_current_client(doctor_id)
    if current_client:
        await safe_send_message(doctor_id, "⚠️ У вас уже есть активный клиент. Завершите текущую консультацию сначала.")
        await call.answer()
        return
    
    set_current_client(doctor_id, user_id)
    r.set(f"client:{user_id}:doctor", doctor_id)
    r.set(f"user:{user_id}:active", 1)
    r.set(f"user:{user_id}:payment_status", "paid")
    
    await safe_send_message(
        user_id,
        f"✅ Оплата подтверждена! Врач принял вашу заявку.\nВаш ID: {anonymous_id}\n\nВрач скоро свяжется с вами."
    )
    
    await call.message.edit_text(
        f"✅ Оплата клиента {anonymous_id} подтверждена.\n"
        f"Клиент подключён. Напишите сообщение.",
        reply_markup=get_doctor_actions_keyboard(user_id)
    )
    await call.answer()

@dp.callback_query(lambda c: c.data.startswith("reject_payment:"))
async def reject_payment(call: types.CallbackQuery):
    doctor_id = call.from_user.id
    
    if not is_doctor(doctor_id):
        await call.answer("⛔ Только для врачей")
        return
    
    user_id = int(call.data.split(":")[1])
    await safe_send_message(user_id, "❌ Оплата не подтверждена. Пожалуйста, проверьте чек и попробуйте снова.")
    await call.message.edit_text("❌ Оплата отклонена.")
    await call.answer()

# ============================================
# ВРАЧ: УПРАВЛЕНИЕ СТАТУСОМ
# ============================================

@dp.callback_query(lambda c: c.data == "doctor_online")
async def doctor_set_online(call: types.CallbackQuery):
    doctor_id = call.from_user.id
    
    if not is_doctor(doctor_id):
        await call.answer("⛔ Только для врачей")
        return
    
    set_doctor_status(doctor_id, "online")
    await call.message.edit_text(
        "🟢 Вы стали онлайн. Клиенты могут записываться к вам.",
        reply_markup=get_doctor_main_keyboard()
    )
    await call.answer()

@dp.callback_query(lambda c: c.data == "doctor_offline")
async def doctor_set_offline(call: types.CallbackQuery):
    doctor_id = call.from_user.id
    
    if not is_doctor(doctor_id):
        await call.answer("⛔ Только для врачей")
        return
    
    set_doctor_status(doctor_id, "offline")
    await call.message.edit_text(
        "🔴 Вы стали офлайн. Клиенты не будут направляться к вам.",
        reply_markup=get_doctor_main_keyboard()
    )
    await call.answer()

@dp.callback_query(lambda c: c.data == "show_status")
async def doctor_show_status(call: types.CallbackQuery):
    doctor_id = call.from_user.id
    
    if not is_doctor(doctor_id):
        await call.answer("⛔ Только для врачей")
        return
    
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
    
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=get_doctor_status_keyboard())
    await call.answer()

@dp.callback_query(lambda c: c.data == "view_queue")
async def doctor_view_queue(call: types.CallbackQuery):
    doctor_id = call.from_user.id
    
    if not is_doctor(doctor_id):
        await call.answer("⛔ Только для врачей")
        return
    
    topic = r.get(f"doctor:{doctor_id}:topic")
    if not topic:
        await safe_send_message(doctor_id, "❌ Не удалось определить вашу специализацию.")
        await call.answer()
        return
    
    queue_length = get_queue(topic)
    if queue_length == 0:
        await safe_send_message(doctor_id, "📭 Очередь пуста.")
    else:
        queue_items = r.lrange(f"queue:{topic}", 0, 9)
        text = f"📋 ОЧЕРЕДЬ ({queue_length}):\n\n"
        for i, item in enumerate(queue_items):
            _, anonymous_id = item.split(":")
            text += f"{i+1}. {anonymous_id}\n"
        await safe_send_message(doctor_id, text)
    await call.answer()

@dp.callback_query(lambda c: c.data == "end_current")
async def end_current_prompt(call: types.CallbackQuery):
    doctor_id = call.from_user.id
    
    if not is_doctor(doctor_id):
        await call.answer("⛔ Только для врачей")
        return
    
    current_client = get_current_client(doctor_id)
    if not current_client:
        await safe_send_message(doctor_id, "⚠️ Нет активного клиента.")
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
    
    if not is_doctor(doctor_id):
        await call.answer("⛔ Только для врачей")
        return
    
    current_client = get_current_client(doctor_id)
    
    if current_client:
        anonymous_id = r.get(f"user:{int(current_client)}:anonymous_id") or "клиент"
        
        r.delete(f"client:{current_client}:doctor")
        r.delete(f"user:{current_client}:active")
        set_current_client(doctor_id, None)
        
        await safe_send_message(int(current_client), "🏁 Консультация завершена. Спасибо, что обратились к нам!")
        
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
                await safe_send_message(doctor_id, f"✅ Консультация с {anonymous_id} завершена. Очередь пуста.")
    
    await call.answer()

@dp.callback_query(lambda c: c.data == "take_next")
async def take_next_after_end(call: types.CallbackQuery):
    doctor_id = call.from_user.id
    
    if not is_doctor(doctor_id):
        await call.answer("⛔ Только для врачей")
        return
    
    topic = r.get(f"doctor:{doctor_id}:topic")
    
    next_client_id, next_anonymous_id = get_next_from_queue(topic)
    if next_client_id:
        set_current_client(doctor_id, next_client_id)
        r.set(f"client:{next_client_id}:doctor", doctor_id)
        r.set(f"user:{next_client_id}:active", 1)
        
        await safe_send_message(
            next_client_id,
            f"✅ Врач принял вашу заявку! Консультация начинается.\nВаш ID: {next_anonymous_id}"
        )
        await safe_send_message(doctor_id, f"✅ Клиент {next_anonymous_id} принят. Напишите сообщение.")
    else:
        await safe_send_message(doctor_id, "📭 Очередь пуста.")
    
    await call.answer()

@dp.callback_query(lambda c: c.data.startswith("end_confirm:"))
async def confirm_end_prompt(call: types.CallbackQuery):
    doctor_id = call.from_user.id
    
    if not is_doctor(doctor_id):
        await call.answer("⛔ Только для врачей")
        return
    
    user_id = int(call.data.split(":")[1])
    anonymous_id = r.get(f"user:{user_id}:anonymous_id") or "клиент"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, завершить", callback_data=f"end:{user_id}")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]
    ])
    await call.message.answer(f"⚠️ Завершить консультацию с {anonymous_id}?", reply_markup=kb)
    await call.answer()

@dp.callback_query(lambda c: c.data.startswith("end:"))
async def end_consultation(call: types.CallbackQuery):
    doctor_id = call.from_user.id
    
    if not is_doctor(doctor_id):
        await call.answer("⛔ Только для врачей")
        return
    
    user_id = int(call.data.split(":")[1])
    anonymous_id = r.get(f"user:{user_id}:anonymous_id") or "клиент"
    
    r.delete(f"client:{user_id}:doctor")
    r.delete(f"user:{user_id}:active")
    
    if get_current_client(doctor_id) == str(user_id):
        set_current_client(doctor_id, None)
    
    await safe_send_message(user_id, "🏁 Консультация завершена. Спасибо, что обратились к нам!")
    await call.message.answer(f"✅ Консультация с {anonymous_id} завершена.")
    await call.answer()

@dp.callback_query(lambda c: c.data.startswith("transfer_confirm:"))
async def confirm_transfer_prompt(call: types.CallbackQuery):
    doctor_id = call.from_user.id
    
    if not is_doctor(doctor_id):
        await call.answer("⛔ Только для врачей")
        return
    
    user_id = int(call.data.split(":")[1])
    anonymous_id = r.get(f"user:{user_id}:anonymous_id") or "клиент"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🦷 Стоматолог", callback_data=f"to:dentistry:{user_id}")],
        [InlineKeyboardButton(text="🔪 Хирург", callback_data=f"to:surgery:{user_id}")],
        [InlineKeyboardButton(text="💊 Терапевт", callback_data=f"to:therapy:{user_id}")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]
    ])
    await call.message.answer(f"⚠️ Перенаправить клиента {anonymous_id}?\nВыберите специалиста:", reply_markup=kb)
    await call.answer()

@dp.callback_query(lambda c: c.data.startswith("to:"))
async def do_transfer(call: types.CallbackQuery):
    doctor_id = call.from_user.id
    
    if not is_doctor(doctor_id):
        await call.answer("⛔ Только для врачей")
        return
    
    _, new_topic, user_id = call.data.split(":")
    user_id = int(user_id)
    anonymous_id = r.get(f"user:{user_id}:anonymous_id") or "клиент"
    new_doctor_id = get_doctor(new_topic)
    
    r.set(f"client:{user_id}:doctor", new_doctor_id)
    
    if get_current_client(doctor_id) == str(user_id):
        set_current_client(doctor_id, None)
    
    await safe_send_message(
        user_id,
        f"🔄 Вас перенаправили к {TOPICS[new_topic]}. Ожидайте ответа."
    )
    await safe_send_message(
        new_doctor_id,
        f"🆕 Клиент {anonymous_id} перенаправлен к вам. Тема: {TOPICS[new_topic]}"
    )
    await call.message.answer(f"✅ Клиент {anonymous_id} перенаправлен {TOPICS[new_topic]}")
    await call.answer()

@dp.callback_query(lambda c: c.data == "cancel")
async def cancel_action(call: types.CallbackQuery):
    await call.message.edit_text("❌ Действие отменено.")
    await call.answer()

# ============================================
# ЧАТ
# ============================================

@dp.message()
async def chat_messages(message: types.Message):
    user_id = message.from_user.id
    
    if message.text in ["✅ Я оплатил"] + list(TOPICS.values()):
        return
    
    if r.get(f"user:{user_id}:active"):
        doctor_id = r.get(f"client:{user_id}:doctor")
        anonymous_id = r.get(f"user:{user_id}:anonymous_id") or "клиент"
        if doctor_id:
            await safe_send_message(
                int(doctor_id),
                f"👤 {anonymous_id}: {message.text}",
                reply_markup=get_doctor_actions_keyboard(user_id)
            )
    
    elif is_doctor(user_id):
        current_client = get_current_client(user_id)
        if current_client:
            await safe_send_message(
                int(current_client),
                f"👨‍⚕️ Врач: {message.text}"
            )

# ============================================
# ЗАПУСК
# ============================================

async def set_commands():
    await bot.set_my_commands([
        BotCommand(command="start", description="Главное меню"),
        BotCommand(command="online", description="Стать онлайн (врач)"),
        BotCommand(command="offline", description="Стать офлайн (врач)"),
        BotCommand(command="status", description="Мой статус (врач)"),
        BotCommand(command="next", description="Взять следующего клиента (врач)"),
        BotCommand(command="clients", description="Текущий клиент (врач)"),
    ])

async def main():
    await set_commands()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())