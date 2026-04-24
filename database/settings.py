"""Настройки бота (PostgreSQL, таблица settings)."""
from __future__ import annotations

from database.db import get_db, _db_lock

_KEY_ACTIVE_PAYMENT = "active_payment_method"
# В БД раньше хранилось tbank — читаем как yookassa
_VALID_MODES = frozenset({"yookassa", "receipt", "tbank"})


def _normalize_mode(raw: str) -> str:
    if raw == "tbank":
        return "yookassa"
    return raw


async def get_active_payment_method() -> str:
    """Активный способ оплаты: yookassa (Telegram Payments) | receipt. По умолчанию yookassa."""
    db = await get_db()
    cur = await db.execute(
        "SELECT value FROM settings WHERE key = ?",
        (_KEY_ACTIVE_PAYMENT,),
    )
    row = await cur.fetchone()
    if row and str(row[0]) in _VALID_MODES:
        return _normalize_mode(str(row[0]))
    return "yookassa"


async def set_active_payment_method(mode: str) -> None:
    if mode not in ("yookassa", "receipt"):
        raise ValueError(mode)
    db = await get_db()
    async with _db_lock:
        await db.execute(
            """
            INSERT INTO settings (key, value) VALUES (?, ?)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            """,
            (_KEY_ACTIVE_PAYMENT, mode),
        )
        await db.commit()
