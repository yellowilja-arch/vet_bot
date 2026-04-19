"""
Отслеживание активного диалога клиент–врач для напоминаний и авто-завершения.
Данные в Redis, переживают перезапуск (при восстановлении сессий в main — вызов init).
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import redis

from config import REDIS_URL

r = redis.from_url(REDIS_URL, decode_responses=True)

DIALOG_KEY_PREFIX = "dialog:by_client:"

# Секунды (как в ТЗ)
REMIND_5_SEC = 300
REMIND_10_SEC = 600
REMIND_15_SEC = 900


def _key(client_id: int) -> str:
    return f"{DIALOG_KEY_PREFIX}{client_id}"


def init_dialog_after_consultation_start(client_id: int, doctor_id: int) -> None:
    """
    После «Начать консультацию»: ждём ответа клиента (как после приглашения написать врачу).
    """
    now = time.time()
    k = _key(client_id)
    r.hset(
        k,
        mapping={
            "doctor_id": str(doctor_id),
            "last_message_ts": str(now),
            "last_sender": "doctor",
            "status": "waiting_client",
            "r5": "0",
            "r10": "0",
            "r15": "0",
        },
    )


def record_client_message(client_id: int, doctor_id: int) -> None:
    """Клиент написал — ждём врача."""
    now = time.time()
    k = _key(client_id)
    r.hset(
        k,
        mapping={
            "doctor_id": str(doctor_id),
            "last_message_ts": str(now),
            "last_sender": "client",
            "status": "waiting_doctor",
            "r5": "0",
            "r10": "0",
            "r15": "0",
        },
    )


def record_doctor_message(client_id: int, doctor_id: int) -> None:
    """Врач написал — ждём клиента."""
    now = time.time()
    k = _key(client_id)
    r.hset(
        k,
        mapping={
            "doctor_id": str(doctor_id),
            "last_message_ts": str(now),
            "last_sender": "doctor",
            "status": "waiting_client",
            "r5": "0",
            "r10": "0",
            "r15": "0",
        },
    )


def clear_dialog_session(client_id: int) -> None:
    r.delete(_key(client_id))


def load_dialog(client_id: int) -> dict[str, str] | None:
    k = _key(client_id)
    data = r.hgetall(k)
    return data if data else None


def mark_reminder_sent(client_id: int, level: str) -> None:
    """level: r5 | r10 | r15"""
    r.hset(_key(client_id), level, "1")


def iter_dialog_client_ids():
    for key in r.scan_iter(f"{DIALOG_KEY_PREFIX}*"):
        try:
            yield int(key.replace(DIALOG_KEY_PREFIX, "", 1))
        except ValueError:
            continue


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def log_tick(msg: str) -> None:
    logging.info("[dialog_inactivity] %s | %s", utc_now_iso(), msg)
