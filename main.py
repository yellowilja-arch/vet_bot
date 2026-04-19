import asyncio
import signal
import sys
from html import escape
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.redis import RedisStorage
import redis.asyncio as redis_async
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError
from config import BOT_TOKEN, ADMIN_IDS, REDIS_URL
from handlers import register_handlers
from workers.backups import backup_worker
from workers.inactivity import inactivity_worker
from utils.helpers import safe_send_message
from database.db import get_db
import logging

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
redis_client = redis_async.from_url(REDIS_URL, decode_responses=True)
dp = Dispatcher(storage=RedisStorage(redis=redis_client))

logging.info(f"🔑 Загруженные администраторы: {ADMIN_IDS}")

@dp.error()
async def global_error_handler(*args, exception=None, **kwargs):
    if exception is None and len(args) >= 2:
        exception = args[1]
    logging.error(f"Глобальная ошибка: {exception}")
    for admin_id in ADMIN_IDS:
        await safe_send_message(admin_id, f"❌ Глобальная ошибка бота:\n<pre>{escape(str(exception))}</pre>", parse_mode="HTML")
    return True

async def init_startup():
    """Инициализация при старте: БД, врачи, сессии"""
    from database.db import init_db
    from database.doctors import init_doctors, load_doctors_from_db
    
    logging.info("🚀 Инициализирую БД и врачей...")
    
    # Инициализация БД
    await init_db()
    
    # Инициализация врачей
    await init_doctors()
    await load_doctors_from_db()
    
    # Восстановление активных консультаций
    import redis
    r = redis.from_url(REDIS_URL, decode_responses=True)
    db = await get_db()
    cursor = await db.execute('SELECT client_id, doctor_id, id FROM consultations WHERE status = "active"')
    rows = await cursor.fetchall()
    for row in rows:
        client_id, doctor_id, consultation_id = row
        if doctor_id:
            r.set(f"client:{client_id}:doctor", doctor_id)
            r.set(f"client:{client_id}:consultation", consultation_id)
            r.set(f"doctor:{doctor_id}:current_client", client_id)
    logging.info(f"✅ Восстановлено {len(rows)} активных консультаций")

async def main():
    await init_startup()
    register_handlers(dp)
    
    # Удаляем webhook, если активен
    await bot.delete_webhook()
    logging.info("✅ Webhook удалён")
    
    # Запуск фоновых задач
    asyncio.create_task(backup_worker())
    asyncio.create_task(inactivity_worker())
    
    # Graceful shutdown
    def signal_handler(signum, frame):
        logging.info("Получен сигнал завершения, останавливаем бота...")
        asyncio.create_task(shutdown())
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logging.error(f"Ошибка в polling: {e}")
    finally:
        await shutdown()

async def shutdown():
    logging.info("Завершение работы...")
    await redis_client.aclose()
    await bot.session.close()
    sys.exit(0)

if __name__ == "__main__":
    asyncio.run(main())