# ============================================
# ТЕЛЕГРАМ БОТ ДЛЯ ВЕТКЛИНИКИ
# Версия: финальная для деплоя на Railway
# ============================================

# Импортируем нужные библиотеки
import logging
import os
import redis
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor

# ============================================
# 1. НАСТРОЙКИ (берутся из переменных окружения)
# ============================================

# Токен бота — получаем из переменной окружения BOT_TOKEN
# Как добавить на Railway: Variables → BOT_TOKEN
API_TOKEN = os.getenv("BOT_TOKEN")

# ID группы, где будут создаваться темы с консультациями
GROUP_ID = int(os.getenv("GROUP_ID", "-1003971711034"))

# ID администраторов (кто может подтверждать оплату и управлять)
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "1092230808").split(",") if x.strip()]

# Номер телефона для оплаты через СБП
PHONE_NUMBER = os.getenv("PHONE_NUMBER", "+79256530940")

# ============================================
# 2. ПОДКЛЮЧЕНИЕ К REDIS (база данных для хранения состояний)
# ============================================

# Railway сам подставит REDIS_URL, когда мы добавим базу данных
# Локально для теста используем redis://localhost:6379
redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
r = redis.from_url(redis_url, decode_responses=True)

# ============================================
# 3. ЗАПУСК БОТА
# ============================================

bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

# Включаем логирование (чтобы видеть ошибки)
logging.basicConfig(level=logging.INFO)

# ============================================
# 4. НАСТРОЙКИ ВРАЧЕЙ (можно добавлять постепенно)
# ============================================

# Названия специализаций (как их увидит клиент)
TOPICS = {
    "dentistry": "Стоматолог",
    "surgery": "Хирург",
    "therapy": "Терапевт"
}

# ID врачей (замените на реальные Telegram ID)
# Как узнать ID: напишите @userinfobot
DOCTORS = {
    "dentistry": [1092230808],      # 👈 ВЫ (админ) для теста
    "surgery": [222222222],         # 👈 ЗАМЕНИТЕ на ID хирурга
    "therapy": [1906114179]         # 👈 Терапевт
}

# Счётчик для очереди терапевтов (round-robin)
# Если терапевтов несколько — клиенты будут распределяться по очереди
therapy_index = 0

def get_doctor(topic):
    """Возвращает ID врача для выбранной темы"""
    global therapy_index
    
    if topic == "therapy":
        # Для терапевтов — по очереди
        doctor_id = DOCTORS["therapy"][therapy_index % len(DOCTORS["therapy"])]
        therapy_index += 1
        return doctor_id
    else:
        # Для остальных — первый в списке
        return DOCTORS[topic][0]

# ============================================
# 5. КОМАНДА /start
# ============================================

@dp.message_handler(commands=["start"])
async def start(msg: types.Message):
    # Создаём клавиатуру с выбором специалиста
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    for t in TOPICS:
        kb.add(TOPICS[t])
    
    await msg.answer(
        "🐾 Добро пожаловать в онлайн-консультации ветклиники!\n\n"
        "Выберите специалиста:",
        reply_markup=kb
    )

# ============================================
# 6. ВЫБОР СПЕЦИАЛИСТА
# ============================================

@dp.message_handler(lambda m: m.text in TOPICS.values())
async def choose_topic(msg: types.Message):
    user_id = msg.from_user.id
    
    # Определяем, какую тему выбрал клиент
    topic_key = None
    for k, v in TOPICS.items():
        if v == msg.text:
            topic_key = k
            break
    
    # Сохраняем выбор в Redis
    r.set(f"user:{user_id}:topic", topic_key)
    r.set(f"user:{user_id}:payment_status", "waiting_payment")
    
    # Кнопка "Я оплатил"
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("✅ Я оплатил")
    
    await msg.answer(
        f"💰 Консультация {msg.text} — 500 ₽\n\n"
        f"📞 Оплата по номеру телефона (СБП):\n"
        f"<code>{PHONE_NUMBER}</code>\n\n"
        f"После оплаты нажмите кнопку ниже и отправьте чек.",
        reply_markup=kb,
        parse_mode="HTML"
    )

# ============================================
# 7. КЛИЕНТ НАЖАЛ "Я ОПЛАТИЛ"
# ============================================

@dp.message_handler(lambda m: m.text == "✅ Я оплатил")
async def paid_button(msg: types.Message):
    user_id = msg.from_user.id
    status = r.get(f"user:{user_id}:payment_status")
    
    if status != "waiting_payment":
        await msg.answer("Сначала выберите специалиста через /start")
        return
    
    r.set(f"user:{user_id}:payment_status", "waiting_receipt")
    await msg.answer("📎 Отправьте скриншот или фото чека.")

# ============================================
# 8. КЛИЕНТ ОТПРАВИЛ ЧЕК (ФОТО)
# ============================================

@dp.message_handler(content_types=["photo"])
async def handle_receipt(msg: types.Message):
    user_id = msg.from_user.id
    status = r.get(f"user:{user_id}:payment_status")
    
    if status != "waiting_receipt":
        await msg.answer("Сначала нажмите «Я оплатил»")
        return
    
    # Получаем тему и врача
    topic = r.get(f"user:{user_id}:topic")
    doctor_id = get_doctor(topic)
    
    # Сохраняем связи в Redis
    r.set(f"client:{user_id}:doctor", doctor_id)
    r.set(f"doctor:{doctor_id}:client", user_id)
    r.set(f"user:{user_id}:payment_status", "pending_review")
    
    # Кнопки для врача (подтвердить/отклонить)
    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton("✅ Подтвердить", callback_data=f"ok:{user_id}"),
        types.InlineKeyboardButton("❌ Отклонить", callback_data=f"no:{user_id}")
    )
    
    # Отправляем чек врачу
    await bot.send_photo(
        doctor_id,
        msg.photo[-1].file_id,
        caption=f"🧾 НОВЫЙ ЧЕК\n"
                f"👤 Клиент: @{msg.from_user.username or msg.from_user.first_name}\n"
                f"📂 Тема: {TOPICS[topic]}\n"
                f"🆔 ID: {user_id}",
        reply_markup=kb
    )
    
    await msg.answer("⏳ Чек отправлен врачу на проверку. Ожидайте подтверждения.")

# ============================================
# 9. ВРАЧ ПОДТВЕРЖДАЕТ ОПЛАТУ
# ============================================

@dp.callback_query_handler(lambda c: c.data.startswith("ok:"))
async def approve_payment(call: types.CallbackQuery):
    user_id = int(call.data.split(":")[1])
    
    # Активируем консультацию
    r.set(f"user:{user_id}:active", 1)
    r.set(f"user:{user_id}:payment_status", "paid")
    
    doctor_id = int(r.get(f"client:{user_id}:doctor"))
    
    # Кнопки для врача во время консультации
    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton("⏳ Врач скоро ответит", callback_data="busy"),
        types.InlineKeyboardButton("🔄 Перенаправить", callback_data="transfer"),
        types.InlineKeyboardButton("❌ Завершить", callback_data="end")
    )
    
    await bot.send_message(user_id, "✅ Оплата подтверждена! Врач скоро свяжется с вами.")
    await bot.send_message(doctor_id, "💬 Клиент подключён. Напишите сообщение.", reply_markup=kb)
    
    await call.answer("Оплата подтверждена")

@dp.callback_query_handler(lambda c: c.data.startswith("no:"))
async def reject_payment(call: types.CallbackQuery):
    user_id = int(call.data.split(":")[1])
    r.set(f"user:{user_id}:payment_status", "rejected")
    
    await bot.send_message(user_id, "❌ Оплата не подтверждена. Попробуйте снова /start")
    await call.answer("Оплата отклонена")

# ============================================
# 10. УПРАВЛЕНИЕ КОНСУЛЬТАЦИЕЙ (КНОПКИ ВРАЧА)
# ============================================

@dp.callback_query_handler(lambda c: c.data == "busy")
async def busy_doctor(call: types.CallbackQuery):
    doctor_id = call.from_user.id
    client_id = r.get(f"doctor:{doctor_id}:client")
    
    if client_id:
        await bot.send_message(client_id, "⏳ Врач сейчас занят, ответит в ближайшее время.")
    await call.answer()

@dp.callback_query_handler(lambda c: c.data == "end")
async def end_consultation(call: types.CallbackQuery):
    doctor_id = call.from_user.id
    client_id = r.get(f"doctor:{doctor_id}:client")
    
    if client_id:
        await bot.send_message(client_id, "🏁 Консультация завершена. Спасибо, что обратились к нам!")
        await bot.send_message(doctor_id, "✅ Консультация завершена.")
        
        # Очищаем связи в Redis
        r.delete(f"doctor:{doctor_id}:client")
        r.delete(f"client:{client_id}:doctor")
        r.delete(f"user:{client_id}:active")
    
    await call.answer()

@dp.callback_query_handler(lambda c: c.data == "transfer")
async def transfer_menu(call: types.CallbackQuery):
    # Показываем меню выбора специалиста для перенаправления
    kb = types.InlineKeyboardMarkup()
    for t in TOPICS:
        kb.add(types.InlineKeyboardButton(TOPICS[t], callback_data=f"to:{t}"))
    kb.add(types.InlineKeyboardButton("❌ Отмена", callback_data="cancel_transfer"))
    
    await call.message.answer("🔄 Выберите специалиста для перенаправления:", reply_markup=kb)
    await call.answer()

@dp.callback_query_handler(lambda c: c.data.startswith("to:"))
async def do_transfer(call: types.CallbackQuery):
    new_topic = call.data.split(":")[1]
    doctor_id = call.from_user.id
    client_id = r.get(f"doctor:{doctor_id}:client")
    
    if not client_id:
        await call.answer("Клиент не найден")
        return
    
    new_doctor_id = get_doctor(new_topic)
    
    # Обновляем связи
    r.set(f"client:{client_id}:doctor", new_doctor_id)
    r.set(f"doctor:{new_doctor_id}:client", client_id)
    r.delete(f"doctor:{doctor_id}:client")
    
    await bot.send_message(client_id, f"🔄 Вас перенаправили к {TOPICS[new_topic]}. Ожидайте ответа.")
    await bot.send_message(new_doctor_id, f"🆕 Новый клиент перенаправлен к вам. Тема: {TOPICS[new_topic]}")
    await call.message.answer(f"✅ Клиент перенаправлен {TOPICS[new_topic]}")
    await call.answer()

@dp.callback_query_handler(lambda c: c.data == "cancel_transfer")
async def cancel_transfer(call: types.CallbackQuery):
    await call.message.edit_text("❌ Перенаправление отменено")
    await call.answer()

# ============================================
# 11. ЧАТ МЕЖДУ КЛИЕНТОМ И ВРАЧОМ
# ============================================

@dp.message_handler()
async def chat_messages(msg: types.Message):
    user_id = msg.from_user.id
    
    # Игнорируем служебные сообщения и команды
    if msg.text in ["✅ Я оплатил"] + list(TOPICS.values()):
        return
    
    # Клиент → Врач
    if r.get(f"user:{user_id}:active"):
        doctor_id = r.get(f"client:{user_id}:doctor")
        if doctor_id:
            await bot.send_message(
                int(doctor_id), 
                f"👤 <b>Клиент:</b> {msg.text}", 
                parse_mode="HTML"
            )
    
    # Врач → Клиент
    elif r.get(f"doctor:{user_id}:client"):
        client_id = r.get(f"doctor:{user_id}:client")
        if client_id:
            await bot.send_message(
                int(client_id), 
                f"👨‍⚕️ <b>Врач:</b> {msg.text}", 
                parse_mode="HTML"
            )

# ============================================
# 12. ЗАПУСК БОТА
# ============================================

if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)