import logging
import redis
from config import REDIS_URL, DOCTORS
from database.db import get_db
from database.doctors import REAL_TELEGRAM_USER_ID_MIN, reconcile_online_presence_from_db
from services.validators import get_doctor_status, get_current_client

r = redis.from_url(REDIS_URL, decode_responses=True)


async def pick_doctor_for_topic(topic_key: str) -> int | None:
    """
    Назначение врача по теме (ключ специализации из БД).
    Источник — только SQLite doctors, не config.DOCTORS.
    Приоритет: онлайн без активного клиента, иначе любой онлайн; внутри группы — round-robin.
    """
    db = await get_db()
    cur = await db.execute(
        """
        SELECT ds.telegram_id
        FROM doctor_specializations ds
        INNER JOIN doctors d ON d.telegram_id = ds.telegram_id
        WHERE d.is_active IS TRUE AND ds.specialization = ? AND d.telegram_id >= ?
        """,
        (topic_key, REAL_TELEGRAM_USER_ID_MIN),
    )
    tids = [int(row[0]) for row in await cur.fetchall()]
    if not tids:
        return None
    await reconcile_online_presence_from_db(tids)
    try:
        online = [t for t in tids if get_doctor_status(t) == "online"]
        if not online:
            return None
        free = [t for t in online if get_current_client(t) is None]
        pool = free if free else online
        pool = sorted(pool)
        rr_key = f"rr_topic:{topic_key}"
        idx = int(r.get(rr_key) or 0)
        chosen = pool[idx % len(pool)]
        r.set(rr_key, idx + 1)
        return chosen
    except (redis.ConnectionError, OSError, TimeoutError) as e:
        logging.warning(
            "Redis недоступен при выборе врача по теме %s, берём первого из БД: %s",
            topic_key,
            e,
        )
        return sorted(tids)[0]
    except Exception as e:
        logging.warning(
            "Сбой Redis/статусов при выборе врача по теме %s, берём первого из БД: %s",
            topic_key,
            e,
        )
        return sorted(tids)[0]


def get_doctor_by_specialization(specialization: str):
    """
    Возвращает ID свободного онлайн-врача по специализации.
    Если все врачи заняты — возвращает None.
    """
    doctors_list = DOCTORS.get(specialization, [])
    
    # Ищем свободного онлайн-врача
    for doctor_id in doctors_list:
        if get_doctor_status(doctor_id) == "online" and get_current_client(doctor_id) is None:
            return doctor_id
    
    return None


def get_available_doctors_by_specialization(specialization: str):
    """Возвращает список всех свободных онлайн-врачей по специализации"""
    doctors_list = DOCTORS.get(specialization, [])
    
    available = []
    for doctor_id in doctors_list:
        if get_doctor_status(doctor_id) == "online" and get_current_client(doctor_id) is None:
            available.append(doctor_id)
    
    return available


def get_all_online_doctors():
    """Возвращает список всех онлайн-врачей (без проверки занятости)"""
    online = []
    for spec, doctors_list in DOCTORS.items():
        for doctor_id in doctors_list:
            if get_doctor_status(doctor_id) == "online":
                online.append(doctor_id)
    return online


def get_doctor_by_specialization_round_robin(specialization: str):
    """
    Выбирает врача по кругу (round-robin) среди всех онлайн-врачей
    данной специализации, даже если они заняты.
    """
    doctors_list = DOCTORS.get(specialization, [])
    
    # Фильтруем только онлайн
    online_doctors = [d for d in doctors_list if get_doctor_status(d) == "online"]
    
    if not online_doctors:
        return None
    
    # Round-robin
    key = f"round_robin:{specialization}"
    current_idx = int(r.get(key) or 0)
    doctor_id = online_doctors[current_idx % len(online_doctors)]
    r.set(key, current_idx + 1)
    
    return doctor_id


def get_least_busy_doctor(specialization: str):
    """
    Выбирает врача с наименьшим количеством активных клиентов.
    """
    doctors_list = DOCTORS.get(specialization, [])
    
    # Фильтруем только онлайн
    online_doctors = [d for d in doctors_list if get_doctor_status(d) == "online"]
    
    if not online_doctors:
        return None
    
    # Сортируем по занятости (текущий клиент или нет)
    def busy_score(doctor_id):
        return 1 if get_current_client(doctor_id) else 0
    
    online_doctors.sort(key=busy_score)
    
    return online_doctors[0]


def get_doctor_info(doctor_id: int):
    """Возвращает информацию о враче из Redis"""
    topic = r.get(f"doctor:{doctor_id}:topic")
    status = get_doctor_status(doctor_id)
    current_client = get_current_client(doctor_id)
    
    return {
        "id": doctor_id,
        "specialization": topic,
        "status": status,
        "current_client": current_client,
        "is_busy": current_client is not None,
        "is_online": status == "online"
    }


def get_all_doctors_info():
    """Возвращает информацию о всех врачах"""
    result = {}
    for spec, doctors_list in DOCTORS.items():
        for doctor_id in doctors_list:
            result[doctor_id] = get_doctor_info(doctor_id)
    return result