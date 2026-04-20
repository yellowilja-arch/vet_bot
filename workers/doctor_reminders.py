"""
Напоминания врачам о неотвеченных консультациях (раз в час) и эскалации главному врачу (15 / 20 / 21+ ч).
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from html import escape

import redis

from config import HEAD_DOCTOR_ID, REDIS_URL
from database.consultations import (
    build_consultation_question_summary,
    list_unanswered_detailed_for_reminders,
)
from keyboards.doctor import get_doctor_unanswered_reminder_keyboard
from utils.helpers import safe_send_message

r = redis.from_url(REDIS_URL, decode_responses=True)


async def _notify_doctors_hourly(rows: list) -> None:
    now = time.time()
    by_doc: dict[int, list] = defaultdict(list)
    for row in rows:
        by_doc[int(row[1])].append(row)

    for doctor_id, drows in by_doc.items():
        oldest = max(float(x[-1] or 0) for x in drows)
        n = len(drows)
        last_raw = r.get(f"doc_unans_remind:{doctor_id}")
        last_ts = float(last_raw) if last_raw else 0.0
        if now - last_ts < 3600:
            continue
        int_h = int(oldest)
        text = (
            "⏰ <b>НАПОМИНАНИЕ</b>\n\n"
            "К вам записан клиент. Не забудьте ответить на консультацию.\n\n"
            f"У вас <b>{n}</b> неотвеченных консультаций.\n"
            f"Самая старая ожидает ответа <b>{int_h}</b> ч.\n"
        )
        await safe_send_message(
            doctor_id,
            text,
            parse_mode="HTML",
            reply_markup=get_doctor_unanswered_reminder_keyboard(),
        )
        r.set(f"doc_unans_remind:{doctor_id}", str(now))


async def _notify_head_doctor(rows: list) -> None:
    if not HEAD_DOCTOR_ID:
        return

    for row in rows:
        cid = int(row[0])
        client_anon = row[3]
        pet_name = row[5]
        pet_species = row[6]
        pch = row[7]
        rill = row[8]
        pk = row[9]
        doctor_name = row[11]
        hours = float(row[12] or 0)
        h = int(hours)
        if h < 15:
            continue

        q = build_consultation_question_summary(pk, pet_name, pet_species, pch, rill)
        dn = escape(str(doctor_name or "—"))
        body_base = (
            f"Консультация <b>#{cid}</b> от клиента <b>{escape(str(client_anon))}</b> "
            f"ожидает ответа <b>{h}</b> ч.\n\n"
            f"👨‍⚕️ Врач: {dn}\n"
            f"🐾 Питомец: {escape(str(pet_name or '—'))} ({escape(str(pet_species or '—'))})\n"
            f"📝 Вопрос: {escape(q[:500])}{'…' if len(q) > 500 else ''}"
        )

        if h >= 15 and not r.get(f"head15sent:{cid}"):
            r.set(f"head15sent:{cid}", "1")
            await safe_send_message(
                HEAD_DOCTOR_ID,
                "⏰ <b>НАПОМИНАНИЕ ГЛАВНОМУ ВРАЧУ</b>\n\n" + body_base,
                parse_mode="HTML",
            )
        if h >= 20 and not r.get(f"head20sent:{cid}"):
            r.set(f"head20sent:{cid}", "1")
            await safe_send_message(
                HEAD_DOCTOR_ID,
                "⏰ <b>НАПОМИНАНИЕ ГЛАВНОМУ ВРАЧУ</b>\n\n" + body_base,
                parse_mode="HTML",
            )
        if h >= 21:
            last_lv = r.get(f"head21h:{cid}")
            try:
                last_i = int(last_lv) if last_lv else 0
            except ValueError:
                last_i = 0
            if h > last_i:
                r.set(f"head21h:{cid}", str(h))
                await safe_send_message(
                    HEAD_DOCTOR_ID,
                    "⏰ <b>НАПОМИНАНИЕ ГЛАВНОМУ ВРАЧУ</b>\n\n" + body_base,
                    parse_mode="HTML",
                )


async def doctor_reminder_tick() -> None:
    rows = await list_unanswered_detailed_for_reminders()
    if not rows:
        return
    await _notify_doctors_hourly(rows)
    await _notify_head_doctor(rows)


async def doctor_reminder_worker() -> None:
    while True:
        await asyncio.sleep(300)
        try:
            await doctor_reminder_tick()
        except Exception:
            logging.exception("doctor_reminder_worker")
