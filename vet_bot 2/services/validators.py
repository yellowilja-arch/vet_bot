import time
import redis
from config import REDIS_URL, ADMIN_IDS, DOCTOR_IDS
from database.db import get_db

r = redis.from_url(REDIS_URL, decode_responses=True)

async def is_doctor(user_id):
    return user_id in DOCTOR_IDS

async def is_admin(user_id):
    return user_id in ADMIN_IDS

async def is_blocked(user_id):
    db = await get_db()
    cursor = await db.execute('SELECT 1 FROM blacklist WHERE user_id = ?', (user_id,))
    return await cursor.fetchone() is not None

async def has_active_consultation(client_id):
    db = await get_db()
    cursor = await db.execute('SELECT id FROM consultations WHERE client_id = ? AND status = "active"', (client_id,))
    return await cursor.fetchone() is not None

async def is_client_active(client_id):
    if r.get(f"user:{client_id}:active"):
        return True
    db = await get_db()
    cursor = await db.execute('SELECT 1 FROM consultations WHERE client_id = ? AND status = "active"', (client_id,))
    return await cursor.fetchone() is not None

def get_doctor_status(doctor_id):
    return r.get(f"doctor:{doctor_id}:status") or "offline"

def get_current_client(doctor_id):
    return r.get(f"doctor:{doctor_id}:current_client")

def set_doctor_status(doctor_id, status):
    r.set(f"doctor:{doctor_id}:status", status)

def set_current_client(doctor_id, user_id):
    if user_id:
        r.set(f"doctor:{doctor_id}:current_client", user_id)
    else:
        r.delete(f"doctor:{doctor_id}:current_client")

def update_doctor_activity(doctor_id):
    r.setex(f"doctor:{doctor_id}:last_activity", 600, str(time.time()))

def update_client_activity(client_id):
    r.setex(f"client:{client_id}:last_activity", 360, str(time.time()))

def clear_session(client_id, doctor_id):
    r.delete(f"client:{client_id}:doctor")
    r.delete(f"doctor:{doctor_id}:current_client")

async def is_payment_confirmed(consultation_id: int):
    """Проверяет, подтверждена ли оплата для консультации"""
    from database.db import get_db
    db = await get_db()
    cursor = await db.execute('SELECT payment_confirmed FROM consultations WHERE id = ?', (consultation_id,))
    row = await cursor.fetchone()
    return row and row[0] == 1