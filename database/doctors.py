import redis
from config import REDIS_URL, INITIAL_DOCTORS, SPECIALISTS
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


async def get_doctor_specialization(doctor_id: int) -> str | None:
    db = await get_db()
    cursor = await db.execute(
        "SELECT specialization FROM doctors WHERE telegram_id = ? AND is_active = 1",
        (doctor_id,),
    )
    row = await cursor.fetchone()
    return row[0] if row else None


def specialization_display_label(spec_key: str | None) -> str:
    """Человекочитаемое название специализации по ключу из БД."""
    if not spec_key:
        return "Не указана"
    return SPECIALISTS.get(spec_key, spec_key)

async def get_all_doctors():
    """Возвращает список всех активных врачей"""
    db = await get_db()
    cursor = await db.execute('''
        SELECT telegram_id, name, specialization FROM doctors WHERE is_active = 1
    ''')
    return await cursor.fetchall()


async def list_distinct_specializations_active() -> list[str]:
    """Все специализации, по которым есть активные врачи."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT DISTINCT specialization FROM doctors WHERE is_active = 1 ORDER BY specialization",
    )
    return [row[0] for row in await cursor.fetchall()]


async def topic_keys_available_for_client_menu() -> list[str]:
    """
    Темы для клиента: специализация видна только если есть ≥1 активный врач
    по этой специализации в статусе online.
    """
    from services.validators import get_doctor_status

    specs = await list_distinct_specializations_active()
    keys: list[str] = []
    db = await get_db()
    for spec in specs:
        cur = await db.execute(
            "SELECT telegram_id FROM doctors WHERE is_active = 1 AND specialization = ?",
            (spec,),
        )
        for (tid,) in await cur.fetchall():
            if get_doctor_status(tid) == "online":
                keys.append(spec)
                break
    return sorted(set(keys))

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