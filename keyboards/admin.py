import config as _cfg
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

from data.problems import SPECIALISTS, SPECIALIZATION_KEYS


def _can_admin_bulk_operations(user_id: int) -> bool:
    """Работает и со старым config.py без can_admin_bulk_operations."""
    fn = getattr(_cfg, "can_admin_bulk_operations", None)
    if callable(fn):
        return fn(user_id)
    forbidden = getattr(_cfg, "ADMIN_BULK_OPS_FORBIDDEN_IDS", None)
    if forbidden is not None:
        return user_id not in forbidden
    line = int(getattr(_cfg, "SUPPORT_LINE_ADMIN_ID", 146617413) or 146617413)
    return user_id != line


def get_admin_main_keyboard(user_id: int | None = None):
    """Главная панель администратора. У ограниченного админа нет массового сброса."""
    rows: list[list[KeyboardButton]] = [
        [KeyboardButton(text="📬 Обращения"), KeyboardButton(text="📊 Статистика")],
        [KeyboardButton(text="🩺 Здоровье"), KeyboardButton(text="🚫 Заблокировать")],
        [KeyboardButton(text="✅ Разблокировать"), KeyboardButton(text="➕ Добавить врача")],
        [KeyboardButton(text="✏️ Изменить врача"), KeyboardButton(text="➖ Удалить врача")],
    ]
    if user_id is None or _can_admin_bulk_operations(user_id):
        rows.append([KeyboardButton(text="🔄 Сброс состояний")])
    rows.append([KeyboardButton(text="💾 Бэкап")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def get_escalation_reply_keyboard(user_id: int, request_id: int) -> InlineKeyboardMarkup:
    """Только «Ответить» — уведомление об эскалации главному админу."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📝 Ответить",
                    callback_data=f"support_reply:{user_id}:{request_id}",
                )
            ],
        ]
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


def get_doctor_multi_spec_keyboard(
    selected: set[str],
    toggle_prefix: str,
    done_data: str,
    cancel_data: str,
) -> InlineKeyboardMarkup:
    """Мультивыбор специализаций (toggle_prefix:key, готово/отмена)."""
    specs = [(k, SPECIALISTS[k]) for k in SPECIALIZATION_KEYS if k in SPECIALISTS]
    rows: list = []
    row: list = []
    for key, title in specs:
        mark = "✓ " if key in selected else ""
        short = mark + (title if len(title) <= 18 else title[:15] + "…")
        if len(short) > 64:
            short = short[:61] + "…"
        row.append(
            InlineKeyboardButton(text=short, callback_data=f"{toggle_prefix}:{key}")
        )
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append(
        [
            InlineKeyboardButton(text="✅ Готово", callback_data=done_data),
            InlineKeyboardButton(text="❌ Отмена", callback_data=cancel_data),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_edit_doctor_active_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🟢 Активен", callback_data="admndoeditact:1"),
                InlineKeyboardButton(text="🔴 Не активен", callback_data="admndoeditact:0"),
            ],
        ]
    )