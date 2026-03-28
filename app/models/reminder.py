from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin


class Reminder(TimestampMixin, Base):
    __tablename__ = "reminders"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    reminder_uuid: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    remind_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    next_remind_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    repeat_type: Mapped[str] = mapped_column(String(20), default="none")
    repeat_value: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    priority: Mapped[str] = mapped_column(String(20), default="medium")
    channel_type: Mapped[str] = mapped_column(String(50), default="telegram")
    sent_flag: Mapped[int] = mapped_column(Integer, default=0)
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_deleted: Mapped[int] = mapped_column(Integer, default=0, index=True)

    user = relationship("User", back_populates="reminders")
    notification_logs = relationship("NotificationLog", back_populates="reminder")
