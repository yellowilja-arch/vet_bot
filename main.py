import asyncio
import signal
import sys
from html import escape
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.redis import RedisStorage
import redis.asyncio as redis_async
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError
from aiogram.types import ErrorEvent
import os
from config import BOT_TOKEN, ADMIN_IDS, REDIS_URL, PORT
from handlers import register_handlers
from services.bot_commands import default_scope_commands
from workers.backups import backup_worker
from workers.inactivity import inactivity_worker
from workers.doctor_reminders import doctor_reminder_worker
from services.support_escalation import support_escalation_worker
from utils.helpers import safe_send_message
from database.db import get_db
import logging

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
redis_client = redis_async.from_url(REDIS_URL, decode_responses=True)
dp = Dispatcher(storage=RedisStorage(redis=redis_client))

logging.info(f"🔑 Загруженные администраторы: {ADMIN_IDS}")

@dp.error()
async def global_error_handler(event: ErrorEvent):
    """В aiogram 3 в хендлер передаётся ErrorEvent; exception в kwargs нет — иначе в логах всегда None."""
    exc = event.exception
    if exc is not None:
        logging.error("Глобальная ошибка: %s", exc, exc_info=exc)
    else:
        logging.error("Глобальная ошибка: exception отсутствует в ErrorEvent")
    detail = escape(str(exc)) if exc is not None else "неизвестная ошибка"
    for admin_id in ADMIN_IDS:
        await safe_send_message(
            admin_id,
            f"❌ Глобальная ошибка бота:\n<pre>{detail}</pre>",
            parse_mode="HTML",
        )
    return True

async def init_startup():
    """Инициализация при старте: БД, врачи, сессии"""
    from database.db import init_db
    from database.doctors import init_doctors
    
    logging.info("🚀 Инициализирую БД и врачей...")
    _dsn = (os.getenv("DATABASE_URL") or os.getenv("PGDATABASE_URL") or "").strip()
    if "@" in _dsn:
        _safe = _dsn.split("@", 1)[-1]
        logging.info("🐘 PostgreSQL: …@%s", _safe[:80])
    else:
        logging.info("🐘 PostgreSQL: DATABASE_URL задан")

    # Инициализация БД
    await init_db()
    
    # Инициализация врачей
    await init_doctors()

    # Восстановление активных консультаций
    import redis
    r = redis.from_url(REDIS_URL, decode_responses=True)
    db = await get_db()
    cursor = await db.execute("SELECT client_id, doctor_id, id FROM consultations WHERE status = 'active'")
    rows = await cursor.fetchall()
    from services.dialog_session import init_dialog_after_consultation_start

    for row in rows:
        client_id, doctor_id, consultation_id = row
        if doctor_id:
            r.set(f"client:{client_id}:doctor", doctor_id)
            r.set(f"client:{client_id}:consultation", consultation_id)
            r.set(f"doctor:{doctor_id}:current_client", client_id)
            init_dialog_after_consultation_start(int(client_id), int(doctor_id))
    logging.info(f"✅ Восстановлено {len(rows)} активных консультаций")

async def main():
    await init_startup()
    register_handlers(dp)
    
    # Удаляем webhook, если активен
    await bot.delete_webhook()
    logging.info("✅ Webhook удалён")
    await bot.set_my_commands(default_scope_commands())
    logging.info("✅ Меню команд по умолчанию (клиент) установлено")
    
    # Запуск фоновых задач
    asyncio.create_task(backup_worker())
    asyncio.create_task(inactivity_worker())
    asyncio.create_task(doctor_reminder_worker())
    asyncio.create_task(support_escalation_worker())
    
    # Graceful shutdown
    def signal_handler(signum, frame):
        logging.info("Получен сигнал завершения, останавливаем бота...")
        asyncio.create_task(shutdown())
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    http_runner = None
    try:
        from services.tbank_server import start_http_site

        http_runner = await start_http_site(bot, dp, host="0.0.0.0", port=PORT)
    except Exception as e:
        logging.warning("HTTP (health, /tbank/notify) не поднят: %s", e)

    try:
        await dp.start_polling(bot)
    except Exception as e:
        logging.error(f"Ошибка в polling: {e}")
    finally:
        if http_runner is not None:
            try:
                await http_runner.cleanup()
            except Exception as e:
                logging.warning("HTTP runner cleanup: %s", e)
        await shutdown()

async def shutdown():
    logging.info("Завершение работы...")
    try:
        from database.db import close_db_connection

        await close_db_connection()
    except Exception as e:
        logging.warning("Не удалось корректно закрыть пул PostgreSQL: %s", e)
    await redis_client.aclose()
    await bot.session.close()
    sys.exit(0)

if __name__ == "__main__":
    asyncio.run(main())