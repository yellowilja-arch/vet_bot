from database.db import get_db
from services.validators import has_active_consultation
from database.doctors import get_doctor_name

async def save_consultation_start(client_id: int, anonymous_id: str, doctor_id: int, specialization: str):
    """Сохраняет начало консультации, возвращает consultation_id"""
    if await has_active_consultation(client_id):
        return None
    
    doctor_name = await get_doctor_name(doctor_id) if doctor_id else None
    
    db = await get_db()
    cursor = await db.execute('''
        INSERT INTO consultations 
        (client_id, client_anonymous_id, doctor_id, doctor_name, doctor_specialization, status)
        VALUES (?, ?, ?, ?, ?, 'waiting_payment')
    ''', (client_id, anonymous_id, doctor_id, doctor_name, specialization))
    await db.commit()
    return cursor.lastrowid

async def save_consultation_end(consultation_id: int, status: str, client_msgs: int = 0, doctor_msgs: int = 0):
    """Сохраняет завершение консультации"""
    db = await get_db()
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

async def update_consultation_doctor(consultation_id: int, doctor_id: int, doctor_name: str):
    """Назначает врача консультации и активирует её"""
    db = await get_db()
    await db.execute('''
        UPDATE consultations 
        SET doctor_id = ?, doctor_name = ?, status = 'active'
        WHERE id = ?
    ''', (doctor_id, doctor_name, consultation_id))
    await db.commit()

async def get_user_consultations(client_id: int, limit: int = 10):
    """Возвращает последние консультации клиента"""
    db = await get_db()
    cursor = await db.execute('''
        SELECT id, doctor_name, doctor_specialization, status, created_at
        FROM consultations 
        WHERE client_id = ? 
        ORDER BY created_at DESC 
        LIMIT ?
    ''', (client_id, limit))
    return await cursor.fetchall()

async def get_active_consultations():
    """Возвращает все активные консультации"""
    db = await get_db()
    cursor = await db.execute('''
        SELECT id, client_id, doctor_id FROM consultations WHERE status = "active"
    ''')
    return await cursor.fetchall()
