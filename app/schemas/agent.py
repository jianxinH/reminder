from typing import Any

from pydantic import BaseModel


class AgentChatRequest(BaseModel):
    user_id: int
    channel: str = "web"
    session_id: str | None = None
    message: str


class AgentChatData(BaseModel):
    intent: str
    reply: str
    tool_result: dict[str, Any] | None = None
