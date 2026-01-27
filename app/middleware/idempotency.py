from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
import hashlib
import json
from app.core.redis import redis_client

class IdempotencyMiddleware(BaseHTTPMiddleware):
    """
    Middleware that enforces idempotency for POST endpoints.
    Caches JSON responses keyed by SHA256 of the Idempotency-Key header.
    """
    
    # TTL for idempotency keys in seconds (e.g., 24 hours)
    CACHE_TTL = 86400
    
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
        redis_key = f"idempotency:{key_hash}"
        
        # 2. Check Cache
        try:
            cached_response = await redis_client.get(redis_key)
            if cached_response:
                payload = json.loads(cached_response)
                # Return cached response immediately
                return JSONResponse(
                    content=payload.get("body"),
                    status_code=payload.get("status_code", 200),
                    headers={"X-Idempotency-Hit": "true"}
                )
        except Exception:
            # If cache read fails or is corrupted, proceed as if new
            pass
        
        # 3. Process Request
        response = await call_next(request)
        
        # 4. Capture Body
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
        
        try:
            # Use SETNX (SET if Not eXists) to handle race conditions
            # Returns True if key was set, False if key already exists
            await redis_client.set(
                redis_key,
                json.dumps(cache_payload),
                ex=self.CACHE_TTL,
                nx=True  # Only set if key doesn't exist (handles race condition)
            )
        except Exception:
            # If Redis write fails, still return the response to the client
            pass
        
        return response