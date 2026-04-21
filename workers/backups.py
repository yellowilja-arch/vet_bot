import asyncio
import logging
from datetime import datetime

from config import YC_ACCESS_KEY_ID, ADMIN_IDS
from utils.helpers import safe_send_message


async def create_backup():
    """Ранее: копия SQLite в Yandex Cloud. Сейчас БД — PostgreSQL; файловый бэкап отключён."""
    logging.info("create_backup: PostgreSQL — используйте pg_dump / бэкапы провайдера")
    return "ℹ️ Бэкап файла .db отключён (PostgreSQL). Настройте pg_dump или снимки в панели БД."


async def backup_worker():
    """Фоновая задача: напоминание, что автозагрузка .db больше не используется."""
    while True:
        await asyncio.sleep(86400)
        if not YC_ACCESS_KEY_ID:
            continue
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        for admin_id in ADMIN_IDS:
            await safe_send_message(
                admin_id,
                "ℹ️ <b>Бэкап</b>: бот на PostgreSQL. Файловый бэкап SQLite отключён. "
                "Используйте бэкапы Postgres (Railway / pg_dump).\n"
                f"<i>{ts}</i>",
                parse_mode="HTML",
            )
