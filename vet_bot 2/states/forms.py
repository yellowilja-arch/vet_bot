from aiogram.fsm.state import State, StatesGroup

class PaymentState(StatesGroup):
    waiting_payment = State()
    waiting_receipt = State()

class WaitingState(StatesGroup):
    waiting_for_doctor = State()
    waiting_for_specific_doctor = State()
    waiting_for_admin_message = State()
    waiting_for_support_reply = State()
    waiting_for_feedback = State()
    waiting_for_rating_comment = State()