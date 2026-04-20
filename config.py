import os
from dotenv import load_dotenv

load_dotenv()

# ============================================
# TELEGRAM НАСТРОЙКИ
# ============================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
GROUP_ID = os.getenv("GROUP_ID")
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "1092230808").split(",") if x.strip()]
# Текст кнопки «Шаблон» при ответе клиенту в поддержке
SUPPORT_TEMPLATE_TEXT = os.getenv("SUPPORT_TEMPLATE_TEXT", "Какой у Вас вопрос/проблема?")
PHONE_NUMBER = os.getenv("PHONE_NUMBER", "+79256530940")

# Railway PORT (HTTP: health + вебхук Т-Банка)
PORT = int(os.getenv("PORT", 8080))

# ============================================
# Т-БАНК — интернет-эквайринг (вебхук + Init)
# ============================================
# Публичный URL без пути, например https://your-app.up.railway.app
PUBLIC_WEBHOOK_BASE = (os.getenv("PUBLIC_WEBHOOK_BASE") or "").strip().rstrip("/")
TBANK_TERMINAL_KEY = (os.getenv("TBANK_TERMINAL_KEY") or "").strip()
TBANK_PASSWORD = (os.getenv("TBANK_PASSWORD") or "").strip()
# Прод: https://securepay.tinkoff.ru/v2 — тестовый терминал: см. кабинет Т-Банка
TBANK_API_BASE = (os.getenv("TBANK_API_BASE") or "https://securepay.tinkoff.ru/v2").strip().rstrip("/")


def tbank_acquiring_configured() -> bool:
    return bool(TBANK_TERMINAL_KEY and TBANK_PASSWORD and PUBLIC_WEBHOOK_BASE)

# ============================================
# YANDEX CLOUD (БЭКАПЫ)
# ============================================

YC_ACCESS_KEY_ID = os.getenv("YC_ACCESS_KEY_ID")
YC_SECRET_ACCESS_KEY = os.getenv("YC_SECRET_ACCESS_KEY")
YC_BUCKET_NAME = os.getenv("YC_BUCKET_NAME", "vet-bot-backups")
YC_ENDPOINT = "https://storage.yandexcloud.net"

# ============================================
# REDIS
# ============================================

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

# ============================================
# SQLite
# ============================================

DB_PATH = "vet_bot.db"

# ============================================
# НАСТРОЙКИ ТАЙМАУТОВ
# ============================================

INACTIVITY_DOCTOR_SECONDS = 600   # 10 минут
INACTIVITY_CLIENT_SECONDS = 360   # 6 минут
MAX_ACTIVE_PER_DOCTOR = 3

# ============================================
# СПЕЦИАЛИЗАЦИИ (канон — data/problems.py)
# ============================================

from data.problems import SPECIALISTS, SPECIALIZATION_KEYS  # noqa: E402

# Стоимость консультации при выборе темы из меню (динамический список из БД)
DEFAULT_CONSULTATION_PRICE = 500

# Врачи по специализациям (Telegram ID) — legacy из конфига; основная маршрутизация — через БД
DOCTORS = {
    "gp": [1092230808],
    "therapist": [1906114179],
    "oncologist": [201000001],
    "cardiologist": [201000002],
    "gastroenterologist": [201000003],
    "orthopedist": [201000004],
    "surgeon": [1092230808],
    "nephrologist": [201000005],
    "neurologist": [201000006],
    "dermatologist": [201000007],
    "reproductologist": [201000008],
    "virologist": [201000009],
    "radiologist": [201000010],
}

# Начальные врачи (инициализация БД). Замените ID на боевые.
INITIAL_DOCTORS = {
    "therapist": [{"id": 1906114179, "name": "Васильева Елена"}],
    "oncologist": [{"id": 201000001, "name": "Петров Иван"}],
    "cardiologist": [{"id": 201000002, "name": "Сидорова Мария"}],
    "gastroenterologist": [{"id": 201000003, "name": "Кузнецов Алексей"}],
    "orthopedist": [{"id": 201000004, "name": "Соколов Дмитрий"}],
    "surgeon": [{"id": 1092230808, "name": "Корнев Михаил"}],
    "nephrologist": [{"id": 201000005, "name": "Павлова Ольга"}],
    "neurologist": [{"id": 201000006, "name": "Новиков Андрей"}],
    "dermatologist": [{"id": 201000007, "name": "Морозова Екатерина"}],
    "reproductologist": [{"id": 201000008, "name": "Волков Сергей"}],
    "virologist": [{"id": 201000009, "name": "Зайцева Анна"}],
    "radiologist": [{"id": 201000010, "name": "Соловьев Илья"}],
}

# Глобальный список ID врачей (заполняется при загрузке)
DOCTOR_IDS = []

# --- Если в деплой попала старая копия config без блока Т-Банка выше, задаём имена из env ---
if "PUBLIC_WEBHOOK_BASE" not in globals():
    PUBLIC_WEBHOOK_BASE = (os.getenv("PUBLIC_WEBHOOK_BASE") or "").strip().rstrip("/")
if "TBANK_TERMINAL_KEY" not in globals():
    TBANK_TERMINAL_KEY = (os.getenv("TBANK_TERMINAL_KEY") or "").strip()
if "TBANK_PASSWORD" not in globals():
    TBANK_PASSWORD = (os.getenv("TBANK_PASSWORD") or "").strip()
if "TBANK_API_BASE" not in globals():
    TBANK_API_BASE = (os.getenv("TBANK_API_BASE") or "https://securepay.tinkoff.ru/v2").strip().rstrip("/")
if "tbank_acquiring_configured" not in globals():

    def tbank_acquiring_configured() -> bool:
        return bool(TBANK_TERMINAL_KEY and TBANK_PASSWORD and PUBLIC_WEBHOOK_BASE)
