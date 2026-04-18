import asyncio
import time
import redis
from config import REDIS_URL, INACTIVITY_DOCTOR_SECONDS, INACTIVITY_CLIENT_SECONDS
from database.doctors import DOCTOR_IDS
from services.validators import get_current_client, set_current_client, clear_session
from database.consultations import save_consultation_end
from utils.helpers import safe_send_message

r = redis.from_url(REDIS_URL, decode_responses=True)

async def inactivity_worker():
    """Фоновый воркер для проверки бездействия врачей и клиентов"""
    while True:
        await asyncio.sleep(30)  # проверка каждые 30 секунд
        
        for doctor_id in DOCTOR_IDS:
            current_client = get_current_client(doctor_id)
            if not current_client:
                continue
            
            doctor_last = r.get(f"doctor:{doctor_id}:last_activity")
            client_last = r.get(f"client:{current_client}:last_activity")
            doctor_inactive = doctor_last and (time.time() - float(doctor_last)) > INACTIVITY_DOCTOR_SECONDS
            client_inactive = client_last and (time.time() - float(client_last)) > INACTIVITY_CLIENT_SECONDS
            
            if doctor_inactive and client_inactive:
                # Счётчик бездействия (3 проверки подряд = 90 секунд)
                counter_key = f"inactivity_counter:{doctor_id}:{current_client}"
                counter = r.incr(counter_key)
                if counter >= 3:
                    # Завершаем консультацию
                    from database.db import get_db
                    db = await get_db()
                    cursor = await db.execute('''
                        SELECT id FROM consultations 
                        WHERE client_id = ? AND status = "active"
                    ''', (int(current_client),))
                    row = await cursor.fetchone()
                    if row:
                        await save_consultation_end(row[0], "auto_ended")
                    set_current_client(doctor_id, None)
                    clear_session(int(current_client), doctor_id)
                    await safe_send_message(int(current_client), "⏰ Консультация завершена из-за длительного бездействия.")
                    await safe_send_message(doctor_id, "⏰ Консультация завершена из-за бездействия.")
                    r.delete(counter_key)
                else:
                    await safe_send_message(doctor_id, f"⚠️ Вы и клиент не активны. Авто-завершение через {3-counter} проверки.")
            else:
                r.delete(f"inactivity_counter:{doctor_id}:{current_client}")
                if doctor_inactive:
                    await safe_send_message(doctor_id, "⚠️ Вы не активны более 10 минут. Если вы здесь, напишите что-нибудь.")
                elif client_inactive:
                    await safe_send_message(int(current_client), "⚠️ Вы не активны более 6 минут. Если вы здесь, напишите что-нибудь.")