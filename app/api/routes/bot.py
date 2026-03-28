from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.agent import AgentChatRequest
from app.schemas.bot import TelegramWebhookRequest
from app.schemas.common import APIResponse
from app.services.agent_service import AgentService
from app.services.telegram_service import TelegramService
from app.services.user_service import UserService

router = APIRouter(prefix="/api/bot", tags=["bot"])


@router.post("/telegram/webhook", response_model=APIResponse[dict])
async def telegram_webhook(payload: TelegramWebhookRequest, db: Session = Depends(get_db)):
    if not payload.message:
        raise HTTPException(status_code=400, detail="Invalid Telegram payload")

    chat = payload.message.get("chat", {})
    chat_id = str(chat.get("id", ""))
    text = payload.message.get("text", "")
    if not chat_id or not text:
        raise HTTPException(status_code=400, detail="Missing chat id or text")

    user = UserService(db).get_by_telegram_chat_id(chat_id)
    if not user:
        raise HTTPException(status_code=404, detail="Telegram user not bound")

    result = await AgentService(db).chat(
        AgentChatRequest(user_id=user.id, channel="telegram", session_id=f"tg_{chat_id}", message=text)
    )
    await TelegramService().send_message(chat_id, result["reply"])
    return APIResponse(data={"reply": result["reply"]})
