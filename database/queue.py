import redis
from config import REDIS_URL
from database.db import get_db, _db_lock
from data.problems import SPECIALISTS

r = redis.from_url(REDIS_URL, decode_responses=True)


async def add_to_queue(topic: str, user_id: int, anonymous_id: str):
    """Добавляет клиента в очередь (SQLite + Redis)"""
    if r.sismember(f"queue_set:{topic}", user_id):
        return await get_queue_position(topic, user_id) or r.llen(f"queue:{topic}")

    db = await get_db()
    async with _db_lock:
        cursor = await db.execute('''
            SELECT id FROM queue
            WHERE topic = ? AND user_id = ? AND status = 'waiting'
            ORDER BY id DESC LIMIT 1
        ''', (topic, user_id))
        existing = await cursor.fetchone()
        if existing:
            queue_id = existing[0]
            if not r.sismember(f"queue_set:{topic}", user_id):
                r.rpush(f"queue:{topic}", f"{user_id}:{anonymous_id}:{queue_id}")
                r.sadd(f"queue_set:{topic}", user_id)
            return await get_queue_position(topic, user_id) or r.llen(f"queue:{topic}")

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


async def return_queue_item_to_tail(topic: str, user_id: int, anonymous_id: str, queue_id: int):
    """
    Вернуть элемент в конец очереди (если «Следующий» взял не того врача —
    клиент закреплён за другим по записи consultations.doctor_id).
    """
    queue_key = f"queue:{topic}"
    set_key = f"queue_set:{topic}"
    r.rpush(queue_key, f"{user_id}:{anonymous_id}:{queue_id}")
    r.sadd(set_key, user_id)
    db = await get_db()
    async with _db_lock:
        await db.execute(
            'UPDATE queue SET status = "waiting" WHERE id = ?',
            (queue_id,),
        )
        await db.commit()


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


async def clear_queue(topic: str) -> tuple[list[int], list[int]]:
    """
    Очищает очередь (Redis + SQLite).
    Возвращает (все client_id, затронутые сбросом; кому слать уведомление в Telegram).

    Важно: при оплате по теме врач часто прописывается в consultations сразу, а в таблицу queue
    клиент не попадает (очередь только для общего пула без предназначения). Тогда старый clear_queue
    не находил client_id и «хирург» оставался в «Мои консультации». Для topic == \"all\" дополнительно
    снимаем предназначение врача у всех консультаций paid / waiting_payment с doctor_id, пока у клиента
    нет активного диалога (status active).
    """
    from services.dialog_session import clear_dialog_session

    db = await get_db()
    async with _db_lock:
        cursor = await db.execute(
            """
            SELECT DISTINCT user_id FROM queue
            WHERE topic = ? AND status IN ("waiting", "processing")
            """,
            (topic,),
        )
        queue_user_ids = [int(row[0]) for row in await cursor.fetchall()]

        stale_preassign_ids: list[int] = []
        if topic == "all":
            cur_stale = await db.execute(
                """
                SELECT DISTINCT c.client_id FROM consultations c
                WHERE c.doctor_id IS NOT NULL
                  AND c.status IN ('paid', 'waiting_payment')
                  AND NOT EXISTS (
                      SELECT 1 FROM consultations x
                      WHERE x.client_id = c.client_id AND x.status = 'active'
                  )
                """
            )
            stale_preassign_ids = [int(row[0]) for row in await cur_stale.fetchall()]

    reset_ids = sorted(set(queue_user_ids) | set(stale_preassign_ids))

    queue_key = f"queue:{topic}"
    set_key = f"queue_set:{topic}"
    r.delete(queue_key)
    r.delete(set_key)

    async with _db_lock:
        await db.execute(
            """
            UPDATE queue SET status = "cancelled"
            WHERE topic = ? AND status IN ("waiting", "processing")
            """,
            (topic,),
        )
        if reset_ids:
            ph = ",".join("?" * len(reset_ids))
            await db.execute(
                f"""
                UPDATE consultations
                SET doctor_id = NULL, doctor_name = NULL, doctor_specialization = NULL
                WHERE doctor_id IS NOT NULL
                  AND status IN ('paid', 'waiting_payment')
                  AND client_id IN ({ph})
                """,
                reset_ids,
            )
        await db.commit()

    active_ids: set[int] = set()
    if reset_ids:
        async with _db_lock:
            ph = ",".join("?" * len(reset_ids))
            cur = await db.execute(
                f"SELECT client_id FROM consultations WHERE status = 'active' AND client_id IN ({ph})",
                reset_ids,
            )
            active_ids = {int(r[0]) for r in await cur.fetchall()}

    for uid in reset_ids:
        r.delete(f"user:{uid}:queue_position")
        if uid in active_ids:
            continue
        r.delete(f"client:{uid}:doctor")
        r.delete(f"client:{uid}:consultation")
        clear_dialog_session(uid)

    notify_ids = [u for u in reset_ids if u not in active_ids]
    return reset_ids, notify_ids