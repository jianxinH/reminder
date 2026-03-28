from sqlalchemy.orm import Session

from app.repositories.user_repository import UserRepository
from app.schemas.user import UserRegisterRequest, UserUpdateRequest


class UserService:
    def __init__(self, db: Session):
        self.repo = UserRepository(db)

    def register(self, payload: UserRegisterRequest):
        return self.repo.create(payload)

    def get_user(self, user_id: int):
        return self.repo.get_by_id(user_id)

    def get_by_telegram_chat_id(self, chat_id: str):
        return self.repo.get_by_telegram_chat_id(chat_id)

    def get_by_wecom_userid(self, wecom_userid: str):
        return self.repo.get_by_wecom_userid(wecom_userid)

    def update_user(self, user_id: int, payload: UserUpdateRequest):
        user = self.repo.get_by_id(user_id)
        if not user:
            return None
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(user, field, value)
        return self.repo.save(user)
