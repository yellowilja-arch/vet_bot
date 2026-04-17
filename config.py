import os
from dotenv import load_dotenv

load_dotenv()

# Telegram
BOT_TOKEN = os.getenv("BOT_TOKEN")
GROUP_ID = os.getenv("GROUP_ID")
ADMIN_IDS = []  # Временно пусто для теста
PHONE_NUMBER = os.getenv("PHONE_NUMBER", "+79256530940")

# Railway PORT
PORT = int(os.getenv("PORT", 8080))

# Yandex Cloud (бэкапы)
YC_ACCESS_KEY_ID = os.getenv("YC_ACCESS_KEY_ID")
YC_SECRET_ACCESS_KEY = os.getenv("YC_SECRET_ACCESS_KEY")
YC_BUCKET_NAME = os.getenv("YC_BUCKET_NAME", "vet-bot-backups")
YC_ENDPOINT = "https://storage.yandexcloud.net"

# Redis
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

# SQLite
DB_PATH = "vet_bot.db"

# Настройки таймаутов
INACTIVITY_DOCTOR_SECONDS = 600   # 10 минут
INACTIVITY_CLIENT_SECONDS = 360   # 6 минут
MAX_ACTIVE_PER_DOCTOR = 3

# Специализации
TOPICS = {
    "dentistry": "Стоматолог",
    "surgery": "Хирург",
    "therapy": "Терапевт"
}

INITIAL_DOCTORS = {
    "dentistry": [{"id": 1092230808, "name": "Корнев Михаил"}],
    "surgery": [{"id": 222222222, "name": "Сидоров Алексей"}],
    "therapy": [{"id": 1906114179, "name": "Васильева Елена"}]
}

DOCTOR_IDS = []  # Будет заполнен при init_doctors()