import redis
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message
from config import REDIS_URL

r = redis.from_url(REDIS_URL, decode_responses=True)
router = Router()


@router.message(Command("start"))
async def start_command(message: Message):
    await message.answer("start works")


