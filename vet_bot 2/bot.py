import asyncio
import sys
import traceback
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.redis import RedisStorage
from config import BOT_TOKEN, REDIS_URL
from database.db import init_db
from database.doctors import init_doctors
from handlers import common, doctor, client, admin
from workers.inactivity import inactivity_worker
from workers.backups import backup_worker
from services.notifications import notify_admin_startup, send_crash_report
from services.reset_tools import reset_all_states
from utils.logger import setup_logging

# Настройка логирования
setup_logging()

# Инициализация бота
bot = Bot(token=BOT_TOKEN)
storage = RedisStorage.from_url(REDIS_URL)
dp = Dispatcher(storage=storage)

# Регистрация роутеров
dp.include_router(common.router)
dp.include_router(doctor.router)
dp.include_router(client.router)
dp.include_router(admin.router)

# Глобальный перехват ошибок
def global_exception_handler(exc_type, exc_value, exc_traceback):
    error_msg = ''.join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    asyncio.create_task(send_crash_report(error_msg))
    sys.__excepthook__(exc_type, exc_value, exc_traceback)

sys.excepthook = global_exception_handler

async def on_startup():
    """Действия при запуске бота"""
    await init_db()
    await init_doctors()
    await reset_all_states()  # Сброс состояний при старте (очистка Redis)
    await notify_admin_startup()
    
    # Запуск фоновых задач
    asyncio.create_task(inactivity_worker())
    asyncio.create_task(backup_worker())
    
    print("✅ Бот успешно запущен!")

async def on_shutdown():
    """Действия при остановке бота"""
    print("🛑 Бот останавливается...")
    await bot.session.close()
    await storage.close()

async def main():
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("🛑 Бот остановлен пользователем")