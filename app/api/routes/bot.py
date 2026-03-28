from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.agent import AgentChatRequest
from app.schemas.bot import TelegramWebhookRequest
from app.schemas.common import APIResponse
from app.services.agent_service import AgentService
from app.services.wecom_callback_service import WeComCallbackService
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


@router.get("/wecom/callback", include_in_schema=False)
async def wecom_callback_verify(
    msg_signature: str = Query(...),
    timestamp: str = Query(...),
    nonce: str = Query(...),
    echostr: str = Query(...),
):
    service = WeComCallbackService()
    if not service.is_configured:
        raise HTTPException(status_code=500, detail="WeCom callback is not configured")
    try:
        plain = service.verify_url(msg_signature, timestamp, nonce, echostr)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(content=plain, media_type="text/plain")


@router.post("/wecom/callback", include_in_schema=False)
async def wecom_callback_receive(
    request: Request,
    msg_signature: str = Query(...),
    timestamp: str = Query(...),
    nonce: str = Query(...),
):
    service = WeComCallbackService()
    if not service.is_configured:
        raise HTTPException(status_code=500, detail="WeCom callback is not configured")

    body = await request.body()
    try:
        service.decrypt_post_body(body, msg_signature, timestamp, nonce)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # WeCom only requires a 200 response here for the callback to be considered delivered.
    return Response(content="success", media_type="text/plain")
