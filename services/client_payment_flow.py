"""
Общий сценарий после подтверждённой оплаты: назначение врача по теме, запуск анкеты.
Используется вручную врачом и автоматически по вебхуку Т-Банка.
"""
from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey

from data.problems import SPECIALISTS
from database.consultations import (
    ensure_doctor_assigned_for_consultation,
    get_fsm_bootstrap_for_consultation,
)
from database.payments import confirm_payment
from states.forms import QuestionnaireState
from utils.helpers import safe_send_message

logger = logging.getLogger(__name__)


async def start_questionnaire_after_confirmed_payment(
    client_id: int,
    consultation_id: int,
    *,
    bot: Bot,
    dispatcher: Dispatcher,
) -> bool:
    """
    Подтверждает платёж в БД, ensure_doctor, переводит клиента в анкету (как после кнопки врача).
    """
    if not await confirm_payment(client_id, consultation_id):
        from database.db import get_db

        db = await get_db()
        cur = await db.execute("SELECT status FROM consultations WHERE id = ?", (consultation_id,))
        st = await cur.fetchone()
        if st and st[0] == "paid":
            logger.info(
                "start_questionnaire_after_confirmed_payment: уже paid, пропуск confirm %s",
                consultation_id,
            )
        else:
            logger.warning(
                "start_questionnaire_after_confirmed_payment: confirm_payment failed %s %s",
                client_id,
                consultation_id,
            )
            return False

    await ensure_doctor_assigned_for_consultation(consultation_id)

    boot = await get_fsm_bootstrap_for_consultation(consultation_id)
    if not boot:
        return False
    anon, pk, did, dname = boot[0], boot[1], boot[2], boot[3]
    problem_name = SPECIALISTS.get(pk, pk or "Консультация")
    if pk == "direct_booking" and dname:
        problem_name = f"Консультация: {dname}"

    client_state = FSMContext(
        storage=dispatcher.storage,
        key=StorageKey(bot_id=bot.id, chat_id=client_id, user_id=client_id),
    )
    payload: dict = {
        "consultation_id": consultation_id,
        "problem_name": problem_name,
        "anonymous_id": anon,
    }
    if pk == "direct_booking" and did is not None:
        payload["direct_doctor_id"] = int(did)
    await client_state.update_data(**payload)
    await client_state.set_state(QuestionnaireState.waiting_pet_name)
    await safe_send_message(
        client_id,
        "✅ <b>Оплата подтверждена!</b>\n\n"
        "Пожалуйста, заполните информацию о питомце.\n\n"
        "🐾 Как зовут вашего питомца?\n\n"
        "<i>(Напишите имя: Барсик, Шарик, Рекс...)</i>",
        parse_mode="HTML",
    )
    return True
