from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router()

@router.message(Command("ping"))
async def ping_command(message: Message):
    await message.answer("pong")

@router.message(Command("stats"))
async def stats_command(message: Message):
    await message.answer("✅ stats работает!")