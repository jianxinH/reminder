from datetime import datetime

from sqlalchemy.orm import Session

from app.models.notification_log import NotificationLog
from app.models.reminder import Reminder


class NotificationRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(
        self,
        reminder_id: int,
        user_id: int,
        channel_type: str,
        send_content: str,
        send_status: str,
        error_message: str | None = None,
        retry_count: int = 0,
    ) -> NotificationLog:
        log = NotificationLog(
            reminder_id=reminder_id,
            user_id=user_id,
            channel_type=channel_type,
            send_content=send_content,
            send_status=send_status,
            error_message=error_message,
            retry_count=retry_count,
            sent_at=datetime.utcnow(),
        )
        self.db.add(log)
        self.db.commit()
        self.db.refresh(log)
        return log

    def list_by_user(self, user_id: int) -> list[NotificationLog]:
        return (
            self.db.query(NotificationLog)
            .filter(NotificationLog.user_id == user_id)
            .order_by(NotificationLog.created_at.desc())
            .all()
        )

    def list_inbox(self, user_id: int, after_id: int = 0) -> list[NotificationLog]:
        return (
            self.db.query(NotificationLog)
            .join(Reminder, Reminder.id == NotificationLog.reminder_id)
            .filter(
                NotificationLog.user_id == user_id,
                NotificationLog.channel_type == "web",
                NotificationLog.send_status == "success",
                NotificationLog.id > after_id,
                Reminder.status == "pending",
                Reminder.sent_flag == 1,
                Reminder.is_deleted == 0,
            )
            .order_by(NotificationLog.id.asc())
            .all()
        )
