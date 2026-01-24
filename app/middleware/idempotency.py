from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from starlette.datastructures import MutableHeaders
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.db import models
from app.db.database import AsyncSessionLocal # Ensure this is exported in database.py
import hashlib
import json
from datetime import datetime, timezone

class IdempotencyMiddleware(BaseHTTPMiddleware):
    """
    Middleware that enforces idempotency for POST endpoints.
    Caches JSON responses keyed by SHA256 of the Idempotency-Key header.
    """

    async def dispatch(self, request, call_next):
        # 1. Filter: Only handle POSTs for specific paths
        if request.method.upper() != "POST":
            return await call_next(request)

        path = request.url.path
        if not (path.startswith("/orders") or path.startswith("/payments")):
            return await call_next(request)

        key = request.headers.get("Idempotency-Key") or request.headers.get("idempotency-key")
        if not key:
            return await call_next(request)

        key_hash = hashlib.sha256(key.encode()).hexdigest()

        # 2. Check Cache (Use a fresh session, not the dependency injection system)
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(models.IdempotencyKey).where(models.IdempotencyKey.key_hash == key_hash)
            )
            existing = result.scalar_one_or_none()
            
            if existing:
                try:
                    payload = json.loads(existing.response_payload)
                    # Return cached response immediately
                    return JSONResponse(
                        content=payload.get("body"), 
                        status_code=payload.get("status_code", 200),
                        # Ideally, we should also cache and restore important headers here
                        headers={"X-Idempotency-Hit": "true"}
                    )
                except Exception:
                    # If cache is corrupted, proceed as if new
                    pass

        # 3. Process Request
        response = await call_next(request)

        # 4. Capture Body
        # We need to consume the iterator to read the body, then queue it back up
        # so the client can still receive it if we fail to save.
        response_body = [section async for section in response.body_iterator]
        response.body_iterator = iter(response_body)
        
        try:
            body_bytes = b"".join(response_body)
            body_text = body_bytes.decode()
            body_json = json.loads(body_text) if body_text else {}
        except Exception:
            # If response isn't JSON, we skip caching to avoid breaking things
            return response

        # Only cache successful/client-error responses, not server errors (500)
        if response.status_code >= 500:
            return response

        # 5. Save to Cache
        cache_payload = {
            "status_code": response.status_code, 
            "body": body_json
        }

        async with AsyncSessionLocal() as session:
            try:
                record = models.IdempotencyKey(
                    key_hash=key_hash,
                    response_payload=json.dumps(cache_payload),
                    created_at=datetime.now(timezone.utc),
                )
                session.add(record)
                await session.commit()
            except IntegrityError:
                # RACE CONDITION HANDLER:
                # If we get here, another request saved this key while we were processing.
                # In a strict system, we might rollback the order, but since the order 
                # is already committed by the endpoint, we just swallow the error 
                # and return the response.
                await session.rollback()
            except Exception:
                await session.rollback()

        return response