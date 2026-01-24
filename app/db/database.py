# app/db/database.py (async)
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker
from app.core.config import settings
import logging
import time
from sqlalchemy import event

# Convert DATABASE_URL to async driver if using postgresql
database_url = settings.DATABASE_URL
if database_url.startswith("postgresql://"):
    database_url = database_url.replace("postgresql://", "postgresql+asyncpg://")

# Create async engine with pooling configuration
engine = create_async_engine(
    database_url,
    future=True,
    echo=False,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_pre_ping=settings.DB_POOL_PRE_PING,
)

AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()


def _setup_slow_query_logging():
    logger = logging.getLogger("sqlalchemy.slow")

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def before_cursor(conn, cursor, statement, parameters, context, executemany):
        conn.info.setdefault("query_start_time", []).append(time.time())

    @event.listens_for(engine.sync_engine, "after_cursor_execute")
    def after_cursor(conn, cursor, statement, parameters, context, executemany):
        start_times = conn.info.get("query_start_time")
        if not start_times:
            return
        start_time = start_times.pop(-1)
        duration_ms = (time.time() - start_time) * 1000
        if duration_ms >= settings.SLOW_QUERY_THRESHOLD_MS:
            logger.warning(
                "Slow query detected",
                extra={
                    "duration_ms": duration_ms,
                    "statement": statement,
                },
            )


_setup_slow_query_logging()


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
