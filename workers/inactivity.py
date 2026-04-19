"""
Фоновый контроль неактивности диалога клиент–врач (напоминания 5 / 10 / 15 мин и авто-закрытие).

Ранее здесь была отдельная логика «оба неактивны 10+6 мин» — заменена сценарием из ТЗ,
чтобы не дублировать авто-завершения и сообщения.
"""
import asyncio
import logging
import time

import redis

from config import REDIS_URL, ADMIN_IDS
from database.consultations import save_consultation_end
from database.db import get_db
from services.dialog_session import (
    REMIND_5_SEC,
    REMIND_10_SEC,
    REMIND_15_SEC,
    clear_dialog_session,
    iter_dialog_client_ids,
    load_dialog,
    mark_reminder_sent,
    log_tick,
)
from services.validators import clear_session, clear_consultation_chat
from utils.helpers import safe_send_message

r = redis.from_url(REDIS_URL, decode_responses=True)


async def _auto_close_client_idle(doctor_id: int, client_id: int) -> None:
    """15 мин ожидания ответа клиента — закрыть консультацию без оценки (как в ТЗ)."""
    db = await get_db()
    cursor = await db.execute(
        'SELECT id FROM consultations WHERE client_id = ? AND status = "active"',
        (client_id,),
    )
    row = await cursor.fetchone()
    if row:
        consultation_id = row[0]
        await save_consultation_end(consultation_id, "auto_ended_client_idle")
        clear_consultation_chat(consultation_id)
    clear_session(int(client_id), doctor_id)
    clear_dialog_session(client_id)
    try:
        await safe_send_message(
            int(client_id),
            "Консультация закрыта из-за отсутствия ответа. При необходимости можете создать новую.",
        )
    except Exception as e:
        logging.warning("dialog_inactivity: не удалось написать клиенту %s: %s", client_id, e)
    try:
        await safe_send_message(
            doctor_id,
            "Диалог автоматически завершён из-за отсутствия ответа клиента.",
        )
    except Exception as e:
        logging.warning("dialog_inactivity: не удалось написать врачу %s: %s", doctor_id, e)
    log_tick(f"auto_close_client_idle client={client_id} doctor={doctor_id}")


async def _tick_one_client(client_id: int) -> None:
    raw_doc = r.get(f"client:{client_id}:doctor")
    if not raw_doc:
        clear_dialog_session(client_id)
        return

    doctor_id = int(raw_doc)
    data = load_dialog(client_id)
    if not data:
        return

    if data.get("doctor_id") != str(doctor_id):
        clear_dialog_session(client_id)
        return

    status = data.get("status")
    if status not in ("waiting_client", "waiting_doctor"):
        return

    try:
        last_ts = float(data.get("last_message_ts", "0"))
    except ValueError:
        return

    elapsed = time.time() - last_ts
    last_sender = data.get("last_sender")

    # --- Ждём врача (последним писал клиент) ---
    if status == "waiting_doctor" and last_sender == "client":
        if elapsed >= REMIND_15_SEC and data.get("r15") != "1":
            mark_reminder_sent(client_id, "r15")
            log_tick(f"remind_15 waiting_doctor client={client_id} doctor={doctor_id}")
            for aid in ADMIN_IDS:
                try:
                    await safe_send_message(
                        aid,
                        f"⚠️ Врач {doctor_id} не отвечает клиенту {client_id} более 15 мин. "
                        f"(ожидание ответа врача).",
                    )
                except Exception as e:
                    logging.warning("dialog_inactivity: админ %s: %s", aid, e)
            try:
                await safe_send_message(
                    client_id,
                    "Врач задерживается с ответом. Пожалуйста, ожидайте.",
                )
            except Exception as e:
                logging.warning("dialog_inactivity: клиент %s: %s", client_id, e)
        elif elapsed >= REMIND_10_SEC and data.get("r10") != "1":
            mark_reminder_sent(client_id, "r10")
            log_tick(f"remind_10 waiting_doctor client={client_id} doctor={doctor_id}")
            try:
                await safe_send_message(doctor_id, "Клиент всё ещё ожидает ответа.")
            except Exception as e:
                logging.warning("dialog_inactivity: врач %s: %s", doctor_id, e)
        elif elapsed >= REMIND_5_SEC and data.get("r5") != "1":
            mark_reminder_sent(client_id, "r5")
            log_tick(f"remind_5 waiting_doctor client={client_id} doctor={doctor_id}")
            try:
                await safe_send_message(doctor_id, "Клиент ожидает вашего ответа.")
            except Exception as e:
                logging.warning("dialog_inactivity: врач %s: %s", doctor_id, e)
        return

    # --- Ждём клиента (последним писал врач) ---
    if status == "waiting_client" and last_sender == "doctor":
        if elapsed >= REMIND_15_SEC:
            log_tick(f"remind_15 auto_close waiting_client client={client_id} doctor={doctor_id}")
            await _auto_close_client_idle(doctor_id, client_id)
            return
        elif elapsed >= REMIND_10_SEC and data.get("r10") != "1":
            mark_reminder_sent(client_id, "r10")
            log_tick(f"remind_10 waiting_client client={client_id} doctor={doctor_id}")
            from keyboards.client import get_client_end_consultation_inline_keyboard

            try:
                await safe_send_message(
                    client_id,
                    "Если вопрос решён, можете завершить консультацию.",
                    reply_markup=get_client_end_consultation_inline_keyboard(client_id),
                )
            except Exception as e:
                logging.warning("dialog_inactivity: клиент %s: %s", client_id, e)
        elif elapsed >= REMIND_5_SEC and data.get("r5") != "1":
            mark_reminder_sent(client_id, "r5")
            log_tick(f"remind_5 waiting_client client={client_id} doctor={doctor_id}")
            try:
                await safe_send_message(client_id, "Врач ожидает вашего ответа.")
            except Exception as e:
                logging.warning("dialog_inactivity: клиент %s: %s", client_id, e)


async def inactivity_worker():
    """Проверка каждые 60 с всех диалогов в Redis (ожидание клиента или врача)."""
    while True:
        await asyncio.sleep(60)
        try:
            for client_id in iter_dialog_client_ids():
                await _tick_one_client(client_id)
        except Exception as e:
            logging.exception("dialog_inactivity worker error: %s", e)
            log_tick(f"ERROR {e}")
