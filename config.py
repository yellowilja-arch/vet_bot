import os
from dotenv import load_dotenv

load_dotenv()

# ============================================
# TELEGRAM НАСТРОЙКИ
# ============================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
GROUP_ID = os.getenv("GROUP_ID")
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "1092230808").split(",") if x.strip()]
PHONE_NUMBER = os.getenv("PHONE_NUMBER", "+79256530940")

# Railway PORT
PORT = int(os.getenv("PORT", 8080))

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
# СПЕЦИАЛИЗАЦИИ И ВРАЧИ
# ============================================

# Специализации (для отображения пользователю)
SPECIALISTS = {
    "gp": "Врач общей практики",
    "therapist": "Терапевт",
    "surgeon": "Хирург",
    "orthopedist": "Ортопед-травматолог",
    "neurologist": "Невролог",
    "gastroenterologist": "Гастроэнтеролог",
    "nephrologist": "Нефролог",
    "oncologist": "Онколог",
    "dermatologist": "Дерматолог",
    "virologist": "Вирусолог",
    "cardiologist": "Кардиолог",
    "ophthalmologist": "Офтальмолог",
    "reproductologist": "Репродуктолог",
    "radiologist": "Врач визуальной диагностики",
}

# Врачи по специализациям (Telegram ID → специализация)
# ВНИМАНИЕ: Замените ID на реальные Telegram ID врачей!
DOCTORS = {
    "gp": [1092230808],                    # Врачи общей практики (пока ты)
    "therapist": [1906114179],             # Терапевты
    "surgeon": [222222222],                # Хирурги
    "orthopedist": [333333333],            # Ортопеды-травматологи
    "neurologist": [444444444],            # Неврологи
    "gastroenterologist": [555555555],     # Гастроэнтерологи
    "nephrologist": [666666666],           # Нефрологи
    "oncologist": [777777777],             # Онкологи
    "dermatologist": [888888888],          # Дерматологи
    "virologist": [999999999],             # Вирусологи
    "cardiologist": [101010101],           # Кардиологи
    "ophthalmologist": [111111111],        # Офтальмологи
    "reproductologist": [121212121],       # Репродуктологи
    "radiologist": [131313131],            # Врачи визуальной диагностики
}

# Начальные врачи (для инициализации БД)
# Здесь только те, у кого есть реальные ID
INITIAL_DOCTORS = {
    "gp": [{"id": 1092230808, "name": "Корнев Михаил"}],
    "therapist": [{"id": 1906114179, "name": "Васильева Елена"}],
    "surgeon": [{"id": 222222222, "name": "Сидоров Алексей"}],
}

# Глобальный список ID врачей (заполняется при загрузке)
DOCTOR_IDS = []