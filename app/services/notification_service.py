import asyncio
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.repositories.notification_repository import NotificationRepository
from app.repositories.user_repository import UserRepository
from app.services.email_service import EmailService
from app.services.telegram_service import TelegramService
from app.services.wecom_service import WeComService
from app.utils.repeat_rule import compute_next_remind_time


class NotificationService:
    def __init__(self, db: Session):
        self.db = db
        self.notification_repo = NotificationRepository(db)
        self.user_repo = UserRepository(db)
        self.email_service = EmailService()
        self.telegram_service = TelegramService()
        self.wecom_service = WeComService()

    async def send_reminder_notification(self, reminder):
        user = self.user_repo.get_by_id(reminder.user_id)
        message = (
            f"提醒你：现在该 {reminder.title} 了。\n"
            f"回复 snooze {reminder.id} 10 可延后 10 分钟。\n"
            f"回复 done {reminder.id} 可标记完成。"
        )

        if not user:
            self.notification_repo.create(
                reminder.id,
                reminder.user_id,
                reminder.channel_type,
                message,
                "failed",
                "User not found",
            )
            return {"success": False, "reason": "User not found"}

        channel_type = (reminder.channel_type or "").strip().lower()
        send_status = "success"
        error_message = None

        if channel_type == "telegram" and user.telegram_chat_id:
            result = await self.telegram_service.send_message(user.telegram_chat_id, message)
            if not result.get("ok"):
                send_status = "failed"
                error_message = result.get("description", "Unknown Telegram error")
        elif channel_type == "email" and user.email:
            subject = f"提醒：{reminder.title}"
            result = await asyncio.to_thread(self.email_service.send_message, user.email, subject, message)
            if not result.get("ok"):
                send_status = "failed"
                error_message = result.get("description", "Unknown email error")
        elif channel_type == "wecom" and user.wecom_userid:
            result = await self.wecom_service.send_message(user.wecom_userid, message)
            if not result.get("ok"):
                send_status = "failed"
                error_message = result.get("description", "Unknown WeCom error")
        elif channel_type == "web":
            send_status = "success"
        else:
            send_status = "failed"
            error_message = "Unsupported channel or missing recipient binding"

        self.notification_repo.create(
            reminder_id=reminder.id,
            user_id=reminder.user_id,
            channel_type=channel_type or reminder.channel_type,
            send_content=message,
            send_status=send_status,
            error_message=error_message,
        )

        if send_status == "success":
            reminder.channel_type = channel_type or reminder.channel_type
            reminder.sent_flag = 1
            reminder.last_sent_at = datetime.now(timezone.utc)

            if reminder.channel_type == "web":
                # Web reminders remain pending until the user explicitly completes or snoozes them.
                reminder.status = "pending"
            else:
                next_time = compute_next_remind_time(reminder.next_remind_time, reminder.repeat_type, reminder.repeat_value)
                if next_time:
                    reminder.next_remind_time = next_time
                    reminder.status = "pending"
                    reminder.sent_flag = 0
                else:
                    reminder.status = "done"

            self.db.add(reminder)
            self.db.commit()
            self.db.refresh(reminder)

        return {"success": send_status == "success", "reason": error_message}

    def list_logs(self, user_id: int):
        return self.notification_repo.list_by_user(user_id)

    def list_inbox(self, user_id: int, after_id: int = 0):
        return self.notification_repo.list_inbox(user_id, after_id)
