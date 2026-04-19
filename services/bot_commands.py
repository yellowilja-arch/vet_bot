"""Команды меню Telegram (/ …) по ролям — BotCommandScopeChat для каждого пользователя."""

from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeChat

from config import ADMIN_IDS
from services.validators import (
    is_doctor,
    user_in_admin_context,
    user_in_doctor_context,
)

# Клиент (по умолчанию для всего бота и для чистых клиентов)
CLIENT_COMMANDS_BASE = [
    BotCommand(command="start", description="Главное меню"),
    BotCommand(command="my_consultations", description="Мои консультации"),
    BotCommand(command="feedback", description="Обратная связь"),
]

DOCTOR_COMMANDS = [
    BotCommand(command="start", description="Главное меню"),
    BotCommand(command="online", description="Стать онлайн"),
    BotCommand(command="offline", description="Стать офлайн"),
    BotCommand(command="next", description="Следующий из очереди"),
    BotCommand(command="status", description="Статус и очередь"),
    BotCommand(command="end", description="Завершить консультацию"),
    BotCommand(command="confirm_payment", description="Подтвердить оплату"),
    BotCommand(command="client", description="Режим клиента (тест)"),
]

ADMIN_COMMANDS = [
    BotCommand(command="start", description="Главное меню"),
    BotCommand(command="doctor", description="Панель врача"),
    BotCommand(command="stats", description="Статистика"),
    BotCommand(command="health", description="Здоровье бота"),
    BotCommand(command="ban", description="Заблокировать пользователя"),
    BotCommand(command="unban", description="Разблокировать"),
    BotCommand(command="user", description="Информация о пользователе"),
    BotCommand(command="clearqueue", description="Очистить очередь"),
    BotCommand(command="resetuser", description="Сбросить состояние user"),
    BotCommand(command="resetall", description="Сбросить все состояния"),
    BotCommand(command="adddoctor", description="Добавить врача"),
    BotCommand(command="removedoctor", description="Удалить врача"),
    BotCommand(command="doctor", description="Панель врача"),
    BotCommand(command="client", description="Режим клиента"),
]


async def _client_commands_for_user(user_id: int) -> list[BotCommand]:
    cmds = list(CLIENT_COMMANDS_BASE)
    if await is_doctor(user_id):
        cmds.append(BotCommand(command="doctor", description="Панель врача"))
    if user_id in ADMIN_IDS:
        cmds.append(BotCommand(command="admin", description="Панель администратора"))
    return cmds


async def apply_commands_for_user(bot: Bot, user_id: int) -> None:
    """Обновляет список slash-команд в меню бота для данного чата (личка)."""
    if await user_in_admin_context(user_id):
        cmds = ADMIN_COMMANDS
    elif await user_in_doctor_context(user_id):
        cmds = DOCTOR_COMMANDS
    else:
        cmds = await _client_commands_for_user(user_id)

    await bot.set_my_commands(
        cmds,
        scope=BotCommandScopeChat(chat_id=user_id),
    )


def default_scope_commands() -> list[BotCommand]:
    """Глобальный список по умолчанию (новые пользователи до первого /start)."""
    return list(CLIENT_COMMANDS_BASE)
