import redis
from config import REDIS_URL, TOPICS, DOCTOR_IDS
from services.validators import get_doctor_status, get_current_client

r = redis.from_url(REDIS_URL, decode_responses=True)

def get_available_doctors(topic: str):
    """Возвращает список свободных онлайн-врачей по специализации"""
    return [
        d for d in DOCTOR_IDS
        if r.get(f"doctor:{d}:topic") == topic
        and get_doctor_status(d) == "online"
        and get_current_client(d) is None
    ]

def get_doctor(topic: str):
    """Выбирает врача: для терапии — round robin, для других — первого свободного"""
    available = get_available_doctors(topic)
    if not available:
        return None
    
    if topic == "therapy":
        current_idx = int(r.get("therapy_round_robin_idx") or 0)
        r.set("therapy_round_robin_idx", current_idx + 1)
        return available[current_idx % len(available)]
    
    return available[0]

def get_available_doctors_list(topic: str = None):
    """Возвращает список всех онлайн-врачей (для выбора конкретного)"""
    doctors = []
    for doctor_id in DOCTOR_IDS:
        if get_doctor_status(doctor_id) == "online":
            topic_key = r.get(f"doctor:{doctor_id}:topic")
            if topic is None or topic_key == topic:
                doctors.append(doctor_id)
    return doctors