from database.db import get_db, _db_lock, sql_qmarks, write_transaction


async def save_payment(client_id: int, consultation_id: int, receipt_file_id: str, amount: int):
    """Сохраняет платёж в статусе pending"""
    db = await get_db()
    async with _db_lock:
        await db.execute('''
            INSERT INTO payments (client_id, consultation_id, amount, status, receipt_file_id)
            VALUES (?, ?, ?, 'pending', ?)
        ''', (client_id, consultation_id, int(amount), receipt_file_id))
        await db.commit()


async def save_tbank_pending_payment(
    client_id: int,
    consultation_id: int,
    amount_rubles: int,
    tbank_order_id: str,
) -> None:
    """Ожидание оплаты через Т-Банк (без фото чека)."""
    db = await get_db()
    async with _db_lock:
        await db.execute(
            "DELETE FROM payments WHERE consultation_id = ? AND status = 'pending'",
            (consultation_id,),
        )
        await db.execute(
            """
            INSERT INTO payments (client_id, consultation_id, amount, status, receipt_file_id, tbank_order_id)
            VALUES (?, ?, ?, 'pending', NULL, ?)
            """,
            (client_id, consultation_id, int(amount_rubles), tbank_order_id),
        )
        await db.commit()


async def get_payment_by_tbank_order_id(tbank_order_id: str):
    """Последняя запись по OrderId Т-Банка."""
    db = await get_db()
    cursor = await db.execute(
        """
        SELECT id, client_id, consultation_id, amount, status, tbank_order_id, tbank_payment_id
        FROM payments
        WHERE tbank_order_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (tbank_order_id,),
    )
    return await cursor.fetchone()


async def set_tbank_payment_id_for_order(tbank_order_id: str, tbank_payment_id: str) -> None:
    db = await get_db()
    async with _db_lock:
        await db.execute(
            """
            UPDATE payments SET tbank_payment_id = ?
            WHERE tbank_order_id = ? AND status = 'pending'
            """,
            (tbank_payment_id, tbank_order_id),
        )
        await db.commit()


async def confirm_payment(client_id: int, consultation_id: int):
    """Подтверждает текущий ожидающий платёж (в т.ч. при повторных консультациях клиента)."""
    async with _db_lock:
        async with write_transaction() as conn:
            if consultation_id:
                row = await conn.fetchrow(
                    sql_qmarks(
                        """
                        SELECT id FROM payments
                        WHERE client_id = ? AND consultation_id = ? AND status = 'pending'
                        FOR UPDATE
                        """
                    ),
                    client_id,
                    consultation_id,
                )
            else:
                row = await conn.fetchrow(
                    sql_qmarks(
                        """
                        SELECT id FROM payments
                        WHERE client_id = ? AND status = 'pending'
                        ORDER BY id DESC
                        LIMIT 1
                        FOR UPDATE
                        """
                    ),
                    client_id,
                )
            if not row:
                return False
            pay_id = int(row[0])

            await conn.execute(
                sql_qmarks(
                    """
                    UPDATE payments
                    SET status = 'confirmed', confirmed_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """
                ),
                pay_id,
            )

            if consultation_id:
                await conn.execute(
                    sql_qmarks(
                        """
                        UPDATE consultations
                        SET status = 'paid', payment_confirmed = TRUE
                        WHERE id = ? AND client_id = ?
                        """
                    ),
                    consultation_id,
                    client_id,
                )

        return True


async def reject_payment(client_id: int):
    """Отклоняет платёж"""
    db = await get_db()
    async with _db_lock:
        await db.execute('''
            UPDATE payments SET status = 'rejected'
            WHERE client_id = ? AND status = 'pending'
        ''', (client_id,))
        await db.commit()


async def get_pending_payment(client_id: int):
    """Возвращает ожидающий платёж клиента"""
    db = await get_db()
    cursor = await db.execute('''
        SELECT id, consultation_id FROM payments
        WHERE client_id = ? AND status = 'pending'
        ORDER BY id DESC LIMIT 1
    ''', (client_id,))
    return await cursor.fetchone()


async def get_payment_by_consultation(consultation_id: int):
    """Возвращает платёж по ID консультации"""
    db = await get_db()
    cursor = await db.execute('''
        SELECT * FROM payments WHERE consultation_id = ?
    ''', (consultation_id,))
    return await cursor.fetchone()