import redis
from config import REDIS_URL

r = redis.from_url(REDIS_URL, decode_responses=True)

from aiogram import Router, F
from aiogram.filters import Command, BaseFilter
from aiogram.enums import MessageEntityType
from aiogram.types import Message, CallbackQuery, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from config import SPECIALISTS
from services.validators import is_doctor, get_doctor_status, get_current_client, set_doctor_status, set_current_client, update_doctor_activity, clear_session
from services.routing import get_doctor_by_specialization
from database.queue import pop_from_queue, get_queue_length, confirm_queue_processed, remove_from_queue
from database.consultations import update_consultation_doctor, save_consultation_end
from database.payments import confirm_payment, get_pending_payment
from database.doctors import get_doctor_name
from utils.helpers import safe_send_message, get_anonymous_id
from keyboards.doctor import (
    get_doctor_main_keyboard,
    get_doctor_status_keyboard,
    get_doctor_actions_keyboard,
)
from states.forms import QuestionnaireState

router = Router()


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
    await safe_send_message(client_id, "✅ Оплата подтверждена!")
    await safe_send_message(doctor_id, "✅ Оплата подтверждена")
    client_state = FSMContext(
        storage=state.storage,
        key=StorageKey(bot_id=bot_id, chat_id=client_id, user_id=client_id),
    )
    await client_state.update_data(consultation_id=consultation_id, problem_name="Консультация")
    from keyboards.client import get_species_keyboard
    await client_state.set_state(QuestionnaireState.waiting_species)
    await safe_send_message(
        client_id,
        "📋 <b>Пожалуйста, заполните информацию о питомце</b>\n\n"
        "Выберите вид животного:",
        reply_markup=get_species_keyboard(),
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
    await update_consultation_doctor(consultation_id, doctor_id, doctor_name)
    set_current_client(doctor_id, client_id)
    r.set(f"client:{client_id}:doctor", doctor_id)
    await safe_send_message(
        int(client_id),
        "✅ Врач принял заявку! Консультация начинается.\n\n"
        "Напишите сообщение врачу.",
        reply_markup=ReplyKeyboardRemove(),
    )
    await safe_send_message(doctor_id, "✅ Клиент принят. Напишите сообщение.")
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


class DoctorToClientTextFilter(BaseFilter):
    """Только сообщения врача (не команды). Иначе апдейт уходит в client_router — кнопки меню."""

    async def __call__(self, message: Message) -> bool:
        if not _not_a_bot_command(message):
            return False
        return await is_doctor(message.from_user.id)


@router.message(Command("online"))
async def go_online(message: Message):
    user_id = message.from_user.id
    if await is_doctor(user_id):
        set_doctor_status(user_id, "online")
        await safe_send_message(user_id, "🟢 Вы онлайн", reply_markup=get_doctor_main_keyboard())


@router.message(Command("offline"))
async def go_offline(message: Message):
    user_id = message.from_user.id
    if await is_doctor(user_id):
        set_doctor_status(user_id, "offline")
        await safe_send_message(user_id, "🔴 Вы офлайн", reply_markup=get_doctor_main_keyboard())


@router.message(Command("status"))
async def show_status(message: Message):
    user_id = message.from_user.id
    if not await is_doctor(user_id):
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
    if not await is_doctor(doctor_id):
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
    if not await is_doctor(doctor_id):
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
    consultation_id = None
    client_id = anonymous_id = queue_id = None

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
        if row:
            consultation_id, _problem_key = row
            break
        await confirm_queue_processed(queue_id)

    if not consultation_id:
        await safe_send_message(
            doctor_id,
            "❌ В очереди нет заявок с оплаченной консультацией. Попросите админа: /clearqueue",
        )
        return

    if not await execute_take_client(doctor_id, client_id, consultation_id, queue_id):
        await safe_send_message(
            doctor_id,
            "❌ Не удалось начать консультацию (статус консультации изменился).",
        )


@router.message(Command("next"))
async def next_command(message: Message):
    user_id = message.from_user.id
    if not await is_doctor(user_id):
        return
    await run_next_from_queue(user_id)


@router.callback_query(lambda c: c.data == "doctor_next")
async def doctor_next_callback(call: CallbackQuery):
    doctor_id = call.from_user.id
    if not await is_doctor(doctor_id):
        await call.answer("⛔", show_alert=True)
        return
    await run_next_from_queue(doctor_id)
    await call.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("take_cn:"))
async def take_consultation_callback(call: CallbackQuery):
    doctor_id = call.from_user.id
    if not await is_doctor(doctor_id):
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
    ok = await execute_take_client(doctor_id, client_id, consultation_id, None)
    await call.answer("Консультация началась" if ok else "Не удалось начать", show_alert=not ok)
    if ok:
        try:
            await call.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass


@router.message(Command("end"))
async def end_command(message: Message):
    user_id = message.from_user.id
    if await is_doctor(user_id):
        current_client = get_current_client(user_id)
        if current_client:
            from database.db import get_db
            db = await get_db()
            cursor = await db.execute('''
                SELECT id FROM consultations 
                WHERE client_id = ? AND status = "active"
            ''', (int(current_client),))
            row = await cursor.fetchone()
            if row:
                consultation_id = row[0]
                await save_consultation_end(consultation_id, "ended_by_doctor")
                from keyboards.client import get_rating_keyboard
                await safe_send_message(int(current_client), "Пожалуйста, оцените консультацию:", reply_markup=get_rating_keyboard(consultation_id, user_id))
            set_current_client(user_id, None)
            clear_session(int(current_client), user_id)
            await safe_send_message(int(current_client), "🔚 Врач завершил консультацию.")
            await safe_send_message(user_id, "✅ Консультация завершена")


@router.callback_query(lambda c: c.data == "doctor_online")
async def doctor_online_callback(call: CallbackQuery):
    doctor_id = call.from_user.id
    if not await is_doctor(doctor_id):
        await call.answer("⛔ Только для врачей")
        return
    set_doctor_status(doctor_id, "online")
    await call.message.edit_text("🟢 Вы стали онлайн.", reply_markup=get_doctor_main_keyboard())
    await call.answer()


@router.callback_query(lambda c: c.data == "doctor_offline")
async def doctor_offline_callback(call: CallbackQuery):
    doctor_id = call.from_user.id
    if not await is_doctor(doctor_id):
        await call.answer("⛔ Только для врачей")
        return
    set_doctor_status(doctor_id, "offline")
    await call.message.edit_text("🔴 Вы стали офлайн.", reply_markup=get_doctor_main_keyboard())
    await call.answer()


@router.callback_query(lambda c: c.data == "view_queue")
async def view_queue_callback(call: CallbackQuery):
    doctor_id = call.from_user.id
    if not await is_doctor(doctor_id):
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
    if not await is_doctor(doctor_id):
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
@router.message(DoctorToClientTextFilter())
async def chat_messages(message: Message):
    user_id = message.from_user.id
    current_client = get_current_client(user_id)
    if not current_client:
        return
    await safe_send_message(int(current_client), f"👨‍⚕️ Врач: {message.text}")
    update_doctor_activity(user_id)