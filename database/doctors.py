import redis
from config import REDIS_URL, INITIAL_DOCTORS, TOPICS
from database.db import get_db

r = redis.from_url(REDIS_URL, decode_responses=True)
DOCTOR_IDS = []

async def load_doctors_from_db():
    """Загружает врачей из БД в память и Redis"""
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
    return DOCTOR_IDS

async def init_doctors():
    """Добавляет начальных врачей в БД при первом запуске"""
    db = await get_db()
    for spec, doctors in INITIAL_DOCTORS.items():
        for doc in doctors:
            await db.execute('''
                INSERT OR IGNORE INTO doctors (telegram_id, name, specialization, is_active)
                VALUES (?, ?, ?, 1)
            ''', (doc["id"], doc["name"], spec))
    await db.commit()
    await load_doctors_from_db()

async def get_doctor_name(doctor_id: int):
    """Возвращает имя врача по его Telegram ID"""
    db = await get_db()
    cursor = await db.execute('SELECT name FROM doctors WHERE telegram_id = ?', (doctor_id,))
    row = await cursor.fetchone()
    return row[0] if row else f"Врач {doctor_id}"

async def get_all_doctors():
    """Возвращает список всех активных врачей"""
    db = await get_db()
    cursor = await db.execute('''
        SELECT telegram_id, name, specialization FROM doctors WHERE is_active = 1
    ''')
    return await cursor.fetchall()

async def add_doctor(telegram_id: int, name: str, specialization: str):
    """Добавляет нового врача"""
    db = await get_db()
    await db.execute('''
        INSERT OR REPLACE INTO doctors (telegram_id, name, specialization, is_active)
        VALUES (?, ?, ?, 1)
    ''', (telegram_id, name, specialization))
    await db.commit()
    await load_doctors_from_db()

async def remove_doctor(telegram_id: int):
    """Удаляет врача (soft delete)"""
    db = await get_db()
    await db.execute('UPDATE doctors SET is_active = 0 WHERE telegram_id = ?', (telegram_id,))
    await db.commit()
    await load_doctors_from_db()