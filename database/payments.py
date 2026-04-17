from database.db import get_db

async def save_payment(client_id: int, consultation_id: int, receipt_file_id: str):
    """Сохраняет платёж в статусе pending"""
    db = await get_db()
    await db.execute('''
        INSERT INTO payments (client_id, consultation_id, amount, status, receipt_file_id)
        VALUES (?, ?, 500, "pending", ?)
    ''', (client_id, consultation_id, receipt_file_id))
    await db.commit()

async def confirm_payment(client_id: int, consultation_id: int):
    """Подтверждает платёж"""
    db = await get_db()
    
    # Проверяем, не подтверждён ли уже
    cursor = await db.execute('''
        SELECT status FROM payments WHERE client_id = ? AND status = "confirmed"
    ''', (client_id,))
    if await cursor.fetchone():
        return False
    
    await db.execute('''
        UPDATE payments 
        SET status = "confirmed", confirmed_at = CURRENT_TIMESTAMP
        WHERE client_id = ? AND status = "pending"
    ''', (client_id,))
    await db.commit()
    
    if consultation_id:
        await db.execute('''
            UPDATE consultations SET status = 'paid', payment_confirmed = 1
            WHERE id = ?
        ''', (consultation_id,))
        await db.commit()
    
    return True

async def get_pending_payment(client_id: int):
    """Возвращает ожидающий платёж клиента"""
    db = await get_db()
    cursor = await db.execute('''
        SELECT id, consultation_id FROM payments
        WHERE client_id = ? AND status = "pending"
        ORDER BY id DESC LIMIT 1
    ''', (client_id,))
    return await cursor.fetchone()