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
    cursor = await db.execute("SELECT COUNT(*) FROM consultations WHERE status = 'active'")
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
    Новое обращение: первая линия (SUPPORT_LINE_ADMIN_ID) с кнопками;
    главный админ не получает уведомление до эскалации (1 ч).
    Врачи — только текст.
    """
    from html import escape

    import config as _cfg
    from config import ADMIN_IDS

    support_line = int(getattr(_cfg, "SUPPORT_LINE_ADMIN_ID", 146617413) or 146617413)
    from database.doctors import DOCTOR_IDS
    from keyboards.admin import get_admin_support_keyboard
    from services.support_escalation import schedule_support_escalation

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

    if support_line in ADMIN_IDS:
        admin_with_keyboard = [support_line]
    else:
        admin_with_keyboard = list(ADMIN_IDS)

    for chat_id in ordered:
        if chat_id in ADMIN_IDS:
            if chat_id not in admin_with_keyboard:
                continue
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

    schedule_support_escalation(
        request_id,
        client_user_id,
        telegram_username,
        first_name,
        text,
    )


async def notify_admins_client_support_reply(
    client_user_id: int,
    telegram_username: str | None,
    first_name: str | None,
    request_id: int,
    text: str,
) -> None:
    """Ответ клиента: первая линия; после эскалации — ещё и главный админ."""
    from html import escape

    import config as _cfg
    from config import ADMIN_IDS

    support_line = int(getattr(_cfg, "SUPPORT_LINE_ADMIN_ID", 146617413) or 146617413)
    primary = int(getattr(_cfg, "PRIMARY_ADMIN_ID", 1092230808) or 1092230808)
    from keyboards.admin import get_admin_support_keyboard
    from services.support_escalation import is_ticket_escalated

    if telegram_username:
        who = f"@{escape(telegram_username)}"
    else:
        who = escape((first_name or "").strip() or "без имени")
    body = (
        f"📬 <b>Ответ от клиента №{request_id}</b>\n\n"
        f"👤 {who} (ID: {client_user_id})\n"
        f"📝 Текст:\n<pre>{escape(text)}</pre>"
        f"\n\n🔔 <i>Новое сообщение в обращении</i>"
    )
    recipients: list[int] = []
    if support_line in ADMIN_IDS:
        recipients.append(support_line)
    if is_ticket_escalated(request_id) and primary in ADMIN_IDS:
        if primary not in recipients:
            recipients.append(primary)
    if not recipients:
        recipients = list(ADMIN_IDS)

    for admin_id in recipients:
        await safe_send_message(
            admin_id,
            body,
            parse_mode="HTML",
            reply_markup=get_admin_support_keyboard(client_user_id, request_id),
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