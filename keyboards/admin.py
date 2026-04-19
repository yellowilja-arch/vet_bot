from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

from data.problems import SPECIALISTS, SPECIALIZATION_KEYS

def get_admin_main_keyboard():
    """Главная панель администратора"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📬 Обращения"), KeyboardButton(text="📊 Статистика")],
            [KeyboardButton(text="🩺 Здоровье"), KeyboardButton(text="🚫 Заблокировать")],
            [KeyboardButton(text="✅ Разблокировать"), KeyboardButton(text="➕ Добавить врача")],
            [KeyboardButton(text="➖ Удалить врача"), KeyboardButton(text="🔄 Сброс состояний")],
            [KeyboardButton(text="💾 Бэкап")],
        ],
        resize_keyboard=True
    )


def get_admin_support_keyboard(user_id: int, request_id: int):
    """Кнопки для входящего обращения в поддержку (только у администраторов)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📝 Ответить",
                    callback_data=f"support_reply:{user_id}:{request_id}",
                ),
                InlineKeyboardButton(
                    text="✅ Закрыть",
                    callback_data=f"support_close:{user_id}:{request_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📋 Шаблон: вопрос/проблема",
                    callback_data=f"support_tpl:{user_id}:{request_id}",
                ),
            ],
        ]
    )


def get_support_queue_keyboard(
    items: list[tuple[int, int, str | None]],
) -> InlineKeyboardMarkup:
    """
    Список открытых обращений: (request_id, user_id, username).
    По одной кнопке на строку.
    """
    rows = []
    for rid, uid, uname in items:
        label = f"№{rid} · @{uname}" if uname else f"№{rid} · id {uid}"
        if len(label) > 60:
            label = label[:57] + "..."
        rows.append(
            [
                InlineKeyboardButton(
                    text=label,
                    callback_data=f"support_reply:{uid}:{rid}",
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_add_doctor_spec_keyboard() -> InlineKeyboardMarkup:
    """Инлайн-выбор специализации при добавлении врача (3 кнопки в ряд)."""
    specs = [(k, SPECIALISTS[k]) for k in SPECIALIZATION_KEYS if k in SPECIALISTS]
    rows: list = []
    row: list = []
    for _key, title in specs:
        short = title if len(title) <= 20 else title[:17] + "…"
        row.append(InlineKeyboardButton(text=short, callback_data=f"admnspec:{_key}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="admnspec_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)