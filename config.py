import os
from dotenv import load_dotenv

load_dotenv()

# ============================================
# TELEGRAM НАСТРОЙКИ
# ============================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
GROUP_ID = os.getenv("GROUP_ID")
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "1092230808").split(",") if x.strip()]
# Главный врач: эскалации по просроченным консультациям (0 = не задан)
HEAD_DOCTOR_ID = int(os.getenv("HEAD_DOCTOR_ID", "0") or "0")
# Универсальная тема «Не знаю, куда обратиться» — закрепление консультаций за этим врачом
UNIVERSAL_TOPIC_DOCTOR_ID = int(os.getenv("UNIVERSAL_TOPIC_DOCTOR_ID", "1906114179") or "1906114179")
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
# PostgreSQL
# ============================================
# Строка подключения (обязательна). В Railway: сервис Postgres → DATABASE_URL;
# при необходимости продублируйте то же значение в PGDATABASE_URL.
DATABASE_URL = (os.getenv("DATABASE_URL") or os.getenv("PGDATABASE_URL") or "").strip()

# ============================================
# Врачи: синхронизация по HTTP (без Volume на PaaS)
# ============================================
# При деплое контейнер часто получает пустой SQLite. Альтернатива тому — хранить
# JSON со списком врачей во внешнем хранилище с HTTP API.
#
# Пример (jsonbin.io): создайте bin с начальным значением [].
#   DOCTORS_SYNC_PULL_URL=https://api.jsonbin.io/v3/b/<BIN_ID>/latest
#   DOCTORS_SYNC_PUSH_URL=https://api.jsonbin.io/v3/b/<BIN_ID>
#   DOCTORS_SYNC_PUSH_METHOD=PUT
#   DOCTORS_SYNC_HTTP_HEADERS={"X-Master-Key":"<ваш ключ>"}
#
# Проще для jsonbin: один ключ без JSON (если HTTP_HEADERS кривой или пустой):
#   DOCTORS_SYNC_JSONBIN_MASTER_KEY=<ваш X-Master-Key>
#
# Ответ GET может быть массивом или обёрткой {"record":[...]} / {"doctors":[...]}.
DOCTORS_SYNC_PULL_URL = (os.getenv("DOCTORS_SYNC_PULL_URL") or "").strip()
DOCTORS_SYNC_PUSH_URL = (os.getenv("DOCTORS_SYNC_PUSH_URL") or "").strip()
DOCTORS_SYNC_HTTP_HEADERS = (os.getenv("DOCTORS_SYNC_HTTP_HEADERS") or "").strip()
DOCTORS_SYNC_PUSH_METHOD = (os.getenv("DOCTORS_SYNC_PUSH_METHOD") or "PUT").strip().upper()
DOCTORS_SYNC_JSONBIN_MASTER_KEY = (
    os.getenv("DOCTORS_SYNC_JSONBIN_MASTER_KEY") or os.getenv("JSONBIN_MASTER_KEY") or ""
).strip()

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

# Legacy: почти не используется (маршрутизация — pick_doctor_for_topic → SQLite).
DOCTORS = {k: [] for k in SPECIALIZATION_KEYS}

# Опциональный сид при первом запуске. Вымышленные ID < 1e9 удаляются при старте в init_doctors.
INITIAL_DOCTORS: dict[str, list[dict]] = {}

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
