import asyncio
import logging
import os
import sys
import shutil
import traceback
import time
from datetime import datetime

import redis
import aiosqlite
import boto3
from botocore.client import Config
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter

# ============================================
# НАСТРОЙКИ ИЗ ПЕРЕМЕННЫХ ОКРУЖЕНИЯ
# ============================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
GROUP_ID = os.getenv("GROUP_ID")
ADMIN_IDS = os.getenv("ADMIN_IDS")
PHONE_NUMBER = os.getenv("PHONE_NUMBER", "+79256530940")

# Yandex Cloud Object Storage (ТОЛЬКО ИЗ ПЕРЕМЕННЫХ ОКРУЖЕНИЯ!)
YC_ACCESS_KEY_ID = os.getenv("YC_ACCESS_KEY_ID")
YC_SECRET_ACCESS_KEY = os.getenv("YC_SECRET_ACCESS_KEY")
YC_BUCKET_NAME = os.getenv("YC_BUCKET_NAME", "vet-bot-backups")
YC_ENDPOINT = "https://storage.yandexcloud.net"

print("=" * 50)
print("ПРОВЕРКА ПЕРЕМЕННЫХ ОКРУЖЕНИЯ:")
print(f"BOT_TOKEN: {'✅ НАЙДЕН' if BOT_TOKEN else '❌ ОТСУТСТВУЕТ'}")
print(f"GROUP_ID: {GROUP_ID if GROUP_ID else '❌ ОТСУТСТВУЕТ'}")
print(f"ADMIN_IDS: {ADMIN_IDS if ADMIN_IDS else '❌ ОТСУТСТВУЕТ'}")
print(f"PHONE_NUMBER: {PHONE_NUMBER}")
print(f"YC_ACCESS_KEY_ID: {'✅ НАЙДЕН' if YC_ACCESS_KEY_ID else '❌ ОТСУТСТВУЕТ'}")
print(f"YC_SECRET_ACCESS_KEY: {'✅ НАЙДЕН' if YC_SECRET_ACCESS_KEY else '❌ ОТСУТСТВУЕТ'}")
print("=" * 50)

if not BOT_TOKEN:
    print("❌ КРИТИЧЕСКАЯ ОШИБКА: BOT_TOKEN не найден!")
    exit(1)

GROUP_ID = int(GROUP_ID) if GROUP_ID else None
ADMIN_IDS = [int(x.strip()) for x in ADMIN_IDS.split(",")] if ADMIN_IDS else []

redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
r = redis.from_url(redis_url, decode_responses=True)

if "localhost" in redis_url or "127.0.0.1" in redis_url:
    try:
        r.config_set("save", "900 1 300 10 60 10000")
        r.config_set("appendonly", "yes")
        r.config_set("appendfsync", "everysec")
        print("✅ Redis персистентность включена")
    except Exception as e:
        print(f"⚠️ Не удалось настроить Redis: {e}")

storage = RedisStorage.from_url(redis_url)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=storage)
logging.basicConfig(level=logging.INFO)

# ============================================
# SQLite — ГЛОБАЛЬНЫЙ ПУЛ С БЛОКИРОВКОЙ
# ============================================

DB_PATH = "vet_bot.db"
_db_pool = None
_db_lock = asyncio.Lock()

async def get_db():
    global _db_pool
    async with _db_lock:
        if _db_pool is None:
            _db_pool = await aiosqlite.connect(DB_PATH)
            await _db_pool.execute("PRAGMA journal_mode=WAL")
            await _db_pool.execute("PRAGMA busy_timeout=5000")
        else:
            try:
                await _db_pool.execute("SELECT 1")
            except:
                _db_pool = await aiosqlite.connect(DB_PATH)
                await _db_pool.execute("PRAGMA journal_mode=WAL")
                await _db_pool.execute("PRAGMA busy_timeout=5000")
        return _db_pool

async def init_db():
    db = await get_db()
    await db.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            full_name TEXT,
            first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    await db.execute('''
        CREATE TABLE IF NOT EXISTS doctors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER UNIQUE NOT NULL,
            name TEXT NOT NULL,
            specialization TEXT NOT NULL,
            is_active BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    await db.execute('''
        CREATE TABLE IF NOT EXISTS consultations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id INTEGER NOT NULL,
            client_anonymous_id TEXT NOT NULL,
            doctor_id INTEGER,
            doctor_name TEXT,
            doctor_specialization TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ended_at TIMESTAMP,
            duration_seconds INTEGER,
            client_messages INTEGER DEFAULT 0,
            doctor_messages INTEGER DEFAULT 0,
            payment_confirmed BOOLEAN DEFAULT 0
        )
    ''')
    # Уникальный индекс для активных консультаций (защита от дублей)
    await db.execute('''
        CREATE UNIQUE INDEX IF NOT EXISTS idx_active_client
        ON consultations(client_id) WHERE status = 'active'
    ''')
    await db.execute('''
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id INTEGER NOT NULL,
            consultation_id INTEGER,
            amount INTEGER NOT NULL,
            status TEXT NOT NULL,
            receipt_file_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            confirmed_at TIMESTAMP
        )
    ''')
    await db.execute('''
        CREATE TABLE IF NOT EXISTS queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            anonymous_id TEXT NOT NULL,
            status TEXT DEFAULT 'waiting',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    await db.execute('''
        CREATE TABLE IF NOT EXISTS doctor_ratings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doctor_id INTEGER NOT NULL,
            client_id INTEGER NOT NULL,
            consultation_id INTEGER NOT NULL,
            rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
            comment TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    await db.execute('''
        CREATE TABLE IF NOT EXISTS support_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT,
            message TEXT NOT NULL,
            status TEXT DEFAULT 'new',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            resolved_at TIMESTAMP
        )
    ''')
    await db.execute('''
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT,
            feedback TEXT NOT NULL,
            status TEXT DEFAULT 'new',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    await db.execute('''
        CREATE TABLE IF NOT EXISTS blacklist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL UNIQUE,
            reason TEXT,
            blocked_by INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    try:
        await db.execute('ALTER TABLE consultations ADD COLUMN doctor_name TEXT')
    except:
        pass
    await db.commit()
    print("✅ База данных SQLite инициализирована")

# ============================================
# БЕЗОПАСНАЯ ОТПРАВКА
# ============================================

async def safe_send_message(chat_id, text, retries=3, **kwargs):
    try:
        return await bot.send_message(chat_id, text, **kwargs)
    except TelegramForbiddenError:
        print(f"⚠️ Пользователь {chat_id} заблокировал бота")
        db = await get_db()
        cursor = await db.execute('SELECT id FROM consultations WHERE client_id = ? AND status = "active"', (chat_id,))
        if await cursor.fetchone():
            doctor_id = r.get(f"client:{chat_id}:doctor")
            if doctor_id:
                await bot.send_message(int(doctor_id), f"⚠️ Клиент заблокировал бота. Консультация завершена.")
            await db.execute('UPDATE consultations SET status = "blocked" WHERE client_id = ? AND status = "active"', (chat_id,))
            await db.commit()
        return None
    except TelegramRetryAfter as e:
        if retries <= 0:
            return None
        await asyncio.sleep(e.retry_after)
        return await safe_send_message(chat_id, text, retries - 1, **kwargs)
    except Exception as e:
        print(f"Ошибка: {e}")
        return None

async def safe_send_photo(chat_id, photo, caption=None, retries=3, **kwargs):
    try:
        return await bot.send_photo(chat_id, photo, caption=caption, **kwargs)
    except TelegramForbiddenError:
        return None
    except TelegramRetryAfter as e:
        if retries <= 0:
            return None
        await asyncio.sleep(e.retry_after)
        return await safe_send_photo(chat_id, photo, caption=caption, retries - 1, **kwargs)
    except Exception as e:
        print(f"Ошибка: {e}")
        return None

# ============================================
# ЧЁРНЫЙ СПИСОК
# ============================================

async def is_blocked(user_id):
    db = await get_db()
    cursor = await db.execute('SELECT 1 FROM blacklist WHERE user_id = ?', (user_id,))
    return await cursor.fetchone() is not None

# ============================================
# ОПЛАТА (ИСТИНА В БД)
# ============================================

async def is_payment_confirmed(consultation_id):
    if not consultation_id:
        return False
    cached = r.get(f"payment:confirmed:{consultation_id}")
    if cached == "1":
        return True
    db = await get_db()
    cursor = await db.execute('''
        SELECT 1 FROM payments
        WHERE consultation_id = ? AND status = "confirmed"
        LIMIT 1
    ''', (consultation_id,))
    result = await cursor.fetchone()
    if result:
        r.setex(f"payment:confirmed:{consultation_id}", 3600, "1")
        return True
    return False

# ============================================
# ОЧЕРЕДЬ (SQLite — источник истины, Redis — кэш)
# ============================================

async def add_to_queue(topic, user_id, anonymous_id):
    """Добавляет в очередь (SQLite + Redis)"""
    db = await get_db()
    async with _db_lock:
        cursor = await db.execute('''
            INSERT INTO queue (topic, user_id, anonymous_id, status)
            VALUES (?, ?, ?, 'waiting')
        ''', (topic, user_id, anonymous_id))
        await db.commit()
        queue_id = cursor.lastrowid
    
    # Кэш в Redis
    r.rpush(f"queue:{topic}", f"{user_id}:{anonymous_id}:{queue_id}")
    r.sadd(f"queue_set:{topic}", user_id)
    return r.llen(f"queue:{topic}")

async def pop_from_queue(topic):
    """Извлекает из очереди (Redis + SQLite)"""
    queue_key = f"queue:{topic}"
    
    # Пытаемся взять из Redis
    item = r.lpop(queue_key)
    if not item:
        return None, None, None
    
    parts = item.split(":")
    if len(parts) != 3:
        return None, None, None
    
    user_id = int(parts[0])
    anonymous_id = parts[1]
    queue_id = int(parts[2])
    
    # Отмечаем в SQLite как обработанный
    db = await get_db()
    async with _db_lock:
        await db.execute('UPDATE queue SET status = "processed" WHERE id = ?', (queue_id,))
        await db.commit()
        r.srem(f"queue_set:{topic}", user_id)
    
    return user_id, anonymous_id, queue_id

async def get_queue_length(topic):
    """Длина очереди (из Redis)"""
    return r.llen(f"queue:{topic}")

async def restore_queue_from_db():
    """Восстанавливает очередь из SQLite при старте"""
    db = await get_db()
    for topic in TOPICS.keys():
        # Очищаем Redis
        r.delete(f"queue:{topic}")
        r.delete(f"queue_set:{topic}")
        
        # Загружаем из SQLite
        cursor = await db.execute('''
            SELECT user_id, anonymous_id, id FROM queue
            WHERE topic = ? AND status = 'waiting'
            ORDER BY id
        ''', (topic,))
        rows = await cursor.fetchall()
        for user_id, anonymous_id, queue_id in rows:
            r.rpush(f"queue:{topic}", f"{user_id}:{anonymous_id}:{queue_id}")
            r.sadd(f"queue_set:{topic}", user_id)
        print(f"🔄 Восстановлена очередь {topic}: {len(rows)} клиентов")

# ============================================
# КОНСИСТЕНТНОСТЬ
# ============================================

def clear_session(client_id, doctor_id):
    r.delete(f"client:{client_id}:doctor")
    r.delete(f"doctor:{doctor_id}:current_client")

# ============================================
# ВРАЧИ
# ============================================

TOPICS = {
    "dentistry": "Стоматолог",
    "surgery": "Хирург",
    "therapy": "Терапевт"
}

INITIAL_DOCTORS = {
    "dentistry": [{"id": 1092230808, "name": "Корнев Михаил"}],
    "surgery": [{"id": 222222222, "name": "Сидоров Алексей"}],
    "therapy": [{"id": 1906114179, "name": "Васильева Елена"}]
}

DOCTOR_IDS = []

def is_doctor(user_id):
    return user_id in DOCTOR_IDS

async def load_doctors_from_db():
    global DOCTOR_IDS
    db = await get_db()
    cursor = await db.execute('SELECT telegram_id, specialization FROM doctors WHERE is_active = 1')
    rows = await cursor.fetchall()
    DOCTOR_IDS = []
    for row in rows:
        doctor_id, specialization = row
        DOCTOR_IDS.append(doctor_id)
        if not r.get(f"doctor:{doctor_id}:topic"):
            r.set(f"doctor:{doctor_id}:topic", specialization)
    print(f"📋 Всего врачей в системе: {len(DOCTOR_IDS)}")

async def init_doctors():
    db = await get_db()
    for spec, doctors in INITIAL_DOCTORS.items():
        for doc in doctors:
            await db.execute('INSERT OR IGNORE INTO doctors (telegram_id, name, specialization, is_active) VALUES (?, ?, ?, 1)', (doc["id"], doc["name"], spec))
    await db.commit()
    await load_doctors_from_db()

async def get_doctor_name(doctor_id):
    db = await get_db()
    cursor = await db.execute('SELECT name FROM doctors WHERE telegram_id = ?', (doctor_id,))
    row = await cursor.fetchone()
    return row[0] if row else f"Врач {doctor_id}"

def get_anonymous_id(topic, user_id):
    short_id = str(user_id)[-4:]
    prefix_map = {"dentistry": "ST", "surgery": "SR", "therapy": "TP"}
    return f"{prefix_map.get(topic, 'CL')}{short_id}"

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

def get_available_doctors(topic):
    return [
        d for d in DOCTOR_IDS
        if r.get(f"doctor:{d}:topic") == topic
        and get_doctor_status(d) == "online"
        and get_current_client(d) is None
    ]

def get_doctor(topic):
    available = get_available_doctors(topic)
    if not available:
        return None
    if topic == "therapy":
        current_idx = int(r.get("therapy_round_robin_idx") or 0)
        r.set("therapy_round_robin_idx", current_idx + 1)
        return available[current_idx % len(available)]
    return available[0]

def update_doctor_activity(doctor_id):
    r.setex(f"doctor:{doctor_id}:last_activity", 600, str(time.time()))

def update_client_activity(client_id):
    r.setex(f"client:{client_id}:last_activity", 360, str(time.time()))

async def is_client_active(client_id):
    db = await get_db()
    cursor = await db.execute('''
        SELECT 1 FROM consultations 
        WHERE client_id = ? AND status = "active"
    ''', (client_id,))
    return await cursor.fetchone() is not None

async def has_active_consultation(client_id):
    db = await get_db()
    cursor = await db.execute('SELECT id FROM consultations WHERE client_id = ? AND status = "active"', (client_id,))
    return await cursor.fetchone() is not None

async def save_consultation_start(client_id, anonymous_id, doctor_id, specialization):
    db = await get_db()
    async with _db_lock:
        # Проверка на активную консультацию (уникальный индекс защитит, но проверим явно)
        cursor = await db.execute('''
            SELECT id FROM consultations 
            WHERE client_id = ? AND status = "active"
        ''', (client_id,))
        if await cursor.fetchone():
            return None
        
        cursor = await db.execute('''
            INSERT INTO consultations 
            (client_id, client_anonymous_id, doctor_id, doctor_specialization, status)
            VALUES (?, ?, ?, ?, 'waiting_payment')
        ''', (client_id, anonymous_id, doctor_id, specialization))
        await db.commit()
        return cursor.lastrowid

async def save_consultation_end(consultation_id, status, client_msgs=0, doctor_msgs=0):
    db = await get_db()
    async with _db_lock:
        await db.execute('''
            UPDATE consultations SET 
                status = ?, 
                ended_at = CURRENT_TIMESTAMP, 
                duration_seconds = (strftime("%s", "now") - strftime("%s", created_at)),
                client_messages = ?,
                doctor_messages = ?
            WHERE id = ?
        ''', (status, client_msgs, doctor_msgs, consultation_id))
        await db.commit()

# ============================================
# ФОНОВЫЙ ВОРКЕР ТАЙМАУТОВ (с grace period)
# ============================================

async def inactivity_worker():
    while True:
        await asyncio.sleep(30)
        for doctor_id in DOCTOR_IDS:
            current_client = get_current_client(doctor_id)
            if not current_client:
                continue
            
            doctor_last = r.get(f"doctor:{doctor_id}:last_activity")
            client_last = r.get(f"client:{current_client}:last_activity")
            doctor_inactive = doctor_last and (time.time() - float(doctor_last)) > 600
            client_inactive = client_last and (time.time() - float(client_last)) > 360
            
            if doctor_inactive and client_inactive:
                # Счётчик бездействия для защиты от ложных срабатываний
                counter_key = f"inactivity_counter:{doctor_id}:{current_client}"
                counter = r.incr(counter_key)
                if counter >= 3:  # 3 проверки подряд (90 секунд)
                    consultation_id = None
                    db = await get_db()
                    cursor = await db.execute('''
                        SELECT id FROM consultations 
                        WHERE client_id = ? AND status = "active"
                    ''', (int(current_client),))
                    row = await cursor.fetchone()
                    if row:
                        consultation_id = row[0]
                    if consultation_id:
                        await save_consultation_end(consultation_id, "auto_ended")
                    set_current_client(doctor_id, None)
                    clear_session(int(current_client), doctor_id)
                    await safe_send_message(int(current_client), "⏰ Консультация завершена из-за длительного бездействия.")
                    await safe_send_message(doctor_id, f"⏰ Консультация завершена из-за бездействия.")
                    r.delete(counter_key)
                else:
                    await safe_send_message(doctor_id, f"⚠️ Вы и клиент не активны. Авто-завершение через {3-counter} проверки.")
            else:
                r.delete(f"inactivity_counter:{doctor_id}:{current_client}")
                if doctor_inactive:
                    await safe_send_message(doctor_id, "⚠️ Вы не активны более 10 минут. Если вы здесь, напишите что-нибудь.")
                elif client_inactive:
                    await safe_send_message(int(current_client), "⚠️ Вы не активны более 6 минут. Если вы здесь, напишите что-нибудь.")

# ============================================
# БЭКАПЫ В YANDEX OBJECT STORAGE
# ============================================

def upload_to_yandex(file_path, object_name):
    """Загружает файл в Yandex Object Storage"""
    if not YC_ACCESS_KEY_ID or not YC_SECRET_ACCESS_KEY:
        print("⚠️ Yandex Cloud не настроен: пропускаем бэкап")
        return False
    
    session = boto3.session.Session()
    client = session.client(
        's3',
        endpoint_url=YC_ENDPOINT,
        aws_access_key_id=YC_ACCESS_KEY_ID,
        aws_secret_access_key=YC_SECRET_ACCESS_KEY,
        region_name='ru-central1',
        config=Config(signature_version='s3v4')
    )
    
    try:
        client.upload_file(file_path, YC_BUCKET_NAME, object_name)
        print(f"✅ Бэкап {object_name} загружен в Yandex Cloud!")
        return True
    except Exception as e:
        print(f"❌ Ошибка загрузки в Yandex Cloud: {e}")
        return False

async def clean_old_backups_from_yandex(max_files=30):
    """Удаляет старые бэкапы из Yandex Cloud, оставляя только последние max_files"""
    if not YC_ACCESS_KEY_ID or not YC_SECRET_ACCESS_KEY:
        return 0
    
    try:
        session = boto3.session.Session()
        client = session.client(
            's3',
            endpoint_url=YC_ENDPOINT,
            aws_access_key_id=YC_ACCESS_KEY_ID,
            aws_secret_access_key=YC_SECRET_ACCESS_KEY,
            region_name='ru-central1',
            config=Config(signature_version='s3v4')
        )
        
        response = client.list_objects_v2(Bucket=YC_BUCKET_NAME)
        if 'Contents' not in response:
            return 0
        
        objects = sorted(response['Contents'], key=lambda x: x['LastModified'], reverse=True)
        deleted_count = 0
        for obj in objects[max_files:]:
            client.delete_object(Bucket=YC_BUCKET_NAME, Key=obj['Key'])
            print(f"🗑️ Удалён старый бэкап: {obj['Key']}")
            deleted_count += 1
        
        if deleted_count > 0:
            print(f"✅ Очистка завершена. Удалено {deleted_count} старых бэкапов.")
        return deleted_count
    except Exception as e:
        print(f"❌ Ошибка очистки бэкапов в Yandex Cloud: {e}")
        return 0

async def backup_to_yandex():
    """Фоновая задача: раз в сутки бэкапим БД в Yandex Cloud"""
    while True:
        await asyncio.sleep(86400)  # 24 часа
        try:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_name = f"vet_bot_backup_{timestamp}.db"
            temp_path = f"/tmp/{backup_name}"
            
            # Копируем файл БД (VACUUM INTO не работает в aiosqlite)
            shutil.copy2(DB_PATH, temp_path)
            
            success = upload_to_yandex(temp_path, backup_name)
            os.remove(temp_path)
            
            if success:
                deleted = await clean_old_backups_from_yandex(max_files=30)
                for admin_id in ADMIN_IDS:
                    await safe_send_message(admin_id, f"✅ Бэкап БД создан и загружен в Yandex Cloud\n📅 {timestamp}\n🗑️ Удалено старых: {deleted}")
            else:
                for admin_id in ADMIN_IDS:
                    await safe_send_message(admin_id, f"❌ Ошибка загрузки бэкапа в Yandex Cloud\n📅 {timestamp}")
        except Exception as e:
            print(f"❌ Ошибка бэкапа: {e}")
            for admin_id in ADMIN_IDS:
                await safe_send_message(admin_id, f"❌ Критическая ошибка бэкапа:\n<pre>{e}</pre>", parse_mode="HTML")

# ============================================
# FSM СОСТОЯНИЯ
# ============================================

class PaymentState(StatesGroup):
    waiting_payment = State()
    waiting_receipt = State()

class WaitingState(StatesGroup):
    waiting_for_doctor = State()
    waiting_for_specific_doctor = State()
    waiting_for_admin_message = State()
    waiting_for_support_reply = State()
    waiting_for_feedback = State()
    waiting_for_rating_comment = State()

# ============================================
# КОМАНДЫ
# ============================================

@dp.message(Command("start"))
async def start(message: types.Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    
    if await is_blocked(user_id):
        await safe_send_message(user_id, "⛔ Ваш аккаунт заблокирован.")
        return
    
    if is_doctor(user_id):
        await safe_send_message(user_id, "👨‍⚕️ Панель врача", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🟢 Стать онлайн", callback_data="doctor_online")],
            [InlineKeyboardButton(text="🔴 Стать офлайн", callback_data="doctor_offline")],
            [InlineKeyboardButton(text="📋 Очередь", callback_data="view_queue")],
            [InlineKeyboardButton(text="📊 Статус", callback_data="show_status")]
        ]))
    else:
        await safe_send_message(user_id, "🐾 Добро пожаловать!\nВыберите специалиста:", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=t) for t in TOPICS.values()]], resize_keyboard=True))

@dp.message(Command("online"))
async def go_online(message: types.Message):
    user_id = message.from_user.id
    if is_doctor(user_id):
        set_doctor_status(user_id, "online")
        await safe_send_message(user_id, "🟢 Вы онлайн")

@dp.message(Command("offline"))
async def go_offline(message: types.Message):
    user_id = message.from_user.id
    if is_doctor(user_id):
        set_doctor_status(user_id, "offline")
        await safe_send_message(user_id, "🔴 Вы офлайн")

@dp.message(Command("next"))
async def next_command(message: types.Message):
    user_id = message.from_user.id
    if not is_doctor(user_id):
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
                # Возвращаем в очередь
                db = await get_db()
                async with _db_lock:
                    await db.execute('UPDATE queue SET status = "waiting" WHERE id = ?', (queue_id,))
                r.rpush(f"queue:{topic}", f"{client_id}:{anonymous_id}:{queue_id}")
                r.sadd(f"queue_set:{topic}", client_id)
                continue
            
            try:
                consultation_id = None
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
                    # Возвращаем в очередь
                    async with _db_lock:
                        await db.execute('UPDATE queue SET status = "waiting" WHERE id = ?', (queue_id,))
                    r.rpush(f"queue:{topic}", f"{client_id}:{anonymous_id}:{queue_id}")
                    r.sadd(f"queue_set:{topic}", client_id)
                    continue
                
                async with _db_lock:
                    await db.execute('''
                        UPDATE consultations 
                        SET doctor_id = ?, doctor_name = ?, status = 'active'
                        WHERE id = ?
                    ''', (user_id, await get_doctor_name(user_id), consultation_id))
                    await db.commit()
                
                set_current_client(user_id, client_id)
                r.set(f"client:{client_id}:doctor", user_id)
                
                await safe_send_message(client_id, f"✅ Врач принял заявку! Ваш ID: {anonymous_id}")
                await safe_send_message(user_id, f"✅ Клиент {anonymous_id} принят")
                update_doctor_activity(user_id)
                return
            finally:
                r.delete(client_lock)
        
        await safe_send_message(user_id, "📭 Нет клиентов с подтверждённой оплатой")
    finally:
        r.delete(doctor_lock)

@dp.message(Command("status"))
async def status_command(message: types.Message):
    user_id = message.from_user.id
    if not is_doctor(user_id):
        return
    topic = r.get(f"doctor:{user_id}:topic")
    current = get_current_client(user_id)
    queue_len = await get_queue_length(topic) if topic else 0
    text = f"📊 Статус: {get_doctor_status(user_id)}\nСпециализация: {TOPICS.get(topic, '?')}\n"
    text += f"👤 Текущий клиент: {current or 'нет'}\n📋 Очередь: {queue_len}"
    await safe_send_message(user_id, text)

@dp.message(Command("my_consultations"))
async def my_consultations(message: types.Message):
    user_id = message.from_user.id
    if is_doctor(user_id):
        await safe_send_message(user_id, "⛔ Эта команда только для клиентов.")
        return
    
    db = await get_db()
    cursor = await db.execute('''
        SELECT id, doctor_name, doctor_specialization, status, created_at
        FROM consultations 
        WHERE client_id = ? 
        ORDER BY created_at DESC 
        LIMIT 10
    ''', (user_id,))
    consultations = await cursor.fetchall()
    
    if not consultations:
        await safe_send_message(user_id, "📭 У вас пока нет консультаций.")
        return
    
    text = "📋 <b>Ваши консультации</b>\n\n"
    for cons in consultations:
        status_emoji = "✅" if cons[3] == "ended" else "⚠️" if cons[3] == "auto_ended" else "⏳"
        date = cons[4][:10] if cons[4] else "дата неизвестна"
        text += f"{status_emoji} #{cons[0]} — {cons[1] or 'Врач не назначен'} ({cons[2]}) от {date}\n"
    
    await safe_send_message(user_id, text, parse_mode="HTML")

@dp.message(Command("end"))
async def end_consultation_command(message: types.Message):
    user_id = message.from_user.id
    
    if is_doctor(user_id):
        current_client = get_current_client(user_id)
        if current_client:
            db = await get_db()
            cursor = await db.execute('''
                SELECT id FROM consultations 
                WHERE client_id = ? AND status = "active"
            ''', (int(current_client),))
            row = await cursor.fetchone()
            if row:
                await save_consultation_end(row[0], "ended_by_doctor")
            set_current_client(user_id, None)
            clear_session(int(current_client), user_id)
            await safe_send_message(int(current_client), "🔚 Врач завершил консультацию.")
            await safe_send_message(user_id, "✅ Консультация завершена")
        return
    
    if await is_client_active(user_id):
        db = await get_db()
        cursor = await db.execute('''
            SELECT id, doctor_id FROM consultations 
            WHERE client_id = ? AND status = "active"
        ''', (user_id,))
        row = await cursor.fetchone()
        if row:
            consultation_id, doctor_id = row
            await save_consultation_end(consultation_id, "ended_by_client")
            if doctor_id:
                clear_session(user_id, doctor_id)
                await safe_send_message(doctor_id, "🔚 Клиент завершил консультацию.")
        await safe_send_message(user_id, "🔚 Вы завершили консультацию.")

# ============================================
# ВЫБОР ТЕМЫ КЛИЕНТОМ
# ============================================

@dp.message(F.text.in_(list(TOPICS.values())))
async def select_topic(message: types.Message, state: FSMContext):
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
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Я оплатил", callback_data=f"paid_{topic_key}")]
        ])
    )
    await state.set_state(PaymentState.waiting_payment)

# ============================================
# ОПЛАТА
# ============================================

@dp.callback_query(lambda c: c.data.startswith("paid_"))
async def process_payment_button(call: types.CallbackQuery, state: FSMContext):
    topic_key = call.data.split("_")[1]
    user_id = call.from_user.id
    
    await safe_send_message(user_id, "📎 Отправьте скриншот или фото чека.")
    await state.update_data(payment_topic=topic_key)
    await state.set_state(PaymentState.waiting_receipt)
    r.setex(f"fsm_timeout:{user_id}:waiting_receipt", 300, "1")
    await call.answer()

@dp.message(PaymentState.waiting_receipt, F.photo)
async def handle_receipt(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    data = await state.get_data()
    topic_key = data.get("payment_topic")
    
    if not topic_key:
        await safe_send_message(user_id, "❌ Ошибка: не выбрана тема. Начните заново с /start")
        await state.clear()
        return
    
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
    
    await db.execute('''
        INSERT INTO payments (client_id, consultation_id, amount, status, receipt_file_id)
        VALUES (?, ?, 500, "pending", ?)
    ''', (user_id, consultation_id, message.photo[-1].file_id))
    await db.commit()
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"confirm_payment:{user_id}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_payment:{user_id}")
        ]
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
    r.delete(f"fsm_timeout:{user_id}:waiting_receipt")

@dp.callback_query(lambda c: c.data.startswith("confirm_payment:"))
async def confirm_payment(call: types.CallbackQuery):
    doctor_id = call.from_user.id
    if not is_doctor(doctor_id):
        return await call.answer("⛔ Только для врачей")
    
    client_id = int(call.data.split(":")[1])
    
    db = await get_db()
    
    cursor = await db.execute('''
        SELECT id, consultation_id FROM payments
        WHERE client_id = ? AND status = "pending"
        ORDER BY id DESC LIMIT 1
    ''', (client_id,))
    row = await cursor.fetchone()
    
    if not row:
        return await call.answer("Платёж не найден")
    
    payment_id, consultation_id = row
    
    cursor = await db.execute('''
        SELECT status FROM payments
        WHERE client_id = ? AND status = "confirmed"
    ''', (client_id,))
    if await cursor.fetchone():
        return await call.answer("Оплата уже подтверждена")
    
    await db.execute('''
        UPDATE payments 
        SET status = "confirmed", confirmed_at = CURRENT_TIMESTAMP
        WHERE id = ?
    ''', (payment_id,))
    await db.commit()
    
    if consultation_id:
        await db.execute('''
            UPDATE consultations SET status = 'paid', payment_confirmed = 1
            WHERE id = ?
        ''', (consultation_id,))
        await db.commit()
        r.setex(f"payment:confirmed:{consultation_id}", 3600, "1")
    
    await safe_send_message(client_id, "✅ Оплата подтверждена! Ожидайте врача.")
    await call.message.edit_caption(call.message.caption + "\n\n✅ Оплата подтверждена")
    await call.answer("Подтверждено")

@dp.callback_query(lambda c: c.data.startswith("reject_payment:"))
async def reject_payment(call: types.CallbackQuery):
    doctor_id = call.from_user.id
    if not is_doctor(doctor_id):
        return await call.answer("⛔ Только для врачей")
    
    client_id = int(call.data.split(":")[1])
    
    db = await get_db()
    await db.execute('''
        UPDATE payments 
        SET status = "rejected"
        WHERE client_id = ? AND status = "pending"
    ''', (client_id,))
    await db.commit()
    
    await safe_send_message(client_id, "❌ Оплата отклонена. Попробуйте снова.")
    await call.message.edit_caption(call.message.caption + "\n\n❌ Оплата отклонена")
    await call.answer("Отклонено")

# ============================================
# ПЕРЕСЫЛКА СООБЩЕНИЙ
# ============================================

@dp.message()
async def chat_messages(message: types.Message):
    user_id = message.from_user.id
    
    if await is_blocked(user_id):
        return
    
    if message.text in ["✅ Я оплатил"] + list(TOPICS.values()):
        return
    
    if await is_client_active(user_id):
        doctor_id = r.get(f"client:{user_id}:doctor")
        if not doctor_id:
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
    
    elif is_doctor(user_id):
        current_client = get_current_client(user_id)
        if current_client:
            await safe_send_message(int(current_client), f"👨‍⚕️ Врач: {message.text}")
            update_doctor_activity(user_id)

# ============================================
# CALLBACK-ОБРАБОТЧИКИ
# ============================================

@dp.callback_query(lambda c: c.data == "doctor_online")
async def doctor_set_online(call: types.CallbackQuery):
    doctor_id = call.from_user.id
    if not is_doctor(doctor_id):
        await call.answer("⛔ Только для врачей")
        return
    set_doctor_status(doctor_id, "online")
    await call.message.edit_text("🟢 Вы стали онлайн.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔴 Стать офлайн", callback_data="doctor_offline")],
        [InlineKeyboardButton(text="📋 Очередь", callback_data="view_queue")],
        [InlineKeyboardButton(text="📊 Статус", callback_data="show_status")]
    ]))
    await call.answer()

@dp.callback_query(lambda c: c.data == "doctor_offline")
async def doctor_set_offline(call: types.CallbackQuery):
    doctor_id = call.from_user.id
    if not is_doctor(doctor_id):
        await call.answer("⛔ Только для врачей")
        return
    set_doctor_status(doctor_id, "offline")
    await call.message.edit_text("🔴 Вы стали офлайн.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🟢 Стать онлайн", callback_data="doctor_online")],
        [InlineKeyboardButton(text="📋 Очередь", callback_data="view_queue")],
        [InlineKeyboardButton(text="📊 Статус", callback_data="show_status")]
    ]))
    await call.answer()

@dp.callback_query(lambda c: c.data == "view_queue")
async def view_queue(call: types.CallbackQuery):
    doctor_id = call.from_user.id
    if not is_doctor(doctor_id):
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

@dp.callback_query(lambda c: c.data == "show_status")
async def show_status_callback(call: types.CallbackQuery):
    doctor_id = call.from_user.id
    if not is_doctor(doctor_id):
        await call.answer("⛔ Только для врачей")
        return
    topic = r.get(f"doctor:{doctor_id}:topic")
    current = get_current_client(doctor_id)
    queue_len = await get_queue_length(topic) if topic else 0
    text = f"📊 Статус: {get_doctor_status(doctor_id)}\nСпециализация: {TOPICS.get(topic, '?')}\n"
    text += f"👤 Текущий клиент: {current or 'нет'}\n📋 Очередь: {queue_len}"
    await call.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Очередь", callback_data="view_queue")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="doctor_online")]
    ]))
    await call.answer()

# ============================================
# АДМИН-КОМАНДЫ
# ============================================

@dp.message(Command("ban"))
async def ban_user(message: types.Message):
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

@dp.message(Command("unban"))
async def unban_user(message: types.Message):
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

@dp.message(Command("stats"))
async def admin_stats(message: types.Message):
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS:
        return
    db = await get_db()
    cursor = await db.execute('SELECT COUNT(*) FROM users')
    users = (await cursor.fetchone())[0]
    cursor = await db.execute('SELECT COUNT(*) FROM consultations')
    cons = (await cursor.fetchone())[0]
    cursor = await db.execute('SELECT COUNT(*) FROM consultations WHERE status = "active"')
    active = (await cursor.fetchone())[0]
    await safe_send_message(user_id, f"📊 Статистика\n👤 Пользователей: {users}\n📋 Консультаций: {cons}\n🟢 Активных: {active}")

# ============================================
# ВОССТАНОВЛЕНИЕ ПОСЛЕ РЕСТАРТА
# ============================================

async def restore_state():
    db = await get_db()
    
    # Очищаем Redis перед восстановлением
    for topic in TOPICS.keys():
        r.delete(f"queue:{topic}")
        r.delete(f"queue_set:{topic}")
    
    # Восстанавливаем очередь из SQLite
    await restore_queue_from_db()
    
    # Восстанавливаем активные консультации
    cursor = await db.execute('''
        SELECT id, client_id, doctor_id FROM consultations 
        WHERE status = "active"
    ''')
    rows = await cursor.fetchall()
    for consultation_id, client_id, doctor_id in rows:
        if doctor_id:
            if not r.get(f"doctor:{doctor_id}:current_client"):
                r.set(f"doctor:{doctor_id}:current_client", client_id)
            if not r.get(f"client:{client_id}:doctor"):
                r.set(f"client:{client_id}:doctor", doctor_id)
        print(f"🔄 Восстановлена консультация #{consultation_id}")
    
    # Восстанавливаем кэш подтверждённых оплат
    cursor = await db.execute('''
        SELECT DISTINCT consultation_id FROM payments 
        WHERE status = "confirmed"
    ''')
    for (consultation_id,) in await cursor.fetchall():
        if consultation_id:
            r.setex(f"payment:confirmed:{consultation_id}", 3600, "1")
            print(f"🔄 Восстановлен кэш оплаты для консультации #{consultation_id}")
    
    # Восстанавливаем статусы врачей
    for doctor_id in DOCTOR_IDS:
        last_activity = r.get(f"doctor:{doctor_id}:last_activity")
        if last_activity and (time.time() - float(last_activity)) < 300:
            set_doctor_status(doctor_id, "online")
        else:
            set_doctor_status(doctor_id, "offline")
    
    print(f"🔄 Восстановление завершено")

# ============================================
# ЗАПУСК
# ============================================

async def set_commands():
    await bot.set_my_commands([
        BotCommand(command="start", description="Главное меню"),
        BotCommand(command="online", description="Стать онлайн (врач)"),
        BotCommand(command="offline", description="Стать офлайн (врач)"),
        BotCommand(command="status", description="Мой статус (врач)"),
        BotCommand(command="next", description="Взять следующего (врач)"),
        BotCommand(command="my_consultations", description="Мои консультации"),
        BotCommand(command="end", description="Завершить консультацию"),
        BotCommand(command="ban", description="Заблокировать (админ)"),
        BotCommand(command="unban", description="Разблокировать (админ)"),
        BotCommand(command="stats", description="Статистика (админ)"),
    ])

async def shutdown():
    print("🛑 Завершение работы...")
    await bot.session.close()
    await dp.storage.close()
    global _db_pool
    if _db_pool:
        await _db_pool.close()

async def main():
    await init_db()
    await init_doctors()
    await restore_state()
    await set_commands()
    asyncio.create_task(inactivity_worker())
    asyncio.create_task(backup_to_yandex())
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        asyncio.run(shutdown())