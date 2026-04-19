from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

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
    """Кнопки для входящего обращения в поддержку."""
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