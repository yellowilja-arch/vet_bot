from aiogram import Router, F
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.filters import Command, StateFilter
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.fsm.context import FSMContext
from html import escape
from config import ADMIN_IDS, DB_PATH, REDIS_URL, SUPPORT_TEMPLATE_TEXT
from services.validators import (
    get_doctor_status,
    is_admin,
    user_in_admin_context,
    user_in_client_context,
)
from services.reset_tools import reset_user_state, reset_all_states, close_stuck_requests, unlock_all_doctors
from database.users import get_user_info, get_recent_users
from database.doctors import (
    add_doctor,
    remove_doctor,
    update_doctor,
    get_doctor_admin_row,
    get_doctor_spec_keys,
    DOCTOR_IDS,
    ordered_spec_keys,
    specializations_slash_plain,
)
from database.queue import get_queue_length, clear_queue
from database.db import get_db, checkpoint_wal_for_backup
from utils.helpers import safe_send_message, split_text_chunks
from keyboards.admin import (
    get_support_queue_keyboard,
    get_doctor_multi_spec_keyboard,
    get_edit_doctor_active_keyboard,
)
from data.problems import SPECIALISTS, SPECIALIZATION_KEYS
from database.support import (
    add_support_message,
    close_support_request,
    get_open_request,
    list_open_requests,
)
from states.forms import WaitingState, AdminState
import logging
import os
import shutil
import tempfile
import redis
from datetime import datetime

r = redis.from_url(REDIS_URL, decode_responses=True)

router = Router()

# Совпадает с подписями в keyboards.admin.get_admin_main_keyboard (локально — чтобы не ломать импорт при частичном деплое)
_ADMIN_MAIN_KEYBOARD_TEXTS = frozenset(
    {
        "📬 Обращения",
        "📊 Статистика",
        "🩺 Здоровье",
        "🚫 Заблокировать",
        "✅ Разблокировать",
        "➕ Добавить врача",
        "✏️ Изменить врача",
        "➖ Удалить врача",
        "🔄 Сброс состояний",
        "💾 Бэкап",
    }
)

# FSM мастеров админки: не перехватывать произвольный текст до общих хендлеров /cancel и «прервать по меню»
_ADMIN_INTERRUPTIBLE_STATES = (
    AdminState.waiting_ban_user_id,
    AdminState.waiting_ban_reason,
    AdminState.waiting_unban_user_id,
    AdminState.waiting_remove_doctor_id,
    AdminState.waiting_resetall_confirm,
    AdminState.add_doctor_telegram,
    AdminState.add_doctor_name,
    AdminState.add_doctor_pick_spec,
    AdminState.edit_doctor_telegram,
    AdminState.edit_doctor_name,
    AdminState.edit_doctor_specs,
    AdminState.edit_doctor_active,
)


def _parse_int(value: str):
    try:
        return int(value)
    except ValueError:
        return None


def _role_label(uid: int, admin_ids: set[int], doctor_ids: set[int]) -> str:
    in_a = uid in admin_ids
    in_d = uid in doctor_ids
    if in_a and in_d:
        return "Админ + Врач"
    if in_d:
        return "Врач"
    if in_a:
        return "Админ"
    return "Клиент"


def _stats_name_title(s: str) -> str:
    """Фамилия имя: каждое слово с заглавной буквы."""
    return " ".join(
        (w[:1].upper() + w[1:].lower()) if w else "" for w in s.split()
    ).strip()


async def _reply_admin_stats(user_id: int) -> None:
    db = await get_db()
    cursor = await db.execute("SELECT COUNT(*) FROM users")
    users_total = (await cursor.fetchone())[0]
    cursor = await db.execute("SELECT COUNT(*) FROM consultations")
    cons_total = (await cursor.fetchone())[0]
    cursor = await db.execute('SELECT COUNT(*) FROM consultations WHERE status = "active"')
    active = (await cursor.fetchone())[0]
    cursor = await db.execute("SELECT COUNT(*) FROM consultations WHERE ended_at IS NOT NULL")
    completed = (await cursor.fetchone())[0]

    cursor = await db.execute(
        "SELECT telegram_id FROM doctors WHERE is_active = 1"
    )
    doctor_rows = await cursor.fetchall()
    doctor_ids = {int(r[0]) for r in doctor_rows}
    admin_set = set(ADMIN_IDS)

    cursor = await db.execute("SELECT user_id FROM blacklist")
    blocked_ids = {int(r[0]) for r in await cursor.fetchall()}

    cursor = await db.execute(
        """
        SELECT user_id, username
        FROM users
        ORDER BY (last_seen IS NULL), last_seen DESC, user_id ASC
        """
    )
    all_user_rows = await cursor.fetchall()

    display_n = min(20, len(all_user_rows))
    rest = max(0, len(all_user_rows) - display_n)

    lines: list[str] = [
        "📊 <b>СТАТИСТИКА БОТА</b>",
        "",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"👥 <b>ПОЛЬЗОВАТЕЛИ ({users_total})</b>",
        "",
    ]
    for row in all_user_rows[:display_n]:
        uid = int(row[0])
        uname = row[1]
        at = f"@{escape(uname)}" if uname else "—"
        role = _role_label(uid, admin_set, doctor_ids)
        extra = ""
        if uid in blocked_ids:
            extra = " 🚫 заблокирован"
        lines.append(f"👤 ID: <code>{uid}</code> | {at} | {escape(role)}{extra}")

    if rest:
        lines.append("")
        lines.append(f"… и ещё {rest} пользователей")

    lines.extend(
        [
            "",
            "━━━━━━━━━━━━━━━━━━━━━━",
            "📋 <b>КОНСУЛЬТАЦИИ</b>",
            f"Всего: {cons_total} | Активных: {active} | Завершённых: {completed}",
            "",
            "━━━━━━━━━━━━━━━━━━━━━━",
        ]
    )

    cursor = await db.execute(
        """
        SELECT d.name, d.specialization, GROUP_CONCAT(ds.specialization, ',') AS spec_csv
        FROM doctors d
        LEFT JOIN doctor_specializations ds ON ds.telegram_id = d.telegram_id
        GROUP BY d.id, d.name, d.specialization
        ORDER BY d.name COLLATE NOCASE ASC
        """
    )
    all_doctor_rows = await cursor.fetchall()
    n_docs = len(all_doctor_rows)
    lines.append(f"👨‍⚕️ <b>ВРАЧИ В СИСТЕМЕ ({n_docs})</b>")
    lines.append("")
    for dname, legacy, spec_csv in all_doctor_rows:
        parts = [x.strip() for x in (spec_csv or "").split(",") if x.strip()]
        keys = ordered_spec_keys(parts)
        if not keys and legacy:
            keys = [legacy]
        nm = _stats_name_title(str(dname or "—").strip())
        sp = specializations_slash_plain(keys) if keys else "—"
        lines.append(escape(f"{nm} {sp}".strip()))

    text = "\n".join(lines)
    for chunk in split_text_chunks(text, max_len=3900):
        await safe_send_message(user_id, chunk, parse_mode="HTML")


async def _reply_admin_health(user_id: int) -> None:
    try:
        r.ping()
        redis_status = "✅"
    except Exception as e:
        redis_status = f"❌ {e}"

    try:
        db = await get_db()
        await db.execute("SELECT 1")
        sqlite_status = "✅"
    except Exception as e:
        sqlite_status = f"❌ {e}"

    try:
        cursor = await db.execute('SELECT COUNT(*) FROM consultations WHERE status = "active"')
        active_cons = (await cursor.fetchone())[0]
    except Exception:
        active_cons = "ошибка"

    online_doctors = sum(1 for d in DOCTOR_IDS if get_doctor_status(d) == "online")
    queue_lengths = {"all": await get_queue_length("all")}

    text = f"🩺 <b>Здоровье бота</b>\n\n"
    text += f"Redis: {redis_status}\n"
    text += f"SQLite: {sqlite_status}\n"
    text += f"Активных консультаций: {active_cons}\n"
    text += f"Врачей онлайн: {online_doctors}\n"
    text += f"Очередь: {queue_lengths}\n"
    await safe_send_message(user_id, text, parse_mode="HTML")


@router.message(Command("start"), StateFilter(*_ADMIN_INTERRUPTIBLE_STATES))
async def admin_fsm_clear_on_start(message: Message, state: FSMContext):
    """
    admin_router подключён раньше client: /start иначе попадает в «введите ID» (F.text),
    если фильтры отработали не в ожидаемом порядке. Сбрасываем FSM и отдаём /start в client.
    """
    await state.clear()
    raise SkipHandler()


@router.message(Command("clearqueue"))
async def admin_clear_queue(message: Message):
    """Сброс Redis/SQLite очереди (в т.ч. после тестов с битым client_id)."""
    user_id = message.from_user.id
    if not await user_in_admin_context(user_id):
        return
    affected, notify_ids, n_active_closed = await clear_queue("all")
    for uid in notify_ids:
        try:
            await safe_send_message(
                uid,
                "ℹ️ Администратор выполнил сброс очереди и ожидающих заявок.\n\n"
                "• Если у вас была открытая консультация с врачом — она завершена.\n"
                "• Предварительное закрепление за врачом по оплате снято.\n\n"
                "При необходимости начните заново из меню или напишите в «🆘 Помощь».",
            )
        except Exception as e:
            logging.warning("clearqueue: не удалось уведомить клиента %s: %s", uid, e)
    await safe_send_message(
        user_id,
        "✅ Сброс выполнен. Принудительно закрыто активных консультаций: "
        f"{n_active_closed}. Клиентов с очищенным ожиданием/очередью: {len(affected)}. "
        f"Уведомлений клиентам: {len(notify_ids)}.",
    )


async def _admin_send_sqlite_backup(
    bot,
    admin_id: int,
    attach_to_message: Message | None,
    *,
    announce_progress: bool = True,
) -> None:
    """Копирует SQLite БД и отправляет .db файл администратору."""
    if not await user_in_admin_context(admin_id):
        await safe_send_message(admin_id, "⛔ Только для администраторов")
        return

    if announce_progress:
        await safe_send_message(admin_id, "⏳ Создаю бэкап базы данных...")

    temp_path: str | None = None
    try:
        db_file = os.path.abspath(DB_PATH)
        if not os.path.isfile(db_file):
            await safe_send_message(admin_id, "❌ Файл базы данных не найден!")
            return

        await checkpoint_wal_for_backup()

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"vet_bot_backup_{timestamp}.db"
        temp_path = os.path.join(tempfile.gettempdir(), backup_name)
        shutil.copy2(db_file, temp_path)
        size_b = os.path.getsize(temp_path)
        document = FSInputFile(temp_path, filename=backup_name)
        caption = f"✅ Бэкап БД от {timestamp}\n📦 Размер: {size_b} байт"
        if attach_to_message is not None:
            await attach_to_message.answer_document(document=document, caption=caption)
        else:
            await bot.send_document(admin_id, document=document, caption=caption)
    except Exception as e:
        await safe_send_message(
            admin_id,
            f"❌ Ошибка создания бэкапа:\n<pre>{escape(str(e))}</pre>",
            parse_mode="HTML",
        )
    finally:
        if temp_path and os.path.isfile(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


@router.message(F.text == "💾 Бэкап")
async def admin_backup_reply_button(message: Message):
    """Reply-кнопка «💾 Бэкап» в панели администратора."""
    await _admin_send_sqlite_backup(message.bot, message.from_user.id, message)


@router.callback_query(F.data == "admin_backup")
async def admin_backup_callback(call: CallbackQuery):
    """Инлайн-кнопка с тем же callback (если используется в другой сборке)."""
    admin_id = call.from_user.id
    if not await user_in_admin_context(admin_id):
        await call.answer("⛔ Только для администраторов", show_alert=True)
        return
    await call.answer("⏳ Создаю бэкап...")
    await _admin_send_sqlite_backup(call.bot, admin_id, call.message, announce_progress=False)


@router.message(Command("stats"))
async def admin_stats(message: Message):
    user_id = message.from_user.id
    if not await user_in_admin_context(user_id):
        await safe_send_message(user_id, "⛔ Доступ запрещен. Используйте /admin или /start.")
        return
    await _reply_admin_stats(user_id)


@router.message(F.text == "📊 Статистика")
async def admin_stats_button(message: Message):
    user_id = message.from_user.id
    if not await user_in_admin_context(user_id):
        return
    await _reply_admin_stats(user_id)


@router.message(Command("ban"))
async def ban_user(message: Message):
    user_id = message.from_user.id
    if not await user_in_admin_context(user_id):
        return

    args = message.text.split()
    if len(args) < 2:
        await safe_send_message(user_id, "⚠️ /ban <user_id> [причина]")
        return
    
    target_id = _parse_int(args[1])
    if target_id is None:
        await safe_send_message(user_id, "⚠️ user_id должен быть числом")
        return
    reason = " ".join(args[2:]) if len(args) > 2 else None
    
    db = await get_db()
    await db.execute('INSERT OR REPLACE INTO blacklist (user_id, reason, blocked_by) VALUES (?, ?, ?)', (target_id, reason, user_id))
    await db.commit()
    
    await safe_send_message(user_id, f"🚫 Пользователь {target_id} заблокирован")
    await safe_send_message(target_id, f"⛔ Вы заблокированы. Причина: {reason or 'не указана'}")


@router.message(Command("unban"))
async def unban_user(message: Message):
    user_id = message.from_user.id
    if not await user_in_admin_context(user_id):
        return

    args = message.text.split()
    if len(args) != 2:
        await safe_send_message(user_id, "⚠️ /unban <user_id>")
        return
    
    target_id = _parse_int(args[1])
    if target_id is None:
        await safe_send_message(user_id, "⚠️ user_id должен быть числом")
        return
    
    db = await get_db()
    await db.execute('DELETE FROM blacklist WHERE user_id = ?', (target_id,))
    await db.commit()
    
    await safe_send_message(user_id, f"✅ Пользователь {target_id} разблокирован")
    await safe_send_message(target_id, "✅ Вы разблокированы")


@router.message(Command("health"))
async def health_check(message: Message):
    user_id = message.from_user.id
    if not await user_in_admin_context(user_id):
        await safe_send_message(user_id, "⛔ Только для админов. /admin")
        return
    await _reply_admin_health(user_id)


@router.message(F.text == "🩺 Здоровье")
async def admin_health_button(message: Message):
    user_id = message.from_user.id
    if not await user_in_admin_context(user_id):
        return
    await _reply_admin_health(user_id)


@router.message(Command("user"))
async def get_user(message: Message):
    user_id = message.from_user.id
    if not await user_in_admin_context(user_id):
        return

    args = message.text.split()
    if len(args) != 2:
        await safe_send_message(user_id, "⚠️ /user <user_id> или /user @username")
        return
    
    identifier = args[1]
    db = await get_db()
    
    if identifier.startswith("@"):
        cursor = await db.execute('SELECT * FROM users WHERE username = ?', (identifier[1:],))
    else:
        numeric_id = _parse_int(identifier)
        if numeric_id is None:
            await safe_send_message(user_id, "⚠️ user_id должен быть числом или @username")
            return
        cursor = await db.execute('SELECT * FROM users WHERE user_id = ?', (numeric_id,))
    
    user = await cursor.fetchone()
    
    if not user:
        await safe_send_message(user_id, f"❌ Пользователь {identifier} не найден.")
        return
    
    text = f"📋 <b>Информация о пользователе</b>\n\n"
    text += f"🆔 ID: {user[0]}\n"
    text += f"👤 Username: @{user[1] or 'нет'}\n"
    text += f"📛 Имя: {user[2] or 'нет'} {user[3] or ''}\n"
    text += f"📅 Первое появление: {user[5]}\n"
    text += f"📅 Последнее: {user[6]}"
    
    await safe_send_message(user_id, text, parse_mode="HTML")


@router.message(Command("resetuser"))
async def reset_user(message: Message):
    user_id = message.from_user.id
    if not await user_in_admin_context(user_id):
        return

    args = message.text.split()
    if len(args) != 2:
        await safe_send_message(user_id, "⚠️ /resetuser <user_id>")
        return
    
    target_id = _parse_int(args[1])
    if target_id is None:
        await safe_send_message(user_id, "⚠️ user_id должен быть числом")
        return
    await reset_user_state(target_id)
    await safe_send_message(user_id, f"✅ Состояние пользователя {target_id} сброшено")


@router.message(Command("resetall"))
async def reset_all(message: Message):
    user_id = message.from_user.id
    if not await user_in_admin_context(user_id):
        return

    await reset_all_states()
    await safe_send_message(user_id, "✅ Все состояния сброшены")


@router.message(F.text == "🔄 Сброс состояний")
async def reset_all_button(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if not await user_in_admin_context(user_id):
        return
    await state.set_state(AdminState.waiting_resetall_confirm)
    await safe_send_message(
        user_id,
        "⚠️ Будут сброшены все состояния бота (Redis + активные консультации в БД).\n\n"
        "Для подтверждения отправьте слово <b>ДА</b> заглавными.\n"
        "/cancel — отмена.",
        parse_mode="HTML",
    )


@router.message(AdminState.waiting_resetall_confirm, F.text)
async def reset_all_confirm(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if not await user_in_admin_context(user_id):
        return
    if (message.text or "").strip() != "ДА":
        await safe_send_message(user_id, "Отправьте ровно «ДА» или /cancel")
        return
    await state.clear()
    await reset_all_states()
    await safe_send_message(user_id, "✅ Все состояния сброшены")


@router.message(
    Command("cancel"),
    StateFilter(*_ADMIN_INTERRUPTIBLE_STATES),
)
async def admin_reply_keyboard_flow_cancel(message: Message, state: FSMContext):
    """/cancel должен обрабатываться раньше шагов «введите ID», иначе /cancel парсится как невалидный ID."""
    if not await user_in_admin_context(message.from_user.id):
        return
    await state.clear()
    await safe_send_message(message.from_user.id, "❌ Действие отменено.")


@router.message(StateFilter(*_ADMIN_INTERRUPTIBLE_STATES), F.text)
async def admin_fsm_yield_menu_and_commands(message: Message, state: FSMContext):
    """
    Во время мастера: команды (/stats, /admin, …) и кнопки панели сбрасывают FSM и передают апдейт дальше.
    Иначе текст «📊 Статистика» попадает в «ожидаем числовой ID».
    """
    if not await user_in_admin_context(message.from_user.id):
        raise SkipHandler()
    text = (message.text or "").strip()
    if text.startswith("/"):
        cmd = text.split()[0].split("@")[0].lower()
        if cmd == "/cancel":
            raise SkipHandler()
        await state.clear()
        raise SkipHandler()
    if text in _ADMIN_MAIN_KEYBOARD_TEXTS:
        await state.clear()
        raise SkipHandler()
    raise SkipHandler()


@router.message(F.text == "🚫 Заблокировать")
async def ban_button(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if not await user_in_admin_context(user_id):
        return
    await state.set_state(AdminState.waiting_ban_user_id)
    await safe_send_message(
        user_id,
        "Введите <b>Telegram ID</b> пользователя для блокировки (целое число).\n"
        "/cancel — отмена.",
        parse_mode="HTML",
    )


@router.message(AdminState.waiting_ban_user_id, F.text)
async def ban_receive_user_id(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if not await user_in_admin_context(user_id):
        return
    raw = (message.text or "").strip()
    if raw.startswith("/"):
        await state.clear()
        raise SkipHandler()
    target_id = _parse_int(raw)
    if target_id is None:
        await safe_send_message(user_id, "⚠️ Нужен числовой ID. Попробуйте снова или /cancel")
        return
    await state.update_data(ban_target_id=target_id)
    await state.set_state(AdminState.waiting_ban_reason)
    await safe_send_message(
        user_id,
        "Введите <b>причину</b> блокировки.\n"
        "Или отправьте <code>-</code> если без причины.\n/cancel — отмена.",
        parse_mode="HTML",
    )


@router.message(AdminState.waiting_ban_reason, F.text)
async def ban_receive_reason(message: Message, state: FSMContext):
    admin_id = message.from_user.id
    if not await user_in_admin_context(admin_id):
        return
    data = await state.get_data()
    target_id = data.get("ban_target_id")
    if target_id is None:
        await state.clear()
        await safe_send_message(admin_id, "Сессия сброшена. Начните с кнопки снова.")
        return
    reason_raw = (message.text or "").strip()
    reason = None if reason_raw == "-" else reason_raw
    db = await get_db()
    await db.execute(
        "INSERT OR REPLACE INTO blacklist (user_id, reason, blocked_by) VALUES (?, ?, ?)",
        (target_id, reason, admin_id),
    )
    await db.commit()
    await state.clear()
    await safe_send_message(admin_id, f"🚫 Пользователь {target_id} заблокирован")
    try:
        await safe_send_message(
            int(target_id),
            f"⛔ Вы заблокированы. Причина: {reason or 'не указана'}",
        )
    except Exception:
        pass


@router.message(F.text == "✅ Разблокировать")
async def unban_button(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if not await user_in_admin_context(user_id):
        return
    await state.set_state(AdminState.waiting_unban_user_id)
    await safe_send_message(
        user_id,
        "Введите <b>Telegram ID</b> пользователя для разблокировки.\n/cancel — отмена.",
        parse_mode="HTML",
    )


@router.message(AdminState.waiting_unban_user_id, F.text)
async def unban_receive_user_id(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if not await user_in_admin_context(user_id):
        return
    raw = (message.text or "").strip()
    if raw.startswith("/"):
        await state.clear()
        raise SkipHandler()
    target_id = _parse_int(raw)
    if target_id is None:
        await safe_send_message(user_id, "⚠️ Нужен числовой ID.")
        return
    db = await get_db()
    await db.execute("DELETE FROM blacklist WHERE user_id = ?", (target_id,))
    await db.commit()
    await state.clear()
    await safe_send_message(user_id, f"✅ Пользователь {target_id} разблокирован")
    try:
        await safe_send_message(target_id, "✅ Вы разблокированы")
    except Exception:
        pass


@router.message(F.text == "➖ Удалить врача")
async def remove_doctor_button(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if not await user_in_admin_context(user_id):
        return
    await state.set_state(AdminState.waiting_remove_doctor_id)
    await safe_send_message(
        user_id,
        "Введите <b>Telegram ID</b> врача для удаления из системы.\n/cancel — отмена.",
        parse_mode="HTML",
    )


@router.message(AdminState.waiting_remove_doctor_id, F.text)
async def remove_doctor_receive_id(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if not await user_in_admin_context(user_id):
        return
    raw = (message.text or "").strip()
    if raw.startswith("/"):
        await state.clear()
        raise SkipHandler()
    tid = _parse_int(raw)
    if tid is None:
        await safe_send_message(user_id, "⚠️ Нужен числовой telegram_id врача.")
        return
    await remove_doctor(tid)
    await state.clear()
    await safe_send_message(user_id, f"✅ Врач {tid} удалён из системы")


@router.message(Command("closestuck"))
async def close_stuck(message: Message):
    user_id = message.from_user.id
    if not await user_in_admin_context(user_id):
        return

    await close_stuck_requests()
    await safe_send_message(user_id, "✅ Зависшие запросы закрыты")


@router.message(Command("unlockdoctors"))
async def unlock_doctors(message: Message):
    user_id = message.from_user.id
    if not await user_in_admin_context(user_id):
        return

    await unlock_all_doctors()
    await safe_send_message(user_id, "✅ Все врачи разблокированы")


@router.message(Command("adddoctor"))
async def add_doctor_command(message: Message):
    user_id = message.from_user.id
    if not await user_in_admin_context(user_id):
        return

    args = message.text.split()
    if len(args) < 4:
        await safe_send_message(
            user_id,
            "⚠️ /adddoctor &lt;telegram_id&gt; &lt;имя&gt; &lt;spec&gt;[,spec2,...]\n"
            "Пример: <code>/adddoctor 123456789 Иванов терапевт,кардиолог</code>",
            parse_mode="HTML",
        )
        return

    telegram_id = _parse_int(args[1])
    if telegram_id is None:
        await safe_send_message(user_id, "⚠️ telegram_id должен быть числом")
        return
    name = args[2]
    specs = [s.strip() for s in args[3].split(",") if s.strip()]

    valid = ", ".join(SPECIALIZATION_KEYS)
    bad = [s for s in specs if s not in SPECIALIZATION_KEYS]
    if bad or not specs:
        await safe_send_message(
            user_id,
            f"❌ Неверная специализация. Доступны:\n<code>{valid}</code>",
            parse_mode="HTML",
        )
        return

    await add_doctor(telegram_id, name, specs)
    spec_line = specializations_slash_plain(specs)
    await safe_send_message(
        user_id,
        f"✅ Врач <b>{escape(name)}</b> ({escape(spec_line)}) добавлен!",
        parse_mode="HTML",
    )
    await safe_send_message(
        telegram_id,
        "👨‍⚕️ Вы добавлены в систему как врач!\nИспользуйте /start для панели управления.",
    )


@router.message(F.text == "➕ Добавить врача")
async def add_doctor_wizard_start(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if not await user_in_admin_context(user_id):
        return
    await state.set_state(AdminState.add_doctor_telegram)
    await safe_send_message(
        user_id,
        "📝 <b>Введите Telegram ID врача:</b>\n\n"
        "Целое число ( можно узнать у врача или через @userinfobot )",
        parse_mode="HTML",
    )


@router.message(AdminState.add_doctor_telegram)
async def add_doctor_wizard_id(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if not await user_in_admin_context(user_id):
        return
    raw = (message.text or "").strip()
    if raw.startswith("/"):
        await state.clear()
        raise SkipHandler()
    if not raw.lstrip("-").isdigit():
        await safe_send_message(user_id, "⚠️ Отправьте только числовой Telegram ID или /cancel")
        return
    tid = int(raw)
    if tid <= 0:
        await safe_send_message(user_id, "⚠️ Некорректный ID")
        return
    await state.update_data(new_doctor_tid=tid)
    await state.set_state(AdminState.add_doctor_name)
    await safe_send_message(
        user_id,
        "📝 <b>Введите имя и фамилию врача:</b>\n\n"
        "Пример: <code>Иванов Иван</code>",
        parse_mode="HTML",
    )


@router.message(AdminState.add_doctor_name)
async def add_doctor_wizard_name(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if not await user_in_admin_context(user_id):
        return
    name = (message.text or "").strip()
    if len(name) < 3:
        await safe_send_message(user_id, "⚠️ Введите не короче 3 символов или /cancel")
        return
    await state.update_data(new_doctor_name=name, add_spec_keys=[])
    await state.set_state(AdminState.add_doctor_pick_spec)
    await message.answer(
        "🏥 <b>Выберите специализации врача</b> (можно несколько), затем «Готово»:",
        reply_markup=get_doctor_multi_spec_keyboard(
            set(),
            "admnspecaddtog",
            "admnspecadddone",
            "admnspecaddcancel",
        ),
        parse_mode="HTML",
    )


@router.callback_query(StateFilter(AdminState.add_doctor_pick_spec), F.data.startswith("admnspecaddtog:"))
async def add_doctor_specs_toggle(call: CallbackQuery, state: FSMContext):
    if not await user_in_admin_context(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    key = call.data.split(":", 1)[1]
    if key not in SPECIALISTS:
        await call.answer()
        return
    data = await state.get_data()
    sel = set(data.get("add_spec_keys") or [])
    if key in sel:
        sel.remove(key)
    else:
        sel.add(key)
    await state.update_data(add_spec_keys=list(sel))
    try:
        await call.message.edit_reply_markup(
            reply_markup=get_doctor_multi_spec_keyboard(
                sel,
                "admnspecaddtog",
                "admnspecadddone",
                "admnspecaddcancel",
            ),
        )
    except Exception:
        pass
    await call.answer()


@router.callback_query(StateFilter(AdminState.add_doctor_pick_spec), F.data == "admnspecadddone")
async def add_doctor_specs_done(call: CallbackQuery, state: FSMContext):
    admin_id = call.from_user.id
    if not await user_in_admin_context(admin_id):
        await call.answer("⛔", show_alert=True)
        return
    data = await state.get_data()
    tid = data.get("new_doctor_tid")
    name = data.get("new_doctor_name")
    keys = ordered_spec_keys(list(data.get("add_spec_keys") or []))
    if not tid or not name:
        await state.clear()
        await call.answer("Сессия сброшена", show_alert=True)
        return
    if not keys:
        await call.answer("Выберите хотя бы одну специализацию", show_alert=True)
        return
    await add_doctor(tid, name, keys)
    await state.clear()
    spec_line = specializations_slash_plain(keys)
    try:
        await call.message.edit_text(
            f"✅ Врач <b>{escape(name)}</b> ({escape(spec_line)}) добавлен!",
            parse_mode="HTML",
        )
    except Exception:
        await safe_send_message(
            admin_id,
            f"✅ Врач <b>{escape(name)}</b> ({escape(spec_line)}) добавлен!",
            parse_mode="HTML",
        )
    await call.answer()
    await safe_send_message(
        tid,
        "👨‍⚕️ Вы добавлены в систему как врач!\nИспользуйте /start для панели управления.",
    )


@router.callback_query(StateFilter(AdminState.add_doctor_pick_spec), F.data == "admnspecaddcancel")
async def add_doctor_wizard_cancel_cb(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.answer("Отменено")
    try:
        await call.message.edit_text("❌ Добавление врача отменено.")
    except Exception:
        pass


@router.message(AdminState.add_doctor_pick_spec)
async def add_doctor_wizard_remind_inline(message: Message):
    if not await user_in_admin_context(message.from_user.id):
        return
    await safe_send_message(
        message.from_user.id,
        "Выберите специализации кнопками выше или отправьте /cancel.",
    )


@router.message(F.text == "✏️ Изменить врача")
async def edit_doctor_wizard_start(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if not await user_in_admin_context(user_id):
        return
    await state.set_state(AdminState.edit_doctor_telegram)
    await safe_send_message(
        user_id,
        "✏️ <b>Редактирование врача</b>\n\nВведите Telegram ID врача:",
        parse_mode="HTML",
    )


@router.message(AdminState.edit_doctor_telegram, F.text)
async def edit_doctor_wizard_tid(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if not await user_in_admin_context(user_id):
        return
    raw = (message.text or "").strip()
    if raw.startswith("/"):
        await state.clear()
        raise SkipHandler()
    if not raw.lstrip("-").isdigit():
        await safe_send_message(user_id, "⚠️ Отправьте числовой Telegram ID или /cancel")
        return
    tid = int(raw)
    row = await get_doctor_admin_row(tid)
    if not row:
        await safe_send_message(user_id, "❌ Врач с таким ID не найден в базе.")
        return
    name, is_act = row
    keys = await get_doctor_spec_keys(tid)
    await state.update_data(
        edit_tid=tid,
        edit_original_name=name,
        edit_was_active=is_act,
        edit_spec_keys=list(keys),
    )
    await state.set_state(AdminState.edit_doctor_name)
    await safe_send_message(
        user_id,
        f"Текущее ФИО: <b>{escape(name)}</b>\n\n"
        "Введите новое ФИО или отправьте «—», чтобы оставить без изменений.",
        parse_mode="HTML",
    )


@router.message(AdminState.edit_doctor_name, F.text)
async def edit_doctor_wizard_name(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if not await user_in_admin_context(user_id):
        return
    raw = (message.text or "").strip()
    if raw in ("—", "-", "–"):
        await state.update_data(edit_keep_name=True, edit_new_name=None)
    else:
        if len(raw) < 3:
            await safe_send_message(user_id, "⚠️ Не короче 3 символов или отправьте «—»")
            return
        await state.update_data(edit_keep_name=False, edit_new_name=raw)
    data = await state.get_data()
    sel = set(data.get("edit_spec_keys") or [])
    await state.set_state(AdminState.edit_doctor_specs)
    await message.answer(
        "Отметьте специализации (можно несколько), затем «Готово»:",
        reply_markup=get_doctor_multi_spec_keyboard(
            sel,
            "admnspecedittog",
            "admnspeceditdone",
            "admnspeceditcancel",
        ),
        parse_mode="HTML",
    )


@router.callback_query(StateFilter(AdminState.edit_doctor_specs), F.data.startswith("admnspecedittog:"))
async def edit_doctor_specs_toggle(call: CallbackQuery, state: FSMContext):
    if not await user_in_admin_context(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    key = call.data.split(":", 1)[1]
    if key not in SPECIALISTS:
        await call.answer()
        return
    data = await state.get_data()
    sel = set(data.get("edit_spec_keys") or [])
    if key in sel:
        sel.remove(key)
    else:
        sel.add(key)
    await state.update_data(edit_spec_keys=list(sel))
    try:
        await call.message.edit_reply_markup(
            reply_markup=get_doctor_multi_spec_keyboard(
                sel,
                "admnspecedittog",
                "admnspeceditdone",
                "admnspeceditcancel",
            ),
        )
    except Exception:
        pass
    await call.answer()


@router.callback_query(StateFilter(AdminState.edit_doctor_specs), F.data == "admnspeceditdone")
async def edit_doctor_specs_done(call: CallbackQuery, state: FSMContext):
    if not await user_in_admin_context(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    data = await state.get_data()
    keys = ordered_spec_keys(list(data.get("edit_spec_keys") or []))
    if not keys:
        await call.answer("Нужна хотя бы одна специализация", show_alert=True)
        return
    await state.update_data(edit_spec_keys=list(keys))
    was = bool(data.get("edit_was_active"))
    await state.set_state(AdminState.edit_doctor_active)
    try:
        await call.message.edit_text(
            "Выберите статус врача в системе:\n\n"
            f"Сейчас: {'🟢 активен' if was else '🔴 не активен'}",
            reply_markup=get_edit_doctor_active_keyboard(),
        )
    except Exception:
        await call.message.answer(
            "Выберите статус врача в системе:\n\n"
            f"Сейчас: {'🟢 активен' if was else '🔴 не активен'}",
            reply_markup=get_edit_doctor_active_keyboard(),
        )
    await call.answer()


@router.callback_query(StateFilter(AdminState.edit_doctor_specs), F.data == "admnspeceditcancel")
async def edit_doctor_specs_cancel(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.answer("Отменено")
    try:
        await call.message.edit_text("❌ Редактирование отменено.")
    except Exception:
        pass


@router.callback_query(StateFilter(AdminState.edit_doctor_active), F.data.startswith("admndoeditact:"))
async def edit_doctor_apply(call: CallbackQuery, state: FSMContext):
    admin_id = call.from_user.id
    if not await user_in_admin_context(admin_id):
        await call.answer("⛔", show_alert=True)
        return
    data = await state.get_data()
    tid = data.get("edit_tid")
    specs = ordered_spec_keys(list(data.get("edit_spec_keys") or []))
    if not tid or not specs:
        await state.clear()
        await call.answer("Сессия устарела", show_alert=True)
        return
    is_active = call.data.endswith(":1")
    kwargs: dict = {"specializations": specs, "is_active": is_active}
    if not data.get("edit_keep_name"):
        nn = data.get("edit_new_name")
        if nn:
            kwargs["name"] = nn
    try:
        await update_doctor(tid, **kwargs)
    except ValueError as e:
        await call.answer(str(e), show_alert=True)
        return
    await state.clear()
    spec_line = specializations_slash_plain(specs)
    try:
        await call.message.edit_text(
            f"✅ Врач <code>{tid}</code> обновлён: <b>{escape(spec_line)}</b>, "
            f"{'активен' if is_active else 'не активен'}.",
            parse_mode="HTML",
        )
    except Exception:
        await safe_send_message(
            admin_id,
            f"✅ Врач {tid} обновлён: {spec_line}, {'активен' if is_active else 'не активен'}.",
        )
    await call.answer()


@router.message(AdminState.edit_doctor_active)
async def edit_doctor_active_remind(message: Message):
    if not await user_in_admin_context(message.from_user.id):
        return
    await safe_send_message(
        message.from_user.id,
        "Нажмите «Активен» или «Не активен» на кнопках выше, либо /cancel.",
    )


@router.message(AdminState.edit_doctor_specs)
async def edit_doctor_specs_remind(message: Message):
    if not await user_in_admin_context(message.from_user.id):
        return
    await safe_send_message(
        message.from_user.id,
        "Используйте инлайн-кнопки выше или /cancel.",
    )


@router.message(Command("removedoctor"))
async def remove_doctor_command(message: Message):
    user_id = message.from_user.id
    if not await user_in_admin_context(user_id):
        return

    args = message.text.split()
    if len(args) != 2:
        await safe_send_message(user_id, "⚠️ /removedoctor <telegram_id>")
        return
    
    telegram_id = _parse_int(args[1])
    if telegram_id is None:
        await safe_send_message(user_id, "⚠️ telegram_id должен быть числом")
        return
    await remove_doctor(telegram_id)
    await safe_send_message(user_id, f"✅ Врач {telegram_id} удалён из системы")


@router.message(Command("feedback"))
async def feedback_command(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if not await user_in_client_context(user_id):
        await safe_send_message(user_id, "⛔ Эта команда только в клиентском режиме (/client).")
        return
    
    await state.set_state(WaitingState.waiting_for_feedback)
    await safe_send_message(
        user_id,
        "📝 <b>Форма обратной связи</b>\n\n"
        "Напишите ваше сообщение (жалоба, предложение, отзыв о работе бота).\n\n"
        "Чтобы отменить, отправьте /cancel.",
        parse_mode="HTML"
    )


@router.message(WaitingState.waiting_for_feedback)
async def process_feedback(message: Message, state: FSMContext):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    
    db = await get_db()
    await db.execute('''
        INSERT INTO feedback (user_id, username, feedback)
        VALUES (?, ?, ?)
    ''', (user_id, username, message.text))
    await db.commit()
    
    for admin_id in ADMIN_IDS:
        await safe_send_message(
            admin_id,
            f"📬 <b>НОВАЯ ОБРАТНАЯ СВЯЗЬ</b>\n\n"
            f"👤 От: @{username} (ID: {user_id})\n"
            f"📝 Текст:\n<pre>{escape(message.text or '')}</pre>",
            parse_mode="HTML"
        )
    
    await safe_send_message(user_id, "✅ Спасибо за обратную связь!")
    await state.clear()


def _support_time_label(created_at: str | None) -> str:
    if not created_at:
        return "??:??"
    parts = str(created_at).strip().split()
    if len(parts) >= 2:
        return ":".join(parts[1].split(":")[:2])
    return (created_at or "")[:5]


@router.message(F.text == "📬 Обращения")
async def admin_support_queue(message: Message):
    """Список открытых обращений (доступно любому ID из ADMIN_IDS, не только в режиме /admin)."""
    user_id = message.from_user.id
    if not await is_admin(user_id):
        return

    items = await list_open_requests()
    if not items:
        await safe_send_message(user_id, "📭 Нет открытых обращений в поддержку.")
        return

    shown = items[:25]
    short = [(row[0], row[1], row[2]) for row in shown]
    kb = get_support_queue_keyboard(short)
    lines: list[str] = []
    for i, row in enumerate(shown, start=1):
        rid, uid, uname, _msg, created_at = row
        label_user = f"@{uname}" if uname else f"id {uid}"
        tm = _support_time_label(created_at)
        lines.append(f"{i}. №{rid} - {label_user} ({tm})")

    text = (
        f"📋 <b>Активные обращения ({len(items)}):</b>\n\n"
        + "\n".join(lines)
        + "\n\nВыберите обращение:"
    )
    if len(items) > 25:
        text += f"\n\n… и ещё {len(items) - 25}"
    await safe_send_message(user_id, text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(lambda c: c.data.startswith("support_reply:"))
async def reply_to_support(call: CallbackQuery, state: FSMContext):
    admin_id = call.from_user.id
    if not await is_admin(admin_id):
        await call.answer("⛔ Только администраторы")
        return

    parts = call.data.split(":")
    user_id = _parse_int(parts[1])
    request_id = _parse_int(parts[2])
    if user_id is None or request_id is None:
        await call.answer("❌ Некорректные параметры")
        return

    if not await get_open_request(request_id):
        await call.answer("Это обращение уже закрыто", show_alert=True)
        return

    await state.update_data(reply_to_user=user_id, reply_request_id=request_id)
    await state.set_state(WaitingState.waiting_for_support_reply)
    await safe_send_message(
        admin_id,
        f"✏️ Режим ответа: обращение №{request_id}, пользователь id {user_id}.\n"
        f"Напишите сообщение (можно несколько). Закрыть обращение — кнопка «✅ Закрыть» в уведомлении.\n"
        f"Выйти из режима ответа без закрытия: /cancel",
    )
    await call.answer()


@router.message(Command("cancel"), WaitingState.waiting_for_support_reply)
async def cancel_support_reply_mode(message: Message, state: FSMContext):
    admin_id = message.from_user.id
    if not await is_admin(admin_id):
        return
    await state.clear()
    await safe_send_message(admin_id, "✅ Режим ответа отменён (обращение остаётся открытым).")


@router.callback_query(lambda c: c.data.startswith("support_close:"))
async def support_close_ticket(call: CallbackQuery, state: FSMContext):
    admin_id = call.from_user.id
    if not await is_admin(admin_id):
        await call.answer("⛔")
        return

    parts = call.data.split(":")
    user_id = _parse_int(parts[1])
    request_id = _parse_int(parts[2])
    if user_id is None or request_id is None:
        await call.answer("❌ Некорректные параметры")
        return

    row = await get_open_request(request_id)
    if not row or int(row[1]) != user_id:
        await call.answer("Обращение уже закрыто или не найдено", show_alert=True)
        return

    ok = await close_support_request(request_id)
    if not ok:
        await call.answer("Не удалось закрыть", show_alert=True)
        return

    await safe_send_message(
        user_id,
        f"✅ Обращение №{request_id} закрыто администратором.\n"
        f"Если снова понадобится помощь — «🆘 Помощь» → «📝 Написать администратору».",
    )
    await safe_send_message(admin_id, f"✅ Обращение №{request_id} закрыто.")

    data = await state.get_data()
    if data.get("reply_request_id") == request_id:
        await state.clear()

    await call.answer()


@router.callback_query(lambda c: c.data.startswith("support_tpl:"))
async def support_send_template(call: CallbackQuery, state: FSMContext):
    """Отправить клиенту шаблонный текст из настроек (config SUPPORT_TEMPLATE_TEXT)."""
    admin_id = call.from_user.id
    if not await is_admin(admin_id):
        await call.answer("⛔")
        return

    parts = call.data.split(":")
    user_id = _parse_int(parts[1])
    request_id = _parse_int(parts[2])
    if user_id is None or request_id is None:
        await call.answer("❌ Некорректные параметры")
        return

    row = await get_open_request(request_id)
    if not row or int(row[1]) != user_id:
        await call.answer("Обращение уже закрыто или не найдено", show_alert=True)
        return

    template = SUPPORT_TEMPLATE_TEXT.strip()
    await add_support_message(request_id, "admin", admin_id, template)
    await safe_send_message(
        user_id,
        f"📬 <b>Сообщение администрации</b> (обращение №{request_id})\n\n{escape(template)}",
        parse_mode="HTML",
    )
    await safe_send_message(admin_id, f"✅ Шаблон отправлен клиенту (№{request_id}).")
    await call.answer()


@router.message(WaitingState.waiting_for_support_reply, F.text)
async def send_support_reply(message: Message, state: FSMContext):
    admin_id = message.from_user.id
    if not await is_admin(admin_id):
        return
    if message.text and message.text.strip().startswith("/"):
        return

    data = await state.get_data()
    user_id = data.get("reply_to_user")
    request_id = data.get("reply_request_id")

    if not user_id or not request_id:
        await safe_send_message(admin_id, "❌ Не выбрано обращение. Откройте «📬 Обращения» или нажмите «📝 Ответить».")
        await state.clear()
        return

    if not await get_open_request(request_id):
        await safe_send_message(admin_id, "❌ Это обращение уже закрыто.")
        await state.clear()
        return

    body = message.text or ""
    await add_support_message(request_id, "admin", admin_id, body)
    await safe_send_message(
        user_id,
        f"📬 <b>Ответ администрации</b> (обращение №{request_id})\n\n{escape(body)}",
        parse_mode="HTML",
    )
    await safe_send_message(
        admin_id,
        f"✅ Сообщение доставлено (№{request_id}). Можно отправить ещё или закрыть обращение кнопкой «✅ Закрыть».",
    )