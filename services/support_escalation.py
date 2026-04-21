"""
Эскалация новых обращений в поддержку: первая линия (SUPPORT_LINE_ADMIN_ID),
через 1 ч без ответа админа — уведомление PRIMARY_ADMIN_ID.
"""
from __future__ import annotations

import asyncio
import logging
import time

import redis
from html import escape

import config as _cfg
from config import ADMIN_IDS, REDIS_URL

# Старый config.py на сервере может не содержать этих имён — задаём значения по умолчанию
PRIMARY_ADMIN_ID = int(getattr(_cfg, "PRIMARY_ADMIN_ID", 1092230808) or 1092230808)
SUPPORT_LINE_ADMIN_ID = int(getattr(_cfg, "SUPPORT_LINE_ADMIN_ID", 146617413) or 146617413)

from database.db import get_db

r = redis.from_url(REDIS_URL, decode_responses=True)

ZKEY = "support_esc:due"
HKEY_PREFIX = "support_esc:data:"


def should_schedule_support_escalation() -> bool:
    """Два разных админа в конфиге — имеет смысл ждать ответ линии и эскалировать главному."""
    return (
        SUPPORT_LINE_ADMIN_ID in ADMIN_IDS
        and PRIMARY_ADMIN_ID in ADMIN_IDS
        and SUPPORT_LINE_ADMIN_ID != PRIMARY_ADMIN_ID
    )


def schedule_support_escalation(
    request_id: int,
    client_user_id: int,
    telegram_username: str | None,
    first_name: str | None,
    text: str,
) -> None:
    if not should_schedule_support_escalation():
        return
    due = int(time.time()) + 3600
    rid = str(request_id)
    r.zadd(ZKEY, {rid: due})
    r.hset(
        HKEY_PREFIX + rid,
        mapping={
            "client_user_id": str(client_user_id),
            "username": telegram_username or "",
            "first_name": first_name or "",
            "text": (text or "")[:3500],
        },
    )


def cancel_support_escalation(request_id: int) -> None:
    """Снять ожидание эскалации (ответ админа до таймера). Флаг follow-up для главного не трогаем."""
    rid = str(request_id)
    r.zrem(ZKEY, rid)
    r.delete(HKEY_PREFIX + rid)


def clear_support_ticket_escalation_meta(request_id: int) -> None:
    """При закрытии тикета — убрать таймер и метку эскалации."""
    cancel_support_escalation(request_id)
    r.delete(f"support:escalated:{request_id}")


def mark_ticket_escalated_for_followups(request_id: int) -> None:
    """После эскалации ответы клиента видит и главный админ."""
    r.set(f"support:escalated:{request_id}", "1", ex=86400 * 14)


def is_ticket_escalated(request_id: int) -> bool:
    return bool(r.get(f"support:escalated:{request_id}"))


async def _has_admin_message(request_id: int) -> bool:
    db = await get_db()
    cur = await db.execute(
        """
        SELECT 1 FROM support_messages
        WHERE request_id = ? AND sender_role = 'admin'
        LIMIT 1
        """,
        (request_id,),
    )
    return await cur.fetchone() is not None


async def run_due_support_escalations() -> None:
    from database.support import get_open_request
    from keyboards.admin import get_escalation_reply_keyboard
    from utils.helpers import safe_send_message

    now = int(time.time())
    due_ids = r.zrangebyscore(ZKEY, "-inf", now, start=0, num=40)
    for rid_s in due_ids:
        try:
            rid = int(rid_s)
        except ValueError:
            r.zrem(ZKEY, rid_s)
            continue

        if not await get_open_request(rid):
            cancel_support_escalation(rid)
            continue

        if await _has_admin_message(rid):
            cancel_support_escalation(rid)
            continue

        h = r.hgetall(HKEY_PREFIX + rid_s)
        if not h:
            r.zrem(ZKEY, rid_s)
            continue

        try:
            client_uid = int(h.get("client_user_id") or 0)
        except ValueError:
            cancel_support_escalation(rid)
            continue

        un = (h.get("username") or "").strip()
        fn = (h.get("first_name") or "").strip()
        if un:
            who_plain = f"@{un}"
        else:
            who_plain = fn or "без имени"

        body_text = h.get("text") or ""

        msg = (
            "⏰ <b>ЭСКАЛАЦИЯ ОБРАЩЕНИЯ</b>\n\n"
            f"Обращение №{rid} от клиента {escape(who_plain)} (ID: {client_uid})\n"
            f"не было отвечено в течение 1 часа.\n\n"
            f"📝 Текст: {escape(body_text)}\n\n"
            "Время ожидания: 1 час"
        )

        try:
            await safe_send_message(
                PRIMARY_ADMIN_ID,
                msg,
                parse_mode="HTML",
                reply_markup=get_escalation_reply_keyboard(client_uid, rid),
            )
        except Exception as e:
            logging.warning("support escalation: не удалось уведомить %s: %s", PRIMARY_ADMIN_ID, e)
            continue

        mark_ticket_escalated_for_followups(rid)
        cancel_support_escalation(rid)


async def support_escalation_worker() -> None:
    while True:
        await asyncio.sleep(45)
        try:
            await run_due_support_escalations()
        except Exception:
            logging.exception("support_escalation_worker")
