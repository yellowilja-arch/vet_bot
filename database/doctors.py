import logging
import redis
from config import (
    REDIS_URL,
    INITIAL_DOCTORS,
    SPECIALISTS,
    SPECIALIZATION_KEYS,
    UNIVERSAL_TOPIC_DOCTOR_ID,
)
from data.problems import UNIVERSAL_TOPIC_KEY
from database.db import get_db

r = redis.from_url(REDIS_URL, decode_responses=True)
DOCTOR_IDS = []

# Минимальный Telegram ID для участия в меню, маршрутизации и публичных списках.
# Не используйте 1e9: у большинства аккаунтов ID — 9 цифр и он МЕНЬШЕ 1_000_000_000,
# тогда темы клиенту не показывались, хотя врач в БД был.
REAL_TELEGRAM_USER_ID_MIN = 1

# При старте удаляем только явные числовые заглушки из старых сидов (не реальные аккаунты).
DOCTOR_STUB_TELEGRAM_ID_MAX = 99

# Частые опечатки / старые значения (в т.ч. из ручного jsonbin) → канонический ключ из SPECIALISTS.
SPECIALIZATION_KEY_ALIASES: dict[str, str] = {
    "therapy": "therapist",
    "therapies": "therapist",
    "terapevt": "therapist",
    "gp_doctor": "gp",
    "general": "gp",
    "practitioner": "gp",
    "cardio": "cardiologist",
    "oncology": "oncologist",
    "gastro": "gastroenterologist",
    "ortho": "orthopedist",
    "orthopaedic": "orthopedist",
    "surgery": "surgeon",
    "nephro": "nephrologist",
    "neuro": "neurologist",
    "derma": "dermatologist",
    "repro": "reproductologist",
    "virus": "virologist",
    "radiology": "radiologist",
    "visual": "radiologist",
}


def canonical_specialization_key(raw: str | None) -> str | None:
    """Приводит строку из БД к ключу из SPECIALISTS (кроме universal_triage)."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    if s == UNIVERSAL_TOPIC_KEY:
        return None
    norm = s.lower().replace(" ", "_").replace("-", "_")
    if norm == UNIVERSAL_TOPIC_KEY:
        return None
    if norm in SPECIALIZATION_KEY_ALIASES:
        cand = SPECIALIZATION_KEY_ALIASES[norm]
        if cand in SPECIALISTS and cand != UNIVERSAL_TOPIC_KEY:
            return cand
    if s in SPECIALISTS and s != UNIVERSAL_TOPIC_KEY:
        return s
    if norm in SPECIALISTS and norm != UNIVERSAL_TOPIC_KEY:
        return norm
    return None


def ordered_spec_keys(keys: list[str]) -> list[str]:
    """Канонический порядок ключей специализаций для отображения."""
    if not keys:
        return []
    normalized: list[str] = []
    for x in keys:
        c = canonical_specialization_key(x)
        if c:
            normalized.append(c)
    if not normalized:
        return []
    s = set(normalized)
    out = [k for k in SPECIALIZATION_KEYS if k in s]
    for k in sorted(s):
        if k not in out:
            out.append(k)
    return out


def primary_spec_key(keys: list[str]) -> str:
    """Первичная специализация для колонки doctors.specialization и Redis topic."""
    for k in SPECIALIZATION_KEYS:
        if k in keys:
            return k
    return sorted(keys)[0]


def specialization_plain_title(spec_key: str | None) -> str:
    """Название роли без ведущего эмодзи (для «Терапевт / Кардиолог»)."""
    if not spec_key:
        return "Не указана"
    raw = SPECIALISTS.get(spec_key, spec_key)
    parts = raw.split()
    i = 0
    while i < len(parts) and not any(ch.isalpha() for ch in parts[i]):
        i += 1
    return " ".join(parts[i:]) if i < len(parts) else raw


def specializations_slash_plain(keys: list[str]) -> str:
    return " / ".join(specialization_plain_title(k) for k in ordered_spec_keys(keys))


async def _fetch_spec_keys_raw(telegram_id: int) -> list[str]:
    db = await get_db()
    cur = await db.execute(
        "SELECT specialization FROM doctor_specializations WHERE telegram_id = ?",
        (telegram_id,),
    )
    rows = [r[0] for r in await cur.fetchall()]
    return ordered_spec_keys(rows)


async def load_doctors_from_db():
    """Загружает врачей из БД в память и Redis"""
    global DOCTOR_IDS
    db = await get_db()
    cursor = await db.execute(
        "SELECT telegram_id, specialization FROM doctors WHERE is_active = 1"
    )
    rows = await cursor.fetchall()

    DOCTOR_IDS = []
    for row in rows:
        doctor_id, specialization = row
        DOCTOR_IDS.append(doctor_id)
        if not r.get(f"doctor:{doctor_id}:topic"):
            r.set(f"doctor:{doctor_id}:topic", specialization)

    print(f"📋 Всего врачей в системе: {len(DOCTOR_IDS)}")
    return DOCTOR_IDS


async def repair_specialization_keys_in_db() -> None:
    """
    Перезаписывает doctor_specializations и поле doctors.specialization каноническими ключами.
    Нужно после импорта jsonbin или если в БД попали опечатки — иначе темы клиентского меню пустые.
    """
    db = await get_db()
    cur = await db.execute("SELECT telegram_id, specialization FROM doctors")
    doctors_rows = await cur.fetchall()
    fixed = 0
    for tid, legacy_sp in doctors_rows:
        tid = int(tid)
        cur2 = await db.execute(
            "SELECT specialization FROM doctor_specializations WHERE telegram_id = ?",
            (tid,),
        )
        raw = [r[0] for r in await cur2.fetchall()]
        if not raw and legacy_sp and str(legacy_sp).strip():
            raw = [legacy_sp]
        canon: list[str] = []
        seen: set[str] = set()
        for x in raw:
            c = canonical_specialization_key(x)
            if c and c not in seen:
                seen.add(c)
                canon.append(c)
        await db.execute("DELETE FROM doctor_specializations WHERE telegram_id = ?", (tid,))
        for c in canon:
            await db.execute(
                "INSERT INTO doctor_specializations (telegram_id, specialization) VALUES (?, ?)",
                (tid, c),
            )
        if canon:
            prim = primary_spec_key(ordered_spec_keys(canon))
            await db.execute(
                "UPDATE doctors SET specialization = ? WHERE telegram_id = ?",
                (prim, tid),
            )
            fixed += 1
        elif raw:
            logging.warning(
                "repair DB: telegram_id=%s — специализации не распознаны (задайте ключи как в админке): %r",
                tid,
                raw,
            )
    await db.commit()
    logging.info("repair_specialization_keys_in_db: врачей с валидными спеками: %s", fixed)


async def init_doctors():
    """
    Удаляет врачей-заглушек с малоцифровыми ID, затем при необходимости сидит INITIAL_DOCTORS.
    """
    db = await get_db()
    await db.execute(
        "DELETE FROM doctor_specializations WHERE telegram_id <= ?",
        (DOCTOR_STUB_TELEGRAM_ID_MAX,),
    )
    await db.execute(
        "DELETE FROM doctors WHERE telegram_id <= ?",
        (DOCTOR_STUB_TELEGRAM_ID_MAX,),
    )
    await db.commit()
    for spec, doctors in INITIAL_DOCTORS.items():
        for doc in doctors:
            await db.execute(
                """
                INSERT OR IGNORE INTO doctors (telegram_id, name, specialization, is_active)
                VALUES (?, ?, ?, 1)
                """,
                (doc["id"], doc["name"], spec),
            )
            await db.execute(
                """
                INSERT OR IGNORE INTO doctor_specializations (telegram_id, specialization)
                VALUES (?, ?)
                """,
                (doc["id"], spec),
            )
    await db.commit()
    await repair_specialization_keys_in_db()
    await load_doctors_from_db()
    logging.info(
        "Врачи в БД после init_doctors: %s (INITIAL_DOCTORS задаёт только опциональный сид)",
        len(DOCTOR_IDS),
    )


async def get_doctor_name(doctor_id: int):
    """Возвращает имя врача по его Telegram ID"""
    db = await get_db()
    cursor = await db.execute(
        "SELECT name FROM doctors WHERE telegram_id = ?", (doctor_id,)
    )
    row = await cursor.fetchone()
    return row[0] if row else f"Врач {doctor_id}"


async def get_doctor_spec_keys(telegram_id: int) -> list[str]:
    """Все ключи специализаций врача (активен или нет)."""
    keys = await _fetch_spec_keys_raw(telegram_id)
    if keys:
        return keys
    db = await get_db()
    cur = await db.execute(
        "SELECT specialization FROM doctors WHERE telegram_id = ?",
        (telegram_id,),
    )
    row = await cur.fetchone()
    if row and row[0]:
        return [row[0]]
    return []


async def get_doctor_specialization(doctor_id: int) -> str | None:
    """
    Строка для БД/UI: «Терапевт / Кардиолог» без эмодзи.
    """
    keys = await get_doctor_spec_keys(doctor_id)
    if not keys:
        return None
    return specializations_slash_plain(keys)


def specialization_display_label(spec_key: str | None) -> str:
    """Человекочитаемое название специализации по ключу из БД (с эмодзи из словаря)."""
    if not spec_key:
        return "Не указана"
    return SPECIALISTS.get(spec_key, spec_key)


async def get_all_doctors():
    """
    Активные врачи: (telegram_id, name, list[spec_keys]).
    """
    db = await get_db()
    cur = await db.execute(
        """
        SELECT telegram_id, name, specialization FROM doctors
        WHERE is_active = 1
        ORDER BY name COLLATE NOCASE
        """
    )
    rows = await cur.fetchall()
    if not rows:
        return []
    tids = [r[0] for r in rows]
    ph = ",".join("?" * len(tids))
    cur2 = await db.execute(
        f"SELECT telegram_id, specialization FROM doctor_specializations "
        f"WHERE telegram_id IN ({ph})",
        tids,
    )
    spec_map: dict[int, list[str]] = {t: [] for t in tids}
    for tid, sp in await cur2.fetchall():
        spec_map.setdefault(tid, []).append(sp)
    out = []
    for tid, name, legacy in rows:
        keys = ordered_spec_keys(spec_map.get(tid, []))
        if not keys and legacy:
            keys = [legacy]
        out.append((tid, name, keys))
    return out


async def get_doctor_admin_row(telegram_id: int) -> tuple[str, bool] | None:
    """(name, is_active) или None."""
    db = await get_db()
    cur = await db.execute(
        "SELECT name, is_active FROM doctors WHERE telegram_id = ?",
        (telegram_id,),
    )
    row = await cur.fetchone()
    if not row:
        return None
    return row[0], bool(row[1])


async def get_public_doctors_for_client():
    """
    Активные врачи для клиента: is_active и реальный Telegram ID (без заглушек из тестовой БД).
    """
    rows = await get_all_doctors()
    filtered = [r for r in rows if r[0] >= REAL_TELEGRAM_USER_ID_MIN]

    def sort_key(row):
        tid, name, keys = row
        if not keys:
            return (999, name.lower())
        p = primary_spec_key(keys)
        idx = (
            SPECIALIZATION_KEYS.index(p) if p in SPECIALIZATION_KEYS else 999
        )
        return (idx, name.lower())

    return sorted(filtered, key=sort_key)


async def is_active_public_doctor(telegram_id: int) -> bool:
    """Врач есть в публичном списке (активен и не заглушка по ID)."""
    if telegram_id < REAL_TELEGRAM_USER_ID_MIN:
        return False
    db = await get_db()
    cursor = await db.execute(
        "SELECT 1 FROM doctors WHERE telegram_id = ? AND is_active = 1",
        (telegram_id,),
    )
    return await cursor.fetchone() is not None


async def list_distinct_specializations_active() -> list[str]:
    """Специализации с хотя бы одним активным врачём (для тем в меню)."""
    db = await get_db()
    cursor = await db.execute(
        """
        SELECT DISTINCT x.spec
        FROM (
            SELECT ds.specialization AS spec
            FROM doctor_specializations ds
            INNER JOIN doctors d ON d.telegram_id = ds.telegram_id
            WHERE d.is_active = 1 AND d.telegram_id >= ?
            UNION
            SELECT d.specialization AS spec
            FROM doctors d
            WHERE d.is_active = 1 AND d.telegram_id >= ?
              AND TRIM(COALESCE(d.specialization, '')) != ''
              AND NOT EXISTS (
                  SELECT 1 FROM doctor_specializations z WHERE z.telegram_id = d.telegram_id
              )
        ) AS x
        ORDER BY x.spec
        """,
        (REAL_TELEGRAM_USER_ID_MIN, REAL_TELEGRAM_USER_ID_MIN),
    )
    raw_specs = [row[0] for row in await cursor.fetchall()]
    seen: set[str] = set()
    out: list[str] = []
    for spec in raw_specs:
        c = canonical_specialization_key(spec)
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    out.sort()
    return out


async def is_universal_topic_menu_available() -> bool:
    """Кнопка универсальной темы, если назначенный врач есть в БД и активен."""
    db = await get_db()
    cur = await db.execute(
        "SELECT 1 FROM doctors WHERE telegram_id = ? AND is_active = 1",
        (UNIVERSAL_TOPIC_DOCTOR_ID,),
    )
    return await cur.fetchone() is not None


async def topic_keys_available_for_client_menu() -> list[str]:
    """
    Темы главного меню: специализация видна, если есть ≥1 активный врач
    (онлайн/офлайн не важно). Плюс универсальная тема при доступности врача.
    """
    db_specs = set(await list_distinct_specializations_active())
    ordered = [k for k in SPECIALIZATION_KEYS if k in db_specs]
    for k in sorted(db_specs):
        if k in SPECIALISTS and k != UNIVERSAL_TOPIC_KEY and k not in ordered:
            ordered.append(k)
    if await is_universal_topic_menu_available():
        ordered.append(UNIVERSAL_TOPIC_KEY)
    return ordered


async def list_active_doctor_ids_for_specialization(spec_key: str) -> list[int]:
    """Активные «реальные» врачи с данной специализацией."""
    db = await get_db()
    cur = await db.execute(
        """
        SELECT ds.telegram_id
        FROM doctor_specializations ds
        INNER JOIN doctors d ON d.telegram_id = ds.telegram_id
        WHERE d.is_active = 1 AND ds.specialization = ? AND d.telegram_id >= ?
        ORDER BY ds.telegram_id
        """,
        (spec_key, REAL_TELEGRAM_USER_ID_MIN),
    )
    return [int(r[0]) for r in await cur.fetchall()]


async def list_online_doctor_ids_for_specialization(spec_key: str) -> list[int]:
    """Врачи по специализации, которые сейчас online (при сбое Redis — пусто)."""
    from services.validators import get_doctor_status

    out: list[int] = []
    for tid in await list_active_doctor_ids_for_specialization(spec_key):
        try:
            if get_doctor_status(tid) == "online":
                out.append(tid)
        except Exception:
            continue
    return out


async def get_first_active_doctor_id_for_topic(topic_key: str) -> int | None:
    """Первый активный врач по теме (офлайн-закрепление)."""
    ids = await list_active_doctor_ids_for_specialization(topic_key)
    return ids[0] if ids else None


async def add_doctor(
    telegram_id: int, name: str, specializations: str | list[str]
):
    """Добавляет или полностью заменяет врача (имя, специализации, активен)."""
    if isinstance(specializations, str):
        keys = [specializations]
    else:
        keys = list(dict.fromkeys(specializations))
    if not keys:
        raise ValueError("Нужна хотя бы одна специализация")
    keys = ordered_spec_keys(keys)
    if not keys:
        raise ValueError("Специализации не распознаны — используйте те же ключи, что в панели админа")
    prim = primary_spec_key(keys)
    db = await get_db()
    await db.execute(
        """
        INSERT OR REPLACE INTO doctors (telegram_id, name, specialization, is_active)
        VALUES (?, ?, ?, 1)
        """,
        (telegram_id, name, prim),
    )
    await db.execute(
        "DELETE FROM doctor_specializations WHERE telegram_id = ?",
        (telegram_id,),
    )
    for k in keys:
        await db.execute(
            """
            INSERT INTO doctor_specializations (telegram_id, specialization)
            VALUES (?, ?)
            """,
            (telegram_id, k),
        )
    await db.commit()
    await load_doctors_from_db()
    from database.doctors_remote_sync import schedule_push_doctors_remote

    schedule_push_doctors_remote()


async def update_doctor(
    telegram_id: int,
    *,
    name: str | None = None,
    specializations: list[str] | None = None,
    is_active: bool | None = None,
):
    """Частичное обновление карточки врача."""
    db = await get_db()
    cur = await db.execute(
        "SELECT 1 FROM doctors WHERE telegram_id = ?", (telegram_id,)
    )
    if not await cur.fetchone():
        raise ValueError("Врач не найден")
    if name is not None:
        await db.execute(
            "UPDATE doctors SET name = ? WHERE telegram_id = ?",
            (name, telegram_id),
        )
    if is_active is not None:
        await db.execute(
            "UPDATE doctors SET is_active = ? WHERE telegram_id = ?",
            (1 if is_active else 0, telegram_id),
        )
    if specializations is not None:
        keys = ordered_spec_keys(list(dict.fromkeys(specializations)))
        if not keys:
            raise ValueError(
                "Специализации не распознаны — используйте те же ключи, что в панели админа"
            )
        prim = primary_spec_key(keys)
        await db.execute(
            "DELETE FROM doctor_specializations WHERE telegram_id = ?",
            (telegram_id,),
        )
        for k in keys:
            await db.execute(
                """
                INSERT INTO doctor_specializations (telegram_id, specialization)
                VALUES (?, ?)
                """,
                (telegram_id, k),
            )
        await db.execute(
            "UPDATE doctors SET specialization = ? WHERE telegram_id = ?",
            (prim, telegram_id),
        )
    await db.commit()
    await load_doctors_from_db()
    from database.doctors_remote_sync import schedule_push_doctors_remote

    schedule_push_doctors_remote()


async def remove_doctor(telegram_id: int):
    """Деактивирует врача (soft delete)."""
    db = await get_db()
    await db.execute(
        "UPDATE doctors SET is_active = 0 WHERE telegram_id = ?", (telegram_id,)
    )
    await db.commit()
    await load_doctors_from_db()
    from database.doctors_remote_sync import schedule_push_doctors_remote

    schedule_push_doctors_remote()
