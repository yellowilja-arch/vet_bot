import redis

from aiogram import Router, F
from aiogram.filters import Command, BaseFilter
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from aiogram.fsm.context import FSMContext
from html import escape
from config import ADMIN_IDS, PHONE_NUMBER, DEFAULT_CONSULTATION_PRICE, REDIS_URL
from data.problems import PROBLEMS, SPECIALISTS
from services.validators import (
    is_blocked,
    is_doctor,
    user_in_client_context,
    user_in_doctor_context,
    user_in_admin_context,
    set_panel_mode,
    get_panel_mode,
    append_consultation_chat_line,
    get_client_consultation_id,
    get_doctor_status,
    get_current_client,
    get_doctor_status_symbol,
)
from database.queue import add_to_queue
from database.doctors import (
    get_all_doctors,
    get_doctor_name,
    topic_keys_available_for_client_menu,
    get_public_doctors_for_client,
    is_active_public_doctor,
    specializations_slash_plain,
)
from database.consultations import (
    save_consultation_start,
    assign_pending_doctor_from_topic,
    assign_pending_doctor_direct,
    get_consultation_doctor_and_topic,
    set_consultation_offline_intake,
    finalize_questionnaire_sla,
)
from database.payments import save_payment
from database.users import save_user_if_new
from database.support import (
    add_support_message,
    create_support_ticket,
    ensure_active_support_ticket_for_client,
    format_user_history,
)
from services.dialog_session import record_client_message
from utils.helpers import safe_send_message, safe_send_photo, get_anonymous_id, split_text_chunks
from keyboards.client import (
    TEXT_BTN_OUR_DOCTORS,
    get_main_keyboard,
    get_topic_pay_keyboard,
    get_species_keyboard,
    get_condition_keyboard,
    get_rating_keyboard,
    get_recent_illness_keyboard,
    get_vaccination_keyboard,
    get_sterilization_keyboard,
    get_support_keyboard,
    get_waiting_keyboard,
    get_back_keyboard,
    get_our_doctors_inline_keyboard,
    get_doctor_free_pay_keyboard,
    get_doctor_busy_keyboard,
    get_doctor_offline_keyboard,
)
from keyboards.admin import get_admin_main_keyboard
from keyboards.doctor import (
    get_doctor_main_keyboard,
    get_confirm_payment_inline_keyboard,
    get_start_consultation_keyboard,
)
from states.forms import PaymentState, QuestionnaireState, WaitingState
from services.bot_commands import apply_commands_for_user
from services.notifications import notify_admins_client_support_reply, notify_support_ticket_created
from services.support_session import set_active_support_ticket

router = Router()
_redis = redis.from_url(REDIS_URL, decode_responses=True)

def _spec_key_from_menu_label(text: str | None) -> str | None:
    """Соответствие текста кнопки темы ключу специализации (как в SPECIALISTS)."""
    if not text:
        return None
    t = text.strip()
    for key, label in SPECIALISTS.items():
        if label == t:
            return key
    return None


async def client_main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Reply-клавиатура: темы из БД (есть онлайн-врач по специализации)."""
    keys = await topic_keys_available_for_client_menu()
    labels = [SPECIALISTS[k] for k in keys]
    return get_main_keyboard(labels)


async def _build_our_doctors_message_and_keyboard():
    """Список врачей: только активные с реальным Telegram ID; статус — 🟢🔴⚪."""
    db_rows = await get_public_doctors_for_client()
    if not db_rows:
        return None, None
    lines_body = ["👨‍⚕️ <b>НАШИ ВРАЧИ</b>\n", "Выберите специалиста:\n"]
    btn_rows: list[tuple[int, str]] = []
    for telegram_id, name, spec_keys in db_rows:
        spec_title = specializations_slash_plain(spec_keys) if spec_keys else "—"
        sym = get_doctor_status_symbol(telegram_id)
        busy_note = ""
        if get_doctor_status(telegram_id) == "online" and get_current_client(telegram_id):
            busy_note = " (в консультации)"
        lines_body.append(f"{sym} {escape(spec_title)} — {escape(name)}{busy_note}")
        btn_rows.append((telegram_id, f"{sym} {spec_title} — {name}"))
    lines_body.append("")
    lines_body.append("<i>🟢 — свободен · 🔴 — в консультации · ⚪ — не в сети</i>")
    text = "\n".join(lines_body)
    kb = get_our_doctors_inline_keyboard(btn_rows)
    return text, kb


def _support_flow_exclude_texts() -> frozenset[str]:
    """Тексты кнопок меню и анкеты — не считать ответом в поддержку."""
    s = {
        "🆘 Помощь",
        TEXT_BTN_OUR_DOCTORS,
        "📋 Мои консультации",
        "🔙 Назад",
        "🐕 Собака",
        "🐈 Кошка",
        "🐇 Грызун",
        "🐦 Птица",
        "📝 Другое",
        "❌ Отмена",
        "🟢 Худощавый",
        "🟢 Нормальный",
        "🟡 Упитанный",
        "🔴 Ожирение",
    }
    for label in SPECIALISTS.values():
        s.add(label)
    return frozenset(s)


_SUPPORT_FLOW_EXCLUDE_TEXTS = _support_flow_exclude_texts()


class ClientSupportFollowupFilter(BaseFilter):
    """Текстовое сообщение клиента в открытом обращении (не первое, не меню, не консультация с врачом)."""

    async def __call__(self, message: Message, **kwargs) -> bool:
        if message.chat.type != "private":
            return False
        if not message.text or not message.text.strip():
            return False
        raw = message.text.strip()
        if raw.startswith("/"):
            return False
        if raw in _SUPPORT_FLOW_EXCLUDE_TEXTS:
            return False
        uid = message.from_user.id
        if not await user_in_client_context(uid):
            return False
        state: FSMContext | None = kwargs.get("state")
        if state is not None:
            st = await state.get_state()
            if st:
                if st.startswith("PaymentState") or st.startswith("QuestionnaireState"):
                    return False
                if st in (
                    WaitingState.waiting_for_admin_message.state,
                    WaitingState.waiting_for_doctor.state,
                    WaitingState.waiting_for_specific_doctor.state,
                    WaitingState.waiting_for_feedback.state,
                    WaitingState.waiting_for_rating_comment.state,
                ):
                    return False
        if _redis.get(f"client:{uid}:doctor"):
            return False
        rid = await ensure_active_support_ticket_for_client(uid)
        return rid is not None


class ClientActiveConsultFilter(BaseFilter):
    """Сообщения клиента в активной консультации (пересылка врачу). Регистрируйте хендлер последним."""

    async def __call__(self, message: Message) -> bool:
        if message.chat.type != "private":
            return False
        if not await user_in_client_context(message.from_user.id):
            return False
        if not _redis.get(f"client:{message.from_user.id}:doctor"):
            return False
        return bool(message.text or message.photo)


def _client_telegram_id(message: Message) -> int:
    """В личке у inline-сообщений from_user — бот; получатель — message.chat.id."""
    if message.chat and message.chat.type == "private":
        return message.chat.id
    return message.from_user.id


def _panel_pick_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👨‍⚕️ Панель врача", callback_data="panel:doctor")],
            [InlineKeyboardButton(text="🛠 Панель администратора", callback_data="panel:admin")],
            [InlineKeyboardButton(text="🐾 Клиентский режим", callback_data="panel:client")],
        ]
    )


@router.message(Command("start"))
async def start_command(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    u = message.from_user
    await save_user_if_new(
        u.id,
        u.username,
        u.first_name,
        u.last_name,
    )

    if await is_blocked(user_id):
        await safe_send_message(user_id, "⛔ Ваш аккаунт заблокирован.")
        return

    async def _sync_cmds() -> None:
        await apply_commands_for_user(message.bot, user_id)

    is_doc = await is_doctor(user_id)
    is_adm = user_id in ADMIN_IDS
    if is_adm and is_doc and get_panel_mode(user_id) is None:
        await safe_send_message(
            user_id,
            "У вас есть и роль врача, и роль администратора.\n"
            "Выберите режим интерфейса (потом можно сменить: /doctor, /admin, /client):",
            reply_markup=_panel_pick_keyboard(),
        )
        await _sync_cmds()
        return

    if await user_in_admin_context(user_id):
        await safe_send_message(
            user_id,
            "🛠 <b>Панель администратора</b>\nКоманды: /stats, /health, /ban и др.",
            reply_markup=get_admin_main_keyboard(),
            parse_mode="HTML",
        )
        await _sync_cmds()
        return

    if await user_in_doctor_context(user_id):
        await safe_send_message(
            user_id,
            "👨‍⚕️ <b>Панель врача</b>",
            reply_markup=get_doctor_main_keyboard(),
            parse_mode="HTML",
        )
        await _sync_cmds()
        return

    await safe_send_message(user_id, "⌨️ Обновляю меню…", reply_markup=ReplyKeyboardRemove())
    kb = await client_main_menu_keyboard()
    keys = await topic_keys_available_for_client_menu()
    if keys:
        welcome = (
            "🐾 <b>Добро пожаловать в онлайн-консультации ветклиники!</b>\n\n"
            "Выберите <b>тему</b> консультации — доступны направления, "
            "по которым сейчас есть врачи в сети."
        )
    else:
        welcome = (
            "🐾 <b>Добро пожаловать!</b>\n\n"
            "Сейчас нет врачей онлайн ни по одному направлению. "
            "Попробуйте позже или загляните в раздел «Наши врачи» / напишите в поддержку."
        )
    await safe_send_message(user_id, welcome, reply_markup=kb, parse_mode="HTML")
    await _sync_cmds()


@router.callback_query(lambda c: c.data and c.data.startswith("panel:"))
async def panel_mode_callback(call: CallbackQuery, state: FSMContext):
    await state.clear()
    mode = call.data.split(":", 1)[1]
    user_id = call.from_user.id
    if mode not in ("doctor", "admin", "client"):
        await call.answer()
        return
    if mode == "doctor" and not await is_doctor(user_id):
        await call.answer("Нет роли врача", show_alert=True)
        return
    if mode == "admin" and user_id not in ADMIN_IDS:
        await call.answer("Нет прав администратора", show_alert=True)
        return
    set_panel_mode(user_id, mode)
    await call.answer("Режим сохранён")
    try:
        await call.message.delete()
    except Exception:
        pass
    if mode == "doctor":
        await safe_send_message(
            user_id,
            "👨‍⚕️ <b>Панель врача</b>",
            reply_markup=get_doctor_main_keyboard(),
            parse_mode="HTML",
        )
    elif mode == "admin":
        await safe_send_message(
            user_id,
            "🛠 <b>Панель администратора</b>",
            reply_markup=get_admin_main_keyboard(),
            parse_mode="HTML",
        )
    else:
        await safe_send_message(user_id, "⌨️ Обновляю меню…", reply_markup=ReplyKeyboardRemove())
        kb = await client_main_menu_keyboard()
        await safe_send_message(
            user_id,
            "🐾 <b>Клиентский режим</b>\nВыберите тему консультации:",
            reply_markup=kb,
            parse_mode="HTML",
        )
    await apply_commands_for_user(call.bot, user_id)


@router.message(Command("doctor"))
async def cmd_doctor_panel(message: Message, state: FSMContext):
    await state.clear()
    uid = message.from_user.id
    if not await is_doctor(uid):
        await safe_send_message(uid, "⛔ У вас нет роли врача.")
        return
    set_panel_mode(uid, "doctor")
    await safe_send_message(
        uid,
        "👨‍⚕️ <b>Панель врача</b>",
        reply_markup=get_doctor_main_keyboard(),
        parse_mode="HTML",
    )
    await apply_commands_for_user(message.bot, uid)


@router.message(Command("admin"))
async def cmd_admin_panel(message: Message, state: FSMContext):
    await state.clear()
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        await safe_send_message(uid, "⛔ Нет прав администратора.")
        return
    set_panel_mode(uid, "admin")
    await safe_send_message(
        uid,
        "🛠 <b>Панель администратора</b>",
        reply_markup=get_admin_main_keyboard(),
        parse_mode="HTML",
    )
    await apply_commands_for_user(message.bot, uid)


@router.message(Command("client"))
async def cmd_client_panel(message: Message, state: FSMContext):
    """Режим клиента (для теста, если у вас также есть роль врача/админа)."""
    await state.clear()
    uid = message.from_user.id
    set_panel_mode(uid, "client")
    await safe_send_message(uid, "⌨️ Обновляю меню…", reply_markup=ReplyKeyboardRemove())
    kb = await client_main_menu_keyboard()
    await safe_send_message(
        uid,
        "🐾 <b>Клиентский режим</b>\nВыберите тему консультации:",
        reply_markup=kb,
        parse_mode="HTML",
    )
    await apply_commands_for_user(message.bot, uid)


@router.message(F.text == TEXT_BTN_OUR_DOCTORS)
async def our_doctors_open(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if not await user_in_client_context(user_id):
        return
    text, kb = await _build_our_doctors_message_and_keyboard()
    if not text or not kb:
        await safe_send_message(user_id, "📭 Список врачей пока пуст. Обратитесь к администратору.")
        return
    await safe_send_message(user_id, text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data.startswith("docsel:"))
async def our_doctor_selected(call: CallbackQuery, state: FSMContext):
    user_id = call.from_user.id
    if not await user_in_client_context(user_id):
        await call.answer("⛔", show_alert=True)
        return
    try:
        tid = int(call.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await call.answer("Ошибка", show_alert=True)
        return
    if not await is_active_public_doctor(tid):
        await call.answer("Этот врач недоступен в списке.", show_alert=True)
        return
    name = await get_doctor_name(tid)
    online = get_doctor_status(tid) == "online"
    busy = get_current_client(tid) is not None

    if online and not busy:
        await call.message.edit_text(
            f"🟢 Врач <b>{escape(name)}</b> готов принять консультацию!\n\n"
            f"💰 Стоимость: {DEFAULT_CONSULTATION_PRICE} ₽",
            reply_markup=get_doctor_free_pay_keyboard(tid),
            parse_mode="HTML",
        )
    elif online and busy:
        await call.message.edit_text(
            f"🔴 Врач <b>{escape(name)}</b> сейчас ведёт консультацию.\n\n"
            f"Вы можете:\n"
            f"• Ожидать освобождения\n"
            f"• Выбрать другого врача\n"
            f"• Оставить заявку в общую очередь (через главное меню)",
            reply_markup=get_doctor_busy_keyboard(tid),
            parse_mode="HTML",
        )
    else:
        await call.message.edit_text(
            f"⚪ Врач <b>{escape(name)}</b> сейчас не в сети.\n\n"
            f"Вы можете оплатить консультацию сейчас — ответ гарантирован в течение <b>24 часов</b> "
            f"после подтверждения оплаты.\n\n"
            f"Или выберите другого врача / тему в главном меню.",
            reply_markup=get_doctor_offline_keyboard(tid),
            parse_mode="HTML",
        )
    await call.answer()


@router.callback_query(F.data == "doclist_reopen")
async def our_doctors_reopen_list(call: CallbackQuery):
    user_id = call.from_user.id
    if not await user_in_client_context(user_id):
        await call.answer("⛔", show_alert=True)
        return
    text, kb = await _build_our_doctors_message_and_keyboard()
    if not text or not kb:
        await call.answer("Список пуст", show_alert=True)
        return
    await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data == "doclist_close")
async def our_doctors_close(call: CallbackQuery):
    await call.answer()
    try:
        await call.message.delete()
    except Exception:
        pass


@router.callback_query(F.data.startswith("docbusy_wait:"))
async def doc_busy_wait_info(call: CallbackQuery):
    await call.answer(
        "Попробуйте позже снова открыть «Наши врачи» или выберите тему в главном меню.",
        show_alert=True,
    )


@router.callback_query(F.data == "docbusy_queue")
async def doc_busy_queue_hint(call: CallbackQuery):
    await call.answer()
    await call.message.answer(
        "📋 <b>Общая очередь</b>\n\n"
        "Нажмите /start и выберите тему консультации — вас закрепят за врачом этого направления.",
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("pay_direct_offline:"))
async def pay_direct_doctor_offline(call: CallbackQuery, state: FSMContext):
    """Оплата записи к врачу, который сейчас офлайн (полный цикл, ответ до 24 ч)."""
    user_id = call.from_user.id
    if not await user_in_client_context(user_id):
        await call.answer("⛔", show_alert=True)
        return
    try:
        tid = int(call.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await call.answer("Ошибка", show_alert=True)
        return
    if not await is_active_public_doctor(tid):
        await call.answer("Врач недоступен", show_alert=True)
        return

    prob_data = PROBLEMS["direct_booking"]
    dname = await get_doctor_name(tid)
    await state.update_data(
        problem_key="direct_booking",
        selected_problem="direct_booking",
        problem_price=prob_data["price"],
        direct_doctor_id=tid,
        offline_doctor_booking=True,
        problem_name=f"Консультация: {dname}",
    )
    await call.message.edit_text(
        f"💰 <b>Оплата консультации</b>\n\n"
        f"Врач: <b>{escape(dname)}</b> (сейчас не в сети)\n"
        f"📅 Ответ в течение 24 часов после подтверждения оплаты.\n\n"
        f"Услуга: запись к выбранному специалисту\n"
        f"Сумма: {prob_data['price']} ₽\n\n"
        f"📞 Оплата по номеру телефона (СБП):\n"
        f"<code>{PHONE_NUMBER}</code>\n\n"
        f"✅ После оплаты нажмите кнопку ниже и отправьте чек.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Я оплатил", callback_data="paid_confirm")],
                [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_payment")],
            ]
        ),
        parse_mode="HTML",
    )
    await call.answer()


@router.callback_query(F.data.startswith("pay_direct:"))
async def pay_direct_doctor(call: CallbackQuery, state: FSMContext):
    user_id = call.from_user.id
    if not await user_in_client_context(user_id):
        await call.answer("⛔", show_alert=True)
        return
    try:
        tid = int(call.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await call.answer("Ошибка", show_alert=True)
        return
    if get_doctor_status(tid) != "online" or get_current_client(tid):
        await call.answer("Врач недоступен", show_alert=True)
        return

    prob_data = PROBLEMS["direct_booking"]
    dname = await get_doctor_name(tid)
    await state.update_data(
        problem_key="direct_booking",
        selected_problem="direct_booking",
        problem_price=prob_data["price"],
        direct_doctor_id=tid,
        problem_name=f"Консультация: {dname}",
    )
    await call.message.edit_text(
        f"💰 <b>Оплата консультации</b>\n\n"
        f"Врач: <b>{escape(dname)}</b>\n"
        f"Услуга: запись к выбранному специалисту\n"
        f"Сумма: {prob_data['price']} ₽\n\n"
        f"📞 Оплата по номеру телефона (СБП):\n"
        f"<code>{PHONE_NUMBER}</code>\n\n"
        f"✅ После оплаты нажмите кнопку ниже и отправьте чек.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Я оплатил", callback_data="paid_confirm")],
                [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_payment")],
            ]
        ),
        parse_mode="HTML",
    )
    await call.answer()


@router.message(
    F.text,
    lambda m: _spec_key_from_menu_label(m.text) is not None,
)
async def select_topic(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if not await user_in_client_context(user_id):
        return
    key = _spec_key_from_menu_label(message.text)
    if not key:
        return
    available = await topic_keys_available_for_client_menu()
    if key not in available:
        await safe_send_message(
            user_id,
            "⚠️ Эта тема сейчас недоступна (нет врачей онлайн). Нажмите /start, чтобы обновить меню.",
        )
        return

    title = SPECIALISTS[key]
    price = DEFAULT_CONSULTATION_PRICE
    await state.update_data(
        problem_key=key,
        selected_problem=key,
        problem_name=title,
        problem_price=price,
    )
    await safe_send_message(
        user_id,
        f"📋 <b>{escape(title)}</b>\n\n"
        f"💰 Стоимость: {price} ₽\n\n"
        f"После оплаты вы заполните информацию о питомце.",
        reply_markup=get_topic_pay_keyboard(key),
        parse_mode="HTML",
    )


@router.callback_query(lambda c: c.data and c.data.startswith("pay_topic:"))
async def pay_topic(call: CallbackQuery, state: FSMContext):
    spec_key = call.data.split(":", 1)[1]
    if spec_key not in SPECIALISTS:
        await call.answer("Некорректная тема", show_alert=True)
        return
    user_id = call.from_user.id
    if not await user_in_client_context(user_id):
        await call.answer("⛔", show_alert=True)
        return
    available = await topic_keys_available_for_client_menu()
    if spec_key not in available:
        await call.answer("Тема недоступна (нет врачей онлайн)", show_alert=True)
        return

    title = SPECIALISTS[spec_key]
    price = DEFAULT_CONSULTATION_PRICE
    await state.update_data(
        problem_key=spec_key,
        selected_problem=spec_key,
        problem_name=title,
        problem_price=price,
    )
    pay_rows = [[InlineKeyboardButton(text="✅ Я оплатил", callback_data="paid_confirm")]]

    await call.message.edit_text(
        f"💰 <b>Оплата консультации</b>\n\n"
        f"Тема: {escape(title)}\n"
        f"Сумма: {price} ₽\n\n"
        f"📞 Оплата по номеру телефона (СБП):\n"
        f"<code>{PHONE_NUMBER}</code>\n\n"
        f"✅ После оплаты нажмите кнопку ниже и отправьте чек.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=pay_rows),
        parse_mode="HTML",
    )
    await call.answer()


@router.callback_query(lambda c: c.data == "paid_confirm")
async def paid_confirm(call: CallbackQuery, state: FSMContext):
    await call.message.edit_text(
        "📎 Отправьте скриншот или фото чека.\n\n"
        "Чек должен содержать сумму, дату и номер телефона.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_payment")]
        ])
    )
    await state.set_state(PaymentState.waiting_receipt)
    await call.answer()


@router.message(PaymentState.waiting_receipt, F.photo)
async def handle_receipt(message: Message, state: FSMContext):
    try:
        user_id = message.from_user.id
        data = await state.get_data()
        
        problem_key = data.get("problem_key")
        if not problem_key:
            await safe_send_message(user_id, "❌ Ошибка: тема не выбрана. Начните заново с /start")
            await state.clear()
            return

        anonymous_id = get_anonymous_id(problem_key, user_id)
        disp_problem = data.get("problem_name") or ""
        if not disp_problem:
            disp_problem = (
                PROBLEMS.get(problem_key, {}).get("name")
                or SPECIALISTS.get(problem_key, problem_key)
            )

        consultation_id = await save_consultation_start(user_id, anonymous_id, None, problem_key)
        if not consultation_id:
            await safe_send_message(user_id, "❌ Ошибка: не удалось создать консультацию.")
            await state.clear()
            return

        await save_payment(user_id, consultation_id, message.photo[-1].file_id)

        direct_tid = data.get("direct_doctor_id")
        notified = False

        if data.get("offline_doctor_booking"):
            await set_consultation_offline_intake(consultation_id)

        if direct_tid:
            tid = int(direct_tid)
            await assign_pending_doctor_direct(consultation_id, tid)
            dnm = await get_doctor_name(tid)
            await safe_send_photo(
                tid,
                message.photo[-1].file_id,
                caption=f"🧾 <b>НОВЫЙ ЧЕК</b>\n"
                f"👤 Клиент: {anonymous_id}\n"
                f"📂 Запись: <b>{escape(disp_problem)}</b>\n"
                f"👨‍⚕️ Врач: {escape(dnm)}\n\n"
                f"Подтвердите оплату кнопкой ниже или командой:\n"
                f"<code>/confirm_payment {user_id}</code>",
                parse_mode="HTML",
                reply_markup=get_confirm_payment_inline_keyboard(user_id),
            )
            notified = True
        else:
            assigned_tid = await assign_pending_doctor_from_topic(consultation_id, problem_key)
            if assigned_tid:
                spec_lbl = SPECIALISTS.get(problem_key, problem_key)
                await safe_send_photo(
                    assigned_tid,
                    message.photo[-1].file_id,
                    caption=f"🧾 <b>НОВЫЙ ЧЕК</b>\n"
                    f"👤 Клиент: {anonymous_id}\n"
                    f"📂 Тема: <b>{escape(disp_problem)}</b>\n"
                    f"👨‍⚕️ Направление: {escape(spec_lbl)}\n\n"
                    f"Подтвердите оплату кнопкой ниже или командой:\n"
                    f"<code>/confirm_payment {user_id}</code>",
                    parse_mode="HTML",
                    reply_markup=get_confirm_payment_inline_keyboard(user_id),
                )
                notified = True

        if not notified:
            from config import ADMIN_IDS
            for admin_id in ADMIN_IDS:
                await safe_send_photo(
                    admin_id,
                    message.photo[-1].file_id,
                    caption=f"🧾 <b>НОВЫЙ ЧЕК (нет врача онлайн по теме)</b>\n"
                    f"👤 Клиент: {anonymous_id}\n"
                    f"📂 Тема: {escape(disp_problem)} ({problem_key})\n\n"
                    f"<code>/confirm_payment {user_id}</code>",
                    parse_mode="HTML",
                    reply_markup=get_confirm_payment_inline_keyboard(user_id),
                )
        
        await safe_send_message(
            user_id,
            "✅ Чек отправлен врачу. Ожидайте подтверждения оплаты.\n\n"
            "После подтверждения вам нужно будет заполнить информацию о питомце."
        )
        
        await state.update_data(consultation_id=consultation_id, anonymous_id=anonymous_id)
        await state.set_state(PaymentState.waiting_confirmation)
        
    except Exception as e:
        import traceback
        error_text = traceback.format_exc()
        print(f"❌ Ошибка в handle_receipt: {error_text}")
        from config import ADMIN_IDS
        for admin_id in ADMIN_IDS:
            await safe_send_message(admin_id, f"❌ Ошибка при обработке чека:\n<pre>{escape(error_text)}</pre>", parse_mode="HTML")
        await safe_send_message(user_id, "❌ Произошла ошибка при обработке чека. Пожалуйста, попробуйте снова.")


@router.callback_query(lambda c: c.data == "cancel_payment")
async def cancel_payment(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("❌ Оплата отменена. Напишите /start для начала.")
    await call.answer()


@router.message(QuestionnaireState.waiting_pet_name)
async def process_pet_name(message: Message, state: FSMContext):
    name = (message.text or "").strip()
    if not name:
        await safe_send_message(message.from_user.id, "Напишите имя питомца текстом.")
        return
    if name == "❌ Отмена":
        await state.clear()
        await safe_send_message(message.from_user.id, "❌ Опросник отменён.", reply_markup=ReplyKeyboardRemove())
        return
    await state.update_data(pet_name=name)
    await state.set_state(QuestionnaireState.waiting_species)
    await safe_send_message(
        message.from_user.id,
        f"✅ Имя сохранено: <b>{escape(name)}</b>\n\n"
        "Выберите вид животного:",
        reply_markup=get_species_keyboard(),
        parse_mode="HTML",
    )


@router.message(QuestionnaireState.waiting_species)
async def process_species(message: Message, state: FSMContext):
    species = message.text
    if species == "❌ Отмена":
        await state.clear()
        await safe_send_message(message.from_user.id, "❌ Опросник отменён.", reply_markup=ReplyKeyboardRemove())
        return
    
    await state.update_data(species=species)
    await state.set_state(QuestionnaireState.waiting_age)
    await safe_send_message(
        message.from_user.id,
        "📝 Укажите возраст питомца:\n\n"
        "Например: <b>2 года</b> или <b>6 месяцев</b>",
        parse_mode="HTML"
    )


@router.message(QuestionnaireState.waiting_age)
async def process_age(message: Message, state: FSMContext):
    age = message.text
    await state.update_data(age=age)
    await state.set_state(QuestionnaireState.waiting_weight)
    await safe_send_message(
        message.from_user.id,
        "⚖️ Укажите вес питомца:\n\n"
        "Например: <b>5.5 кг</b>",
        parse_mode="HTML"
    )


@router.message(QuestionnaireState.waiting_weight)
async def process_weight(message: Message, state: FSMContext):
    weight = message.text
    await state.update_data(weight=weight)
    await state.set_state(QuestionnaireState.waiting_breed)
    await safe_send_message(
        message.from_user.id,
        "🐕 Укажите породу питомца:\n\n"
        "Например: <b>Мейн-кун</b> или <b>Бигль</b>",
        parse_mode="HTML"
    )


@router.message(QuestionnaireState.waiting_breed)
async def process_breed(message: Message, state: FSMContext):
    breed = message.text
    await state.update_data(breed=breed)
    await state.set_state(QuestionnaireState.waiting_condition)
    await safe_send_message(
        message.from_user.id,
        "📊 Оцените упитанность питомца:",
        reply_markup=get_condition_keyboard(),
        parse_mode="HTML"
    )


@router.message(QuestionnaireState.waiting_condition)
async def process_condition(message: Message, state: FSMContext):
    condition = message.text
    if condition == "❌ Отмена":
        await state.clear()
        await safe_send_message(message.from_user.id, "❌ Опросник отменён.", reply_markup=ReplyKeyboardRemove())
        return
    
    await state.update_data(condition=condition)
    await state.set_state(QuestionnaireState.waiting_chronic)
    await safe_send_message(
        message.from_user.id,
        "📋 Есть ли у питомца хронические заболевания?\n\n"
        "Если нет, напишите <b>нет</b> или нажмите кнопку ниже.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Нет хронических заболеваний", callback_data="no_chronic")]
        ]),
        parse_mode="HTML"
    )


@router.callback_query(lambda c: c.data == "no_chronic")
async def no_chronic(call: CallbackQuery, state: FSMContext):
    await state.update_data(chronic="Нет")
    await call.answer()
    try:
        await call.message.delete()
    except Exception:
        pass
    await state.set_state(QuestionnaireState.waiting_recent_illness)
    await safe_send_message(
        call.message.chat.id,
        "🩺 <b>Болел ли питомец чем-то за последний месяц?</b>\n\n"
        "Опишите симптомы, диагноз или лечение, если были.\n"
        "Если не болел, напишите <b>нет</b> или нажмите кнопку ниже.",
        reply_markup=get_recent_illness_keyboard(),
        parse_mode="HTML",
    )


@router.message(QuestionnaireState.waiting_chronic)
async def process_chronic(message: Message, state: FSMContext):
    chronic = message.text
    await state.update_data(chronic=chronic)
    await state.set_state(QuestionnaireState.waiting_recent_illness)
    await safe_send_message(
        message.from_user.id,
        "🩺 <b>Болел ли питомец чем-то за последний месяц?</b>\n\n"
        "Опишите симптомы, диагноз или лечение, если были.\n"
        "Если не болел, напишите <b>нет</b> или нажмите кнопку ниже.",
        reply_markup=get_recent_illness_keyboard(),
        parse_mode="HTML",
    )


async def _send_vaccination_step(chat_id: int, state: FSMContext) -> None:
    await state.set_state(QuestionnaireState.waiting_vaccination)
    await safe_send_message(
        chat_id,
        "💉 <b>Была ли проведена комплексная вакцинация?</b>\n\n"
        "Комплексная вакцинация защищает от основных заболеваний:\n"
        "собаки — чума, парвовирус, аденовирус, лептоспироз\n"
        "кошки — ринотрахеит, калицивироз, панлейкопения",
        reply_markup=get_vaccination_keyboard(),
        parse_mode="HTML",
    )


async def _send_sterilization_step(chat_id: int, state: FSMContext) -> None:
    await state.set_state(QuestionnaireState.waiting_sterilization)
    await safe_send_message(
        chat_id,
        "✂️ <b>Проведена ли кастрация / стерилизация?</b>\n\n"
        "Кастрация — удаление семенников (самцы)\n"
        "Стерилизация — удаление матки и яичников (самки)",
        reply_markup=get_sterilization_keyboard(),
        parse_mode="HTML",
    )


_VAC_MAP = {"vac:yes": "Да", "vac:no": "Нет", "vac:unk": "Не знаю"}
_STER_MAP = {"ster:yes": "Да", "ster:no": "Нет", "ster:unk": "Не знаю"}


@router.callback_query(lambda c: c.data and c.data.startswith("vac:"))
async def vaccination_chosen(call: CallbackQuery, state: FSMContext):
    if await state.get_state() != QuestionnaireState.waiting_vaccination.state:
        await call.answer()
        return
    label = _VAC_MAP.get(call.data)
    if not label:
        await call.answer()
        return
    await state.update_data(vaccination=label)
    await call.answer()
    try:
        await call.message.delete()
    except Exception:
        pass
    await _send_sterilization_step(call.message.chat.id, state)


@router.callback_query(lambda c: c.data and c.data.startswith("ster:"))
async def sterilization_chosen(call: CallbackQuery, state: FSMContext):
    if await state.get_state() != QuestionnaireState.waiting_sterilization.state:
        await call.answer()
        return
    label = _STER_MAP.get(call.data)
    if not label:
        await call.answer()
        return
    await state.update_data(sterilization=label)
    await call.answer()
    try:
        await call.message.delete()
    except Exception:
        pass
    await send_pet_info_to_doctor(call.message, state)


@router.callback_query(lambda c: c.data == "no_recent_illness")
async def no_recent_illness(call: CallbackQuery, state: FSMContext):
    await state.update_data(recent_illness="Нет")
    await call.answer()
    try:
        await call.message.delete()
    except Exception:
        pass
    await _send_vaccination_step(call.message.chat.id, state)


@router.message(QuestionnaireState.waiting_recent_illness)
async def process_recent_illness(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if not text:
        await safe_send_message(
            message.from_user.id,
            "Напишите ответ или нажмите «✅ Нет, не болел».",
        )
        return
    await state.update_data(recent_illness=text)
    await _send_vaccination_step(message.from_user.id, state)


async def send_pet_info_to_doctor(message: Message, state: FSMContext):
    data = await state.get_data()

    pet_name = data.get("pet_name", "Не указано")
    species = data.get("species", "Не указан")
    age = data.get("age", "Не указан")
    weight = data.get("weight", "Не указан")
    breed = data.get("breed", "Не указана")
    condition = data.get("condition", "Не указана")
    chronic = data.get("chronic", "Не указано")
    recent_illness = data.get("recent_illness", "Не указано")
    vaccination = data.get("vaccination", "Не указано")
    sterilization = data.get("sterilization", "Не указано")
    consultation_id = data.get("consultation_id")
    anonymous_id = data.get("anonymous_id", "anon")
    if not consultation_id:
        uid = _client_telegram_id(message)
        await safe_send_message(uid, "❌ Ошибка: консультация не найдена. Начните с /start")
        return

    from database.db import get_db
    db = await get_db()
    await db.execute('''
        UPDATE consultations SET
            pet_name = ?,
            pet_species = ?,
            pet_age = ?,
            pet_weight = ?,
            pet_breed = ?,
            pet_condition = ?,
            pet_chronic = ?,
            recent_illness = ?,
            vaccination = ?,
            sterilization = ?
        WHERE id = ?
    ''', (
        pet_name,
        species,
        age,
        weight,
        breed,
        condition,
        chronic,
        recent_illness,
        vaccination,
        sterilization,
        consultation_id,
    ))
    await db.commit()

    cur_off = await db.execute(
        "SELECT COALESCE(offline_intake, 0) FROM consultations WHERE id = ?",
        (consultation_id,),
    )
    off_row = await cur_off.fetchone()
    offline_intake = bool(off_row and off_row[0])
    await finalize_questionnaire_sla(consultation_id, offline_intake=offline_intake)

    uid = _client_telegram_id(message)
    
    prob_title = escape(str(data.get("problem_name", "Не указана")))
    anon = escape(str(data.get("anonymous_id", "Не указан")))
    vet_message = (
        f"🆕 <b>НОВАЯ КОНСУЛЬТАЦИЯ</b>\n\n"
        f"📂 Проблема: {prob_title}\n"
        f"👤 Клиент ID: {anon}\n\n"
        f"📋 <b>ИНФОРМАЦИЯ О ПИТОМЦЕ:</b>\n\n"
        f"🐾 Имя: {escape(str(pet_name))}\n"
        f"🐾 Вид: {escape(str(species))}\n"
        f"📅 Возраст: {escape(str(age))}\n"
        f"⚖️ Вес: {escape(str(weight))}\n"
        f"🐕 Порода: {escape(str(breed))}\n"
        f"📊 Упитанность: {escape(str(condition))}\n"
        f"💊 Хронические заболевания: {escape(str(chronic))}\n"
        f"🩺 Болезни за последний месяц: {escape(str(recent_illness))}\n"
        f"💉 Комплексная вакцинация: {escape(str(vaccination))}\n"
        f"✂️ Кастрация/стерилизация: {escape(str(sterilization))}\n"
    )

    doc_row = await get_consultation_doctor_and_topic(consultation_id)
    assigned_id = int(doc_row[0]) if doc_row and doc_row[0] is not None else None

    notified_doctors = set()
    direct_tid = data.get("direct_doctor_id")

    if direct_tid:
        t_id = int(direct_tid)
        sent = await safe_send_message(
            t_id,
            vet_message,
            parse_mode="HTML",
            reply_markup=get_start_consultation_keyboard(uid, consultation_id),
        )
        if sent is not None:
            notified_doctors.add(t_id)
    elif assigned_id is not None:
        sent = await safe_send_message(
            assigned_id,
            vet_message,
            parse_mode="HTML",
            reply_markup=get_start_consultation_keyboard(uid, consultation_id),
        )
        if sent is not None:
            notified_doctors.add(assigned_id)
    else:
        for row in await get_all_doctors():
            doctor_tid = int(row[0])
            sent = await safe_send_message(
                doctor_tid,
                vet_message,
                parse_mode="HTML",
                reply_markup=get_start_consultation_keyboard(uid, consultation_id),
            )
            if sent is not None:
                notified_doctors.add(doctor_tid)

    use_queue = assigned_id is None and not direct_tid
    queue_position = None
    if use_queue:
        queue_position = await add_to_queue("all", uid, anonymous_id)

    if not notified_doctors:
        await safe_send_message(
            uid,
            "⚠️ Не удалось отправить анкету врачу (нет доставки в Telegram). "
            "Напишите в «🆘 Помощь» — администратор поможет.\n\n"
            + (
                f"Вы в общей очереди, позиция: {queue_position}."
                if queue_position is not None
                else "Попробуйте /start позже."
            ),
            reply_markup=ReplyKeyboardRemove(),
        )
    elif queue_position is not None:
        await safe_send_message(
            uid,
            "✅ Информация о питомце передана врачу!\n\n"
            f"Вы добавлены в очередь. Позиция: {queue_position}.\n"
            "Врач скоро свяжется с вами.",
            reply_markup=ReplyKeyboardRemove(),
        )
    else:
        if offline_intake:
            cur_nm = await db.execute(
                "SELECT doctor_name FROM consultations WHERE id = ?",
                (consultation_id,),
            )
            dnr = await cur_nm.fetchone()
            dname_esc = escape(str(dnr[0] if dnr and dnr[0] else "врач"))
            await safe_send_message(
                uid,
                "✅ <b>Оплата подтверждена! Анкета заполнена.</b>\n\n"
                f"⚠️ Врач <b>{dname_esc}</b> сейчас не в сети, но ваш вопрос принят.\n\n"
                "📅 Ответ придёт в течение 24 часов.\n"
                f"🆔 Номер консультации: <b>#{consultation_id}</b>\n\n"
                "Вы получите уведомление, когда врач начнёт консультацию.",
                parse_mode="HTML",
                reply_markup=ReplyKeyboardRemove(),
            )
        else:
            await safe_send_message(
                uid,
                "✅ Информация о питомце передана назначенному врачу!\n"
                "Он получит анкету и сможет начать консультацию.",
                reply_markup=ReplyKeyboardRemove(),
            )
    
    await state.clear()


@router.callback_query(lambda c: c.data.startswith("rate:"))
async def rate_doctor(call: CallbackQuery):
    data = call.data.split(":")
    consultation_id = int(data[1])
    doctor_id = int(data[2])
    rating = int(data[3])
    user_id = call.from_user.id
    
    from database.db import get_db
    db = await get_db()
    await db.execute('''
        INSERT OR IGNORE INTO doctor_ratings (doctor_id, client_id, consultation_id, rating)
        VALUES (?, ?, ?, ?)
    ''', (doctor_id, user_id, consultation_id, rating))
    await db.commit()
    
    await call.message.edit_text(f"⭐ Спасибо за оценку! Вы поставили {rating}")
    await call.answer()


@router.callback_query(lambda c: c.data == "skip_rating")
async def skip_rating(call: CallbackQuery):
    await call.message.edit_text("Оценка пропущена.")
    await call.answer()


@router.message(F.text == "📋 Мои консультации")
@router.message(Command("my_consultations"))
async def my_consultations(message: Message):
    user_id = message.from_user.id
    
    if not await user_in_client_context(user_id):
        await safe_send_message(user_id, "⛔ Эта команда только для клиентов.")
        return

    from database.consultations import get_user_consultations
    consultations = await get_user_consultations(user_id)
    
    if not consultations:
        await safe_send_message(user_id, "📭 У вас пока нет консультаций.")
        return
    
    text = "📋 <b>Ваши консультации</b>\n\n"
    for cons in consultations:
        status_emoji = "✅" if cons[3] == "ended" else "⚠️" if cons[3] == "auto_ended" else "⏳"
        date = cons[4][:10] if cons[4] else "дата неизвестна"
        text += f"{status_emoji} #{cons[0]} — {cons[1] or 'Врач не назначен'} от {date}\n"
    
    await safe_send_message(user_id, text, parse_mode="HTML")


@router.message(F.text == "🆘 Помощь")
async def help_button(message: Message):
    user_id = message.from_user.id

    if not await user_in_client_context(user_id):
        await safe_send_message(user_id, "🆘 В панели врача/админа используйте команды или /client для клиентского меню.")
        return
    
    await safe_send_message(
        user_id,
        "🆘 <b>Помощь и поддержка</b>\n\n"
        "Выберите действие:",
        reply_markup=get_support_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(lambda c: c.data == "contact_admin")
async def contact_admin(call: CallbackQuery, state: FSMContext):
    await state.set_state(WaitingState.waiting_for_admin_message)
    await call.message.edit_text(
        "📝 Напишите ваше сообщение администратору.\n\n"
        "Опишите проблему. Администратор ответит вам в этот чат.\n\n"
        "Чтобы отменить — отправьте /cancel."
    )
    await call.answer()


@router.message(Command("cancel"), WaitingState.waiting_for_admin_message)
async def cancel_admin_message(message: Message, state: FSMContext):
    await state.clear()
    await safe_send_message(
        message.from_user.id,
        "❌ Отправка сообщения отменена.",
        reply_markup=get_support_keyboard(),
    )


@router.callback_query(lambda c: c.data == "support_history")
async def support_history_callback(call: CallbackQuery):
    user_id = call.from_user.id
    if not await user_in_client_context(user_id):
        await call.answer("Сначала переключитесь в режим клиента: /client", show_alert=True)
        return
    hist = await format_user_history(user_id, limit=30)
    if not hist:
        await safe_send_message(user_id, "📭 Пока нет переписки с поддержкой.")
    else:
        escaped = escape(hist)
        header = "📜 <b>Последние сообщения с поддержкой</b>\n\n"
        full = header + f"<pre>{escaped}</pre>"
        if len(full) <= 4000:
            await safe_send_message(user_id, full, parse_mode="HTML")
        else:
            await safe_send_message(
                user_id,
                header + "<i>(сообщения разбиты на части)</i>",
                parse_mode="HTML",
            )
            for chunk in split_text_chunks(escaped, 3800):
                await safe_send_message(user_id, f"<pre>{chunk}</pre>", parse_mode="HTML")
    await call.answer()


@router.message(WaitingState.waiting_for_admin_message)
async def forward_to_admin(message: Message, state: FSMContext):
    user_id = message.from_user.id
    tg_user = message.from_user.username
    first_name = message.from_user.first_name
    display_for_db = tg_user or first_name or ""

    if not message.text or not message.text.strip():
        await safe_send_message(
            user_id,
            "⚠️ Отправьте текстовое сообщение (без вложений). Для отмены — /cancel.",
        )
        return

    text = message.text.strip()
    request_id = await create_support_ticket(user_id, display_for_db, text)
    set_active_support_ticket(user_id, request_id)

    await notify_support_ticket_created(
        user_id,
        tg_user,
        first_name,
        text,
        request_id,
    )

    await safe_send_message(
        user_id,
        "✅ Ваше обращение №{rid} принято!\n"
        "Администратор ответит в ближайшее время.\n\n"
        "Ваше сообщение:\n{msg}".format(rid=request_id, msg=text),
    )
    await state.clear()


@router.message(F.text == "🔙 Назад")
async def back_to_previous(message: Message, state: FSMContext):
    kb = await client_main_menu_keyboard()
    await safe_send_message(
        message.from_user.id,
        "🐾 <b>Выберите тему консультации:</b>\n\n"
        "Показаны только направления, по которым сейчас есть врачи в сети.",
        reply_markup=kb,
        parse_mode="HTML",
    )


@router.callback_query(
    lambda c: c.data in ("back_to_topics", "back_to_main", "back_to_category"),
)
async def back_to_topics_inline(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.answer()
    try:
        await call.message.delete()
    except Exception:
        pass
    kb = await client_main_menu_keyboard()
    await safe_send_message(
        call.from_user.id,
        "🐾 <b>Выберите тему консультации:</b>",
        reply_markup=kb,
        parse_mode="HTML",
    )


@router.callback_query(lambda c: c.data == "my_cons")
async def my_cons_callback(call: CallbackQuery):
    await my_consultations(call.message)
    await call.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("cli_end_cf:"))
async def client_end_consultation_from_reminder(call: CallbackQuery):
    """Inline «Завершить консультацию» из напоминания неактивности (ждём клиента)."""
    try:
        client_id = int(call.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await call.answer("Некорректные данные.", show_alert=True)
        return
    if call.from_user.id != client_id:
        await call.answer("⛔ Недоступно.", show_alert=True)
        return
    raw = _redis.get(f"client:{client_id}:doctor")
    if not raw:
        await call.answer("Консультация уже завершена.", show_alert=True)
        return
    doctor_id = int(raw)
    from handlers.doctor import finalize_consultation_from_client

    await finalize_consultation_from_client(client_id, doctor_id)
    await call.answer()


@router.message(ClientSupportFollowupFilter())
async def client_support_followup(message: Message):
    """Ответ клиента в уже открытом обращении (после шаблона/сообщений админа)."""
    uid = message.from_user.id
    txt = message.text.strip()
    rid = await ensure_active_support_ticket_for_client(uid)
    if not rid:
        return
    await add_support_message(rid, "client", uid, txt)
    await notify_admins_client_support_reply(
        uid,
        message.from_user.username,
        message.from_user.first_name,
        rid,
        txt,
    )


@router.message(ClientActiveConsultFilter())
async def relay_client_to_doctor(message: Message):
    """Текст/фото от клиента к назначенному врачу (после /next или кнопки «Начать консультацию»)."""
    from services.validators import update_client_activity

    raw = _redis.get(f"client:{message.from_user.id}:doctor")
    if not raw:
        return
    doctor_id = int(raw)
    uid = message.from_user.id
    cid = get_client_consultation_id(uid)
    if message.text:
        if cid:
            append_consultation_chat_line(cid, f"👤 Клиент: {message.text}")
        await safe_send_message(doctor_id, f"👤 Клиент: {message.text}")
    elif message.photo:
        cap = message.caption or "📷 фото"
        if cid:
            append_consultation_chat_line(cid, f"👤 Клиент: [фото] {cap}")
        await safe_send_photo(
            doctor_id,
            message.photo[-1].file_id,
            caption=f"👤 Клиент: {cap}",
        )
    update_client_activity(uid)
    record_client_message(uid, doctor_id)