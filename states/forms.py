from aiogram.fsm.state import State, StatesGroup


class PaymentState(StatesGroup):
    """Состояния для процесса оплаты"""
    waiting_payment = State()      # Ожидание начала оплаты
    waiting_receipt = State()      # Ожидание чека
    waiting_confirmation = State() # Ожидание подтверждения от врача


class QuestionnaireState(StatesGroup):
    """Состояния для опросника после оплаты"""
    waiting_species = State()      # Вид животного
    waiting_age = State()          # Возраст
    waiting_weight = State()       # Вес
    waiting_breed = State()        # Порода
    waiting_condition = State()    # Упитанность
    waiting_chronic = State()      # Хронические заболевания


class WaitingState(StatesGroup):
    """Состояния ожидания"""
    waiting_for_doctor = State()           # Ожидание свободного врача
    waiting_for_specific_doctor = State()  # Ожидание конкретного врача
    waiting_for_admin_message = State()    # Ожидание сообщения админу
    waiting_for_support_reply = State()    # Ожидание ответа поддержки
    waiting_for_feedback = State()         # Ожидание обратной связи
    waiting_for_rating_comment = State()   # Ожидание комментария к оценке


class AdminState(StatesGroup):
    """Состояния для админ-действий"""
    waiting_broadcast = State()    # Рассылка сообщения
    waiting_user_id = State()      # Ожидание ID пользователя
    waiting_doctor_id = State()    # Ожидание ID врача
    waiting_ban_reason = State()   # Причина блокировки
    add_doctor_telegram = State()   # Шаг 1: Telegram ID нового врача
    add_doctor_name = State()       # Шаг 2: ФИО
    add_doctor_pick_spec = State()  # Шаг 3: выбор специализации (callback)