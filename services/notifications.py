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

async def notify_support_ticket_created(
    client_user_id: int,
    telegram_username: str | None,
    first_name: str | None,
    text: str,
    request_id: int,
) -> None:
    """
    Уведомляет администраторов (с кнопками) и всех активных врачей (только текст).
    Врач видит обращение, ответ через кнопки — у администратора.
    """
    from html import escape

    from config import ADMIN_IDS
    from database.doctors import DOCTOR_IDS
    from keyboards.admin import get_admin_support_keyboard

    if telegram_username:
        who = f"@{escape(telegram_username)}"
    else:
        who = escape((first_name or "").strip() or "без имени")
    body = (
        f"📬 <b>НОВОЕ ОБРАЩЕНИЕ В ПОДДЕРЖКУ</b>\n\n"
        f"👤 От: {who} (ID: {client_user_id})\n"
        f"🆔 №{request_id}\n"
        f"📝 Текст:\n<pre>{escape(text)}</pre>"
    )
    doctor_footer = (
        "\n\n<i>Ответ клиенту оформляет администратор. У вас только уведомление.</i>"
    )

    seen: set[int] = set()
    ordered: list[int] = []
    for uid in list(ADMIN_IDS) + list(DOCTOR_IDS):
        if uid not in seen:
            seen.add(uid)
            ordered.append(uid)

    for chat_id in ordered:
        if chat_id in ADMIN_IDS:
            await safe_send_message(
                chat_id,
                body,
                parse_mode="HTML",
                reply_markup=get_admin_support_keyboard(client_user_id, request_id),
            )
        else:
            await safe_send_message(
                chat_id,
                body + doctor_footer,
                parse_mode="HTML",
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