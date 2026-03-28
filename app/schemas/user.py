from datetime import datetime

from pydantic import BaseModel, ConfigDict


class UserRegisterRequest(BaseModel):
    username: str | None = None
    display_name: str | None = None
    telegram_chat_id: str | None = None
    wecom_userid: str | None = None
    email: str | None = None
    default_channel: str = "web"
    timezone: str = "Asia/Shanghai"


class UserUpdateRequest(BaseModel):
    username: str | None = None
    display_name: str | None = None
    telegram_chat_id: str | None = None
    wecom_userid: str | None = None
    email: str | None = None
    default_channel: str | None = None
    timezone: str | None = None
    status: str | None = None


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_uuid: str
    username: str | None = None
    display_name: str | None = None
    timezone: str
    telegram_chat_id: str | None = None
    wecom_userid: str | None = None
    email: str | None = None
    default_channel: str
    status: str
    created_at: datetime
    updated_at: datetime


class UserRegisterData(BaseModel):
    user_id: int
    user_uuid: str
