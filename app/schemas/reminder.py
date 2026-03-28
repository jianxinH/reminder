from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ReminderCreateRequest(BaseModel):
    user_id: int
    title: str
    content: str | None = None
    source_text: str | None = None
    remind_time: datetime
    repeat_type: str = "none"
    repeat_value: str | None = None
    priority: str = "medium"
    channel_type: str = "web"


class ReminderUpdateRequest(BaseModel):
    title: str | None = None
    content: str | None = None
    next_remind_time: datetime | None = None
    repeat_type: str | None = None
    repeat_value: str | None = None
    priority: str | None = None
    channel_type: str | None = None
    status: str | None = None


class ReminderSnoozeRequest(BaseModel):
    minutes: int = Field(gt=0, le=1440)


class ReminderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    reminder_uuid: str
    user_id: int
    title: str
    content: str | None = None
    source_text: str | None = None
    remind_time: datetime
    next_remind_time: datetime
    repeat_type: str
    repeat_value: str | None = None
    status: str
    priority: str
    channel_type: str
    sent_flag: int
    last_sent_at: datetime | None = None
    is_deleted: int
    created_at: datetime
    updated_at: datetime


class ReminderCreateData(BaseModel):
    reminder_id: int
    title: str
    next_remind_time: datetime
    status: str


class ReminderDuplicateItem(BaseModel):
    id: int
    title: str
    next_remind_time: datetime
    status: str
    created_at: datetime


class ReminderDuplicateGroup(BaseModel):
    duplicate_key: str
    normalized_title: str
    next_remind_time: datetime
    repeat_type: str
    channel_type: str
    items: list[ReminderDuplicateItem]


class ReminderAuditData(BaseModel):
    total_active: int
    duplicate_group_count: int
    duplicate_item_count: int
    groups: list[ReminderDuplicateGroup]


class ReminderDeduplicateData(BaseModel):
    kept_ids: list[int]
    removed_ids: list[int]
    removed_count: int
