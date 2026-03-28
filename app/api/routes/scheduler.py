from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.common import APIResponse
from app.services.scheduler_service import SchedulerService

router = APIRouter(prefix="/api/scheduler", tags=["scheduler"])


@router.post("/scan-due-reminders", response_model=APIResponse[dict])
async def scan_due_reminders(db: Session = Depends(get_db)):
    result = await SchedulerService(db).scan_due_reminders()
    return APIResponse(data=result)
