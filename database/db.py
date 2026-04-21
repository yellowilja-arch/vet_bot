"""
PostgreSQL через asyncpg. Совместимость с прежним API: get_db().execute → курсор с fetchall/fetchone,
lastrowid для INSERT в consultations / queue / support_requests, rowcount для UPDATE/DELETE, commit() — no-op.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import asyncpg

_pool: asyncpg.Pool | None = None

# Сохраняем для модулей, которые сериализуют записи (consultations, payments, queue)
_db_lock = asyncio.Lock()


def _database_dsn() -> str:
    dsn = (os.getenv("DATABASE_URL") or os.getenv("PGDATABASE_URL") or "").strip()
    if not dsn:
        raise RuntimeError(
            "Задайте DATABASE_URL или PGDATABASE_URL (PostgreSQL connection string)"
        )
    if dsn.startswith("postgres://"):
        dsn = "postgresql://" + dsn[len("postgres://") :]
    return dsn


def _qmarks_to_numbered(sql: str) -> str:
    n = 0

    def repl(_m: re.Match) -> str:
        nonlocal n
        n += 1
        return f"${n}"

    return re.sub(r"\?", repl, sql)


def _parse_cmd_rowcount(status: str) -> int:
    if not status:
        return 0
    parts = status.split()
    if parts and parts[-1].isdigit():
        return int(parts[-1])
    return 0


_INSERT_RETURNING_TABLES = frozenset(
    {"consultations", "queue", "support_requests"}
)


def _insert_table_name(sql: str) -> str | None:
    m = re.search(r"INSERT\s+INTO\s+([a-zA-Z_][a-zA-Z0-9_]*)", sql, re.IGNORECASE)
    return m.group(1).lower() if m else None


class PgCursor:
    __slots__ = ("_rows", "lastrowid", "rowcount")

    def __init__(
        self,
        *,
        rows: list[asyncpg.Record] | None = None,
        lastrowid: int | None = None,
        rowcount: int = 0,
    ):
        self._rows = rows or []
        self.lastrowid = lastrowid
        self.rowcount = rowcount

    async def fetchall(self) -> list[asyncpg.Record]:
        return list(self._rows)

    async def fetchone(self) -> asyncpg.Record | None:
        return self._rows[0] if self._rows else None


class _PgConnectionFacade:
    """Имитация соединения aiosqlite для существующего кода."""

    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def execute(self, sql: str, params: tuple | list | None = None) -> PgCursor:
        if self._pool is None:
            raise RuntimeError("Пул БД не инициализирован (вызовите init_db при старте)")
        params = tuple(params) if params is not None else ()
        q = _qmarks_to_numbered(sql)
        stripped = q.lstrip()
        head = stripped.upper()

        if head.startswith("SELECT") or head.startswith("WITH"):
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(q, *params)
            return PgCursor(rows=list(rows))

        if head.startswith("INSERT"):
            tbl = _insert_table_name(q)
            if tbl in _INSERT_RETURNING_TABLES and "RETURNING" not in head:
                q_ret = stripped.rstrip().rstrip(";") + " RETURNING id"
                async with self._pool.acquire() as conn:
                    row = await conn.fetchrow(q_ret, *params)
                rid = int(row["id"]) if row and "id" in row else None
                return PgCursor(lastrowid=rid)

            async with self._pool.acquire() as conn:
                status = await conn.execute(q, *params)
            return PgCursor(rowcount=_parse_cmd_rowcount(status))

        async with self._pool.acquire() as conn:
            status = await conn.execute(q, *params)
        return PgCursor(rowcount=_parse_cmd_rowcount(status))

    async def commit(self) -> None:
        """asyncpg фиксирует команду в execute; отдельный commit не нужен."""
        return None


async def get_db() -> _PgConnectionFacade:
    global _pool
    if _pool is None:
        raise RuntimeError("Пул PostgreSQL не создан — сначала await init_db()")
    return _PgConnectionFacade(_pool)


async def init_db() -> None:
    """Создаёт пул и схему PostgreSQL."""
    global _pool
    if _pool is not None:
        return
    dsn = _database_dsn()
    _pool = await asyncpg.create_pool(dsn, min_size=1, max_size=20, command_timeout=60)
    db = _PgConnectionFacade(_pool)
    await _run_ddl(db)
    try:
        from database.support import backfill_messages_from_legacy

        await backfill_messages_from_legacy()
    except Exception as e:
        logging.warning("support_messages backfill: %s", e)
    print("✅ База данных PostgreSQL инициализирована")


async def _run_ddl(db: _PgConnectionFacade) -> None:
    stmts = [
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            full_name TEXT,
            first_seen TIMESTAMP DEFAULT NOW(),
            last_seen TIMESTAMP DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS doctors (
            id SERIAL PRIMARY KEY,
            telegram_id BIGINT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            specialization TEXT NOT NULL,
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS doctor_specializations (
            telegram_id BIGINT NOT NULL,
            specialization TEXT NOT NULL,
            PRIMARY KEY (telegram_id, specialization)
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_doctor_specializations_spec
        ON doctor_specializations(specialization)
        """,
        """
        CREATE TABLE IF NOT EXISTS consultations (
            id SERIAL PRIMARY KEY,
            client_id BIGINT NOT NULL,
            client_anonymous_id TEXT NOT NULL,
            doctor_id BIGINT,
            doctor_name TEXT,
            doctor_specialization TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW(),
            ended_at TIMESTAMP,
            duration_seconds INTEGER,
            client_messages INTEGER DEFAULT 0,
            doctor_messages INTEGER DEFAULT 0,
            payment_confirmed BOOLEAN DEFAULT FALSE,
            problem_key TEXT,
            pet_species TEXT,
            pet_name TEXT,
            pet_age TEXT,
            pet_weight TEXT,
            pet_breed TEXT,
            pet_condition TEXT,
            pet_chronic TEXT,
            recent_illness TEXT,
            vaccination TEXT,
            sterilization TEXT,
            waiting_reply_since TIMESTAMP,
            offline_intake INTEGER DEFAULT 0
        )
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_active_client
        ON consultations(client_id) WHERE status = 'active'
        """,
        "DROP INDEX IF EXISTS idx_open_client_consultation",
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_open_client_consultation
        ON consultations(client_id) WHERE status IN (
            'waiting_payment', 'paid', 'active', 'waiting_doctor_offline'
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS payments (
            id SERIAL PRIMARY KEY,
            client_id BIGINT NOT NULL,
            consultation_id INTEGER,
            amount INTEGER NOT NULL,
            status TEXT NOT NULL,
            receipt_file_id TEXT,
            created_at TIMESTAMP DEFAULT NOW(),
            confirmed_at TIMESTAMP,
            tbank_order_id TEXT,
            tbank_payment_id TEXT
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_payments_tbank_order ON payments(tbank_order_id)
        """,
        """
        CREATE TABLE IF NOT EXISTS queue (
            id SERIAL PRIMARY KEY,
            topic TEXT NOT NULL,
            user_id BIGINT NOT NULL,
            anonymous_id TEXT NOT NULL,
            status TEXT DEFAULT 'waiting',
            created_at TIMESTAMP DEFAULT NOW()
        )
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_waiting_queue
        ON queue(topic, user_id) WHERE status = 'waiting'
        """,
        """
        CREATE TABLE IF NOT EXISTS doctor_ratings (
            id SERIAL PRIMARY KEY,
            doctor_id BIGINT NOT NULL,
            client_id BIGINT NOT NULL,
            consultation_id INTEGER NOT NULL,
            rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
            comment TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        )
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_rating_per_consultation
        ON doctor_ratings(client_id, consultation_id)
        """,
        """
        CREATE TABLE IF NOT EXISTS support_requests (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            username TEXT,
            message TEXT NOT NULL,
            status TEXT DEFAULT 'open',
            created_at TIMESTAMP DEFAULT NOW(),
            resolved_at TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS support_messages (
            id SERIAL PRIMARY KEY,
            request_id INTEGER NOT NULL REFERENCES support_requests(id),
            sender_role TEXT NOT NULL,
            sender_id BIGINT NOT NULL,
            body TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_support_messages_request
        ON support_messages(request_id)
        """,
        """
        CREATE TABLE IF NOT EXISTS feedback (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            username TEXT,
            feedback TEXT NOT NULL,
            status TEXT DEFAULT 'new',
            created_at TIMESTAMP DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS blacklist (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL UNIQUE,
            reason TEXT,
            blocked_by BIGINT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        )
        """,
    ]
    for s in stmts:
        await db.execute(s)

    alters = [
        "ALTER TABLE consultations ADD COLUMN IF NOT EXISTS problem_key TEXT",
        "ALTER TABLE consultations ADD COLUMN IF NOT EXISTS pet_species TEXT",
        "ALTER TABLE consultations ADD COLUMN IF NOT EXISTS pet_name TEXT",
        "ALTER TABLE consultations ADD COLUMN IF NOT EXISTS pet_age TEXT",
        "ALTER TABLE consultations ADD COLUMN IF NOT EXISTS pet_weight TEXT",
        "ALTER TABLE consultations ADD COLUMN IF NOT EXISTS pet_breed TEXT",
        "ALTER TABLE consultations ADD COLUMN IF NOT EXISTS pet_condition TEXT",
        "ALTER TABLE consultations ADD COLUMN IF NOT EXISTS pet_chronic TEXT",
        "ALTER TABLE consultations ADD COLUMN IF NOT EXISTS recent_illness TEXT",
        "ALTER TABLE consultations ADD COLUMN IF NOT EXISTS vaccination TEXT",
        "ALTER TABLE consultations ADD COLUMN IF NOT EXISTS sterilization TEXT",
        "ALTER TABLE consultations ADD COLUMN IF NOT EXISTS waiting_reply_since TIMESTAMP",
        "ALTER TABLE consultations ADD COLUMN IF NOT EXISTS offline_intake INTEGER DEFAULT 0",
        "ALTER TABLE consultations ADD COLUMN IF NOT EXISTS doctor_name TEXT",
        "ALTER TABLE payments ADD COLUMN IF NOT EXISTS tbank_order_id TEXT",
        "ALTER TABLE payments ADD COLUMN IF NOT EXISTS tbank_payment_id TEXT",
    ]
    for s in alters:
        try:
            await db.execute(s)
        except Exception as e:
            logging.warning("ALTER (миграция колонки): %s", e)

    try:
        await db.execute(
            "UPDATE doctor_specializations SET specialization = 'therapist' WHERE specialization = 'gp'"
        )
        await db.execute(
            "UPDATE doctors SET specialization = 'therapist' WHERE specialization = 'gp'"
        )
        await db.commit()
    except Exception as e:
        logging.warning("Миграция gp → therapist: %s", e)

    await db.execute(
        """
        INSERT INTO doctor_specializations (telegram_id, specialization)
        SELECT telegram_id, specialization FROM doctors
        WHERE specialization IS NOT NULL AND TRIM(specialization) != ''
        ON CONFLICT (telegram_id, specialization) DO NOTHING
        """
    )

    try:
        await db.execute(
            "UPDATE support_requests SET status = 'closed' WHERE status = 'replied'"
        )
        await db.execute(
            "UPDATE support_requests SET status = 'open' WHERE status = 'new'"
        )
    except Exception:
        pass


async def close_db_connection() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


# Совместимость: старый код бэкапов SQLite
async def checkpoint_wal_for_backup() -> None:
    """PostgreSQL: не требуется."""
    return None
