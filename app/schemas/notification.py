from datetime import datetime

from pydantic import BaseModel, ConfigDict


class NotificationSendRequest(BaseModel):
    reminder_id: int


class NotificationLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    reminder_id: int
    user_id: int
    channel_type: str
    send_content: str | None = None
    send_status: str
    error_message: str | None = None
    retry_count: int
    sent_at: datetime | None = None
    created_at: datetime


class NotificationInboxItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    reminder_id: int
    user_id: int
    channel_type: str
    send_content: str | None = None
    send_status: str
    created_at: datetime
