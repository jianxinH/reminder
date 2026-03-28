from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import app.models  # noqa: F401
from app.api.routes.agent import router as agent_router
from app.api.routes.bot import router as bot_router
from app.api.routes.notifications import router as notifications_router
from app.api.routes.reminders import router as reminders_router
from app.api.routes.scheduler import router as scheduler_router
from app.api.routes.users import router as users_router
from app.core.config import get_settings
from app.core.database import Base, engine, ensure_schema
from app.core.scheduler import start_scheduler, stop_scheduler

settings = get_settings()
BASE_DIR = Path(__file__).resolve().parent


def serve_static_page(filename: str) -> FileResponse:
    return FileResponse(
        BASE_DIR / "static" / filename,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    ensure_schema()
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)


@app.get("/")
def healthcheck():
    return {"success": True, "message": "Reminder Agent MVP is running"}


@app.get("/chat", include_in_schema=False)
def chat_page():
    return serve_static_page("chat.html")


@app.get("/wechat", include_in_schema=False)
def wechat_page():
    return serve_static_page("wechat.html")


app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


app.include_router(users_router)
app.include_router(reminders_router)
app.include_router(agent_router)
app.include_router(bot_router)
app.include_router(notifications_router)
app.include_router(scheduler_router)
