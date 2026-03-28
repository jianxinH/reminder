from collections.abc import Generator

from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()
BASE_DIR = Path(__file__).resolve().parents[2]


def _resolve_database_url(raw_url: str) -> str:
    if raw_url.startswith("sqlite:///./"):
        db_path = BASE_DIR / raw_url.removeprefix("sqlite:///./")
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{db_path.as_posix()}"
    if raw_url.startswith("sqlite:////"):
        parsed = urlparse(raw_url)
        db_path = Path(parsed.path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
    return raw_url

engine = create_engine(
    _resolve_database_url(settings.database_url),
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def ensure_schema() -> None:
    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("users")}
    with engine.begin() as connection:
        if "wecom_userid" not in columns:
            connection.execute(text("ALTER TABLE users ADD COLUMN wecom_userid VARCHAR(100)"))


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
