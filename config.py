import os
from dotenv import load_dotenv

load_dotenv()

# ============================================
# TELEGRAM НАСТРОЙКИ
# ============================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
GROUP_ID = os.getenv("GROUP_ID")
ADMIN_IDS = [
    int(x.strip())
    for x in os.getenv("ADMIN_IDS", "1092230808,146617413").split(",")
    if x.strip()
]
# Главный администратор (массовые сбросы без ограничений, эскалация поддержки с 2-й линии)
PRIMARY_ADMIN_ID = int(os.getenv("PRIMARY_ADMIN_ID", "1092230808") or "1092230808")
# Первая линия поддержки: новые обращения сначала ему; без массовых /clearqueue и /resetall
SUPPORT_LINE_ADMIN_ID = int(os.getenv("SUPPORT_LINE_ADMIN_ID", "146617413") or "146617413")
_admin_bulk_raw = os.getenv("ADMIN_BULK_OPS_FORBIDDEN_IDS", "").strip()
if _admin_bulk_raw:
    ADMIN_BULK_OPS_FORBIDDEN_IDS: frozenset[int] = frozenset(
        int(x.strip()) for x in _admin_bulk_raw.split(",") if x.strip()
    )
else:
    ADMIN_BULK_OPS_FORBIDDEN_IDS = frozenset({SUPPORT_LINE_ADMIN_ID})

ADMIN_BULK_ACCESS_DENIED = (
    "⛔ У вас нет доступа к этой команде. Обратитесь к главному администратору."
)


def can_admin_bulk_operations(user_id: int) -> bool:
    """Второй админ (первая линия поддержки) не может /clearqueue, /resetall и кнопку массового сброса."""
    return user_id not in ADMIN_BULK_OPS_FORBIDDEN_IDS


# Главный врач: эскалации по просроченным консультациям (0 = не задан)
HEAD_DOCTOR_ID = int(os.getenv("HEAD_DOCTOR_ID", "0") or "0")
# Универсальная тема «Не знаю, куда обратиться» — закрепление консультаций за этим врачом
UNIVERSAL_TOPIC_DOCTOR_ID = int(os.getenv("UNIVERSAL_TOPIC_DOCTOR_ID", "146617413") or "146617413")
# Текст кнопки «Шаблон» при ответе клиенту в поддержке
SUPPORT_TEMPLATE_TEXT = os.getenv("SUPPORT_TEMPLATE_TEXT", "Какой у Вас вопрос/проблема?")
PHONE_NUMBER = os.getenv("PHONE_NUMBER", "+79256530940")

# Railway PORT (HTTP: health-check)
PORT = int(os.getenv("PORT", 8080))

# ============================================
# TELEGRAM PAYMENTS (ЮKassa в @BotFather → Payments — provider token)
# ============================================
PAYMENT_PROVIDER_TOKEN = (os.getenv("PAYMENT_PROVIDER_TOKEN") or "").strip()


def yookassa_telegram_payments_configured() -> bool:
    return bool(PAYMENT_PROVIDER_TOKEN)

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
DEFAULT_CONSULTATION_PRICE = 1300

# Legacy: почти не используется (маршрутизация — pick_doctor_for_topic → БД).
DOCTORS = {k: [] for k in SPECIALIZATION_KEYS}

# Опциональный сид при первом запуске. Вымышленные ID < 1e9 удаляются при старте в init_doctors.
INITIAL_DOCTORS: dict[str, list[dict]] = {}

# Глобальный список ID врачей (заполняется при загрузке)
DOCTOR_IDS = []

# --- Legacy-совместимость: старые деплои без PAYMENT_PROVIDER_TOKEN выше ---
if "PAYMENT_PROVIDER_TOKEN" not in globals():
    PAYMENT_PROVIDER_TOKEN = (os.getenv("PAYMENT_PROVIDER_TOKEN") or "").strip()
if "yookassa_telegram_payments_configured" not in globals():

    def yookassa_telegram_payments_configured() -> bool:
        return bool(PAYMENT_PROVIDER_TOKEN)
