import json
from typing import Any

from sqlalchemy.orm import Session

from app.models.conversation_log import ConversationLog


class ConversationRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(
        self,
        user_id: int,
        session_id: str | None,
        channel: str,
        user_message: str,
        agent_intent: str | None,
        tool_name: str | None,
        tool_payload: dict[str, Any] | None,
        agent_response: str | None,
    ) -> ConversationLog:
        log = ConversationLog(
            user_id=user_id,
            session_id=session_id,
            channel=channel,
            user_message=user_message,
            agent_intent=agent_intent,
            tool_name=tool_name,
            tool_payload=json.dumps(tool_payload, ensure_ascii=False) if tool_payload else None,
            agent_response=agent_response,
        )
        self.db.add(log)
        self.db.commit()
        self.db.refresh(log)
        return log
