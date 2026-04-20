import asyncio
import aiosqlite
import logging
from config import DB_PATH

_db_pool = None
_db_lock = asyncio.Lock()

async def get_db():
    global _db_pool
    async with _db_lock:
        if _db_pool is None:
            _db_pool = await aiosqlite.connect(DB_PATH)
            await _db_pool.execute("PRAGMA journal_mode=WAL")
            await _db_pool.execute("PRAGMA busy_timeout=5000")
        else:
            try:
                await _db_pool.execute("SELECT 1")
            except:
                logging.error("Database connection lost, reconnecting...")
                _db_pool = await aiosqlite.connect(DB_PATH)
                await _db_pool.execute("PRAGMA journal_mode=WAL")
                await _db_pool.execute("PRAGMA busy_timeout=5000")
        return _db_pool


async def checkpoint_wal_for_backup() -> None:
    """
    Сбрасывает WAL в основной файл vet_bot.db.
    Без этого копирование только .db при journal_mode=WAL даёт неполный/«пустой» бэкап.
    """
    db = await get_db()
    await db.execute("PRAGMA wal_checkpoint(FULL)")
    await db.commit()


async def init_db():
    db = await get_db()
    
    # Пользователи
    await db.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            full_name TEXT,
            first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Врачи
    await db.execute('''
        CREATE TABLE IF NOT EXISTS doctors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER UNIQUE NOT NULL,
            name TEXT NOT NULL,
            specialization TEXT NOT NULL,
            is_active BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    await db.execute('''
        CREATE TABLE IF NOT EXISTS doctor_specializations (
            telegram_id INTEGER NOT NULL,
            specialization TEXT NOT NULL,
            PRIMARY KEY (telegram_id, specialization)
        )
    ''')
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_doctor_specializations_spec "
        "ON doctor_specializations(specialization)"
    )
    try:
        await db.execute(
            """
            INSERT OR IGNORE INTO doctor_specializations (telegram_id, specialization)
            SELECT telegram_id, specialization FROM doctors
            WHERE specialization IS NOT NULL AND TRIM(specialization) != ''
            """
        )
        await db.commit()
    except Exception as e:
        logging.warning("doctor_specializations backfill: %s", e)

    # Консультации
    await db.execute('''
        CREATE TABLE IF NOT EXISTS consultations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id INTEGER NOT NULL,
            client_anonymous_id TEXT NOT NULL,
            doctor_id INTEGER,
            doctor_name TEXT,
            doctor_specialization TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ended_at TIMESTAMP,
            duration_seconds INTEGER,
            client_messages INTEGER DEFAULT 0,
            doctor_messages INTEGER DEFAULT 0,
            payment_confirmed BOOLEAN DEFAULT 0
        )
    ''')
    
    # Добавляем колонку problem_key, если её нет
    try:
        await db.execute('ALTER TABLE consultations ADD COLUMN problem_key TEXT')
        print("✅ Колонка problem_key добавлена")
    except:
        print("ℹ️ Колонка problem_key уже существует")
    
    # Добавляем колонки для опросника, если их нет
    try:
        await db.execute('ALTER TABLE consultations ADD COLUMN pet_species TEXT')
        print("✅ Колонка pet_species добавлена")
    except:
        pass

    try:
        await db.execute('ALTER TABLE consultations ADD COLUMN pet_name TEXT')
        print("✅ Колонка pet_name добавлена")
    except:
        pass
    
    try:
        await db.execute('ALTER TABLE consultations ADD COLUMN pet_age TEXT')
        print("✅ Колонка pet_age добавлена")
    except:
        pass
    
    try:
        await db.execute('ALTER TABLE consultations ADD COLUMN pet_weight TEXT')
        print("✅ Колонка pet_weight добавлена")
    except:
        pass
    
    try:
        await db.execute('ALTER TABLE consultations ADD COLUMN pet_breed TEXT')
        print("✅ Колонка pet_breed добавлена")
    except:
        pass
    
    try:
        await db.execute('ALTER TABLE consultations ADD COLUMN pet_condition TEXT')
        print("✅ Колонка pet_condition добавлена")
    except:
        pass
    
    try:
        await db.execute('ALTER TABLE consultations ADD COLUMN pet_chronic TEXT')
        print("✅ Колонка pet_chronic добавлена")
    except:
        pass

    try:
        await db.execute('ALTER TABLE consultations ADD COLUMN recent_illness TEXT')
        print("✅ Колонка recent_illness добавлена")
    except:
        pass

    try:
        await db.execute("ALTER TABLE consultations ADD COLUMN vaccination TEXT")
        print("✅ Колонка vaccination добавлена")
    except Exception:
        pass
    try:
        await db.execute("ALTER TABLE consultations ADD COLUMN sterilization TEXT")
        print("✅ Колонка sterilization добавлена")
    except Exception:
        pass

    try:
        await db.execute(
            "ALTER TABLE consultations ADD COLUMN waiting_reply_since TIMESTAMP"
        )
        print("✅ Колонка waiting_reply_since добавлена")
    except Exception:
        pass

    try:
        await db.execute(
            "ALTER TABLE consultations ADD COLUMN offline_intake INTEGER DEFAULT 0"
        )
        print("✅ Колонка offline_intake добавлена")
    except Exception:
        pass
    
    # Уникальный индекс для активных консультаций
    await db.execute('''
        CREATE UNIQUE INDEX IF NOT EXISTS idx_active_client
        ON consultations(client_id) WHERE status = 'active'
    ''')
    await db.execute("DROP INDEX IF EXISTS idx_open_client_consultation")
    await db.execute('''
        CREATE UNIQUE INDEX IF NOT EXISTS idx_open_client_consultation
        ON consultations(client_id) WHERE status IN (
            'waiting_payment', 'paid', 'active', 'waiting_doctor_offline'
        )
    ''')
    
    # Платежи
    await db.execute('''
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id INTEGER NOT NULL,
            consultation_id INTEGER,
            amount INTEGER NOT NULL,
            status TEXT NOT NULL,
            receipt_file_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            confirmed_at TIMESTAMP
        )
    ''')
    try:
        await db.execute("ALTER TABLE payments ADD COLUMN tbank_order_id TEXT")
        print("✅ Колонка tbank_order_id добавлена")
    except Exception:
        pass
    try:
        await db.execute("ALTER TABLE payments ADD COLUMN tbank_payment_id TEXT")
        print("✅ Колонка tbank_payment_id добавлена")
    except Exception:
        pass
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_payments_tbank_order ON payments(tbank_order_id)"
    )
    
    # Очередь (бэкап)
    await db.execute('''
        CREATE TABLE IF NOT EXISTS queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            anonymous_id TEXT NOT NULL,
            status TEXT DEFAULT 'waiting',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    await db.execute('''
        CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_waiting_queue
        ON queue(topic, user_id) WHERE status = 'waiting'
    ''')
    
    # Оценки врачей
    await db.execute('''
        CREATE TABLE IF NOT EXISTS doctor_ratings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doctor_id INTEGER NOT NULL,
            client_id INTEGER NOT NULL,
            consultation_id INTEGER NOT NULL,
            rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
            comment TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    await db.execute('''
        CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_rating_per_consultation
        ON doctor_ratings(client_id, consultation_id)
    ''')
    
    # Обращения в поддержку
    await db.execute('''
        CREATE TABLE IF NOT EXISTS support_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT,
            message TEXT NOT NULL,
            status TEXT DEFAULT 'new',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            resolved_at TIMESTAMP
        )
    ''')

    await db.execute('''
        CREATE TABLE IF NOT EXISTS support_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id INTEGER NOT NULL,
            sender_role TEXT NOT NULL,
            sender_id INTEGER NOT NULL,
            body TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (request_id) REFERENCES support_requests(id)
        )
    ''')
    await db.execute(
        'CREATE INDEX IF NOT EXISTS idx_support_messages_request ON support_messages(request_id)'
    )

    # Статусы: open | closed (миграция со старых new/replied)
    try:
        await db.execute(
            "UPDATE support_requests SET status = 'closed' WHERE status = 'replied'"
        )
        await db.execute(
            "UPDATE support_requests SET status = 'open' WHERE status = 'new'"
        )
        await db.commit()
    except Exception:
        pass
    
    # Обратная связь
    await db.execute('''
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT,
            feedback TEXT NOT NULL,
            status TEXT DEFAULT 'new',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Чёрный список
    await db.execute('''
        CREATE TABLE IF NOT EXISTS blacklist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL UNIQUE,
            reason TEXT,
            blocked_by INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Добавляем колонку doctor_name, если её нет
    try:
        await db.execute('ALTER TABLE consultations ADD COLUMN doctor_name TEXT')
    except:
        pass
    
    await db.commit()

    try:
        from database.support import backfill_messages_from_legacy

        await backfill_messages_from_legacy()
    except Exception as e:
        logging.warning("support_messages backfill: %s", e)

    print("✅ База данных SQLite инициализирована")