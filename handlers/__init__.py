from .common import router as common_router
from .client import router as client_router
from .doctor import router as doctor_router
from .admin import router as admin_router

print("✅ __init__.py ЗАГРУЖЕН, роутеры импортированы")

def register_handlers(dp):
    print("✅ register_handlers ВЫЗВАН")
    # ВАЖНО: порядок имеет значение!
    # common_router должен быть первым, но без конфликтующих команд
    dp.include_router(common_router)
    print("   common_router добавлен")
    dp.include_router(admin_router)
    print("   admin_router добавлен")
    dp.include_router(doctor_router)
    print("   doctor_router добавлен")
    dp.include_router(client_router)  # client_router последним, чтобы его /start был главным
    print("   client_router добавлен")