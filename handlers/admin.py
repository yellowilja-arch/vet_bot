from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from config import ADMIN_IDS, DOCTOR_IDS, TOPICS
from services.validators import is_doctor, get_doctor_status
from services.reset_tools import reset_user_state, reset_all_states, close_stuck_requests, unlock_all_doctors
from database.users import get_user_info, get_recent_users
from database.doctors import add_doctor, remove_doctor, get_all_doctors
from database.queue import get_queue_length
from database.db import get_db
from utils.helpers import safe_send_message
from keyboards.admin import get_admin_support_keyboard
from states.forms import WaitingState
import redis
from config import REDIS_URL

r = redis.from_url(REDIS_URL, decode_responses=True)

router = Router()
@router.message(Command("stats"))
async def admin_stats(message: Message):
    print("🔍 admin /stats received")
    await message.answer("stats from admin")
    
@router.message(Command("ban"))
async def ban_user(message: Message):
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS:
        return
    
    args = message.text.split()
    if len(args) < 2:
        await safe_send_message(user_id, "⚠️ /ban <user_id> [причина]")
        return
    
    target_id = int(args[1])
    reason = " ".join(args[2:]) if len(args) > 2 else None
    
    db = await get_db()
    await db.execute('INSERT OR REPLACE INTO blacklist (user_id, reason, blocked_by) VALUES (?, ?, ?)', (target_id, reason, user_id))
    await db.commit()
    
    await safe_send_message(user_id, f"🚫 Пользователь {target_id} заблокирован")
    await safe_send_message(target_id, f"⛔ Вы заблокированы. Причина: {reason or 'не указана'}")

@router.message(Command("unban"))
async def unban_user(message: Message):
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS:
        return
    
    args = message.text.split()
    if len(args) != 2:
        await safe_send_message(user_id, "⚠️ /unban <user_id>")
        return
    
    target_id = int(args[1])
    
    db = await get_db()
    await db.execute('DELETE FROM blacklist WHERE user_id = ?', (target_id,))
    await db.commit()
    
    await safe_send_message(user_id, f"✅ Пользователь {target_id} разблокирован")
    await safe_send_message(target_id, "✅ Вы разблокированы")

@router.message(Command("stats"))
async def admin_stats(message: Message):
    user_id = message.from_user.id
    logging.info(f"🔍 /stats: user_id={user_id}, ADMIN_IDS={ADMIN_IDS}, in_admin={user_id in ADMIN_IDS}")
    import logging
    logging.info(f"🔍 /stats: user_id={user_id}, ADMIN_IDS={ADMIN_IDS}, in_admin={user_id in ADMIN_IDS}")
    
    # Отправляем ответ ВСЕ РАВНО, чтобы проверить, вызывается ли обработчик
    if not ADMIN_IDS:
        logging.info("ADMIN_IDS пуст")
        await safe_send_message(user_id, "❌ ADMIN_IDS пуст! Установите ADMIN_IDS в .env")
        logging.error("ADMIN_IDS пуст!")
        return
    
    if user_id not in ADMIN_IDS:
        logging.info(f"Не админ: {user_id} not in {ADMIN_IDS}")
        await safe_send_message(user_id, f"⛔ Доступ запрещен. Ваш ID: {user_id}\nАдмины: {ADMIN_IDS}")
        return
    
    try:
        logging.info("Получаю статистику")
        db = await get_db()
        cursor = await db.execute('SELECT COUNT(*) FROM users')
        users = (await cursor.fetchone())[0]
        cursor = await db.execute('SELECT COUNT(*) FROM consultations')
        cons = (await cursor.fetchone())[0]
        cursor = await db.execute('SELECT COUNT(*) FROM consultations WHERE status = "active"')
        active = (await cursor.fetchone())[0]
        
        text = f"📊 Статистика\n👤 Пользователей: {users}\n📋 Консультаций: {cons}\n🟢 Активных: {active}"
        logging.info(f"Отправляю: {text}")
        await safe_send_message(user_id, text)
        logging.info("Отправлено")
    except Exception as e:
        logging.info(f"Ошибка в /stats: {e}")
        logging.error(f"Ошибка в /stats: {e}")
        await safe_send_message(user_id, f"❌ Ошибка: {e}")

@router.message(Command("health"))
async def health_check(message: Message):
    """Проверка здоровья бота (Redis, SQLite, активные консультации)"""
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS:
        await safe_send_message(user_id, "⛔ Только для админов")
        return
    
    # Проверка Redis
    try:
        r.ping()
        redis_status = "✅"
    except Exception as e:
        redis_status = f"❌ {e}"
    
    # Проверка SQLite
    try:
        db = await get_db()
        await db.execute("SELECT 1")
        sqlite_status = "✅"
    except Exception as e:
        sqlite_status = f"❌ {e}"
    
    # Количество активных консультаций
    try:
        cursor = await db.execute('SELECT COUNT(*) FROM consultations WHERE status = "active"')
        active_cons = (await cursor.fetchone())[0]
    except:
        active_cons = "ошибка"
    
    # Количество врачей онлайн
    online_doctors = sum(1 for d in DOCTOR_IDS if get_doctor_status(d) == "online")
    
    # Длина очередей
    queue_lengths = {}
    for topic in TOPICS.keys():
        queue_lengths[topic] = await get_queue_length(topic)
    
    text = f"🩺 <b>Здоровье бота</b>\n\n"
    text += f"Redis: {redis_status}\n"
    text += f"SQLite: {sqlite_status}\n"
    text += f"Активных консультаций: {active_cons}\n"
    text += f"Врачей онлайн: {online_doctors}\n"
    text += f"Очередь: {queue_lengths}\n"
    
    await safe_send_message(user_id, text, parse_mode="HTML")

@router.message(Command("backup"))
async def manual_backup(message: Message):
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS:
        return
    
    from workers.backups import create_backup
    result = await create_backup()
    await safe_send_message(user_id, result)

@router.message(Command("user"))
async def get_user(message: Message):
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS:
        return
    
    args = message.text.split()
    if len(args) != 2:
        await safe_send_message(user_id, "⚠️ /user <user_id> или /user @username")
        return
    
    identifier = args[1]
    db = await get_db()
    
    if identifier.startswith("@"):
        cursor = await db.execute('SELECT * FROM users WHERE username = ?', (identifier[1:],))
    else:
        cursor = await db.execute('SELECT * FROM users WHERE user_id = ?', (int(identifier),))
    
    user = await cursor.fetchone()
    
    if not user:
        await safe_send_message(user_id, f"❌ Пользователь {identifier} не найден.")
        return
    
    text = f"📋 <b>Информация о пользователе</b>\n\n"
    text += f"🆔 ID: {user[0]}\n"
    text += f"👤 Username: @{user[1] or 'нет'}\n"
    text += f"📛 Имя: {user[2] or 'нет'} {user[3] or ''}\n"
    text += f"📅 Первое появление: {user[5]}\n"
    text += f"📅 Последнее: {user[6]}"
    
    await safe_send_message(user_id, text, parse_mode="HTML")

# ============================================
# КОМАНДЫ ВОССТАНОВЛЕНИЯ
# ============================================

@router.message(Command("resetuser"))
async def reset_user(message: Message):
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS:
        return
    
    args = message.text.split()
    if len(args) != 2:
        await safe_send_message(user_id, "⚠️ /resetuser <user_id>")
        return
    
    target_id = int(args[1])
    await reset_user_state(target_id)
    await safe_send_message(user_id, f"✅ Состояние пользователя {target_id} сброшено")

@router.message(Command("resetall"))
async def reset_all(message: Message):
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS:
        return
    
    await reset_all_states()
    await safe_send_message(user_id, "✅ Все состояния сброшены")

@router.message(Command("closestuck"))
async def close_stuck(message: Message):
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS:
        return
    
    await close_stuck_requests()
    await safe_send_message(user_id, "✅ Зависшие запросы закрыты")

@router.message(Command("unlockdoctors"))
async def unlock_doctors(message: Message):
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS:
        return
    
    await unlock_all_doctors()
    await safe_send_message(user_id, "✅ Все врачи разблокированы")

# ============================================
# УПРАВЛЕНИЕ ВРАЧАМИ
# ============================================

@router.message(Command("adddoctor"))
async def add_doctor_command(message: Message):
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS:
        return
    
    args = message.text.split()
    if len(args) < 4:
        await safe_send_message(user_id, "⚠️ /adddoctor <telegram_id> <имя> <specialization>")
        return
    
    telegram_id = int(args[1])
    name = args[2]
    specialization = args[3]
    
    if specialization not in ["dentistry", "surgery", "therapy"]:
        await safe_send_message(user_id, "❌ Неверная специализация. Доступны: dentistry, surgery, therapy")
        return
    
    await add_doctor(telegram_id, name, specialization)
    await safe_send_message(user_id, f"✅ Врач {name} добавлен!")
    await safe_send_message(telegram_id, "👨‍⚕️ Вы добавлены в систему как врач!\nИспользуйте /start для панели управления.")

@router.message(Command("removedoctor"))
async def remove_doctor_command(message: Message):
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS:
        return
    
    args = message.text.split()
    if len(args) != 2:
        await safe_send_message(user_id, "⚠️ /removedoctor <telegram_id>")
        return
    
    telegram_id = int(args[1])
    await remove_doctor(telegram_id)
    await safe_send_message(user_id, f"✅ Врач {telegram_id} удалён из системы")

# ============================================
# ПОДДЕРЖКА
# ============================================

@router.message(Command("feedback"))
async def feedback_command(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if await is_doctor(user_id):
        await safe_send_message(user_id, "⛔ Эта команда только для клиентов.")
        return
    
    await state.set_state(WaitingState.waiting_for_feedback)
    await safe_send_message(
        user_id,
        "📝 <b>Форма обратной связи</b>\n\n"
        "Напишите ваше сообщение (жалоба, предложение, отзыв о работе бота).\n\n"
        "Чтобы отменить, отправьте /cancel.",
        parse_mode="HTML"
    )

@router.message(WaitingState.waiting_for_feedback)
async def process_feedback(message: Message, state: FSMContext):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    
    db = await get_db()
    await db.execute('''
        INSERT INTO feedback (user_id, username, feedback)
        VALUES (?, ?, ?)
    ''', (user_id, username, message.text))
    await db.commit()
    
    for admin_id in ADMIN_IDS:
        await safe_send_message(
            admin_id,
            f"📬 <b>НОВАЯ ОБРАТНАЯ СВЯЗЬ</b>\n\n"
            f"👤 От: @{username} (ID: {user_id})\n"
            f"📝 Текст:\n<pre>{message.text}</pre>",
            parse_mode="HTML"
        )
    
    await safe_send_message(user_id, "✅ Спасибо за обратную связь!")
    await state.clear()

# ============================================
# ОБРАБОТКА ОБРАЩЕНИЙ В ПОДДЕРЖКУ
# ============================================

@router.callback_query(lambda c: c.data.startswith("support_reply:"))
async def reply_to_support(call: CallbackQuery, state: FSMContext):
    admin_id = call.from_user.id
    if admin_id not in ADMIN_IDS:
        await call.answer("⛔ Только для админов")
        return
    
    parts = call.data.split(":")
    user_id = int(parts[1])
    request_id = int(parts[2])
    
    await state.update_data(reply_to_user=user_id, reply_request_id=request_id)
    await state.set_state(WaitingState.waiting_for_support_reply)
    await safe_send_message(admin_id, f"✏️ Напишите ответ пользователю (обращение #{request_id}).")
    await call.answer()

@router.message(WaitingState.waiting_for_support_reply)
async def send_support_reply(message: Message, state: FSMContext):
    admin_id = message.from_user.id
    if admin_id not in ADMIN_IDS:
        return
    
    data = await state.get_data()
    user_id = data.get("reply_to_user")
    request_id = data.get("reply_request_id")
    
    if user_id:
        await safe_send_message(user_id, f"📬 <b>Ответ администрации</b>\n\n{message.text}", parse_mode="HTML")
        
        db = await get_db()
        await db.execute('UPDATE support_requests SET status = "replied", resolved_at = CURRENT_TIMESTAMP WHERE id = ?', (request_id,))
        await db.commit()
        
        await safe_send_message(admin_id, f"✅ Ответ отправлен пользователю (обращение #{request_id}).")
    else:
        await safe_send_message(admin_id, "❌ Не найден пользователь для ответа.")
    
    await state.clear()
