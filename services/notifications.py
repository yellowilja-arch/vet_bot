import asyncio
from config import ADMIN_IDS, BOT_TOKEN
from aiogram import Bot
from utils.helpers import safe_send_message

bot = Bot(token=BOT_TOKEN)

async def notify_admin(message: str, parse_mode="HTML"):
    """Отправляет уведомление всем админам"""
    for admin_id in ADMIN_IDS:
        await safe_send_message(admin_id, message, parse_mode=parse_mode)

async def notify_admin_startup():
    """Уведомляет о запуске бота"""
    from database.db import get_db
    from database.doctors import DOCTOR_IDS
    db = await get_db()
    cursor = await db.execute('SELECT COUNT(*) FROM consultations WHERE status = "active"')
    active_count = (await cursor.fetchone())[0]
    
    await notify_admin(
        f"🟢 <b>Бот запущен</b>\n\n"
        f"👨‍⚕️ Врачей в системе: {len(DOCTOR_IDS)}\n"
        f"🟢 Активных консультаций: {active_count}"
    )

async def send_crash_report(error_text: str):
    """Отправляет отчёт об ошибке админам"""
    await notify_admin(
        f"🔴 <b>КРИТИЧЕСКАЯ ОШИБКА</b>\n\n<pre>{error_text[:3000]}</pre>",
        parse_mode="HTML"
    )

async def notify_new_queue_client(doctor_id: int, topic: str, queue_length: int):
    """Уведомляет врача о новом клиенте в очереди"""
    from utils.helpers import safe_send_message
    from keyboards.doctor import get_doctor_main_keyboard
    await safe_send_message(
        doctor_id,
        f"🆕 Новый клиент в очереди к {topic}!\n"
        f"Всего в очереди: {queue_length}.\n"
        f"Используйте /next, чтобы взять следующего.",
        reply_markup=get_doctor_main_keyboard()
    )