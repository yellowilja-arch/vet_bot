"""Обращения в поддержку: тикеты и переписка."""
from __future__ import annotations

from database.db import get_db


async def backfill_messages_from_legacy() -> None:
    """Переносит первое сообщение из support_requests в support_messages, если строк ещё нет."""
    db = await get_db()
    cur = await db.execute(
        """
        SELECT sr.id, sr.user_id, sr.message
        FROM support_requests sr
        WHERE NOT EXISTS (SELECT 1 FROM support_messages sm WHERE sm.request_id = sr.id)
        """
    )
    rows = await cur.fetchall()
    for rid, uid, msg in rows:
        await db.execute(
            """
            INSERT INTO support_messages (request_id, sender_role, sender_id, body)
            VALUES (?, 'client', ?, ?)
            """,
            (rid, uid, msg or ""),
        )
    if rows:
        await db.commit()


async def create_support_ticket(user_id: int, username: str | None, text: str) -> int:
    db = await get_db()
    cur = await db.execute(
        """
        INSERT INTO support_requests (user_id, username, message, status)
        VALUES (?, ?, ?, 'open')
        """,
        (user_id, username or "", text),
    )
    await db.commit()
    request_id = cur.lastrowid
    await db.execute(
        """
        INSERT INTO support_messages (request_id, sender_role, sender_id, body)
        VALUES (?, 'client', ?, ?)
        """,
        (request_id, user_id, text),
    )
    await db.commit()
    return request_id


async def add_support_message(request_id: int, sender_role: str, sender_id: int, body: str) -> None:
    db = await get_db()
    await db.execute(
        """
        INSERT INTO support_messages (request_id, sender_role, sender_id, body)
        VALUES (?, ?, ?, ?)
        """,
        (request_id, sender_role, sender_id, body),
    )
    await db.commit()


async def get_open_request(request_id: int) -> tuple | None:
    """Возвращает строку support_requests, если обращение открыто."""
    db = await get_db()
    cur = await db.execute(
        """
        SELECT id, user_id, username, status, message, created_at
        FROM support_requests
        WHERE id = ? AND status = 'open'
        """,
        (request_id,),
    )
    return await cur.fetchone()


async def close_support_request(request_id: int) -> bool:
    db = await get_db()
    cur = await db.execute(
        """
        UPDATE support_requests
        SET status = 'closed', resolved_at = CURRENT_TIMESTAMP
        WHERE id = ? AND status = 'open'
        """,
        (request_id,),
    )
    await db.commit()
    return cur.rowcount > 0


async def list_open_requests() -> list[tuple[int, int, str | None, str, str]]:
    """
    Открытые обращения: id, user_id, username, первое сообщение (превью), created_at.
    Сначала старые (FIFO).
    """
    db = await get_db()
    cur = await db.execute(
        """
        SELECT id, user_id, username, message, created_at
        FROM support_requests
        WHERE status = 'open'
        ORDER BY created_at ASC
        """
    )
    return await cur.fetchall()


async def format_user_history(user_id: int, limit: int = 30) -> str:
    """Текст последних сообщений переписки с поддержкой (по всем тикетам пользователя)."""
    db = await get_db()
    cur = await db.execute(
        """
        SELECT sm.sender_role, sm.body, sm.created_at, sm.request_id
        FROM support_messages sm
        INNER JOIN support_requests sr ON sr.id = sm.request_id
        WHERE sr.user_id = ?
        ORDER BY sm.id DESC
        LIMIT ?
        """,
        (user_id, limit),
    )
    rows = await cur.fetchall()
    if not rows:
        return ""
    lines: list[str] = []
    for role, body, created_at, req_id in reversed(rows):
        who = "Вы" if role == "client" else "Администратор"
        ts = (created_at or "")[:16]
        lines.append(f"[№{req_id}] {ts} · {who}:\n{body}")
    return "\n\n".join(lines)


async def ensure_active_support_ticket_for_client(client_id: int) -> int | None:
    """
    Актуальное открытое обращение для переписки: Redis, иначе последнее open в БД (после рестарта).
    """
    from services.support_session import (
        clear_active_support_ticket,
        get_active_support_ticket,
        set_active_support_ticket,
    )

    rid = get_active_support_ticket(client_id)
    if rid:
        if await get_open_request(rid):
            return rid
        clear_active_support_ticket(client_id)

    rid2 = await get_latest_open_ticket_for_user(client_id)
    if rid2 and await get_open_request(rid2):
        set_active_support_ticket(client_id, rid2)
        return rid2
    return None


async def get_latest_open_ticket_for_user(user_id: int) -> int | None:
    """Самое новое открытое обращение пользователя (для ответов после перезапуска Redis)."""
    db = await get_db()
    cur = await db.execute(
        """
        SELECT id FROM support_requests
        WHERE user_id = ? AND status = 'open'
        ORDER BY id DESC
        LIMIT 1
        """,
        (user_id,),
    )
    row = await cur.fetchone()
    return int(row[0]) if row else None


async def count_open_for_user(user_id: int) -> int:
    db = await get_db()
    cur = await db.execute(
        "SELECT COUNT(*) FROM support_requests WHERE user_id = ? AND status = 'open'",
        (user_id,),
    )
    row = await cur.fetchone()
    return int(row[0]) if row else 0
