import asyncio
import redis
from config import REDIS_URL
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram import Bot
from config import BOT_TOKEN

r = redis.from_url(REDIS_URL, decode_responses=True)
bot = Bot(token=BOT_TOKEN)

async def safe_send_message(chat_id, text, retries=3, **kwargs):
    try:
        return await bot.send_message(chat_id, text, **kwargs)
    except TelegramForbiddenError:
        print(f"⚠️ Пользователь {chat_id} заблокировал бота")
        from database.db import get_db
        db = await get_db()
        cursor = await db.execute('SELECT id FROM consultations WHERE client_id = ? AND status = "active"', (chat_id,))
        if await cursor.fetchone():
            doctor_id = r.get(f"client:{chat_id}:doctor")
            if doctor_id:
                await bot.send_message(int(doctor_id), f"⚠️ Клиент заблокировал бота. Консультация завершена.")
            await db.execute('UPDATE consultations SET status = "blocked" WHERE client_id = ? AND status = "active"', (chat_id,))
            await db.commit()
        return None
    except TelegramRetryAfter as e:
        if retries <= 0:
            return None
        await asyncio.sleep(e.retry_after)
        return await safe_send_message(chat_id, text, retries=retries - 1, **kwargs)
    except Exception as e:
        print(f"Ошибка: {e}")
        return None

async def safe_send_photo(chat_id, photo, caption=None, retries=3, **kwargs):
    try:
        return await bot.send_photo(chat_id, photo, caption=caption, **kwargs)
    except TelegramForbiddenError:
        return None
    except TelegramRetryAfter as e:
        if retries <= 0:
            return None
        await asyncio.sleep(e.retry_after)
        return await safe_send_photo(chat_id, photo, caption=caption, retries=retries - 1, **kwargs)
    except Exception as e:
        print(f"Ошибка: {e}")
        return None

def get_anonymous_id(topic, user_id):
    short_id = str(user_id)[-4:]
    prefix_map = {"dentistry": "ST", "surgery": "SR", "therapy": "TP"}
    prefix = prefix_map.get(topic, "CL")
    return f"{prefix}{short_id}"