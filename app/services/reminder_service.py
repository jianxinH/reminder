from datetime import datetime, timedelta
from collections import defaultdict

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.repositories.reminder_repository import ReminderRepository
from app.repositories.user_repository import UserRepository
from app.schemas.reminder import ReminderCreateRequest, ReminderUpdateRequest


class ReminderService:
    DUPLICATE_TIME_WINDOW_SECONDS = 300

    def __init__(self, db: Session):
        self.repo = ReminderRepository(db)
        self.user_repo = UserRepository(db)

    def create_reminder(self, payload: ReminderCreateRequest):
        user = self.user_repo.get_by_id(payload.user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        duplicate = self.find_duplicate_reminder(
            user_id=payload.user_id,
            title=payload.title,
            remind_time=payload.remind_time,
            repeat_type=payload.repeat_type,
            channel_type=payload.channel_type,
        )
        if duplicate:
            raise HTTPException(
                status_code=409,
                detail=f"检测到一条高度重复的提醒：#{duplicate.id} {duplicate.title}（{duplicate.next_remind_time:%Y-%m-%d %H:%M}）。如果你确实要保留两条，再换个时间或标题。",
            )
        return self.repo.create(payload)

    def list_reminders(
        self,
        user_id: int,
        status: str | None = None,
        repeat_type: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ):
        return self.repo.list_for_user(user_id, status, repeat_type, date_from, date_to)

    def get_reminder(self, reminder_id: int):
        reminder = self.repo.get_by_id(reminder_id)
        if not reminder:
            raise HTTPException(status_code=404, detail="Reminder not found")
        return reminder

    def update_reminder(self, reminder_id: int, payload: ReminderUpdateRequest):
        reminder = self.get_reminder(reminder_id)
        target_time = payload.next_remind_time or reminder.next_remind_time
        target_title = payload.title or reminder.title
        target_repeat_type = payload.repeat_type or reminder.repeat_type
        target_channel_type = payload.channel_type or reminder.channel_type
        duplicate = self.find_duplicate_reminder(
            user_id=reminder.user_id,
            title=target_title,
            remind_time=target_time,
            repeat_type=target_repeat_type,
            channel_type=target_channel_type,
            exclude_id=reminder_id,
        )
        if duplicate:
            raise HTTPException(
                status_code=409,
                detail=f"这次修改会和现有提醒 #{duplicate.id} 冲突：{duplicate.title}（{duplicate.next_remind_time:%Y-%m-%d %H:%M}）。请确认是否改成别的时间或标题。",
            )
        if payload.next_remind_time is not None:
            reminder.next_remind_time = payload.next_remind_time
        return self.repo.update(reminder, payload)

    def delete_reminder(self, reminder_id: int):
        reminder = self.get_reminder(reminder_id)
        reminder.is_deleted = 1
        reminder.status = "cancelled"
        return self.repo.save(reminder)

    def snooze_reminder(self, reminder_id: int, minutes: int):
        reminder = self.get_reminder(reminder_id)
        reminder.next_remind_time = reminder.next_remind_time + timedelta(minutes=minutes)
        reminder.sent_flag = 0
        reminder.status = "pending"
        return self.repo.save(reminder)

    def mark_done(self, reminder_id: int):
        reminder = self.get_reminder(reminder_id)
        reminder.status = "done"
        return self.repo.save(reminder)

    def find_due_reminders(self, now: datetime):
        return self.repo.find_due_reminders(now)

    def list_recent_reminders(self, user_id: int, limit: int = 20, include_finished: bool = True):
        return self.repo.list_recent_for_user(user_id=user_id, limit=limit, include_finished=include_finished)

    def search_reminders(self, user_id: int, keyword: str, limit: int = 20, include_finished: bool = True):
        return self.repo.search_for_user(user_id=user_id, keyword=keyword, limit=limit, include_finished=include_finished)

    def audit_duplicates(self, user_id: int):
        reminders = self.repo.list_active_for_user(user_id)
        groups: dict[tuple[str, datetime, str, str], list] = defaultdict(list)
        for reminder in reminders:
            key = (
                self._normalize_title(reminder.title),
                reminder.next_remind_time.replace(second=0, microsecond=0),
                reminder.repeat_type or "none",
                reminder.channel_type or "web",
            )
            groups[key].append(reminder)

        duplicate_groups = []
        duplicate_item_count = 0
        for (normalized_title, next_remind_time, repeat_type, channel_type), items in groups.items():
            if len(items) < 2:
                continue
            duplicate_item_count += len(items)
            duplicate_groups.append(
                {
                    "duplicate_key": f"{normalized_title}|{next_remind_time.isoformat()}|{repeat_type}|{channel_type}",
                    "normalized_title": normalized_title,
                    "next_remind_time": next_remind_time,
                    "repeat_type": repeat_type,
                    "channel_type": channel_type,
                    "items": [
                        {
                            "id": item.id,
                            "title": item.title,
                            "next_remind_time": item.next_remind_time,
                            "status": item.status,
                            "created_at": item.created_at,
                        }
                        for item in items
                    ],
                }
            )

        duplicate_groups.sort(key=lambda group: (group["next_remind_time"], group["normalized_title"]))
        return {
            "total_active": len(reminders),
            "duplicate_group_count": len(duplicate_groups),
            "duplicate_item_count": duplicate_item_count,
            "groups": duplicate_groups,
        }

    def deduplicate_reminders(self, user_id: int):
        audit = self.audit_duplicates(user_id)
        kept_ids: list[int] = []
        removed_ids: list[int] = []
        for group in audit["groups"]:
            items = sorted(group["items"], key=lambda item: (item["created_at"], item["id"]))
            keep_id = items[0]["id"]
            kept_ids.append(keep_id)
            for item in items[1:]:
                reminder = self.get_reminder(item["id"])
                reminder.is_deleted = 1
                reminder.status = "cancelled"
                self.repo.save(reminder)
                removed_ids.append(reminder.id)
        return {
            "kept_ids": kept_ids,
            "removed_ids": removed_ids,
            "removed_count": len(removed_ids),
        }

    def find_duplicate_reminder(
        self,
        user_id: int,
        title: str,
        remind_time: datetime,
        repeat_type: str,
        channel_type: str,
        exclude_id: int | None = None,
    ):
        normalized_title = self._normalize_title(title)
        for reminder in self.repo.list_active_for_user(user_id):
            if exclude_id is not None and reminder.id == exclude_id:
                continue
            if reminder.status != "pending":
                continue
            if self._normalize_title(reminder.title) != normalized_title:
                continue
            if (reminder.repeat_type or "none") != (repeat_type or "none"):
                continue
            if (reminder.channel_type or "web") != (channel_type or "web"):
                continue
            existing_time = self._normalize_datetime(reminder.next_remind_time)
            target_time = self._normalize_datetime(remind_time)
            if abs((existing_time - target_time).total_seconds()) <= self.DUPLICATE_TIME_WINDOW_SECONDS:
                return reminder
        return None

    def _normalize_title(self, value: str) -> str:
        return " ".join((value or "").strip().lower().split())

    def _normalize_datetime(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=None)
        return value.astimezone().replace(tzinfo=None)
