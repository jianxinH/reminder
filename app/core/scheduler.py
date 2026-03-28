from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.services.scheduler_service import SchedulerService

settings = get_settings()
scheduler = AsyncIOScheduler(timezone=settings.default_timezone)


async def run_due_scan_job():
    db = SessionLocal()
    try:
        await SchedulerService(db).scan_due_reminders()
    finally:
        db.close()


def start_scheduler() -> None:
    if scheduler.running:
        return
    scheduler.add_job(
        run_due_scan_job,
        "interval",
        seconds=settings.scheduler_scan_interval_seconds,
        id="scan_due_reminders",
        replace_existing=True,
    )
    scheduler.start()


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
