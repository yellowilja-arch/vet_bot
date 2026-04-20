"""
Резервное хранение списка врачей вне контейнера (HTTP JSON).

Если нет постоянного диска (Railway без Volume), SQLite обнуляется при деплое.
Тогда задают DOCTORS_SYNC_PULL_URL / DOCTORS_SYNC_PUSH_URL — например jsonbin.io
или любой свой endpoint, принимающий PUT/POST JSON-массива.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

import aiohttp

from config import (
    DOCTORS_SYNC_HTTP_HEADERS,
    DOCTORS_SYNC_JSONBIN_MASTER_KEY,
    DOCTORS_SYNC_PULL_URL,
    DOCTORS_SYNC_PUSH_METHOD,
    DOCTORS_SYNC_PUSH_URL,
)
from database.db import get_db
from database.doctors import REAL_TELEGRAM_USER_ID_MIN

logger = logging.getLogger(__name__)


def _sync_headers() -> dict[str, str]:
    """Заголовки для jsonbin и др. Частая ошибка в Railway — ключ без JSON-объекта."""
    out: dict[str, str] = {}
    raw = (DOCTORS_SYNC_HTTP_HEADERS or "").strip()
    if raw:
        try:
            h = json.loads(raw)
            if isinstance(h, dict):
                out.update({str(k): str(v) for k, v in h.items()})
            else:
                logger.warning(
                    "DOCTORS_SYNC_HTTP_HEADERS должен быть JSON-объектом, например "
                    '{"X-Master-Key":"..."} или задайте DOCTORS_SYNC_JSONBIN_MASTER_KEY'
                )
        except json.JSONDecodeError:
            if "{" not in raw and len(raw) >= 8:
                out["X-Master-Key"] = raw
                logger.info(
                    "DOCTORS_SYNC: значение DOCTORS_SYNC_HTTP_HEADERS не JSON — "
                    "используем его как X-Master-Key (удобно для jsonbin)."
                )
            else:
                logger.warning(
                    "DOCTORS_SYNC_HTTP_HEADERS не JSON (%s…). Задайте "
                    '{"X-Master-Key":"ключ"} или переменную DOCTORS_SYNC_JSONBIN_MASTER_KEY.',
                    raw[:20],
                )
    mk = (DOCTORS_SYNC_JSONBIN_MASTER_KEY or "").strip()
    if mk:
        out["X-Master-Key"] = mk
    return out


def _normalize_payload(data: Any) -> list[dict[str, Any]]:
    if data is None:
        return []
    if isinstance(data, dict):
        if "record" in data:
            rec = data["record"]
            if isinstance(rec, str) and rec.strip():
                try:
                    rec = json.loads(rec)
                except json.JSONDecodeError:
                    return []
            if isinstance(rec, list):
                data = rec
            else:
                return []
        elif "doctors" in data and isinstance(data["doctors"], list):
            data = data["doctors"]
        else:
            return []
    if not isinstance(data, list):
        return []
    out: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        tid = item.get("telegram_id")
        if tid is None:
            continue
        try:
            tid_i = int(tid)
        except (TypeError, ValueError):
            continue
        if tid_i < REAL_TELEGRAM_USER_ID_MIN:
            continue
        name = item.get("name")
        if name is None or str(name).strip() == "":
            continue
        specs = item.get("spec_keys") or item.get("specializations") or []
        if isinstance(specs, str):
            specs = [specs]
        if not isinstance(specs, list) or not specs:
            continue
        spec_list = [str(s) for s in specs if s]
        if not spec_list:
            continue
        active = item.get("is_active")
        is_active = True if active is None else bool(active)
        out.append(
            {
                "telegram_id": tid_i,
                "name": str(name).strip(),
                "spec_keys": spec_list,
                "is_active": is_active,
            }
        )
    return out


async def export_doctors_for_sync() -> list[dict[str, Any]]:
    from database.doctors import ordered_spec_keys

    db = await get_db()
    cur = await db.execute(
        """
        SELECT telegram_id, name, specialization, is_active FROM doctors
        WHERE telegram_id >= ?
        ORDER BY telegram_id
        """,
        (REAL_TELEGRAM_USER_ID_MIN,),
    )
    rows = await cur.fetchall()
    if not rows:
        return []
    tids = [int(r[0]) for r in rows]
    ph = ",".join("?" * len(tids))
    cur2 = await db.execute(
        f"SELECT telegram_id, specialization FROM doctor_specializations "
        f"WHERE telegram_id IN ({ph})",
        tids,
    )
    spec_map: dict[int, list[str]] = {t: [] for t in tids}
    for tid, sp in await cur2.fetchall():
        spec_map.setdefault(int(tid), []).append(str(sp))
    out: list[dict[str, Any]] = []
    for tid, name, legacy, is_active in rows:
        tid_i = int(tid)
        keys = ordered_spec_keys(spec_map.get(tid_i, []))
        if not keys and legacy:
            keys = ordered_spec_keys([str(legacy)])
        if not keys:
            continue
        out.append(
            {
                "telegram_id": tid_i,
                "name": str(name),
                "spec_keys": keys,
                "is_active": bool(is_active),
            }
        )
    return out


async def _apply_doctor_row(
    telegram_id: int, name: str, spec_keys: list[str], is_active: bool
) -> None:
    from database.doctors import ordered_spec_keys, primary_spec_key

    keys = ordered_spec_keys(list(dict.fromkeys(spec_keys)))
    if not keys:
        return
    prim = primary_spec_key(keys)
    db = await get_db()
    await db.execute(
        """
        INSERT OR REPLACE INTO doctors (telegram_id, name, specialization, is_active)
        VALUES (?, ?, ?, ?)
        """,
        (telegram_id, name, prim, 1 if is_active else 0),
    )
    await db.execute(
        "DELETE FROM doctor_specializations WHERE telegram_id = ?",
        (telegram_id,),
    )
    for k in keys:
        await db.execute(
            "INSERT INTO doctor_specializations (telegram_id, specialization) VALUES (?, ?)",
            (telegram_id, k),
        )


async def pull_doctors_from_remote() -> None:
    url = (DOCTORS_SYNC_PULL_URL or "").strip()
    if not url:
        return
    headers = {**_sync_headers(), "Accept": "application/json"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status >= 400:
                    body = await resp.text()
                    logger.error(
                        "DOCTORS_SYNC: GET %s → %s %s",
                        url,
                        resp.status,
                        body[:500],
                    )
                    return
                data = await resp.json(content_type=None)
    except Exception as e:
        logger.error("DOCTORS_SYNC: ошибка загрузки: %s", e, exc_info=True)
        return
    rows = _normalize_payload(data)
    if not rows:
        logger.warning(
            "DOCTORS_SYNC: после GET нет валидных врачей в ответе — импорт пропущен "
            "(проверьте ключ jsonbin, тело bin и формат массива с telegram_id/name/spec_keys)."
        )
        return
    try:
        for r in rows:
            await _apply_doctor_row(
                int(r["telegram_id"]),
                str(r["name"]),
                list(r["spec_keys"]),
                bool(r["is_active"]),
            )
        db = await get_db()
        await db.commit()
    except Exception as e:
        logger.error("DOCTORS_SYNC: ошибка записи в SQLite: %s", e, exc_info=True)
        return
    from database.doctors import load_doctors_from_db, repair_specialization_keys_in_db

    await repair_specialization_keys_in_db()
    await load_doctors_from_db()
    logger.info("DOCTORS_SYNC: импортировано врачей из HTTP: %s", len(rows))


async def push_doctors_to_remote() -> None:
    url = (DOCTORS_SYNC_PUSH_URL or "").strip()
    if not url:
        return
    method = (DOCTORS_SYNC_PUSH_METHOD or "PUT").strip().upper()
    if method not in ("POST", "PUT", "PATCH"):
        method = "PUT"
    payload = await export_doctors_for_sync()
    if not payload:
        allow_empty = os.getenv("DOCTORS_SYNC_ALLOW_EMPTY_PUSH", "").strip().lower() in (
            "1",
            "true",
            "yes",
        )
        if not allow_empty:
            logger.warning(
                "DOCTORS_SYNC: выгрузка отменена — в SQLite нет врачей (пустой PUT стирает бэкап в jsonbin). "
                "Добавьте врачей или задайте DOCTORS_SYNC_ALLOW_EMPTY_PUSH=1 чтобы разрешить пустую запись."
            )
            return
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {**_sync_headers(), "Content-Type": "application/json"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.request(
                method,
                url,
                data=body,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status >= 400:
                    text = await resp.text()
                    logger.error(
                        "DOCTORS_SYNC: %s %s → %s %s",
                        method,
                        url,
                        resp.status,
                        text[:500],
                    )
                    return
    except Exception as e:
        logger.error("DOCTORS_SYNC: ошибка выгрузки: %s", e, exc_info=True)
        return
    logger.info("DOCTORS_SYNC: выгружено записей врачей: %s", len(payload))


def schedule_push_doctors_remote() -> None:
    if not (DOCTORS_SYNC_PUSH_URL or "").strip():
        return

    async def _run():
        try:
            await push_doctors_to_remote()
        except Exception as e:
            logger.error("DOCTORS_SYNC push task: %s", e, exc_info=True)

    try:
        asyncio.get_running_loop().create_task(_run())
    except RuntimeError:
        logger.warning("DOCTORS_SYNC: нет активного event loop — push не запланирован")
