from database.db import get_db, _db_lock
from services.validators import has_active_consultation
from database.doctors import get_doctor_name, get_doctor_specialization

# Совпадает с частичным UNIQUE idx_open_client_consultation в db.py
_OPEN_CONSULTATION_STATUSES = (
    "waiting_payment",
    "paid",
    "active",
    "waiting_doctor_offline",
)


async def save_consultation_start(client_id: int, anonymous_id: str, doctor_id: int, problem_key: str):
    """Сохраняет начало консультации, возвращает consultation_id"""
    if await has_active_consultation(client_id):
        return None

    doctor_name = await get_doctor_name(doctor_id) if doctor_id else None
    doctor_spec = (
        await get_doctor_specialization(doctor_id) if doctor_id else None
    )
    # Колонка в БД NOT NULL; без назначенного врача кладём тему (как раньше по смыслу).
    spec_for_db = doctor_spec if doctor_spec is not None else (problem_key or "")

    db = await get_db()
    async with _db_lock:
        ph = ",".join("?" * len(_OPEN_CONSULTATION_STATUSES))
        cur = await db.execute(
            f"""
            SELECT id, status FROM consultations
            WHERE client_id = ? AND status IN ({ph})
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (client_id, *_OPEN_CONSULTATION_STATUSES),
        )
        row = await cur.fetchone()
        if row:
            cid, st = int(row[0]), row[1]
            if st == "waiting_payment":
                await db.execute(
                    """
                    UPDATE consultations SET
                        client_anonymous_id = ?,
                        doctor_id = ?,
                        doctor_name = ?,
                        doctor_specialization = ?,
                        problem_key = ?
                    WHERE id = ?
                    """,
                    (
                        anonymous_id,
                        doctor_id,
                        doctor_name,
                        spec_for_db,
                        problem_key,
                        cid,
                    ),
                )
            await db.commit()
            return cid

        cursor = await db.execute(
            """
            INSERT INTO consultations
            (client_id, client_anonymous_id, doctor_id, doctor_name, doctor_specialization, status, problem_key)
            VALUES (?, ?, ?, ?, ?, 'waiting_payment', ?)
            """,
            (
                client_id,
                anonymous_id,
                doctor_id,
                doctor_name,
                spec_for_db,
                problem_key,
            ),
        )
        await db.commit()
        return cursor.lastrowid


async def cancel_pending_checkout(consultation_id: int, client_id: int) -> None:
    """Отмена ожидающей оплаты: pending-платёж и консультация waiting_payment."""
    db = await get_db()
    async with _db_lock:
        await db.execute(
            "DELETE FROM payments WHERE consultation_id = ? AND status = 'pending'",
            (consultation_id,),
        )
        await db.execute(
            """
            UPDATE consultations SET status = 'cancelled'
            WHERE id = ? AND client_id = ? AND status = 'waiting_payment'
            """,
            (consultation_id, client_id),
        )
        await db.commit()


async def save_consultation_end(consultation_id: int, status: str, client_msgs: int = 0, doctor_msgs: int = 0):
    """Сохраняет завершение консультации"""
    db = await get_db()
    async with _db_lock:
        await db.execute('''
            UPDATE consultations SET 
                status = ?, 
                ended_at = CURRENT_TIMESTAMP, 
                duration_seconds = (EXTRACT(EPOCH FROM NOW())::bigint - EXTRACT(EPOCH FROM created_at)::bigint),
                client_messages = ?,
                doctor_messages = ?
            WHERE id = ?
        ''', (status, client_msgs, doctor_msgs, consultation_id))
        await db.commit()


async def update_consultation_doctor(
    consultation_id: int,
    doctor_id: int,
    doctor_name: str,
    doctor_specialization: str,
):
    """Назначает врача консультации и активирует её"""
    db = await get_db()
    async with _db_lock:
        await db.execute(
            """
            UPDATE consultations
            SET doctor_id = ?, doctor_name = ?, doctor_specialization = ?, status = 'active'
            WHERE id = ?
            """,
            (doctor_id, doctor_name, doctor_specialization, consultation_id),
        )
        await db.commit()


async def update_consultation_pet_info(
    consultation_id: int,
    species: str,
    age: str,
    weight: str,
    breed: str,
    condition: str,
    chronic: str
):
    """Обновляет информацию о питомце в консультации"""
    db = await get_db()
    async with _db_lock:
        await db.execute('''
            UPDATE consultations SET
                pet_species = ?,
                pet_age = ?,
                pet_weight = ?,
                pet_breed = ?,
                pet_condition = ?,
                pet_chronic = ?
            WHERE id = ?
        ''', (species, age, weight, breed, condition, chronic, consultation_id))
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
        SELECT id, client_id, doctor_id FROM consultations WHERE status = 'active'
    ''')
    return await cursor.fetchall()


async def get_consultation_by_id(consultation_id: int):
    """Возвращает консультацию по ID"""
    db = await get_db()
    cursor = await db.execute('''
        SELECT * FROM consultations WHERE id = ?
    ''', (consultation_id,))
    return await cursor.fetchone()


async def get_consultation_doctor_and_topic(consultation_id: int):
    """doctor_id, problem_key для логики назначения."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT doctor_id, problem_key FROM consultations WHERE id = ?",
        (consultation_id,),
    )
    return await cursor.fetchone()


async def get_consultation_problem_key(consultation_id: int) -> str | None:
    """Ключ темы (специализации) для консультации."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT problem_key FROM consultations WHERE id = ?",
        (consultation_id,),
    )
    row = await cursor.fetchone()
    return row[0] if row else None


async def _write_pending_doctor_assignment(
    consultation_id: int, tid: int, topic_key: str
) -> None:
    name = await get_doctor_name(tid)
    spec = await get_doctor_specialization(tid) or topic_key
    db = await get_db()
    async with _db_lock:
        await db.execute(
            """
            UPDATE consultations
            SET doctor_id = ?, doctor_name = ?, doctor_specialization = ?
            WHERE id = ?
            """,
            (tid, name, spec, consultation_id),
        )
        await db.commit()


async def assign_pending_doctor_from_topic(consultation_id: int, topic_key: str) -> int | None:
    """
    Закрепление врача после чека: онлайн (round-robin) / универсальная тема /
    иначе первый активный по теме (офлайн, 24 ч).
    """
    from config import UNIVERSAL_TOPIC_DOCTOR_ID
    from data.problems import UNIVERSAL_TOPIC_KEY
    from database.doctors import get_first_active_doctor_id_for_topic
    from services.routing import pick_doctor_for_topic
    from services.validators import get_doctor_status

    if topic_key == UNIVERSAL_TOPIC_KEY:
        tid = UNIVERSAL_TOPIC_DOCTOR_ID
        await _write_pending_doctor_assignment(consultation_id, tid, topic_key)
        try:
            if get_doctor_status(tid) != "online":
                await set_consultation_offline_intake(consultation_id)
        except Exception:
            await set_consultation_offline_intake(consultation_id)
        return tid

    from data.problems import PROBLEMS

    def _routing_specs(menu_key: str) -> list[str]:
        pdata = PROBLEMS.get(menu_key)
        if pdata is not None:
            specs = pdata.get("specialists") or []
            return specs if specs else ["therapist"]
        return [menu_key]

    specs = _routing_specs(topic_key)
    for spec in specs:
        tid = await pick_doctor_for_topic(spec)
        if tid:
            await _write_pending_doctor_assignment(consultation_id, tid, spec)
            return tid

    for spec in specs:
        first = await get_first_active_doctor_id_for_topic(spec)
        if first:
            await _write_pending_doctor_assignment(consultation_id, first, spec)
            await set_consultation_offline_intake(consultation_id)
            return first
    return None


async def assign_pending_doctor_direct(consultation_id: int, doctor_telegram_id: int) -> None:
    """Закрепление за выбранным врачом (запись «Наши врачи»)."""
    name = await get_doctor_name(doctor_telegram_id)
    spec = await get_doctor_specialization(doctor_telegram_id) or "—"
    db = await get_db()
    async with _db_lock:
        await db.execute(
            """
            UPDATE consultations
            SET doctor_id = ?, doctor_name = ?, doctor_specialization = ?
            WHERE id = ?
            """,
            (doctor_telegram_id, name, spec, consultation_id),
        )
        await db.commit()


async def ensure_doctor_assigned_for_consultation(consultation_id: int) -> int | None:
    """
    Если врач ещё не закреплён (напр. все были офлайн при чеке) — пробуем снова.
    Возвращает telegram_id врача из строки консультации или None.
    """
    row = await get_consultation_doctor_and_topic(consultation_id)
    if not row:
        return None
    doctor_id, problem_key = row[0], row[1]
    if doctor_id is not None:
        return int(doctor_id)
    if not problem_key or problem_key == "direct_booking":
        return None
    tid = await assign_pending_doctor_from_topic(consultation_id, problem_key)
    return tid

async def get_consultations_by_doctor(doctor_id: int, limit: int = 20):
    """Возвращает консультации врача"""
    db = await get_db()
    cursor = await db.execute('''
        SELECT id, client_id, client_anonymous_id, status, created_at, ended_at
        FROM consultations 
        WHERE doctor_id = ? 
        ORDER BY created_at DESC 
        LIMIT ?
    ''', (doctor_id, limit))
    return await cursor.fetchall()


def build_consultation_question_summary(
    problem_key: str | None,
    pet_name: str | None,
    species: str | None,
    chronic: str | None,
    recent_illness: str | None,
) -> str:
    from data.problems import SPECIALISTS

    parts: list[str] = []
    if problem_key and problem_key != "direct_booking":
        parts.append(SPECIALISTS.get(problem_key, problem_key))
    if pet_name or species:
        parts.append(f"{pet_name or '—'} ({species or '—'})")
    if chronic:
        parts.append(f"хроника: {chronic}")
    if recent_illness:
        parts.append(f"за месяц: {recent_illness}")
    return "; ".join(parts) if parts else "—"


async def set_consultation_offline_intake(consultation_id: int) -> None:
    db = await get_db()
    async with _db_lock:
        await db.execute(
            "UPDATE consultations SET offline_intake = 1 WHERE id = ?",
            (consultation_id,),
        )
        await db.commit()


async def finalize_questionnaire_sla(consultation_id: int, *, offline_intake: bool) -> None:
    """После анкеты: таймер ответа врача; офлайн-запись → статус waiting_doctor_offline."""
    db = await get_db()
    async with _db_lock:
        if offline_intake:
            await db.execute(
                """
                UPDATE consultations
                SET status = 'waiting_doctor_offline',
                    waiting_reply_since = COALESCE(waiting_reply_since, CURRENT_TIMESTAMP)
                WHERE id = ?
                """,
                (consultation_id,),
            )
        else:
            await db.execute(
                """
                UPDATE consultations
                SET waiting_reply_since = COALESCE(waiting_reply_since, CURRENT_TIMESTAMP)
                WHERE id = ?
                """,
                (consultation_id,),
            )
        await db.commit()


async def list_unanswered_rows_for_doctor(doctor_telegram_id: int):
    """Неотвеченные консультации одного врача (для кнопки «Посмотреть»)."""
    db = await get_db()
    cur = await db.execute(
        """
        SELECT
            c.id,
            c.client_id,
            c.client_anonymous_id,
            c.waiting_reply_since,
            c.pet_name,
            c.pet_species,
            c.pet_chronic,
            c.recent_illness,
            c.problem_key,
            c.status,
            (EXTRACT(EPOCH FROM NOW()) - EXTRACT(EPOCH FROM c.waiting_reply_since)) / 3600.0
        FROM consultations c
        WHERE c.doctor_id = ?
          AND c.pet_name IS NOT NULL
          AND c.waiting_reply_since IS NOT NULL
          AND c.status IN ('paid', 'waiting_doctor_offline')
        ORDER BY c.waiting_reply_since ASC
        """,
        (doctor_telegram_id,),
    )
    return await cur.fetchall()


async def list_unanswered_detailed_for_reminders():
    """Все оплаченные/офлайн-ожидание консультации с анкетой, без активного диалога."""
    db = await get_db()
    cur = await db.execute(
        """
        SELECT
            c.id,
            c.doctor_id,
            c.client_id,
            c.client_anonymous_id,
            c.waiting_reply_since,
            c.pet_name,
            c.pet_species,
            c.pet_chronic,
            c.recent_illness,
            c.problem_key,
            c.status,
            c.doctor_name,
            (EXTRACT(EPOCH FROM NOW()) - EXTRACT(EPOCH FROM c.waiting_reply_since)) / 3600.0
        FROM consultations c
        WHERE c.doctor_id IS NOT NULL
          AND c.pet_name IS NOT NULL
          AND c.waiting_reply_since IS NOT NULL
          AND c.status IN ('paid', 'waiting_doctor_offline')
        ORDER BY c.waiting_reply_since ASC
        """
    )
    return await cur.fetchall()


async def list_offline_pending_for_doctor(doctor_telegram_id: int):
    db = await get_db()
    cur = await db.execute(
        """
        SELECT id, client_id, client_anonymous_id, pet_name, pet_species, problem_key,
               pet_chronic, recent_illness
        FROM consultations
        WHERE doctor_id = ?
          AND status = 'waiting_doctor_offline'
          AND pet_name IS NOT NULL
        ORDER BY waiting_reply_since ASC
        """,
        (doctor_telegram_id,),
    )
    return await cur.fetchall()


async def get_fsm_bootstrap_for_consultation(consultation_id: int):
    """Данные для FSM клиента после подтверждения оплаты."""
    db = await get_db()
    cur = await db.execute(
        """
        SELECT client_anonymous_id, problem_key, doctor_id, doctor_name
        FROM consultations WHERE id = ?
        """,
        (consultation_id,),
    )
    return await cur.fetchone()