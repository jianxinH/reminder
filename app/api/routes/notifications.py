from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.common import APIResponse
from app.schemas.notification import NotificationInboxItem, NotificationLogResponse, NotificationSendRequest
from app.services.notification_service import NotificationService
from app.services.reminder_service import ReminderService

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.post("/send", response_model=APIResponse[dict])
async def send_notification(payload: NotificationSendRequest, db: Session = Depends(get_db)):
    reminder = ReminderService(db).get_reminder(payload.reminder_id)
    result = await NotificationService(db).send_reminder_notification(reminder)
    return APIResponse(data=result)


@router.get("/logs", response_model=APIResponse[list[NotificationLogResponse]])
def list_notification_logs(user_id: int, db: Session = Depends(get_db)):
    logs = NotificationService(db).list_logs(user_id)
    return APIResponse(data=[NotificationLogResponse.model_validate(item) for item in logs])


@router.get("/inbox", response_model=APIResponse[list[NotificationInboxItem]])
def list_notification_inbox(user_id: int, after_id: int = 0, db: Session = Depends(get_db)):
    items = NotificationService(db).list_inbox(user_id, after_id)
    return APIResponse(data=[NotificationInboxItem.model_validate(item) for item in items])
