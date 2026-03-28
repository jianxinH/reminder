from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_uuid: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(100), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    timezone: Mapped[str] = mapped_column(String(50), default="Asia/Shanghai")
    telegram_chat_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    wecom_userid: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    default_channel: Mapped[str] = mapped_column(String(50), default="telegram")
    status: Mapped[str] = mapped_column(String(20), default="active")

    reminders = relationship("Reminder", back_populates="user")
    notification_logs = relationship("NotificationLog", back_populates="user")
    conversation_logs = relationship("ConversationLog", back_populates="user")
