from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from sqlalchemy.pool import NullPool
from app.config import get_settings

settings = get_settings()


# NullPool para ambiente de pipeline — evita connection leaks em scripts longos
engine = create_engine(
    settings.database_url,
    poolclass=NullPool,
    echo=settings.app_env == "development",
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency para injeção de sessão."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_session():
    """Context manager para uso em scripts/pipeline."""
    return SessionLocal()