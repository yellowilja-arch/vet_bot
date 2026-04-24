"""
Лёгкий HTTP (aiohttp): health-check для Railway/деплоя.
"""
from __future__ import annotations

import logging

from aiohttp import web

logger = logging.getLogger(__name__)


async def _health(_request: web.Request) -> web.Response:
    return web.Response(text="ok")


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/health", _health)
    return app


async def start_http_site(*, host: str, port: int) -> web.AppRunner:
    app = create_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    logger.info("HTTP %s:%s — GET /health", host, port)
    return runner
