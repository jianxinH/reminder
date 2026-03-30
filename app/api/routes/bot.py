import logging
import re
import time

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response
from sqlalchemy.orm import Session

from app.core.database import SessionLocal, get_db
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

_WECOM_DEDUP_TTL_SECONDS = 600
_wecom_seen_messages: dict[str, float] = {}


def _prune_wecom_seen_messages(now: float) -> None:
    expired_keys = [key for key, seen_at in _wecom_seen_messages.items() if now - seen_at > _WECOM_DEDUP_TTL_SECONDS]
    for key in expired_keys:
        _wecom_seen_messages.pop(key, None)


def _build_wecom_message_key(message: dict[str, str]) -> str:
    msg_id = (message.get("MsgId") or "").strip()
    if msg_id:
        return f"msgid:{msg_id}"

    from_user = _extract_wecom_actor_id(message)
    create_time = (message.get("CreateTime") or "").strip()
    msg_type = (message.get("MsgType") or "").strip().lower()
    event = (message.get("Event") or "").strip().lower()
    event_key = (message.get("EventKey") or "").strip()
    content = (message.get("Content") or "").strip()
    return f"fallback:{from_user}:{create_time}:{msg_type}:{event}:{event_key}:{content}"


def _extract_wecom_actor_id(message: dict[str, str]) -> str:
    candidates = (
        "Sender_UserID",
        "Sender_OpenUserID",
        "Sender_ExternalUserID",
        "UserID",
        "OpenUserID",
        "ExternalUserID",
        "FromUserName",
    )
    for key in candidates:
        value = (message.get(key) or "").strip()
        if value:
            return value
    return ""


def _extract_wecom_display_name(message: dict[str, str], actor_id: str) -> str:
    candidates = (
        "Sender_Name",
        "Sender_NickName",
        "UserName",
        "FromUserName",
    )
    for key in candidates:
        value = (message.get(key) or "").strip()
        if value:
            return value
    return actor_id


def _normalize_wecom_content(content: str) -> str:
    text = (content or "").strip()
    if not text:
        return ""
    text = re.sub(r"^(?:@\S+\s*)+", "", text).strip()
    return text


async def _process_wecom_message(message: dict[str, str]) -> None:
    db = SessionLocal()
    try:
        msg_type = (message.get("MsgType") or "").strip().lower()
        from_user = _extract_wecom_actor_id(message)
        event = (message.get("Event") or "").strip().lower()
        display_name = _extract_wecom_display_name(message, from_user)

        logger.info("WeCom callback received: msg_type=%s event=%s from_user=%s payload=%s", msg_type, event, from_user, message)

        if msg_type == "text" and from_user:
            user_service = UserService(db)
            user = user_service.get_or_create_by_wecom_userid(from_user, display_name=display_name)
            content = _normalize_wecom_content(message.get("Content") or "")
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
            return

        if msg_type == "event" and event == "enter_agent" and from_user:
            user_service = UserService(db)
            user_service.get_or_create_by_wecom_userid(from_user, display_name=display_name)
            await WeComService().send_message(
                from_user,
                "欢迎使用提醒助手。你可以直接发送一句话，例如：明天下午三点提醒我开会；也可以发送“帮助”查看快捷命令。",
            )
    except Exception:
        logger.exception("WeCom callback handling failed. payload=%s", message)
    finally:
        db.close()


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
    background_tasks: BackgroundTasks,
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
    now = time.time()
    _prune_wecom_seen_messages(now)
    message_key = _build_wecom_message_key(message)
    if message_key in _wecom_seen_messages:
        logger.info("Skipping duplicate WeCom callback: key=%s payload=%s", message_key, message)
        return Response(content="success", media_type="text/plain")

    _wecom_seen_messages[message_key] = now
    background_tasks.add_task(_process_wecom_message, message)
    return Response(content="success", media_type="text/plain")
