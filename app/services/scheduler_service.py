from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.services.notification_service import NotificationService
from app.services.reminder_service import ReminderService


class SchedulerService:
    def __init__(self, db: Session):
        self.settings = get_settings()
        self.reminder_service = ReminderService(db)
        self.notification_service = NotificationService(db)

    async def scan_due_reminders(self):
        now = datetime.now(ZoneInfo(self.settings.default_timezone))
        due_items = self.reminder_service.find_due_reminders(now)
        sent_success = 0
        sent_failed = 0

        for reminder in due_items:
            result = await self.notification_service.send_reminder_notification(reminder)
            if result["success"]:
                sent_success += 1
            else:
                sent_failed += 1

        return {
            "total_due": len(due_items),
            "sent_success": sent_success,
            "sent_failed": sent_failed,
        }
