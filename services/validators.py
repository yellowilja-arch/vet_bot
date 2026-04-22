import time
import redis
from config import REDIS_URL, ADMIN_IDS
from database.db import get_db

r = redis.from_url(REDIS_URL, decode_responses=True)


async def is_doctor(user_id):
    """Проверяет, является ли пользователь врачом (берёт список из database.doctors)"""
    from database.doctors import DOCTOR_IDS
    return user_id in DOCTOR_IDS


async def is_admin(user_id):
    """Проверяет, является ли пользователь администратором"""
    return user_id in ADMIN_IDS


async def is_blocked(user_id):
    """Проверяет, заблокирован ли пользователь"""
    db = await get_db()
    cursor = await db.execute('SELECT 1 FROM blacklist WHERE user_id = ?', (user_id,))
    return await cursor.fetchone() is not None


async def has_active_consultation(client_id):
    """Проверяет, есть ли у клиента активная консультация"""
    db = await get_db()
    cursor = await db.execute("SELECT id FROM consultations WHERE client_id = ? AND status = 'active'", (client_id,))
    return await cursor.fetchone() is not None


async def is_client_active(client_id):
    """Проверяет, активен ли клиент (Redis + PostgreSQL)"""
    if r.get(f"user:{client_id}:active"):
        return True
    db = await get_db()
    cursor = await db.execute("SELECT 1 FROM consultations WHERE client_id = ? AND status = 'active'", (client_id,))
    return await cursor.fetchone() is not None


def _normalize_presence(raw: str | None) -> str:
    if raw is None:
        return "offline"
    s = str(raw).strip().lower()
    return "online" if s == "online" else "offline"


def get_doctor_status(doctor_id):
    """Актуальный статус врача из Redis (online/offline). Ключ всегда с int(telegram_id)."""
    try:
        did = int(doctor_id)
    except (TypeError, ValueError):
        return "offline"
    return _normalize_presence(r.get(f"doctor:{did}:status"))


def get_current_client(doctor_id):
    """Текущий клиент врача (Redis)."""
    try:
        did = int(doctor_id)
    except (TypeError, ValueError):
        return None
    return r.get(f"doctor:{did}:current_client")


def safe_get_doctor_status(doctor_id) -> str:
    """Статус врача; при сбое Redis — offline (не роняем оплату/чек)."""
    try:
        return get_doctor_status(doctor_id)
    except Exception:
        return "offline"


def safe_get_current_client(doctor_id):
    try:
        return get_current_client(doctor_id)
    except Exception:
        return None


def get_doctor_status_symbol(doctor_id: int) -> str:
    """
    Статус для отображения клиенту:
    🟢 — онлайн и свободен, 🔴 — онлайн, ведёт консультацию, ⚪ — офлайн.
    """
    if safe_get_doctor_status(doctor_id) == "online":
        if safe_get_current_client(doctor_id):
            return "🔴"
        return "🟢"
    return "⚪"


def set_doctor_status(doctor_id, status):
    """Записывает статус врача только в Redis (см. persist_doctor_presence_to_db для БД)."""
    try:
        did = int(doctor_id)
    except (TypeError, ValueError):
        return
    st = _normalize_presence(status)
    r.set(f"doctor:{did}:status", st)


async def persist_doctor_presence_to_db(doctor_id, status: str) -> None:
    """Сохраняет online/offline в PostgreSQL (переживает рестарт; Redis — основной источник в рантайме)."""
    try:
        did = int(doctor_id)
    except (TypeError, ValueError):
        return
    st = _normalize_presence(status)
    db = await get_db()
    await db.execute(
        "UPDATE doctors SET presence_status = ? WHERE telegram_id = ?",
        (st, did),
    )
    await db.commit()


def set_current_client(doctor_id, user_id):
    """Устанавливает текущего клиента врача"""
    try:
        did = int(doctor_id)
    except (TypeError, ValueError):
        return
    if user_id:
        r.set(f"doctor:{did}:current_client", user_id)
    else:
        r.delete(f"doctor:{did}:current_client")


def update_doctor_activity(doctor_id):
    """Обновляет активность врача"""
    try:
        did = int(doctor_id)
    except (TypeError, ValueError):
        return
    r.setex(f"doctor:{did}:last_activity", 600, str(time.time()))


def update_client_activity(client_id):
    """Обновляет активность клиента"""
    r.setex(f"client:{client_id}:last_activity", 360, str(time.time()))


def clear_session(client_id, doctor_id):
    """Очищает сессию клиента и врача в Redis"""
    from services.dialog_session import clear_dialog_session

    r.delete(f"client:{client_id}:doctor")
    r.delete(f"client:{client_id}:consultation")
    try:
        did = int(doctor_id)
    except (TypeError, ValueError):
        did = doctor_id
    r.delete(f"doctor:{did}:current_client")
    clear_dialog_session(int(client_id))


def get_panel_mode(user_id: int) -> str | None:
    """Режим интерфейса: client | doctor | admin (для разных кнопок у одного Telegram ID)."""
    return r.get(f"user:{user_id}:panel")


def set_panel_mode(user_id: int, mode: str) -> None:
    r.set(f"user:{user_id}:panel", mode)


async def user_in_client_context(user_id: int) -> bool:
    """Клиентское меню (без кнопок врача/админа)."""
    mode = get_panel_mode(user_id)
    if mode == "client":
        return True
    if mode == "doctor" or mode == "admin":
        return False
    if user_id in ADMIN_IDS and await is_doctor(user_id):
        return False
    if await is_doctor(user_id):
        return False
    if user_id in ADMIN_IDS:
        return False
    return True


async def user_in_doctor_context(user_id: int) -> bool:
    """Панель врача."""
    mode = get_panel_mode(user_id)
    if mode == "doctor":
        return True
    if mode == "client" or mode == "admin":
        return False
    if user_id in ADMIN_IDS and await is_doctor(user_id):
        return False
    return await is_doctor(user_id)


async def user_in_admin_context(user_id: int) -> bool:
    """Панель администратора (команды /admin)."""
    mode = get_panel_mode(user_id)
    if mode == "admin":
        return True
    if mode == "client" or mode == "doctor":
        return False
    if user_id not in ADMIN_IDS:
        return False
    return not await is_doctor(user_id)


def set_client_consultation(client_id: int, consultation_id: int) -> None:
    r.set(f"client:{client_id}:consultation", str(consultation_id))


def get_client_consultation_id(client_id: int) -> int | None:
    raw = r.get(f"client:{client_id}:consultation")
    try:
        return int(raw) if raw else None
    except (TypeError, ValueError):
        return None


def append_consultation_chat_line(consultation_id: int, line: str) -> None:
    r.rpush(f"consultation:{consultation_id}:chat", line)


def get_consultation_chat_text(consultation_id: int) -> str:
    lines = r.lrange(f"consultation:{consultation_id}:chat", 0, -1)
    if not lines:
        return "(сообщений в переписке ещё не было)"
    return "\n".join(lines)


def clear_consultation_chat(consultation_id: int) -> None:
    r.delete(f"consultation:{consultation_id}:chat")


async def is_payment_confirmed(consultation_id: int):
    """Проверяет, подтверждена ли оплата для консультации"""
    from database.db import get_db
    db = await get_db()
    cursor = await db.execute('SELECT payment_confirmed FROM consultations WHERE id = ?', (consultation_id,))
    row = await cursor.fetchone()
    return bool(row and row[0])