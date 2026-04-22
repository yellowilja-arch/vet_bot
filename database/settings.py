"""Настройки бота (PostgreSQL, таблица settings)."""
from __future__ import annotations

from database.db import get_db, _db_lock

_KEY_ACTIVE_PAYMENT = "active_payment_method"
_VALID_MODES = frozenset({"tbank", "receipt"})


async def get_active_payment_method() -> str:
    """Активный способ оплаты для клиентов: tbank | receipt. По умолчанию tbank."""
    db = await get_db()
    cur = await db.execute(
        "SELECT value FROM settings WHERE key = ?",
        (_KEY_ACTIVE_PAYMENT,),
    )
    row = await cur.fetchone()
    if row and str(row[0]) in _VALID_MODES:
        return str(row[0])
    return "tbank"


async def set_active_payment_method(mode: str) -> None:
    if mode not in _VALID_MODES:
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
