import redis
from config import REDIS_URL
from database.db import get_db, _db_lock
from data.problems import SPECIALISTS

r = redis.from_url(REDIS_URL, decode_responses=True)


async def add_to_queue(topic: str, user_id: int, anonymous_id: str):
    """Добавляет клиента в очередь (SQLite + Redis)"""
    db = await get_db()
    async with _db_lock:
        cursor = await db.execute('''
            INSERT INTO queue (topic, user_id, anonymous_id, status)
            VALUES (?, ?, ?, 'waiting')
        ''', (topic, user_id, anonymous_id))
        await db.commit()
        queue_id = cursor.lastrowid
    
    r.rpush(f"queue:{topic}", f"{user_id}:{anonymous_id}:{queue_id}")
    r.sadd(f"queue_set:{topic}", user_id)
    return r.llen(f"queue:{topic}")


async def pop_from_queue(topic: str):
    """Извлекает клиента из очереди (Redis + SQLite)"""
    queue_key = f"queue:{topic}"
    item = r.lpop(queue_key)
    if not item:
        return None, None, None
    
    parts = item.split(":")
    if len(parts) != 3:
        return None, None, None
    
    user_id = int(parts[0])
    anonymous_id = parts[1]
    queue_id = int(parts[2])
    
    db = await get_db()
    async with _db_lock:
        await db.execute('UPDATE queue SET status = "processing" WHERE id = ?', (queue_id,))
        await db.commit()
        r.srem(f"queue_set:{topic}", user_id)
    
    return user_id, anonymous_id, queue_id


async def confirm_queue_processed(queue_id: int):
    """Подтверждает успешную обработку клиента из очереди"""
    db = await get_db()
    async with _db_lock:
        await db.execute('UPDATE queue SET status = "processed" WHERE id = ?', (queue_id,))
        await db.commit()


async def get_queue_length(topic: str):
    """Возвращает длину очереди"""
    return r.llen(f"queue:{topic}")


async def get_queue_items(topic: str, limit: int = 10):
    """Возвращает список клиентов в очереди"""
    queue_key = f"queue:{topic}"
    items = r.lrange(queue_key, 0, limit - 1)
    result = []
    for item in items:
        parts = item.split(":")
        if len(parts) == 3:
            result.append((int(parts[0]), parts[1], int(parts[2])))
    return result


async def get_queue_position(topic: str, user_id: int):
    """Возвращает позицию пользователя в очереди"""
    queue_key = f"queue:{topic}"
    queue = r.lrange(queue_key, 0, -1)
    for i, item in enumerate(queue):
        parts = item.split(":")
        if len(parts) == 3 and int(parts[0]) == user_id:
            return i + 1
    return None


async def remove_from_queue(topic: str, user_id: int):
    """Удаляет пользователя из очереди"""
    queue_key = f"queue:{topic}"
    set_key = f"queue_set:{topic}"
    
    queue = r.lrange(queue_key, 0, -1)
    for item in queue:
        parts = item.split(":")
        if len(parts) == 3 and int(parts[0]) == user_id:
            r.lrem(queue_key, 1, item)
            break
    
    r.srem(set_key, user_id)
    
    db = await get_db()
    async with _db_lock:
        await db.execute('''
            UPDATE queue SET status = "cancelled"
            WHERE user_id = ? AND status = "waiting"
        ''', (user_id,))
        await db.commit()


async def restore_queue_from_db():
    """Восстанавливает очередь из SQLite при старте"""
    db = await get_db()
    for topic in SPECIALISTS.keys():
        r.delete(f"queue:{topic}")
        r.delete(f"queue_set:{topic}")
        
        cursor = await db.execute('''
            SELECT user_id, anonymous_id, id FROM queue
            WHERE topic = ? AND status = 'waiting'
            ORDER BY id
        ''', (topic,))
        rows = await cursor.fetchall()
        for user_id, anonymous_id, queue_id in rows:
            r.rpush(f"queue:{topic}", f"{user_id}:{anonymous_id}:{queue_id}")
            r.sadd(f"queue_set:{topic}", user_id)
        
        cursor = await db.execute('''
            SELECT user_id, anonymous_id, id FROM queue
            WHERE topic = ? AND status = 'processing' 
            AND created_at < datetime('now', '-60 seconds')
            ORDER BY id
        ''', (topic,))
        rows = await cursor.fetchall()
        for user_id, anonymous_id, queue_id in rows:
            r.rpush(f"queue:{topic}", f"{user_id}:{anonymous_id}:{queue_id}")
            r.sadd(f"queue_set:{topic}", user_id)
            await db.execute('UPDATE queue SET status = "waiting" WHERE id = ?', (queue_id,))
        await db.commit()
        
        print(f"🔄 Восстановлена очередь {topic}: {len(rows)} клиентов")


async def clear_queue(topic: str):
    """Очищает всю очередь (для админов)"""
    queue_key = f"queue:{topic}"
    set_key = f"queue_set:{topic}"
    
    r.delete(queue_key)
    r.delete(set_key)
    
    db = await get_db()
    async with _db_lock:
        await db.execute('''
            UPDATE queue SET status = "cancelled"
            WHERE topic = ? AND status = "waiting"
        ''', (topic,))
        await db.commit()