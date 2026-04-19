import redis

from aiogram import Router, F
from aiogram.filters import Command, BaseFilter
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext
from html import escape
from config import ADMIN_IDS, PHONE_NUMBER, DOCTORS, REDIS_URL
from data.problems import CATEGORIES, PROBLEMS, SPECIALISTS
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
)
from services.routing import get_doctor_by_specialization
from database.queue import add_to_queue
from database.consultations import save_consultation_start
from database.payments import save_payment
from database.users import save_user_if_new
from utils.helpers import safe_send_message, safe_send_photo, get_anonymous_id
from keyboards.client import (
    get_main_keyboard, get_category_problems_keyboard, get_problem_info_keyboard,
    get_species_keyboard, get_condition_keyboard, get_rating_keyboard,
    get_support_keyboard, get_waiting_keyboard, get_back_keyboard
)
from keyboards.admin import get_admin_main_keyboard
from keyboards.doctor import (
    get_doctor_main_keyboard,
    get_confirm_payment_inline_keyboard,
    get_start_consultation_keyboard,
)
from states.forms import PaymentState, QuestionnaireState, WaitingState
from services.bot_commands import apply_commands_for_user

router = Router()
_redis = redis.from_url(REDIS_URL, decode_responses=True)

# Точные подписи кнопок категорий (не использовать contains("🆘") — пересекается с «🆘 Помощь»)
_CATEGORY_REPLY_LABELS = tuple(f"{c['emoji']} {c['name']}" for c in CATEGORIES.values())


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
    await safe_send_message(
        user_id,
        "🐾 <b>Добро пожаловать в онлайн-консультации ветклиники!</b>\n\n"
        "Выберите категорию проблемы:",
        reply_markup=get_main_keyboard(),
        parse_mode="HTML",
    )
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
        await safe_send_message(
            user_id,
            "🐾 Выберите категорию проблемы:",
            reply_markup=get_main_keyboard(),
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
    await safe_send_message(
        uid,
        "🐾 <b>Клиентский режим</b>\nВыберите категорию проблемы:",
        reply_markup=get_main_keyboard(),
        parse_mode="HTML",
    )
    await apply_commands_for_user(message.bot, uid)


@router.message(F.text.in_(_CATEGORY_REPLY_LABELS))
async def select_category(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if not await user_in_client_context(user_id):
        return
    
    selected_category = None
    for cat_key, cat_data in CATEGORIES.items():
        if message.text == f"{cat_data['emoji']} {cat_data['name']}":
            selected_category = cat_key
            break
    
    if not selected_category:
        return
    
    await state.update_data(selected_category=selected_category)
    await safe_send_message(
        user_id,
        f"📋 <b>{CATEGORIES[selected_category]['name']}</b>\n\n"
        f"Выберите проблему:",
        reply_markup=get_category_problems_keyboard(selected_category),
        parse_mode="HTML"
    )


@router.message(lambda m: m.text in [p["name"] for p in PROBLEMS.values()])
async def select_problem(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if not await user_in_client_context(user_id):
        return
    
    selected_problem = None
    for prob_key, prob_data in PROBLEMS.items():
        if message.text == prob_data["name"]:
            selected_problem = prob_key
            break
    
    if not selected_problem:
        return
    
    prob_data = PROBLEMS[selected_problem]
    
    specialists_list = []
    for spec in prob_data.get("specialists", []):
        specialists_list.append(SPECIALISTS.get(spec, spec))
    
    specialists_text = ", ".join(specialists_list) if specialists_list else "Любой специалист"
    
    await state.update_data(
        selected_problem=selected_problem,
        problem_name=prob_data["name"],
        problem_price=prob_data["price"],
        problem_specialists=prob_data.get("specialists", []),
        problem_description=prob_data.get("description", "")
    )
    
    if prob_data.get("urgent", False):
        urgent_text = "\n\n⚠️ <b>Это экстренный случай! Врач свяжется с вами в ближайшее время.</b>"
    else:
        urgent_text = ""
    
    await safe_send_message(
        user_id,
        f"📋 <b>{prob_data['name']}</b>\n\n"
        f"📝 {prob_data['description']}\n\n"
        f"👨‍⚕️ Специалисты: {specialists_text}\n"
        f"💰 Стоимость: {prob_data['price']} ₽{urgent_text}\n\n"
        f"После оплаты вам нужно будет заполнить информацию о питомце.",
        reply_markup=get_problem_info_keyboard(selected_problem),
        parse_mode="HTML"
    )


@router.callback_query(lambda c: c.data.startswith("pay_problem:"))
async def pay_problem(call: CallbackQuery, state: FSMContext):
    problem_key = call.data.split(":")[1]
    prob_data = PROBLEMS[problem_key]
    
    await state.update_data(
        problem_key=problem_key,
        problem_price=prob_data["price"]
    )
    
    await call.message.edit_text(
        f"💰 <b>Оплата консультации</b>\n\n"
        f"Услуга: {prob_data['name']}\n"
        f"Сумма: {prob_data['price']} ₽\n\n"
        f"📞 Оплата по номеру телефона (СБП):\n"
        f"<code>{PHONE_NUMBER}</code>\n\n"
        f"✅ После оплаты нажмите кнопку ниже и отправьте чек.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Я оплатил", callback_data="paid_confirm")]
        ]),
        parse_mode="HTML"
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
            await safe_send_message(user_id, "❌ Ошибка: проблема не выбрана. Начните заново с /start")
            await state.clear()
            return
        
        prob_data = PROBLEMS[problem_key]
        anonymous_id = get_anonymous_id(problem_key, user_id)
        
        consultation_id = await save_consultation_start(user_id, anonymous_id, None, problem_key)
        if not consultation_id:
            await safe_send_message(user_id, "❌ Ошибка: не удалось создать консультацию.")
            await state.clear()
            return
        
        await save_payment(user_id, consultation_id, message.photo[-1].file_id)
        
        specialists = prob_data.get("specialists", [])
        notified = False
        
        for spec in specialists:
            doctor_id = get_doctor_by_specialization(spec)
            if doctor_id:
                await safe_send_photo(
                    doctor_id,
                    message.photo[-1].file_id,
                    caption=f"🧾 <b>НОВЫЙ ЧЕК</b>\n"
                            f"👤 Клиент: {anonymous_id}\n"
                            f"📂 Проблема: {prob_data['name']}\n"
                            f"👨‍⚕️ Специализация: {SPECIALISTS.get(spec, spec)}\n\n"
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
                    caption=f"🧾 <b>НОВЫЙ ЧЕК (нет подходящего врача)</b>\n"
                            f"👤 Клиент: {anonymous_id}\n"
                            f"📂 Проблема: {prob_data['name']}\n"
                            f"Требуемые специалисты: {', '.join(specialists)}\n\n"
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
        "Например: <b>Мейн-кун</b> или <b>Дворняга</b>",
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
    await send_pet_info_to_doctor(call.message, state)


@router.message(QuestionnaireState.waiting_chronic)
async def process_chronic(message: Message, state: FSMContext):
    chronic = message.text
    await state.update_data(chronic=chronic)
    await send_pet_info_to_doctor(message, state)


async def send_pet_info_to_doctor(message: Message, state: FSMContext):
    data = await state.get_data()
    
    species = data.get("species", "Не указан")
    age = data.get("age", "Не указан")
    weight = data.get("weight", "Не указан")
    breed = data.get("breed", "Не указана")
    condition = data.get("condition", "Не указана")
    chronic = data.get("chronic", "Не указано")
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
            pet_species = ?,
            pet_age = ?,
            pet_weight = ?,
            pet_breed = ?,
            pet_condition = ?,
            pet_chronic = ?
        WHERE id = ?
    ''', (species, age, weight, breed, condition, chronic, consultation_id))
    await db.commit()

    uid = _client_telegram_id(message)
    
    vet_message = (
        f"🆕 <b>НОВАЯ КОНСУЛЬТАЦИЯ</b>\n\n"
        f"📂 Проблема: {data.get('problem_name', 'Не указана')}\n"
        f"👤 Клиент ID: {data.get('anonymous_id', 'Не указан')}\n\n"
        f"📋 <b>ИНФОРМАЦИЯ О ПИТОМЦЕ</b>\n"
        f"🐾 Вид: {species}\n"
        f"📅 Возраст: {age}\n"
        f"⚖️ Вес: {weight}\n"
        f"🐕 Порода: {breed}\n"
        f"📊 Упитанность: {condition}\n"
        f"💊 Хронические заболевания: {chronic}\n"
    )

    cursor = await db.execute(
        "SELECT problem_key FROM consultations WHERE id = ?", (consultation_id,)
    )
    pk_row = await cursor.fetchone()
    problem_key = pk_row[0] if pk_row else None
    prob_data = PROBLEMS.get(problem_key, {}) if problem_key else {}
    specialists = prob_data.get("specialists", [])
    notified_doctors = set()
    for spec in specialists:
        for doctor_tid in DOCTORS.get(spec, []):
            if doctor_tid in notified_doctors:
                continue
            notified_doctors.add(doctor_tid)
            await safe_send_message(
                doctor_tid,
                vet_message,
                parse_mode="HTML",
                reply_markup=get_start_consultation_keyboard(uid, consultation_id),
            )
    if not notified_doctors:
        from database.doctors import get_all_doctors
        for row in await get_all_doctors():
            doctor_tid = row[0]
            await safe_send_message(
                doctor_tid,
                vet_message,
                parse_mode="HTML",
                reply_markup=get_start_consultation_keyboard(uid, consultation_id),
            )
    
    queue_position = await add_to_queue("all", uid, anonymous_id)
    
    await safe_send_message(
        uid,
        "✅ Информация о питомце передана врачу!\n\n"
        f"Вы добавлены в очередь. Позиция: {queue_position}.\n"
        "Врач скоро свяжется с вами.",
        reply_markup=ReplyKeyboardRemove()
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
        "Если у вас возникли проблемы с оплатой или консультацией,\n"
        "напишите администратору:",
        reply_markup=get_support_keyboard(),
        parse_mode="HTML"
    )


@router.callback_query(lambda c: c.data == "contact_admin")
async def contact_admin(call: CallbackQuery, state: FSMContext):
    await state.set_state(WaitingState.waiting_for_admin_message)
    await call.message.edit_text(
        "📝 Напишите ваше сообщение администратору.\n\n"
        "Опишите проблему. Администратор ответит вам в этот чат."
    )
    await call.answer()


@router.message(WaitingState.waiting_for_admin_message)
async def forward_to_admin(message: Message, state: FSMContext):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    
    from database.db import get_db
    db = await get_db()
    cursor = await db.execute('''
        INSERT INTO support_requests (user_id, username, message)
        VALUES (?, ?, ?)
    ''', (user_id, username, message.text))
    await db.commit()
    request_id = cursor.lastrowid
    
    from config import ADMIN_IDS
    for admin_id in ADMIN_IDS:
        await safe_send_message(
            admin_id,
            f"📬 <b>НОВОЕ ОБРАЩЕНИЕ В ПОДДЕРЖКУ</b>\n\n"
            f"👤 От: @{username} (ID: {user_id})\n"
            f"🆔 #{request_id}\n"
            f"📝 Текст:\n<pre>{escape(message.text or '')}</pre>",
            parse_mode="HTML"
        )
    
    await safe_send_message(user_id, "✅ Ваше сообщение отправлено администратору.")
    await state.clear()


@router.message(F.text == "🔙 Назад")
async def back_to_previous(message: Message, state: FSMContext):
    data = await state.get_data()
    selected_category = data.get("selected_category")
    
    if selected_category:
        await safe_send_message(
            message.from_user.id,
            f"📋 <b>{CATEGORIES[selected_category]['name']}</b>\n\n"
            f"Выберите проблему:",
            reply_markup=get_category_problems_keyboard(selected_category),
            parse_mode="HTML"
        )
    else:
        await safe_send_message(
            message.from_user.id,
            "🐾 Выберите категорию проблемы:",
            reply_markup=get_main_keyboard(),
            parse_mode="HTML"
        )


@router.callback_query(lambda c: c.data == "back_to_category")
async def back_to_category(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected_category = data.get("selected_category")
    
    if selected_category:
        await call.message.edit_text(
            f"📋 <b>{CATEGORIES[selected_category]['name']}</b>\n\n"
            f"Выберите проблему:",
            reply_markup=get_category_problems_keyboard(selected_category),
            parse_mode="HTML"
        )
    else:
        await call.message.edit_text(
            "🐾 Выберите категорию проблемы:",
            reply_markup=get_main_keyboard(),
            parse_mode="HTML"
        )
    await call.answer()


@router.callback_query(lambda c: c.data == "back_to_main")
async def back_to_main(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text(
        "🐾 Выберите категорию проблемы:",
        reply_markup=get_main_keyboard(),
        parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(lambda c: c.data == "my_cons")
async def my_cons_callback(call: CallbackQuery):
    await my_consultations(call.message)
    await call.answer()


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