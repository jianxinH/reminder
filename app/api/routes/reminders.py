from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.common import APIResponse
from app.schemas.reminder import (
    ReminderAuditData,
    ReminderCreateData,
    ReminderCreateRequest,
    ReminderDeduplicateData,
    ReminderResponse,
    ReminderSnoozeRequest,
    ReminderUpdateRequest,
)
from app.services.reminder_service import ReminderService

router = APIRouter(prefix="/api/reminders", tags=["reminders"])


@router.post("", response_model=APIResponse[ReminderCreateData])
def create_reminder(payload: ReminderCreateRequest, db: Session = Depends(get_db)):
    reminder = ReminderService(db).create_reminder(payload)
    return APIResponse(
        data=ReminderCreateData(
            reminder_id=reminder.id,
            title=reminder.title,
            next_remind_time=reminder.next_remind_time,
            status=reminder.status,
        )
    )


@router.get("", response_model=APIResponse[list[ReminderResponse]])
def list_reminders(
    user_id: int,
    status: str | None = None,
    repeat_type: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    db: Session = Depends(get_db),
):
    reminders = ReminderService(db).list_reminders(user_id, status, repeat_type, date_from, date_to)
    return APIResponse(data=[ReminderResponse.model_validate(item) for item in reminders])


@router.get("/audit", response_model=APIResponse[ReminderAuditData])
def audit_reminders(user_id: int, db: Session = Depends(get_db)):
    audit = ReminderService(db).audit_duplicates(user_id)
    return APIResponse(data=ReminderAuditData(**audit))


@router.post("/deduplicate", response_model=APIResponse[ReminderDeduplicateData])
def deduplicate_reminders(user_id: int, db: Session = Depends(get_db)):
    result = ReminderService(db).deduplicate_reminders(user_id)
    return APIResponse(
        data=ReminderDeduplicateData(**result),
        message=f"已清理 {result['removed_count']} 条重复提醒",
    )


@router.get("/{reminder_id}", response_model=APIResponse[ReminderResponse])
def get_reminder(reminder_id: int, db: Session = Depends(get_db)):
    reminder = ReminderService(db).get_reminder(reminder_id)
    return APIResponse(data=ReminderResponse.model_validate(reminder))


@router.patch("/{reminder_id}", response_model=APIResponse[None])
def update_reminder(reminder_id: int, payload: ReminderUpdateRequest, db: Session = Depends(get_db)):
    ReminderService(db).update_reminder(reminder_id, payload)
    return APIResponse(message="提醒已更新")


@router.delete("/{reminder_id}", response_model=APIResponse[None])
def delete_reminder(reminder_id: int, db: Session = Depends(get_db)):
    ReminderService(db).delete_reminder(reminder_id)
    return APIResponse(message="提醒已删除")


@router.post("/{reminder_id}/snooze", response_model=APIResponse[None])
def snooze_reminder(reminder_id: int, payload: ReminderSnoozeRequest, db: Session = Depends(get_db)):
    ReminderService(db).snooze_reminder(reminder_id, payload.minutes)
    return APIResponse(message=f"提醒已延后 {payload.minutes} 分钟")


@router.post("/{reminder_id}/done", response_model=APIResponse[None])
def mark_done(reminder_id: int, db: Session = Depends(get_db)):
    ReminderService(db).mark_done(reminder_id)
    return APIResponse(message="提醒已标记为完成")
