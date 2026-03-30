import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.agent import AgentChatRequest
from app.schemas.bot import TelegramWebhookRequest
from app.schemas.common import APIResponse
from app.services.agent_service import AgentService
from app.services.telegram_service import TelegramService
from app.services.user_service import UserService
from app.services.wecom_callback_service import WeComCallbackService
from app.services.wecom_command_service import WeComCommandService
from app.services.wecom_service import WeComService

router = APIRouter(prefix="/api/bot", tags=["bot"])
logger = logging.getLogger(__name__)


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
    db: Session = Depends(get_db),
    msg_signature: str = Query(...),
    timestamp: str = Query(...),
    nonce: str = Query(...),
):
    service = WeComCallbackService()
    if not service.is_configured:
        raise HTTPException(status_code=500, detail="WeCom callback is not configured")

    body = await request.body()
    try:
        plain_xml = service.decrypt_post_body(body, msg_signature, timestamp, nonce)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    message = service.parse_message(plain_xml)
    msg_type = (message.get("MsgType") or "").strip().lower()
    from_user = (message.get("FromUserName") or "").strip()
    event = (message.get("Event") or "").strip().lower()
    display_name = (message.get("UserName") or "").strip() or from_user

    try:
        logger.info("WeCom callback received: msg_type=%s event=%s from_user=%s payload=%s", msg_type, event, from_user, message)

        if msg_type == "text" and from_user:
            user_service = UserService(db)
            user = user_service.get_or_create_by_wecom_userid(from_user, display_name=display_name)
            content = (message.get("Content") or "").strip()
            if content:
                command_reply = WeComCommandService(db).try_handle(user.id, content)
                if command_reply is not None:
                    await WeComService().send_message(from_user, command_reply)
                else:
                    result = await AgentService(db).chat(
                        AgentChatRequest(
                            user_id=user.id,
                            channel="wecom",
                            session_id=f"wecom_{from_user}",
                            message=content,
                        )
                    )
                    await WeComService().send_message(from_user, result["reply"])
        elif msg_type == "event" and event == "enter_agent" and from_user:
            user_service = UserService(db)
            user_service.get_or_create_by_wecom_userid(from_user, display_name=display_name)
            await WeComService().send_message(
                from_user,
                "欢迎使用提醒助手。你可以直接发送一句话，例如：明天下午三点提醒我开会；也可以发送“帮助”查看快捷命令。",
            )
    except Exception:
        logger.exception("WeCom callback handling failed. payload=%s plain_xml=%s", message, plain_xml)

    return Response(content="success", media_type="text/plain")
