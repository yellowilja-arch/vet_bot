from .ping import router as ping_router

def register_handlers(dp):
    dp.include_router(ping_router)