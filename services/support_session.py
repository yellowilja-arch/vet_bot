"""Активное обращение в поддержку для клиента (Redis)."""
from __future__ import annotations

import redis
from config import REDIS_URL

r = redis.from_url(REDIS_URL, decode_responses=True)


def _key(client_id: int) -> str:
    return f"support:client:{client_id}:active_ticket"


def set_active_support_ticket(client_id: int, request_id: int) -> None:
    """Клиент ведёт диалог по этому обращению (ответы уходят админу)."""
    r.set(_key(client_id), str(request_id))


def clear_active_support_ticket(client_id: int, request_id: int | None = None) -> None:
    """Снять привязку; если передан request_id — удалить только при совпадении."""
    cur = r.get(_key(client_id))
    if request_id is None:
        r.delete(_key(client_id))
        return
    if cur and int(cur) == int(request_id):
        r.delete(_key(client_id))


def get_active_support_ticket(client_id: int) -> int | None:
    raw = r.get(_key(client_id))
    try:
        return int(raw) if raw else None
    except (TypeError, ValueError):
        return None
