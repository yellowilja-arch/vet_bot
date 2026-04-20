"""
MVP: Т-Банк интернет-эквайринг (Tinkoff API v2) — токен, Init, проверка уведомления.
Документация: https://developer.tbank.ru/eacq/
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

import aiohttp

import config as app_config

TBANK_API_BASE = getattr(app_config, "TBANK_API_BASE", None) or "https://securepay.tinkoff.ru/v2"
TBANK_PASSWORD = getattr(app_config, "TBANK_PASSWORD", None) or ""
TBANK_TERMINAL_KEY = getattr(app_config, "TBANK_TERMINAL_KEY", None) or ""

logger = logging.getLogger(__name__)


def tbank_token_from_root_params(params: dict[str, Any], password: str) -> str:
    """
    Подпись запроса/уведомления: корневые скаляры без Token; вложенные объекты не участвуют.
    """
    pairs: list[tuple[str, str]] = []
    for key in sorted(params.keys()):
        if key == "Token":
            continue
        val = params[key]
        if val is None or isinstance(val, (dict, list)):
            continue
        if isinstance(val, bool):
            sval = str(val).lower()
        else:
            sval = str(val)
        pairs.append((key, sval))
    pairs.append(("Password", password))
    pairs.sort(key=lambda x: x[0])
    concat = "".join(p[1] for p in pairs)
    return hashlib.sha256(concat.encode("utf-8")).hexdigest()


def tbank_verify_notification_token(body: dict[str, Any], password: str) -> bool:
    recv = body.get("Token")
    if not recv or not password:
        return False
    calc = tbank_token_from_root_params(body, password)
    return str(recv).lower() == calc.lower()


async def tbank_init_payment(
    *,
    amount_kopecks: int,
    order_id: str,
    description: str,
    notification_url: str,
    session: aiohttp.ClientSession | None = None,
) -> dict[str, Any]:
    """POST Init. Возвращает распарсенный JSON ответа."""
    if not TBANK_TERMINAL_KEY or not TBANK_PASSWORD:
        raise RuntimeError("TBANK_TERMINAL_KEY / TBANK_PASSWORD не заданы")

    payload: dict[str, Any] = {
        "TerminalKey": TBANK_TERMINAL_KEY,
        "Amount": int(amount_kopecks),
        "OrderId": order_id,
        "Description": description[:140],
        "NotificationURL": notification_url,
    }
    payload["Token"] = tbank_token_from_root_params(payload, TBANK_PASSWORD)

    url = f"{TBANK_API_BASE.rstrip('/')}/Init"
    close_session = False
    if session is None:
        session = aiohttp.ClientSession()
        close_session = True
    try:
        async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            text = await resp.text()
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                logger.error("T-Bank Init: не JSON: %s", text[:500])
                return {"Success": False, "Message": "Invalid JSON from bank"}
            if not data.get("Success"):
                logger.warning("T-Bank Init отказ: %s", data)
            return data
    finally:
        if close_session:
            await session.close()
