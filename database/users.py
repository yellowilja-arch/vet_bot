import logging
from database.db import get_db

async def save_user_if_new(user_id: int, username: str = None, first_name: str = None, last_name: str = None):
    """Сохраняет пользователя в БД, если его ещё нет"""
    db = await get_db()
    cursor = await db.execute('SELECT 1 FROM users WHERE user_id = ?', (user_id,))
    exists = await cursor.fetchone()
    
    if not exists:
        full_name = f"{first_name or ''} {last_name or ''}".strip()
        try:
            await db.execute('''
                INSERT INTO users (user_id, username, first_name, last_name, full_name)
                VALUES (?, ?, ?, ?, ?)
            ''', (user_id, username, first_name, last_name, full_name))
            await db.commit()
            print(f"📝 Новый пользователь сохранён: {user_id} (@{username})")
        except Exception as e:
            # Игнорируем ситуацию гонки, если пользователь уже добавлен
            if "UNIQUE constraint failed" in str(e) or "duplicate key" in str(e).lower():
                logging.info(f"Пользователь уже есть в БД: {user_id}")
            else:
                raise

async def get_user_info(user_id: int):
    """Возвращает информацию о пользователе"""
    db = await get_db()
    cursor = await db.execute('''
        SELECT user_id, username, first_name, last_name, full_name, first_seen, last_seen
        FROM users WHERE user_id = ?
    ''', (user_id,))
    return await cursor.fetchone()

async def get_recent_users(limit: int = 50):
    """Возвращает последних пользователей"""
    db = await get_db()
    cursor = await db.execute('''
        SELECT user_id, username, full_name, last_seen
        FROM users ORDER BY last_seen DESC LIMIT ?
    ''', (limit,))
    return await cursor.fetchall()