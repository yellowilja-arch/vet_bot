import redis
from config import REDIS_URL, DOCTORS
from services.validators import get_doctor_status, get_current_client

r = redis.from_url(REDIS_URL, decode_responses=True)


def get_doctor_by_specialization(specialization: str):
    """
    Возвращает ID свободного онлайн-врача по специализации.
    Если все врачи заняты — возвращает None.
    """
    doctors_list = DOCTORS.get(specialization, [])
    
    # Ищем свободного онлайн-врача
    for doctor_id in doctors_list:
        if get_doctor_status(doctor_id) == "online" and get_current_client(doctor_id) is None:
            return doctor_id
    
    return None


def get_available_doctors_by_specialization(specialization: str):
    """Возвращает список всех свободных онлайн-врачей по специализации"""
    doctors_list = DOCTORS.get(specialization, [])
    
    available = []
    for doctor_id in doctors_list:
        if get_doctor_status(doctor_id) == "online" and get_current_client(doctor_id) is None:
            available.append(doctor_id)
    
    return available


def get_all_online_doctors():
    """Возвращает список всех онлайн-врачей (без проверки занятости)"""
    online = []
    for spec, doctors_list in DOCTORS.items():
        for doctor_id in doctors_list:
            if get_doctor_status(doctor_id) == "online":
                online.append(doctor_id)
    return online


def get_doctor_by_specialization_round_robin(specialization: str):
    """
    Выбирает врача по кругу (round-robin) среди всех онлайн-врачей
    данной специализации, даже если они заняты.
    """
    doctors_list = DOCTORS.get(specialization, [])
    
    # Фильтруем только онлайн
    online_doctors = [d for d in doctors_list if get_doctor_status(d) == "online"]
    
    if not online_doctors:
        return None
    
    # Round-robin
    key = f"round_robin:{specialization}"
    current_idx = int(r.get(key) or 0)
    doctor_id = online_doctors[current_idx % len(online_doctors)]
    r.set(key, current_idx + 1)
    
    return doctor_id


def get_least_busy_doctor(specialization: str):
    """
    Выбирает врача с наименьшим количеством активных клиентов.
    """
    doctors_list = DOCTORS.get(specialization, [])
    
    # Фильтруем только онлайн
    online_doctors = [d for d in doctors_list if get_doctor_status(d) == "online"]
    
    if not online_doctors:
        return None
    
    # Сортируем по занятости (текущий клиент или нет)
    def busy_score(doctor_id):
        return 1 if get_current_client(doctor_id) else 0
    
    online_doctors.sort(key=busy_score)
    
    return online_doctors[0]


def get_doctor_info(doctor_id: int):
    """Возвращает информацию о враче из Redis"""
    topic = r.get(f"doctor:{doctor_id}:topic")
    status = get_doctor_status(doctor_id)
    current_client = get_current_client(doctor_id)
    
    return {
        "id": doctor_id,
        "specialization": topic,
        "status": status,
        "current_client": current_client,
        "is_busy": current_client is not None,
        "is_online": status == "online"
    }


def get_all_doctors_info():
    """Возвращает информацию о всех врачах"""
    result = {}
    for spec, doctors_list in DOCTORS.items():
        for doctor_id in doctors_list:
            result[doctor_id] = get_doctor_info(doctor_id)
    return result