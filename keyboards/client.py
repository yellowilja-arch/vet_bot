from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from data.problems import CATEGORIES, PROBLEMS


def get_main_keyboard():
    """Главное меню клиента (категории)"""
    buttons = []
    for cat_key, cat_data in CATEGORIES.items():
        buttons.append([KeyboardButton(text=f"{cat_data['emoji']} {cat_data['name']}")])
    buttons.append(
        [
            KeyboardButton(text="📋 Наши врачи"),
            KeyboardButton(text="📋 Мои консультации"),
        ]
    )
    buttons.append([KeyboardButton(text="🆘 Помощь")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


def get_category_problems_keyboard(category_key: str):
    """Клавиатура с проблемами выбранной категории"""
    buttons = []
    for prob_key, prob_data in PROBLEMS.items():
        if prob_data.get("category") == category_key:
            buttons.append([KeyboardButton(text=prob_data["name"])])
    buttons.append([KeyboardButton(text="🔙 Назад")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


def get_problem_info_keyboard(problem_key: str):
    """Клавиатура с кнопкой оплаты для выбранной проблемы"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Оплатить консультацию", callback_data=f"pay_problem:{problem_key}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_category")]
    ])


def get_back_keyboard():
    """Клавиатура с кнопкой 'Назад'"""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🔙 Назад")]],
        resize_keyboard=True
    )


def get_confirm_payment_keyboard():
    """Клавиатура для подтверждения оплаты"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить оплату", callback_data="confirm_payment")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_payment")]
    ])


def get_species_keyboard():
    """Клавиатура для выбора вида животного"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🐕 Собака"), KeyboardButton(text="🐈 Кошка")],
            [KeyboardButton(text="🐇 Грызун"), KeyboardButton(text="🐦 Птица")],
            [KeyboardButton(text="📝 Другое"), KeyboardButton(text="❌ Отмена")]
        ],
        resize_keyboard=True
    )


def get_condition_keyboard():
    """Клавиатура для выбора упитанности"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🟢 Худощавый"), KeyboardButton(text="🟢 Нормальный")],
            [KeyboardButton(text="🟡 Упитанный"), KeyboardButton(text="🔴 Ожирение")],
            [KeyboardButton(text="❌ Отмена")]
        ],
        resize_keyboard=True
    )


def get_rating_keyboard(consultation_id, doctor_id):
    """Клавиатура для оценки врача"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ 1", callback_data=f"rate:{consultation_id}:{doctor_id}:1"),
         InlineKeyboardButton(text="⭐ 2", callback_data=f"rate:{consultation_id}:{doctor_id}:2"),
         InlineKeyboardButton(text="⭐ 3", callback_data=f"rate:{consultation_id}:{doctor_id}:3"),
         InlineKeyboardButton(text="⭐ 4", callback_data=f"rate:{consultation_id}:{doctor_id}:4"),
         InlineKeyboardButton(text="⭐ 5", callback_data=f"rate:{consultation_id}:{doctor_id}:5")],
        [InlineKeyboardButton(text="❌ Пропустить", callback_data="skip_rating")]
    ])


def get_recent_illness_keyboard():
    """Болезни за последний месяц — быстрый ответ «не болел»."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Нет, не болел", callback_data="no_recent_illness")],
        ]
    )


def get_support_keyboard():
    """Клавиатура для поддержки"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Написать администратору", callback_data="contact_admin")],
        [InlineKeyboardButton(text="📜 История переписки", callback_data="support_history")],
        [InlineKeyboardButton(text="📋 Мои консультации", callback_data="my_cons")],
    ])


def get_waiting_keyboard():
    """Клавиатура для ожидания врача"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, я готов ждать", callback_data="wait_accept")],
        [InlineKeyboardButton(text="🔙 Выбрать другую проблему", callback_data="back_to_main")]
    ])


def get_our_doctors_inline_keyboard(lines: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    """lines: (telegram_id, текст на кнопке)"""
    rows = []
    for tid, label in lines:
        short = label if len(label) <= 58 else label[:55] + "…"
        rows.append([InlineKeyboardButton(text=short, callback_data=f"docsel:{tid}")])
    rows.append([InlineKeyboardButton(text="🔙 Главное меню", callback_data="doclist_close")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_doctor_free_pay_keyboard(doctor_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💰 Оплатить консультацию",
                    callback_data=f"pay_direct:{doctor_id}",
                )
            ],
            [InlineKeyboardButton(text="🔙 К списку врачей", callback_data="doclist_reopen")],
        ]
    )


def get_doctor_busy_keyboard(doctor_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⏳ Ждать", callback_data=f"docbusy_wait:{doctor_id}")],
            [InlineKeyboardButton(text="🔄 Выбрать другого", callback_data="doclist_reopen")],
            [InlineKeyboardButton(text="📋 Общая очередь", callback_data="docbusy_queue")],
        ]
    )


def get_doctor_offline_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Выбрать другого", callback_data="doclist_reopen")],
            [InlineKeyboardButton(text="📋 Общая очередь", callback_data="docbusy_queue")],
        ]
    )