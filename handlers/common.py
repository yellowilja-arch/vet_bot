import redis
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext
from config import REDIS_URL, ADMIN_IDS
from services.validators import is_blocked, is_doctor, is_admin, get_doctor_status, get_current_client, set_doctor_status, update_doctor_activity
from database.doctors import get_all_doctors
from database.queue import get_queue_length
from database.users import save_user_if_new
from utils.helpers import safe_send_message, safe_send_photo, get_anonymous_id
from keyboards.client import get_main_keyboard
from keyboards.doctor import get_doctor_main_keyboard, get_doctor_status_keyboard
from states.forms import PaymentState

r = redis.from_url(REDIS_URL, decode_responses=True)
router = Router()


@router.message(Command("reset_state"))
async def reset_state(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("✅ Состояние сброшено. Напишите /start")

