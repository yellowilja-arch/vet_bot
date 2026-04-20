"""
HTTP-сервер (aiohttp): health-check и вебхук Т-Банка.
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from aiohttp import web

import config as app_config

TBANK_PASSWORD = getattr(app_config, "TBANK_PASSWORD", None) or ""


def tbank_acquiring_configured() -> bool:
    fn = getattr(app_config, "tbank_acquiring_configured", None)
    if callable(fn):
        return fn()
    return bool(
        getattr(app_config, "TBANK_TERMINAL_KEY", "")
        and TBANK_PASSWORD
        and (getattr(app_config, "PUBLIC_WEBHOOK_BASE", None) or "")
    )

if TYPE_CHECKING:
    from aiogram import Bot, Dispatcher

logger = logging.getLogger(__name__)


async def _finalize_tbank_payment(order_id: str, payment_id: str, bot: "Bot", dp: "Dispatcher") -> None:
    from database.payments import get_payment_by_tbank_order_id, set_tbank_payment_id_for_order
    from services.client_payment_flow import start_questionnaire_after_confirmed_payment

    try:
        row = await get_payment_by_tbank_order_id(order_id)
        if not row:
            logger.warning("T-Bank: OrderId не найден в БД: %s", order_id)
            return
        _pay_row_id, client_id, consultation_id, _amount, status, _oid, _existing_pid = row
        if status == "confirmed":
            return
        if consultation_id is None:
            logger.warning("T-Bank: нет consultation_id для order %s", order_id)
            return
        if payment_id:
            await set_tbank_payment_id_for_order(order_id, payment_id)
        await start_questionnaire_after_confirmed_payment(
            int(client_id),
            int(consultation_id),
            bot=bot,
            dispatcher=dp,
        )
    except Exception:
        logger.exception("T-Bank: ошибка финализации order=%s", order_id)


async def tbank_notify_handler(request: web.Request) -> web.Response:
    from services.tbank import tbank_verify_notification_token

    try:
        if request.content_type and "json" in request.content_type.lower():
            body = await request.json()
        else:
            body = dict(await request.post())
    except Exception as e:
        logger.warning("T-Bank notify: разбор тела: %s", e)
        return web.Response(status=400, text="BAD")

    if not isinstance(body, dict):
        return web.Response(status=400, text="BAD")

    if not tbank_verify_notification_token(body, TBANK_PASSWORD):
        logger.warning("T-Bank notify: неверный Token, OrderId=%s", body.get("OrderId"))
        return web.Response(status=403, text="FAIL")

    status = str(body.get("Status") or "")
    success = str(body.get("Success", "")).lower() in ("true", "1")
    if success and status == "CONFIRMED":
        bot: Bot = request.app["bot"]
        dp: Dispatcher = request.app["dp"]
        order_id = str(body.get("OrderId") or "")
        payment_id = str(body.get("PaymentId") or "")
        if order_id:
            asyncio.create_task(_finalize_tbank_payment(order_id, payment_id, bot, dp))

    return web.Response(text="OK")


async def health_handler(_request: web.Request) -> web.Response:
    return web.Response(text="ok")


def create_tbank_app(bot: "Bot", dp: "Dispatcher") -> web.Application:
    app = web.Application()
    app["bot"] = bot
    app["dp"] = dp
    app.router.add_get("/health", health_handler)
    if tbank_acquiring_configured():
        app.router.add_post("/tbank/notify", tbank_notify_handler)
        logger.info("T-Bank: POST /tbank/notify включён")
    else:
        logger.info("T-Bank: вебхук выключен (заполните TBANK_* и PUBLIC_WEBHOOK_BASE)")
    return app


async def start_http_site(bot: "Bot", dp: "Dispatcher", *, host: str, port: int) -> web.AppRunner:
    app = create_tbank_app(bot, dp)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    logger.info("HTTP %s:%s — GET /health%s", host, port, " + POST /tbank/notify" if tbank_acquiring_configured() else "")
    return runner
