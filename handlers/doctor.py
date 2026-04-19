import redis
from html import escape
from config import REDIS_URL

r = redis.from_url(REDIS_URL, decode_responses=True)

from aiogram import Router, F
from aiogram.filters import Command, BaseFilter
from aiogram.enums import MessageEntityType
from aiogram.types import Message, CallbackQuery, ReplyKeyboardRemove
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from config import SPECIALISTS
from services.validators import (
    user_in_doctor_context,
    get_doctor_status,
    get_current_client,
    set_doctor_status,
    set_current_client,
    update_doctor_activity,
    clear_session,
    set_client_consultation,
    append_consultation_chat_line,
    clear_consultation_chat,
    get_client_consultation_id,
    get_consultation_chat_text,
)
from database.queue import (
    pop_from_queue,
    get_queue_length,
    confirm_queue_processed,
    remove_from_queue,
    return_queue_item_to_tail,
)
from database.consultations import (
    update_consultation_doctor,
    save_consultation_end,
    get_consultation_doctor_and_topic,
    ensure_doctor_assigned_for_consultation,
)
from database.payments import confirm_payment, get_pending_payment
from database.doctors import (
    get_doctor_name,
    get_doctor_specialization,
    get_all_doctors,
    specialization_display_label,
)
from utils.helpers import safe_send_message, safe_send_photo, split_text_chunks
from keyboards.doctor import (
    get_doctor_main_keyboard,
    get_doctor_status_keyboard,
    get_doctor_actions_keyboard,
    get_end_confirmation_keyboard,
    get_redirect_doctors_keyboard,
    get_redirect_confirm_keyboard,
    DOCTORS_PAGE_SIZE,
)
from states.forms import QuestionnaireState

router = Router()


async def _end_active_consultation(doctor_id: int, client_id: int) -> None:
    """Завершение консультации врачом (рейтинг, очистка Redis)."""
    from database.db import get_db
    from keyboards.client import get_rating_keyboard

    db = await get_db()
    cursor = await db.execute(
        "SELECT id FROM consultations WHERE client_id = ? AND status = 'active'",
        (client_id,),
    )
    row = await cursor.fetchone()
    if row:
        consultation_id = row[0]
        await save_consultation_end(consultation_id, "ended_by_doctor")
        clear_consultation_chat(consultation_id)
        await safe_send_message(
            int(client_id),
            "Пожалуйста, оцените консультацию:",
            reply_markup=get_rating_keyboard(consultation_id, doctor_id),
        )
    set_current_client(doctor_id, None)
    clear_session(int(client_id), doctor_id)
    await safe_send_message(int(client_id), "🔚 Врач завершил консультацию.")
    await safe_send_message(doctor_id, "✅ Консультация завершена")


async def _run_confirm_payment_flow(doctor_id: int, client_id: int, state: FSMContext, bot_id: int) -> bool:
    """Подтверждение оплаты и запуск анкеты у клиента."""
    payment = await get_pending_payment(client_id)
    if not payment:
        await safe_send_message(doctor_id, "❌ Платёж не найден или уже подтверждён")
        return False
    _pid, consultation_id = payment
    if not await confirm_payment(client_id, consultation_id):
        await safe_send_message(doctor_id, "❌ Ошибка подтверждения")
        await safe_send_message(client_id, "❌ Ошибка подтверждения оплаты")
        return False
    await ensure_doctor_assigned_for_consultation(consultation_id)
    await safe_send_message(
        doctor_id,
        f"✅ Оплата клиента #{client_id} подтверждена!\n\n"
        "Клиент заполняет анкету о питомце. После заполнения вы получите уведомление "
        "с кнопкой «▶️ Начать консультацию».",
    )
    client_state = FSMContext(
        storage=state.storage,
        key=StorageKey(bot_id=bot_id, chat_id=client_id, user_id=client_id),
    )
    await client_state.update_data(consultation_id=consultation_id, problem_name="Консультация")
    await client_state.set_state(QuestionnaireState.waiting_pet_name)
    await safe_send_message(
        client_id,
        "✅ <b>Оплата подтверждена!</b>\n\n"
        "Пожалуйста, заполните информацию о питомце.\n\n"
        "🐾 Как зовут вашего питомца?\n\n"
        "<i>(Напишите имя: Барсик, Шарик, Рекс...)</i>",
        parse_mode="HTML",
    )
    return True


async def execute_take_client(
    doctor_id: int,
    client_id: int,
    consultation_id: int,
    queue_id: int | None = None,
) -> bool:
    """Назначить врача на оплаченную консультацию и связать чат."""
    from database.db import get_db

    db = await get_db()
    cur = await db.execute(
        "SELECT client_id, status FROM consultations WHERE id = ?",
        (consultation_id,),
    )
    row = await cur.fetchone()
    if not row or int(row[0]) != int(client_id) or row[1] != "paid":
        return False
    if queue_id is not None:
        await confirm_queue_processed(queue_id)
    await remove_from_queue("all", int(client_id))
    doctor_name = await get_doctor_name(doctor_id)
    raw_spec = await get_doctor_specialization(doctor_id)
    doctor_spec = raw_spec or "—"
    spec_display = specialization_display_label(raw_spec)
    await update_consultation_doctor(consultation_id, doctor_id, doctor_name, doctor_spec)
    set_current_client(doctor_id, client_id)
    r.set(f"client:{client_id}:doctor", str(doctor_id))
    set_client_consultation(int(client_id), consultation_id)
    await safe_send_message(
        int(client_id),
        (
            "✅ <b>Консультация начата!</b>\n\n"
            f"👨‍⚕️ <b>Ваш врач:</b> {escape(doctor_name)}\n"
            f"📂 <b>Специализация:</b> {escape(spec_display)}\n"
            f"🆔 <b>ID консультации:</b> #{consultation_id}\n\n"
            "💬 Напишите сообщение, чтобы задать вопрос врачу.\n"
            "📎 Вы можете отправлять фото, видео и документы.\n\n"
            "❌ Для завершения консультации используйте команду <b>/end</b>"
        ),
        parse_mode="HTML",
        reply_markup=ReplyKeyboardRemove(),
    )
    await safe_send_message(
        doctor_id,
        "✅ Консультация начата! Напишите сообщение клиенту.",
        reply_markup=get_doctor_actions_keyboard(int(client_id)),
    )
    update_doctor_activity(doctor_id)
    return True


def _not_a_bot_command(message: Message) -> bool:
    """Не перехватывать команды (/start и т.д.) — их обрабатывает client_router."""
    ents = message.entities or []
    if ents and ents[0].offset == 0 and ents[0].type == MessageEntityType.BOT_COMMAND:
        return False
    text = message.text or ""
    if text.lstrip().startswith("/"):
        return False
    return True


class DoctorToClientMediaFilter(BaseFilter):
    """Текст/фото от врача к клиенту (не команды)."""

    async def __call__(self, message: Message) -> bool:
        if not _not_a_bot_command(message):
            return False
        if not await user_in_doctor_context(message.from_user.id):
            return False
        return bool(message.text or message.photo)


@router.message(Command("online"))
async def go_online(message: Message):
    user_id = message.from_user.id
    if await user_in_doctor_context(user_id):
        set_doctor_status(user_id, "online")
        await safe_send_message(user_id, "🟢 Вы онлайн", reply_markup=get_doctor_main_keyboard())


@router.message(Command("offline"))
async def go_offline(message: Message):
    user_id = message.from_user.id
    if await user_in_doctor_context(user_id):
        set_doctor_status(user_id, "offline")
        await safe_send_message(user_id, "🔴 Вы офлайн", reply_markup=get_doctor_main_keyboard())


@router.message(Command("status"))
async def show_status(message: Message):
    user_id = message.from_user.id
    if not await user_in_doctor_context(user_id):
        return
    
    current = get_current_client(user_id)
    queue_len = await get_queue_length("all")
    
    text = f"📊 Статус: {get_doctor_status(user_id)}\n"
    text += f"👤 Текущий клиент: {current or 'нет'}\n📋 В очереди: {queue_len}"
    
    has_client = current is not None
    await safe_send_message(user_id, text, reply_markup=get_doctor_status_keyboard(has_client))


@router.message(Command("confirm_payment"))
async def confirm_payment_command(message: Message, state: FSMContext):
    """Врач подтверждает оплату клиента"""
    doctor_id = message.from_user.id
    if not await user_in_doctor_context(doctor_id):
        await safe_send_message(doctor_id, "⛔ Только для врачей")
        return
    
    args = message.text.split()
    if len(args) != 2:
        await safe_send_message(doctor_id, "⚠️ Использование: /confirm_payment <user_id>")
        return
    
    try:
        client_id = int(args[1])
    except ValueError:
        await safe_send_message(doctor_id, "⚠️ user_id должен быть числом")
        return
    
    await _run_confirm_payment_flow(doctor_id, client_id, state, message.bot.id)


@router.callback_query(lambda c: c.data and c.data.startswith("cfm_pay:"))
async def confirm_payment_callback(call: CallbackQuery, state: FSMContext):
    doctor_id = call.from_user.id
    if not await user_in_doctor_context(doctor_id):
        await call.answer("⛔ Только для врачей", show_alert=True)
        return
    try:
        client_id = int(call.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await call.answer("Некорректные данные", show_alert=True)
        return
    ok = await _run_confirm_payment_flow(doctor_id, client_id, state, call.bot.id)
    await call.answer("Готово" if ok else "Ошибка", show_alert=not ok)


async def run_next_from_queue(doctor_id: int) -> None:
    if get_current_client(doctor_id):
        await safe_send_message(doctor_id, "⚠️ У вас уже есть активный клиент. Завершите его сначала.")
        return

    from database.db import get_db

    db = await get_db()

    for _ in range(25):
        popped = await pop_from_queue("all")
        if not popped[0]:
            await safe_send_message(doctor_id, "📭 В очереди нет клиентов.")
            return
        client_id, anonymous_id, queue_id = popped
        cursor = await db.execute(
            """
            SELECT id, problem_key FROM consultations 
            WHERE client_id = ? AND status = "paid"
            ORDER BY id DESC LIMIT 1
            """,
            (client_id,),
        )
        row = await cursor.fetchone()
        if not row:
            await confirm_queue_processed(queue_id)
            continue
        consultation_id, _problem_key = row
        slot = await get_consultation_doctor_and_topic(consultation_id)
        if slot and slot[0] is not None and int(slot[0]) != doctor_id:
            await return_queue_item_to_tail("all", client_id, anonymous_id, queue_id)
            continue
        ok = await execute_take_client(doctor_id, client_id, consultation_id, queue_id)
        if not ok:
            await safe_send_message(
                doctor_id,
                "❌ Не удалось начать консультацию (статус консультации изменился).",
            )
        return

    await safe_send_message(
        doctor_id,
        "❌ В очереди нет заявок с оплаченной консультацией для вас. Попросите админа: /clearqueue",
    )


@router.message(Command("next"))
async def next_command(message: Message):
    user_id = message.from_user.id
    if not await user_in_doctor_context(user_id):
        return
    await run_next_from_queue(user_id)


@router.callback_query(lambda c: c.data == "doctor_next")
async def doctor_next_callback(call: CallbackQuery):
    doctor_id = call.from_user.id
    if not await user_in_doctor_context(doctor_id):
        await call.answer("⛔", show_alert=True)
        return
    await run_next_from_queue(doctor_id)
    await call.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("take_cn:"))
async def take_consultation_callback(call: CallbackQuery):
    doctor_id = call.from_user.id
    if not await user_in_doctor_context(doctor_id):
        await call.answer("⛔ Только для врачей", show_alert=True)
        return
    if get_current_client(doctor_id):
        await call.answer("Сначала завершите текущую консультацию (/end).", show_alert=True)
        return
    parts = call.data.split(":")
    if len(parts) != 3:
        await call.answer("Ошибка данных", show_alert=True)
        return
    try:
        client_id = int(parts[1])
        consultation_id = int(parts[2])
    except ValueError:
        await call.answer("Ошибка данных", show_alert=True)
        return
    row = await get_consultation_doctor_and_topic(consultation_id)
    if row and row[0] is not None and int(row[0]) != doctor_id:
        await call.answer("Этот клиент закреплён за другим врачом.", show_alert=True)
        return
    ok = await execute_take_client(doctor_id, client_id, consultation_id, None)
    await call.answer("Консультация началась" if ok else "Не удалось начать", show_alert=not ok)
    if ok:
        try:
            base = call.message.html_text or call.message.text or ""
            await call.message.edit_text(
                f"{base}\n\n🟢 Консультация активна",
                parse_mode="HTML",
            )
        except (TelegramBadRequest, Exception):
            try:
                await call.message.edit_text(
                    f"{call.message.text or ''}\n\n🟢 Консультация активна",
                )
            except Exception:
                try:
                    await call.message.edit_reply_markup(reply_markup=None)
                except Exception:
                    pass
                await safe_send_message(doctor_id, "🟢 Консультация активна")


def _button_caption(name: str, spec_key: str) -> str:
    label = f"{name} ({SPECIALISTS.get(spec_key, spec_key)})"
    return label if len(label) <= 64 else f"{name[:50]}…"


@router.callback_query(lambda c: c.data and c.data.startswith("endcf:"))
async def end_consultation_ask(call: CallbackQuery):
    doctor_id = call.from_user.id
    if not await user_in_doctor_context(doctor_id):
        await call.answer("⛔", show_alert=True)
        return
    try:
        client_id = int(call.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await call.answer("Ошибка", show_alert=True)
        return
    cur = get_current_client(doctor_id)
    if not cur or int(cur) != client_id:
        await call.answer("Нет такого активного клиента.", show_alert=True)
        return
    await call.message.answer(
        "Завершить консультацию с этим клиентом?",
        reply_markup=get_end_confirmation_keyboard(client_id),
    )
    await call.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("endgo:"))
async def end_consultation_do(call: CallbackQuery):
    doctor_id = call.from_user.id
    if not await user_in_doctor_context(doctor_id):
        await call.answer("⛔", show_alert=True)
        return
    try:
        client_id = int(call.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await call.answer("Ошибка", show_alert=True)
        return
    cur = get_current_client(doctor_id)
    if not cur or int(cur) != client_id:
        await call.answer("Клиент уже не активен.", show_alert=True)
        return
    await _end_active_consultation(doctor_id, client_id)
    await call.answer()
    try:
        await call.message.delete()
    except Exception:
        pass


@router.callback_query(lambda c: c.data == "endcancel")
async def end_consultation_cancel(call: CallbackQuery):
    await call.answer("Отменено")
    try:
        await call.message.delete()
    except Exception:
        pass


@router.callback_query(lambda c: c.data == "end_current")
async def end_current_from_status(call: CallbackQuery):
    doctor_id = call.from_user.id
    if not await user_in_doctor_context(doctor_id):
        await call.answer("⛔", show_alert=True)
        return
    cur = get_current_client(doctor_id)
    if not cur:
        await call.answer("Нет активного клиента", show_alert=True)
        return
    await call.message.answer(
        "Завершить консультацию с текущим клиентом?",
        reply_markup=get_end_confirmation_keyboard(int(cur)),
    )
    await call.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("reflist:"))
async def redirect_show_list(call: CallbackQuery):
    doctor_id = call.from_user.id
    if not await user_in_doctor_context(doctor_id):
        await call.answer("⛔", show_alert=True)
        return
    parts = call.data.split(":")
    if len(parts) != 3:
        await call.answer("Ошибка", show_alert=True)
        return
    try:
        client_id = int(parts[1])
        page = int(parts[2])
    except ValueError:
        await call.answer("Ошибка", show_alert=True)
        return
    cur = get_current_client(doctor_id)
    if not cur or int(cur) != client_id:
        await call.answer("Нет активного клиента с этим ID.", show_alert=True)
        return
    cid = get_client_consultation_id(client_id)
    if not cid:
        await call.answer("Не найдена консультация.", show_alert=True)
        return
    all_rows = [x for x in await get_all_doctors() if x[0] != doctor_id]
    if not all_rows:
        await call.answer("Нет других врачей в системе.", show_alert=True)
        return
    start = page * DOCTORS_PAGE_SIZE
    chunk = all_rows[start : start + DOCTORS_PAGE_SIZE]
    has_next = start + DOCTORS_PAGE_SIZE < len(all_rows)
    rows_btns = [(tid, _button_caption(name, spec)) for tid, name, spec in chunk]
    text = (
        "↪️ <b>Перенаправление клиента</b>\n\n"
        "Выберите специалиста из списка:"
    )
    await call.message.answer(
        text,
        parse_mode="HTML",
        reply_markup=get_redirect_doctors_keyboard(client_id, cid, rows_btns, page, has_next),
    )
    await call.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("refsel:"))
async def redirect_ask_confirm(call: CallbackQuery):
    doctor_id = call.from_user.id
    if not await user_in_doctor_context(doctor_id):
        await call.answer("⛔", show_alert=True)
        return
    parts = call.data.split(":")
    if len(parts) != 4:
        await call.answer("Ошибка", show_alert=True)
        return
    try:
        target_tid = int(parts[1])
        client_id = int(parts[2])
        consultation_id = int(parts[3])
    except ValueError:
        await call.answer("Ошибка", show_alert=True)
        return
    cur = get_current_client(doctor_id)
    if not cur or int(cur) != client_id:
        await call.answer("Нет активного клиента.", show_alert=True)
        return
    if target_tid == doctor_id:
        await call.answer("Нельзя выбрать себя.", show_alert=True)
        return
    tname = await get_doctor_name(target_tid)
    spec = await get_doctor_specialization(target_tid) or ""
    title = SPECIALISTS.get(spec, spec) if spec else ""
    await call.message.answer(
        f"Подтвердить перенаправление к <b>{escape(tname)}</b>"
        + (f" ({escape(title)})" if title else "")
        + "?",
        parse_mode="HTML",
        reply_markup=get_redirect_confirm_keyboard(target_tid, client_id, consultation_id),
    )
    await call.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("refok:"))
async def redirect_execute(call: CallbackQuery):
    from database.db import get_db
    from database import doctors as doctors_mod

    doctor_id = call.from_user.id
    if not await user_in_doctor_context(doctor_id):
        await call.answer("⛔", show_alert=True)
        return
    parts = call.data.split(":")
    if len(parts) != 4:
        await call.answer("Ошибка", show_alert=True)
        return
    try:
        target_tid = int(parts[1])
        client_id = int(parts[2])
        consultation_id = int(parts[3])
    except ValueError:
        await call.answer("Ошибка", show_alert=True)
        return
    cur = get_current_client(doctor_id)
    if not cur or int(cur) != client_id:
        await call.answer("Клиент не у вас в работе.", show_alert=True)
        return
    if target_tid == doctor_id:
        await call.answer("Нельзя выбрать себя.", show_alert=True)
        return
    if target_tid not in doctors_mod.DOCTOR_IDS:
        await call.answer("Этот врач не найден в системе.", show_alert=True)
        return
    if get_current_client(target_tid):
        await call.answer("Выбранный врач сейчас занят другим клиентом.", show_alert=True)
        return

    old_name = await get_doctor_name(doctor_id)
    new_name = await get_doctor_name(target_tid)
    new_spec = await get_doctor_specialization(target_tid) or "—"

    append_consultation_chat_line(
        consultation_id,
        f"—— Система: перенаправление от {old_name} к {new_name} ——",
    )

    set_current_client(doctor_id, None)

    await update_consultation_doctor(consultation_id, target_tid, new_name, new_spec)
    set_current_client(target_tid, str(client_id))
    r.set(f"client:{client_id}:doctor", str(target_tid))
    set_client_consultation(client_id, consultation_id)

    db = await get_db()
    cur_sql = await db.execute(
        """
        SELECT client_anonymous_id, problem_key,
               pet_name, pet_species, pet_age, pet_weight, pet_breed, pet_condition, pet_chronic,
               recent_illness
        FROM consultations WHERE id = ?
        """,
        (consultation_id,),
    )
    qrow = await cur_sql.fetchone()

    head = (
        f"↪️ <b>К вам перенаправлен клиент</b>\n\n"
        f"От врача: {escape(old_name)}\n"
        f"Клиент в системе: {escape(qrow[0]) if qrow else '—'}\n\n"
        f"📋 <b>Данные из опросника</b>\n"
    )
    if qrow:
        (
            _anon,
            pk,
            pet_nm,
            sp,
            ag,
            w,
            br,
            cond,
            chr,
            recent_ill,
        ) = qrow
        head += (
            f"Проблема (ключ): {escape(pk or '—')}\n"
            f"Имя питомца: {escape(pet_nm or '—')}\n"
            f"Вид: {escape(sp or '—')}\n"
            f"Возраст: {escape(ag or '—')}\n"
            f"Вес: {escape(w or '—')}\n"
            f"Порода: {escape(br or '—')}\n"
            f"Упитанность: {escape(cond or '—')}\n"
            f"Хроника: {escape(chr or '—')}\n"
            f"За последний месяц: {escape(recent_ill or '—')}\n\n"
        )
    head += "💬 <b>Переписка до перенаправления</b>\n"
    await safe_send_message(target_tid, head, parse_mode="HTML")
    chat_raw = get_consultation_chat_text(consultation_id)
    if chat_raw.strip():
        for chunk in split_text_chunks(escape(chat_raw), 3500):
            await safe_send_message(target_tid, f"<pre>{chunk}</pre>", parse_mode="HTML")
    await safe_send_message(
        target_tid,
        "Оплата по этой консультации уже подтверждена. Напишите клиенту.",
        reply_markup=get_doctor_actions_keyboard(client_id),
    )

    await safe_send_message(
        client_id,
        f"↪️ Вас перенаправили к другому специалисту: <b>{escape(new_name)}</b>.\n"
        f"Продолжите диалог — сообщения уйдут новому врачу.",
        parse_mode="HTML",
    )
    await safe_send_message(
        doctor_id,
        f"✅ Клиент перенаправлен к {new_name}.",
    )
    await call.answer("Готово")
    try:
        await call.message.delete()
    except Exception:
        pass


@router.callback_query(lambda c: c.data == "refcancel")
async def redirect_cancel(call: CallbackQuery):
    await call.answer("Отменено")
    try:
        await call.message.delete()
    except Exception:
        pass


@router.message(Command("end"))
async def end_command(message: Message):
    user_id = message.from_user.id
    if await user_in_doctor_context(user_id):
        current_client = get_current_client(user_id)
        if current_client:
            await _end_active_consultation(user_id, int(current_client))


@router.callback_query(lambda c: c.data == "doctor_online")
async def doctor_online_callback(call: CallbackQuery):
    doctor_id = call.from_user.id
    if not await user_in_doctor_context(doctor_id):
        await call.answer("⛔ Только для врачей")
        return
    set_doctor_status(doctor_id, "online")
    await call.message.edit_text("🟢 Вы стали онлайн.", reply_markup=get_doctor_main_keyboard())
    await call.answer()


@router.callback_query(lambda c: c.data == "doctor_offline")
async def doctor_offline_callback(call: CallbackQuery):
    doctor_id = call.from_user.id
    if not await user_in_doctor_context(doctor_id):
        await call.answer("⛔ Только для врачей")
        return
    set_doctor_status(doctor_id, "offline")
    await call.message.edit_text("🔴 Вы стали офлайн.", reply_markup=get_doctor_main_keyboard())
    await call.answer()


@router.callback_query(lambda c: c.data == "view_queue")
async def view_queue_callback(call: CallbackQuery):
    doctor_id = call.from_user.id
    if not await user_in_doctor_context(doctor_id):
        await call.answer("⛔ Только для врачей")
        return
    
    queue_len = await get_queue_length("all")
    if queue_len == 0:
        await safe_send_message(doctor_id, "📭 Очередь пуста.")
    else:
        from database.queue import get_queue_items
        items = await get_queue_items("all", limit=10)
        text = f"📋 ОЧЕРЕДЬ ({queue_len}):\n\n"
        for i, (client_id, anonymous_id, queue_id) in enumerate(items):
            text += f"{i+1}. {anonymous_id}\n"
        await safe_send_message(doctor_id, text)
    await call.answer()


@router.callback_query(lambda c: c.data == "show_status")
async def show_status_callback(call: CallbackQuery):
    doctor_id = call.from_user.id
    if not await user_in_doctor_context(doctor_id):
        await call.answer("⛔ Только для врачей")
        return
    
    current = get_current_client(doctor_id)
    queue_len = await get_queue_length("all")
    
    text = f"📊 Статус: {get_doctor_status(doctor_id)}\n"
    text += f"👤 Текущий клиент: {current or 'нет'}\n📋 Очередь: {queue_len}"
    
    has_client = current is not None
    await call.message.edit_text(text, reply_markup=get_doctor_status_keyboard(has_client))
    await call.answer()


# Нельзя использовать ~Command() без аргументов — в aiogram это ValueError.
@router.message(DoctorToClientMediaFilter())
async def chat_messages(message: Message):
    user_id = message.from_user.id
    current_client = get_current_client(user_id)
    if not current_client:
        return
    cid = get_client_consultation_id(int(current_client))
    if message.text:
        if cid:
            append_consultation_chat_line(cid, f"👨‍⚕️ Врач: {message.text}")
        await safe_send_message(int(current_client), f"👨‍⚕️ Врач: {message.text}")
    elif message.photo:
        cap = message.caption or ""
        if cid:
            append_consultation_chat_line(cid, f"👨‍⚕️ Врач: [фото] {cap}")
        await safe_send_photo(
            int(current_client),
            message.photo[-1].file_id,
            caption=f"👨‍⚕️ Врач: {cap}" if cap else "👨‍⚕️ Врач: 📷",
        )
    update_doctor_activity(user_id)