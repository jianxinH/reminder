from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.agent import AgentChatData, AgentChatRequest
from app.schemas.common import APIResponse
from app.services.agent_service import AgentService

router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.post("/chat", response_model=APIResponse[AgentChatData])
async def agent_chat(payload: AgentChatRequest, db: Session = Depends(get_db)):
    result = await AgentService(db).chat(payload)
    return APIResponse(data=AgentChatData(**result))
