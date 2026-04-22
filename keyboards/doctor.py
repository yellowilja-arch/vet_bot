from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

DOCTORS_PAGE_SIZE = 8


def get_doctor_main_keyboard():
    """Главная панель врача"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🟢 Стать онлайн", callback_data="doctor_online")],
        [InlineKeyboardButton(text="🔴 Стать офлайн", callback_data="doctor_offline")],
        [InlineKeyboardButton(text="📋 Очередь", callback_data="view_queue")],
        [InlineKeyboardButton(text="📊 Статус", callback_data="show_status")],
        [InlineKeyboardButton(text="▶️ Следующий клиент (/next)", callback_data="doctor_next")],
    ])


def get_confirm_payment_inline_keyboard(client_user_id: int):
    """Под фото чека — подтверждение оплаты без ввода команды."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Оплата подтверждена", callback_data=f"cfm_pay:{client_user_id}")]
    ])


def get_start_consultation_keyboard(client_user_id: int, consultation_id: int):
    """Под анкетой — взять этого клиента в работу."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="▶️ Начать консультацию", callback_data=f"take_cn:{client_user_id}:{consultation_id}")]
    ])


def get_doctor_unanswered_reminder_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📋 Посмотреть консультации", callback_data="doc_unanswered_list")]
        ]
    )


def get_doctor_status_keyboard(has_active_client: bool = False):
    """Клавиатура для просмотра статуса"""
    buttons = [[InlineKeyboardButton(text="📋 Очередь", callback_data="view_queue")]]
    if has_active_client:
        buttons.append([InlineKeyboardButton(text="❌ Завершить текущего", callback_data="end_current")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_doctor_actions_keyboard(client_id: int):
    """Действия врача во время активной консультации (после оплаты и начала диалога)."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Завершить консультацию", callback_data=f"endcf:{client_id}")],
        [InlineKeyboardButton(text="↪️ Перенаправить другому специалисту", callback_data=f"reflist:{client_id}:0")],
        [InlineKeyboardButton(text="📋 Очередь", callback_data="view_queue")],
    ])


def get_end_confirmation_keyboard(client_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, завершить", callback_data=f"endgo:{client_id}")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="endcancel")],
    ])


def get_redirect_doctors_keyboard(
    client_id: int,
    consultation_id: int,
    rows: list[tuple[int, str]],
    page: int,
    has_next: bool,
):
    """Список врачей для перенаправления (по одному в строке)."""
    buttons = []
    for tid, label in rows:
        buttons.append([
            InlineKeyboardButton(
                text=label,
                callback_data=f"refsel:{tid}:{client_id}:{consultation_id}",
            )
        ])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"reflist:{client_id}:{page - 1}"))
    if has_next:
        nav.append(InlineKeyboardButton(text="Вперёд ➡️", callback_data=f"reflist:{client_id}:{page + 1}"))
    if nav:
        buttons.append(nav)
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="refcancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_redirect_confirm_keyboard(target_doctor_id: int, client_id: int, consultation_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="✅ Подтвердить перенаправление",
            callback_data=f"refok:{target_doctor_id}:{client_id}:{consultation_id}",
        )],
        [InlineKeyboardButton(text="🔙 К списку врачей", callback_data=f"reflist:{client_id}:0")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="refcancel")],
    ])
