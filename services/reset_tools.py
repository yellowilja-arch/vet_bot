import redis
from config import REDIS_URL
from database.doctors import DOCTOR_IDS
from database.db import get_db
from services.validators import set_doctor_status

r = redis.from_url(REDIS_URL, decode_responses=True)

async def reset_user_state(user_id: int):
    """Сбрасывает состояние пользователя (очищает Redis и SQLite)"""
    # Очищаем Redis
    r.delete(f"user:{user_id}:active")
    r.delete(f"user:{user_id}:consultation_id")
    r.delete(f"user:{user_id}:payment")
    r.delete(f"user:{user_id}:topic")
    r.delete(f"user:{user_id}:anonymous_id")
    r.delete(f"user:{user_id}:queue_position")
    r.delete(f"client:{user_id}:doctor")
    
    # Закрываем консультацию в БД
    db = await get_db()
    await db.execute('''
        UPDATE consultations SET status = "cancelled"
        WHERE client_id = ? AND status = "active"
    ''', (user_id,))
    await db.commit()

async def reset_doctor_state(doctor_id: int):
    """Сбрасывает состояние врача"""
    r.delete(f"doctor:{doctor_id}:current_client")
    set_doctor_status(doctor_id, "offline")

async def reset_all_states():
    """Сбрасывает все состояния (для админа)"""
    # Очищаем все активные консультации в БД
    db = await get_db()
    await db.execute('''
        UPDATE consultations SET status = "cancelled"
        WHERE status = "active"
    ''')
    await db.commit()
    
    # Очищаем Redis
    for key in r.scan_iter("user:*:active"):
        r.delete(key)
    for key in r.scan_iter("user:*:consultation_id"):
        r.delete(key)
    for key in r.scan_iter("doctor:*:current_client"):
        r.delete(key)
    
    # Сбрасываем статусы врачей
    for doctor_id in DOCTOR_IDS:
        set_doctor_status(doctor_id, "offline")

async def close_stuck_requests():
    """Закрывает зависшие запросы (старше 24 часов)"""
    db = await get_db()
    await db.execute('''
        UPDATE consultations SET status = "auto_ended"
        WHERE status = "active" AND created_at < datetime('now', '-1 day')
    ''')
    await db.commit()

async def unlock_all_doctors():
    """Разблокирует всех врачей (снимает current_client)"""
    for doctor_id in DOCTOR_IDS:
        r.delete(f"doctor:{doctor_id}:current_client")
        set_doctor_status(doctor_id, "offline")