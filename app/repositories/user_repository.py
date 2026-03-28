from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.user import User
from app.schemas.user import UserRegisterRequest


class UserRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, payload: UserRegisterRequest) -> User:
        user = User(
            user_uuid=f"u_{uuid4().hex[:12]}",
            username=payload.username,
            display_name=payload.display_name,
            telegram_chat_id=payload.telegram_chat_id,
            wecom_userid=payload.wecom_userid,
            email=payload.email,
            default_channel=payload.default_channel,
            timezone=payload.timezone,
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def get_by_id(self, user_id: int) -> User | None:
        return self.db.query(User).filter(User.id == user_id).first()

    def get_by_telegram_chat_id(self, chat_id: str) -> User | None:
        return self.db.query(User).filter(User.telegram_chat_id == chat_id).first()

    def save(self, user: User) -> User:
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user
