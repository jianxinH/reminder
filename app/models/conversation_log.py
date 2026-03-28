from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin


class ConversationLog(TimestampMixin, Base):
    __tablename__ = "conversation_logs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    session_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    channel: Mapped[str | None] = mapped_column(String(50), nullable=True)
    user_message: Mapped[str] = mapped_column(Text)
    agent_intent: Mapped[str | None] = mapped_column(String(50), nullable=True)
    tool_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    tool_payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    agent_response: Mapped[str | None] = mapped_column(Text, nullable=True)

    user = relationship("User", back_populates="conversation_logs")
