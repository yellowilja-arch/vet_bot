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


async def save_invoice_pending_payment(
    client_id: int,
    consultation_id: int,
    amount_rubles: int,
    invoice_payload: str,
) -> None:
    """Ожидание оплаты через Bot Payments (ЮKassa / provider token), без фото чека."""
    db = await get_db()
    async with _db_lock:
        await db.execute(
            "DELETE FROM payments WHERE consultation_id = ? AND status = 'pending'",
            (consultation_id,),
        )
        await db.execute(
            """
            INSERT INTO payments (client_id, consultation_id, amount, status, receipt_file_id, invoice_payload)
            VALUES (?, ?, ?, 'pending', NULL, ?)
            """,
            (client_id, consultation_id, int(amount_rubles), invoice_payload),
        )
        await db.commit()


async def get_pending_payment_by_invoice_payload(invoice_payload: str):
    """Ожидающая оплата по payload инвойса Telegram (до 128 байт)."""
    db = await get_db()
    cursor = await db.execute(
        """
        SELECT id, client_id, consultation_id, amount, status
        FROM payments
        WHERE invoice_payload = ? AND status = 'pending'
        ORDER BY id DESC
        LIMIT 1
        """,
        (invoice_payload,),
    )
    return await cursor.fetchone()


async def set_telegram_charge_for_invoice(
    invoice_payload: str,
    *,
    telegram_payment_charge_id: str,
    provider_payment_charge_id: str | None = None,
) -> None:
    """Сохраняет ID списания Telegram и (если есть) ID провайдера. Колонки tbank_* — legacy-имена в схеме."""
    prov = (provider_payment_charge_id or "").strip()
    db = await get_db()
    async with _db_lock:
        await db.execute(
            """
            UPDATE payments
            SET tbank_order_id = ?, tbank_payment_id = ?
            WHERE invoice_payload = ? AND status = 'pending'
            """,
            (prov, telegram_payment_charge_id, invoice_payload),
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
