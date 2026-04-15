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

# Максимум активных консультаций на врача
MAX_ACTIVE_PER_DOCTOR = 3

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
    "dentistry": [1092230808],      # 👈 ВЫ (админ) для теста
    "surgery": [222222222],         # 👈 ЗАМЕНИТЕ на ID хирурга
    "therapy": [1906114179]         # 👈 Терапевт
}

# ============================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================

def get_anonymous_id(topic, user_id):
    """Генерирует анонимный ID клиента с префиксом по специализации"""
    short_id = str(user_id)[-4:]
    prefix_map = {"dentistry": "ST", "surgery": "SR", "therapy": "TP"}
    prefix = prefix_map.get(topic, "CL")
    return f"{prefix}{short_id}"

def get_doctor(topic):
    """Возвращает ID врача для выбранной темы"""
    if topic == "therapy":
        current_idx = int(r.get("therapy_round_robin_idx") or 0)
        doctor_id = DOCTORS["therapy"][current_idx % len(DOCTORS["therapy"])]
        r.set("therapy_round_robin_idx", current_idx + 1)
        return doctor_id
    return DOCTORS[topic][0]

def get_active_count(doctor_id):
    """Возвращает количество активных консультаций у врача"""
    active_clients = r.smembers(f"doctor:{doctor_id}:active_clients")
    return len(active_clients)

def can_take_new_client(doctor_id):
    """Проверяет, может ли врач взять нового клиента"""
    return get_active_count(doctor_id) < MAX_ACTIVE_PER_DOCTOR

def add_active_client(doctor_id, user_id):
    """Добавляет клиента в список активных у врача"""
    r.sadd(f"doctor:{doctor_id}:active_clients", user_id)

def remove_active_client(doctor_id, user_id):
    """Удаляет клиента из списка активных у врача"""
    r.srem(f"doctor:{doctor_id}:active_clients", user_id)

def add_to_queue(topic, user_id, anonymous_id):
    """Добавляет клиента в очередь"""
    queue_key = f"queue:{topic}"
    r.rpush(queue_key, f"{user_id}:{anonymous_id}")
    return r.llen(queue_key) - 1

def get_next_from_queue(topic):
    """Забирает следующего клиента из очереди"""
    queue_key = f"queue:{topic}"
    next_client = r.lpop(queue_key)
    if next_client:
        user_id, anonymous_id = next_client.split(":")
        return int(user_id), anonymous_id
    return None, None

# ============================================
# КЛАВИАТУРЫ
# ============================================

def get_main_keyboard():
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=TOPICS[t])] for t in TOPICS],
        resize_keyboard=True
    )
    return kb

def get_doctor_keyboard(user_id):
    """Клавиатура для врача с кнопками действий"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Завершить", callback_data=f"end_confirm:{user_id}")],
        [InlineKeyboardButton(text="🔄 Перенаправить", callback_data=f"transfer_confirm:{user_id}")],
        [InlineKeyboardButton(text="⏳ Врач занят", callback_data=f"busy:{user_id}")],
        [InlineKeyboardButton(text="📋 Мои клиенты", callback_data="show_clients")],
    ])
    return keyboard

# ============================================
# FSM СОСТОЯНИЯ
# ============================================

class PaymentState(StatesGroup):
    waiting_payment = State()
    waiting_receipt = State()

# ============================================
# КОМАНДА /start
# ============================================

@dp.message(Command("start"))
async def start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "🐾 Добро пожаловать в онлайн-консультации ветклиники!\n\n"
        "Выберите специалиста:",
        reply_markup=get_main_keyboard()
    )

# ============================================
# КОМАНДА /clients (список активных клиентов для врача)
# ============================================

@dp.message(Command("clients"))
async def list_active_clients_command(message: types.Message):
    doctor_id = message.from_user.id
    active_clients = r.smembers(f"doctor:{doctor_id}:active_clients")
    
    if not active_clients:
        await message.answer("📭 Нет активных консультаций.")
        return
    
    text = "📋 <b>Ваши активные клиенты:</b>\n\n"
    for client_id in active_clients:
        client_id = int(client_id)
        anonymous_id = r.get(f"user:{client_id}:anonymous_id") or "клиент"
        text += f"• {anonymous_id}\n"
    
    await message.answer(text, parse_mode="HTML")

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
    
    anonymous_id = get_anonymous_id(topic_key, user_id)
    
    r.set(f"user:{user_id}:topic", topic_key)
    r.set(f"user:{user_id}:anonymous_id", anonymous_id)
    await state.update_data(topic=message.text, anonymous_id=anonymous_id)
    
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="✅ Я оплатил")]],
        resize_keyboard=True
    )
    
    await message.answer(
        f"💰 Консультация {message.text} — 500 ₽\n\n"
        f"📞 Оплата по номеру телефона (СБП):\n"
        f"<code>{PHONE_NUMBER}</code>\n\n"
        f"Ваш ID для консультации: <b>{anonymous_id}</b>\n\n"
        f"После оплаты нажмите кнопку ниже и отправьте чек.",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await state.set_state(PaymentState.waiting_payment)

# ============================================
# Я ОПЛАТИЛ
# ============================================

@dp.message(F.text == "✅ Я оплатил", PaymentState.waiting_payment)
async def paid_button(message: types.Message, state: FSMContext):
    await message.answer("📎 Отправьте скриншот или фото чека.")
    await state.set_state(PaymentState.waiting_receipt)

# ============================================
# ПРИЁМ ЧЕКА
# ============================================

@dp.message(PaymentState.waiting_receipt, F.photo)
async def handle_receipt(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    topic_key = r.get(f"user:{user_id}:topic")
    anonymous_id = r.get(f"user:{user_id}:anonymous_id")
    doctor_id = get_doctor(topic_key)
    
    if can_take_new_client(doctor_id):
        # Врач свободен — подключаем
        add_active_client(doctor_id, user_id)
        r.set(f"client:{user_id}:doctor", doctor_id)
        r.set(f"doctor:{doctor_id}:current_client", user_id)
        r.set(f"user:{user_id}:active", 1)
        
        await bot.send_photo(
            doctor_id,
            message.photo[-1].file_id,
            caption=f"🧾 НОВЫЙ ЧЕК\n"
                    f"👤 Клиент: {anonymous_id}\n"
                    f"📂 Тема: {TOPICS[topic_key]}\n\n"
                    f"✅ Активных консультаций: {get_active_count(doctor_id)}/{MAX_ACTIVE_PER_DOCTOR}",
            reply_markup=get_doctor_keyboard(user_id)
        )
        
        await bot.send_message(
            doctor_id,
            f"💬 Клиент {anonymous_id} подключён. Напишите сообщение."
        )
        
        await message.answer(
            f"✅ Оплата подтверждена! Врач свяжется с вами.\n"
            f"Ваш ID: {anonymous_id}"
        )
        
        await state.clear()
        
    else:
        # Врач занят — добавляем в очередь
        position = add_to_queue(topic_key, user_id, anonymous_id)
        
        await bot.send_photo(
            doctor_id,
            message.photo[-1].file_id,
            caption=f"🧾 НОВЫЙ ЧЕК\n"
                    f"👤 Клиент: {anonymous_id}\n"
                    f"📂 Тема: {TOPICS[topic_key]}\n\n"
                    f"⏳ ВРАЧ ЗАНЯТ ({MAX_ACTIVE_PER_DOCTOR}/{MAX_ACTIVE_PER_DOCTOR})\n"
                    f"Клиент добавлен в очередь. Позиция: {position + 1}"
        )
        
        await message.answer(
            f"⏳ Врач сейчас ведёт {MAX_ACTIVE_PER_DOCTOR} консультаций.\n"
            f"Вы в очереди на позиции {position + 1}.\n"
            f"Как только врач освободится, вы получите уведомление.\n"
            f"Ваш ID: {anonymous_id}"
        )
        
        r.set(f"user:{user_id}:payment_status", "queued")
        await state.clear()

# ============================================
# ПОДТВЕРЖДЕНИЕ ЗАВЕРШЕНИЯ
# ============================================

@dp.callback_query_handler(lambda c: c.data.startswith("end_confirm:"))
async def confirm_end_prompt(call: types.CallbackQuery):
    user_id = int(call.data.split(":")[1])
    anonymous_id = r.get(f"user:{user_id}:anonymous_id") or "клиент"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, завершить", callback_data=f"end:{user_id}")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]
    ])
    
    await call.message.answer(
        f"⚠️ Вы уверены, что хотите завершить консультацию с {anonymous_id}?\n\n"
        f"Это действие нельзя отменить.",
        reply_markup=kb
    )
    await call.answer()

# ============================================
# ЗАВЕРШЕНИЕ КОНСУЛЬТАЦИИ
# ============================================

@dp.callback_query_handler(lambda c: c.data.startswith("end:"))
async def end_consultation(call: types.CallbackQuery):
    user_id = int(call.data.split(":")[1])
    doctor_id = call.from_user.id
    
    anonymous_id = r.get(f"user:{user_id}:anonymous_id") or "клиент"
    
    remove_active_client(doctor_id, user_id)
    
    r.delete(f"client:{user_id}:doctor")
    r.delete(f"user:{user_id}:active")
    r.delete(f"user:{user_id}:payment_status")
    
    if r.get(f"doctor:{doctor_id}:current_client") == str(user_id):
        r.delete(f"doctor:{doctor_id}:current_client")
    
    await bot.send_message(
        user_id,
        "🏁 Консультация завершена. Спасибо, что обратились к нам!"
    )
    
    topic_key = r.get(f"user:{user_id}:topic")
    if topic_key:
        next_client_id, next_anonymous_id = get_next_from_queue(topic_key)
        
        if next_client_id:
            add_active_client(doctor_id, next_client_id)
            r.set(f"client:{next_client_id}:doctor", doctor_id)
            r.set(f"doctor:{doctor_id}:current_client", next_client_id)
            r.set(f"user:{next_client_id}:active", 1)
            r.delete(f"user:{next_client_id}:payment_status")
            
            await bot.send_message(
                next_client_id,
                f"✅ Врач освободился! Ваша консультация начинается.\n"
                f"Ваш ID: {next_anonymous_id}"
            )
            
            await bot.send_message(
                doctor_id,
                f"💬 Новый клиент {next_anonymous_id} из очереди подключён.\n"
                f"Активных консультаций: {get_active_count(doctor_id)}/{MAX_ACTIVE_PER_DOCTOR}",
                reply_markup=get_doctor_keyboard(next_client_id)
            )
            
            await call.message.answer(f"✅ Клиент {next_anonymous_id} из очереди подключён")
        else:
            await call.message.answer(f"✅ Консультация с {anonymous_id} завершена. Очередь пуста.")
    
    await call.answer()

# ============================================
# ПОДТВЕРЖДЕНИЕ ПЕРЕНАПРАВЛЕНИЯ
# ============================================

@dp.callback_query_handler(lambda c: c.data.startswith("transfer_confirm:"))
async def confirm_transfer_prompt(call: types.CallbackQuery):
    user_id = int(call.data.split(":")[1])
    anonymous_id = r.get(f"user:{user_id}:anonymous_id") or "клиент"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🦷 Стоматолог", callback_data=f"to:dentistry:{user_id}")],
        [InlineKeyboardButton(text="🔪 Хирург", callback_data=f"to:surgery:{user_id}")],
        [InlineKeyboardButton(text="💊 Терапевт", callback_data=f"to:therapy:{user_id}")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]
    ])
    
    await call.message.answer(
        f"⚠️ Вы хотите перенаправить клиента {anonymous_id}.\n\n"
        f"Выберите специалиста:",
        reply_markup=kb
    )
    await call.answer()

# ============================================
# ПЕРЕНАПРАВЛЕНИЕ
# ============================================

@dp.callback_query_handler(lambda c: c.data.startswith("to:"))
async def do_transfer(call: types.CallbackQuery):
    _, new_topic, user_id = call.data.split(":")
    user_id = int(user_id)
    doctor_id = call.from_user.id
    
    anonymous_id = r.get(f"user:{user_id}:anonymous_id") or "клиент"
    new_doctor_id = get_doctor(new_topic)
    
    remove_active_client(doctor_id, user_id)
    add_active_client(new_doctor_id, user_id)
    r.set(f"client:{user_id}:doctor", new_doctor_id)
    
    if r.get(f"doctor:{doctor_id}:current_client") == str(user_id):
        r.delete(f"doctor:{doctor_id}:current_client")
    
    await bot.send_message(
        user_id,
        f"🔄 Вас перенаправили к {TOPICS[new_topic]}. Ожидайте ответа."
    )
    await bot.send_message(
        new_doctor_id,
        f"🆕 Клиент {anonymous_id} перенаправлен к вам. Тема: {TOPICS[new_topic]}\n"
        f"Активных консультаций: {get_active_count(new_doctor_id)}/{MAX_ACTIVE_PER_DOCTOR}",
        reply_markup=get_doctor_keyboard(user_id) if can_take_new_client(new_doctor_id) else None
    )
    await call.message.answer(f"✅ Клиент {anonymous_id} перенаправлен {TOPICS[new_topic]}")
    await call.answer()

# ============================================
# КНОПКА "ВРАЧ ЗАНЯТ"
# ============================================

@dp.callback_query_handler(lambda c: c.data.startswith("busy:"))
async def busy_doctor(call: types.CallbackQuery):
    user_id = int(call.data.split(":")[1])
    anonymous_id = r.get(f"user:{user_id}:anonymous_id") or "клиент"
    
    await bot.send_message(
        user_id,
        "⏳ Врач сейчас занят, ответит в ближайшее время."
    )
    await call.answer(f"Уведомление отправлено {anonymous_id}")

# ============================================
# ПОКАЗ СПИСКА АКТИВНЫХ КЛИЕНТОВ (ДЛЯ ВРАЧА)
# ============================================

@dp.callback_query_handler(lambda c: c.data == "show_clients")
async def show_clients(call: types.CallbackQuery):
    doctor_id = call.from_user.id
    active_clients = r.smembers(f"doctor:{doctor_id}:active_clients")
    
    if not active_clients:
        await call.message.answer("📭 Нет активных консультаций.")
        await call.answer()
        return
    
    text = "📋 <b>Ваши активные клиенты:</b>\n\n"
    buttons = []
    
    for client_id in active_clients:
        client_id = int(client_id)
        anonymous_id = r.get(f"user:{client_id}:anonymous_id") or "клиент"
        text += f"• {anonymous_id}\n"
        buttons.append([InlineKeyboardButton(text=f"💬 Переключиться на {anonymous_id}", callback_data=f"switch:{client_id}")])
    
    buttons.append([InlineKeyboardButton(text="❌ Закрыть", callback_data="cancel")])
    
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    await call.message.answer(text, reply_markup=kb, parse_mode="HTML")
    await call.answer()

# ============================================
# ПЕРЕКЛЮЧЕНИЕ МЕЖДУ КЛИЕНТАМИ
# ============================================

@dp.callback_query_handler(lambda c: c.data.startswith("switch:"))
async def switch_client(call: types.CallbackQuery):
    client_id = int(call.data.split(":")[1])
    doctor_id = call.from_user.id
    anonymous_id = r.get(f"user:{client_id}:anonymous_id") or "клиент"
    
    r.set(f"doctor:{doctor_id}:current_client", client_id)
    
    await call.message.answer(
        f"✅ Вы переключились на клиента {anonymous_id}.\n"
        f"Теперь все ваши сообщения будут отправлены ему."
    )
    await call.answer()

# ============================================
# ОТМЕНА ДЕЙСТВИЯ
# ============================================

@dp.callback_query_handler(lambda c: c.data == "cancel")
async def cancel_action(call: types.CallbackQuery):
    await call.message.edit_text("❌ Действие отменено.")
    await call.answer()

# ============================================
# ЧАТ МЕЖДУ КЛИЕНТОМ И ВРАЧОМ
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
                reply_markup=get_doctor_keyboard(user_id)
            )
    
    # Врач → Текущий клиент
    elif r.get(f"doctor:{user_id}:current_client"):
        client_id = r.get(f"doctor:{user_id}:current_client")
        if client_id:
            await bot.send_message(
                int(client_id),
                f"👨‍⚕️ Врач: {message.text}"
            )

# ============================================
# УСТАНОВКА КОМАНД В МЕНЮ БОТА
# ============================================

async def set_commands():
    commands = [
        BotCommand(command="start", description="Начать консультацию"),
        BotCommand(command="clients", description="📋 Мои активные клиенты"),
    ]
    await bot.set_my_commands(commands)

# ============================================
# ЗАПУСК БОТА
# ============================================

async def main():
    await set_commands()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())