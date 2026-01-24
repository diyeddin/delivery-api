from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response
from typing import Callable
import hashlib
import json
from datetime import datetime, timezone

from app.db import database, models
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import inspect


class IdempotencyMiddleware(BaseHTTPMiddleware):
    """Middleware that enforces idempotency for POST endpoints when Idempotency-Key header is provided.

    It caches JSON responses keyed by SHA256 of the header value. Only applied to POST /orders and /payments paths.
    """

    async def dispatch(self, request, call_next: Callable):
        # Only handle POSTs for targeted endpoints
        if request.method.upper() != "POST":
            return await call_next(request)

        path = request.url.path
        if not (path.startswith("/orders") or path.startswith("/payments")):
            return await call_next(request)

        key = request.headers.get("Idempotency-Key") or request.headers.get("idempotency-key")
        if not key:
            return await call_next(request)

        key_hash = hashlib.sha256(key.encode()).hexdigest()

        # acquire a DB session; prefer app's dependency override (used by tests)
        get_db_override = None
        try:
            get_db_override = request.app.dependency_overrides.get(database.get_db)
        except Exception:
            get_db_override = None

        # Obtain generator from override or default dependency
        gen = None
        async_gen = False
        try:
            if get_db_override:
                gen = get_db_override()
            else:
                gen = database.get_db()

            if inspect.isasyncgen(gen):
                # async generator -> await next to get session
                db = await gen.__anext__()
                async_gen = True
            else:
                db = next(gen)

            # Check for existing cache entry using sync or async session APIs
            existing = None
            if isinstance(db, AsyncSession):
                res = await db.execute(select(models.IdempotencyKey).where(models.IdempotencyKey.key_hash == key_hash))
                existing = res.scalar_one_or_none()
            else:
                existing = db.query(models.IdempotencyKey).filter(models.IdempotencyKey.key_hash == key_hash).first()

            if existing:
                try:
                    payload = json.loads(existing.response_payload)
                    return JSONResponse(content=payload.get("body"), status_code=payload.get("status_code", 200))
                except Exception:
                    pass

            # Not cached: process request
            response = await call_next(request)

            # Safely read response body
            body_bytes = b""
            if hasattr(response, "body") and response.body is not None:
                body_bytes = response.body
            else:
                try:
                    chunks = []
                    async for chunk in response.body_iterator:
                        chunks.append(chunk)
                    body_bytes = b"".join(chunks)
                except Exception:
                    body_bytes = b""

            try:
                body_text = body_bytes.decode()
                body_json = json.loads(body_text) if body_text else {}
            except Exception:
                body_json = body_bytes.decode(errors="ignore")

            cache_payload = {"status_code": response.status_code, "body": body_json}

            record = models.IdempotencyKey(
                key_hash=key_hash,
                response_payload=json.dumps(cache_payload),
                created_at=datetime.now(timezone.utc),
            )

            try:
                if isinstance(db, AsyncSession):
                    db.add(record)
                    await db.commit()
                else:
                    db.add(record)
                    db.commit()
            except Exception:
                try:
                    if isinstance(db, AsyncSession):
                        await db.rollback()
                    else:
                        db.rollback()
                except Exception:
                    pass

            return JSONResponse(content=cache_payload["body"], status_code=cache_payload["status_code"])
        finally:
            # close session and close generator appropriately
            try:
                if gen is not None:
                    if async_gen:
                        await gen.aclose()
                    else:
                        try:
                            gen.close()
                        except Exception:
                            pass
            except Exception:
                pass
