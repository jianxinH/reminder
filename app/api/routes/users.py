from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.common import APIResponse
from app.schemas.user import UserRegisterData, UserRegisterRequest, UserResponse, UserUpdateRequest
from app.services.user_service import UserService

router = APIRouter(prefix="/api/users", tags=["users"])


@router.post("/register", response_model=APIResponse[UserRegisterData])
def register_user(payload: UserRegisterRequest, db: Session = Depends(get_db)):
    user = UserService(db).register(payload)
    return APIResponse(data=UserRegisterData(user_id=user.id, user_uuid=user.user_uuid))


@router.get("/{user_id}", response_model=APIResponse[UserResponse])
def get_user(user_id: int, db: Session = Depends(get_db)):
    user = UserService(db).get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return APIResponse(data=UserResponse.model_validate(user))


@router.patch("/{user_id}", response_model=APIResponse[None])
def update_user(user_id: int, payload: UserUpdateRequest, db: Session = Depends(get_db)):
    user = UserService(db).update_user(user_id, payload)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return APIResponse(message="User updated")
