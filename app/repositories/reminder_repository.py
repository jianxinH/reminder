from datetime import datetime
from uuid import uuid4

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.reminder import Reminder
from app.schemas.reminder import ReminderCreateRequest, ReminderUpdateRequest


class ReminderRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, payload: ReminderCreateRequest) -> Reminder:
        reminder = Reminder(
            reminder_uuid=f"r_{uuid4().hex[:12]}",
            user_id=payload.user_id,
            title=payload.title,
            content=payload.content,
            source_text=payload.source_text,
            remind_time=payload.remind_time,
            next_remind_time=payload.remind_time,
            repeat_type=payload.repeat_type,
            repeat_value=payload.repeat_value,
            priority=payload.priority,
            channel_type=payload.channel_type,
        )
        self.db.add(reminder)
        self.db.commit()
        self.db.refresh(reminder)
        return reminder

    def get_by_id(self, reminder_id: int) -> Reminder | None:
        return (
            self.db.query(Reminder)
            .filter(Reminder.id == reminder_id, Reminder.is_deleted == 0)
            .first()
        )

    def list_for_user(
        self,
        user_id: int,
        status: str | None = None,
        repeat_type: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> list[Reminder]:
        query = self.db.query(Reminder).filter(Reminder.user_id == user_id, Reminder.is_deleted == 0)
        if status:
            query = query.filter(Reminder.status == status)
        if repeat_type:
            query = query.filter(Reminder.repeat_type == repeat_type)
        if date_from:
            query = query.filter(Reminder.next_remind_time >= date_from)
        if date_to:
            query = query.filter(Reminder.next_remind_time <= date_to)
        return query.order_by(Reminder.next_remind_time.asc()).all()

    def list_active_for_user(self, user_id: int) -> list[Reminder]:
        return (
            self.db.query(Reminder)
            .filter(Reminder.user_id == user_id, Reminder.is_deleted == 0)
            .order_by(Reminder.next_remind_time.asc(), Reminder.id.asc())
            .all()
        )

    def update(self, reminder: Reminder, payload: ReminderUpdateRequest) -> Reminder:
        for field, value in payload.model_dump(exclude_unset=True, exclude_none=True).items():
            setattr(reminder, field, value)
        self.db.add(reminder)
        self.db.commit()
        self.db.refresh(reminder)
        return reminder

    def save(self, reminder: Reminder) -> Reminder:
        self.db.add(reminder)
        self.db.commit()
        self.db.refresh(reminder)
        return reminder

    def find_due_reminders(self, now: datetime) -> list[Reminder]:
        return (
            self.db.query(Reminder)
            .filter(
                Reminder.status == "pending",
                Reminder.is_deleted == 0,
                Reminder.next_remind_time <= now,
            )
            .order_by(Reminder.next_remind_time.asc())
            .all()
        )

    def list_recent_for_user(self, user_id: int, limit: int = 20, include_finished: bool = True) -> list[Reminder]:
        query = self.db.query(Reminder).filter(Reminder.user_id == user_id, Reminder.is_deleted == 0)
        if not include_finished:
            query = query.filter(Reminder.status == "pending")
        return query.order_by(Reminder.created_at.desc(), Reminder.id.desc()).limit(limit).all()

    def search_for_user(self, user_id: int, keyword: str, limit: int = 20, include_finished: bool = True) -> list[Reminder]:
        query = self.db.query(Reminder).filter(
            Reminder.user_id == user_id,
            Reminder.is_deleted == 0,
            or_(Reminder.title.contains(keyword), Reminder.source_text.contains(keyword), Reminder.content.contains(keyword)),
        )
        if not include_finished:
            query = query.filter(Reminder.status == "pending")
        return query.order_by(Reminder.created_at.desc(), Reminder.id.desc()).limit(limit).all()
