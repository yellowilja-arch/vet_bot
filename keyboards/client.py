from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from config import TOPICS

def get_client_main_keyboard():
    """Главное меню клиента (выбор специалиста + Мои консультации)"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=TOPICS[t]) for t in TOPICS],
            [KeyboardButton(text="📋 Мои консультации")]
        ],
        resize_keyboard=True
    )

def get_payment_keyboard(topic_key):
    """Клавиатура после выбора специалиста (кнопка оплаты)"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Я оплатил", callback_data=f"paid_{topic_key}")]
    ])

def get_waiting_keyboard(topic_key):
    """Клавиатура для ожидания врача"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, я готов ждать", callback_data=f"wait:{topic_key}")],
        [InlineKeyboardButton(text="🔙 Выбрать другого врача", callback_data="back_to_menu")],
        [InlineKeyboardButton(text="👨‍⚕️ Выбрать конкретного врача", callback_data="back_to_doctor_menu")]
    ])

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

def get_doctors_list_keyboard(doctors):
    """Клавиатура для выбора конкретного врача"""
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for doc_id, name, spec in doctors:
        status_emoji = "🟢"  # будет заменяться на онлайн/офлайн
        kb.inline_keyboard.append([
            InlineKeyboardButton(text=f"{status_emoji} {name} — {TOPICS.get(spec, spec)}", callback_data=f"select_doctor:{doc_id}")
        ])
    kb.inline_keyboard.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")])
    return kb

def get_support_keyboard():
    """Клавиатура для поддержки"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Написать администратору", callback_data="contact_admin")],
        [InlineKeyboardButton(text="📋 Мои консультации", callback_data="my_cons")]
    ])