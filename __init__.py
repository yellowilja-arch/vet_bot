from .common import router as common_router
from .client import router as client_router
from .doctor import router as doctor_router
from .admin import router as admin_router

def register_handlers(dp):
    dp.include_router(common_router)
    dp.include_router(client_router)
    dp.include_router(doctor_router)
    dp.include_router(admin_router)