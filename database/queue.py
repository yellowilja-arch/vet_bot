import redis
from config import REDIS_URL, TOPICS
from database.db import get_db

r = redis.from_url(REDIS_URL, decode_responses=True)

async def add_to_queue(topic: str, user_id: int, anonymous_id: str):
    """Добавляет клиента в очередь (SQLite + Redis)"""
    db = await get_db()
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
    await db.execute('UPDATE queue SET status = "processed" WHERE id = ?', (queue_id,))
    await db.commit()
    r.srem(f"queue_set:{topic}", user_id)
    
    return user_id, anonymous_id, queue_id

async def get_queue_length(topic: str):
    """Возвращает длину очереди"""
    return r.llen(f"queue:{topic}")

async def restore_queue_from_db():
    """Восстанавливает очередь из SQLite при старте"""
    db = await get_db()
    for topic in TOPICS.keys():
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
        print(f"🔄 Восстановлена очередь {topic}: {len(rows)} клиентов")