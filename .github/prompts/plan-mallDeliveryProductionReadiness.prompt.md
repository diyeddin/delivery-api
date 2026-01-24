# Mall Delivery API - Production Readiness Implementation Plan

## Executive Summary

This document outlines a phased approach to transform the Mall Delivery API from development-ready to production-grade. The plan addresses critical gaps in concurrency control, observability, security, and scalability.

**Estimated Timeline:** 6-8 weeks (3 phases)  
**Priority Order:** Security → Concurrency → Observability → Scalability

---

## Phase 1: Security & Data Integrity (Weeks 1-2)

### Critical Priority

#### 1.1 Atomic Order Operations with Distributed Locking
**Problem:** Race condition in driver order acceptance allows double-booking.

**Files to Modify:**
- `app/routers/drivers.py` (accept_order endpoint)
- `app/routers/orders.py` (assign_driver endpoint)
- `app/db/database.py` (add pessimistic locking)

**Pattern Example:**
```python
from sqlalchemy import select
from sqlalchemy.orm import Session

async def accept_order_atomic(db: Session, order_id: int, driver_id: int):
    """Atomic order acceptance with row-level locking"""
    async with db.begin():
        # SELECT ... FOR UPDATE locks the row
        stmt = select(Order).where(
            Order.id == order_id,
            Order.status == OrderStatus.confirmed,
            Order.driver_id.is_(None)
        ).with_for_update()
        
        result = await db.execute(stmt)
        order = result.scalar_one_or_none()
        
        if not order:
            raise ConflictError("Order already assigned or unavailable")
        
        order.driver_id = driver_id
        order.status = OrderStatus.assigned
        # Commit happens automatically at context exit
```

**Tasks:**
- [x] Add `SELECT ... FOR UPDATE` to order acceptance queries
- [x] Implement retry logic with exponential backoff for lock conflicts
- [x] Add integration tests for concurrent order acceptance
- [x] Update OpenAPI docs to reflect 409 Conflict responses

---

#### 1.2 Idempotency Keys for Critical Endpoints
**Problem:** Duplicate order creation on network retries.

**Files to Modify:**
- `app/routers/orders.py` (create_order endpoint)
- `app/db/models.py` (add IdempotencyKey model)
- `app/middleware/` (create new idempotency middleware)

**Pattern Example:**
```python
from fastapi import Header, HTTPException
from typing import Optional
import hashlib

async def check_idempotency(
    idempotency_key: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    """Middleware to prevent duplicate requests"""
    if not idempotency_key:
        raise HTTPException(422, "Idempotency-Key header required")
    
    key_hash = hashlib.sha256(idempotency_key.encode()).hexdigest()
    existing = await db.get(IdempotencyKey, key_hash)
    
    if existing:
        return existing.response_data  # Return cached response
    
    return None  # Proceed with request
```

**Tasks:**
- [x] Create `IdempotencyKey` model with (key_hash, response_json, created_at)
- [ ] Add TTL cleanup job for old idempotency records (7 days)
- [x] Implement middleware for POST /orders and POST /payments
- [ ] Add `Idempotency-Key` to OpenAPI schema
- [x] Write unit tests for duplicate request scenarios

---

#### 1.3 Pydantic Request Validation Hardening
**Problem:** Missing `extra='forbid'` allows unexpected fields.

**Files to Modify:**
- `app/schemas/order.py`
- `app/schemas/product.py`
- `app/schemas/store.py`
- `app/schemas/user.py`

**Pattern Example:**
```python
from pydantic import BaseModel, ConfigDict

class OrderCreate(BaseModel):
    model_config = ConfigDict(
        extra='forbid',  # Reject unknown fields
        frozen=True,     # Immutable after creation
        str_strip_whitespace=True
    )
    
    items: List[OrderItemCreate] = Field(..., min_length=1)
```

**Tasks:**
    - [x] Add `extra='forbid'` to all request schemas
    - [x] Add `frozen=True` to prevent mutation attacks
    - [x] Update integration tests to verify rejection of extra fields
    - [ ] Document breaking change in API changelog

---

#### 1.4 JWT Scope-Based Authorization
**Problem:** Role checking is inconsistent; missing granular permissions.

**Files to Modify:**
- `app/core/security.py` (add scope encoding)
- `app/utils/dependencies.py` (add scope verification)

**Pattern Example:**
```python
def create_access_token(user: User) -> str:
    scopes = {
        UserRole.admin: ["orders:read", "orders:write", "users:manage"],
        UserRole.driver: ["orders:read", "orders:update_status"],
        UserRole.customer: ["orders:create", "orders:read_own"]
    }
    
    payload = {
        "sub": user.email,
        "scopes": scopes[user.role],
        "exp": datetime.utcnow() + timedelta(minutes=30)
    }
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")

def require_scope(required_scope: str):
    def scope_checker(token: str = Depends(oauth2_scheme)):
        payload = verify_token(token)
        if required_scope not in payload.get("scopes", []):
            raise HTTPException(403, f"Missing scope: {required_scope}")
    return scope_checker
```

**Tasks:**
- [x] Define scope matrix for all roles
- [x] Update `create_access_token` to include scopes
- [x] Replace `require_role` with `require_scope` in routers
- [x] Add scope verification tests
- [ ] Document scopes in OpenAPI security schemes

---

## Phase 2: Async Architecture & Concurrency (Weeks 3-4)

### High Priority

#### 2.1 Migrate to Async SQLAlchemy
**Problem:** Synchronous DB calls block the event loop under high load.

**Files to Modify:**
- `app/db/database.py` (switch to AsyncEngine)
- All routers and services (add `async`/`await`)
- `app/utils/dependencies.py` (async session dependency)

**Pattern Example:**
```python
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

engine = create_async_engine(
    settings.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://"),
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True
)

AsyncSessionLocal = sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
```

**Tasks:**
- [x] Install `asyncpg` and `sqlalchemy[asyncio]`
- [x] Update `DATABASE_URL` to use `postgresql+asyncpg://`
- [ ] Convert all `db.query()` to `await db.execute(select(...))`
- [ ] Update Alembic to use async engine
- [ ] Load test async vs sync performance (target: 3x throughput)

---

#### 2.2 Background Task Queue with Celery/ARQ
**Problem:** No async processing for notifications, analytics, cleanup jobs.

**Files to Create:**
- `app/tasks/celery_app.py`
- `app/tasks/order_tasks.py`
- `app/tasks/notification_tasks.py`

**Pattern Example:**
```python
from celery import Celery

celery_app = Celery(
    "mall_delivery",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL
)

@celery_app.task(bind=True, max_retries=3)
def send_order_notification(self, order_id: int):
    try:
        order = get_order(order_id)
        send_sms(order.user.phone, f"Order #{order_id} is on the way!")
    except Exception as exc:
        raise self.retry(exc=exc, countdown=60)
```

**Tasks:**
- [ ] Choose Celery (mature) vs ARQ (async-native)
- [ ] Set up Redis as message broker
- [ ] Create tasks for: order notifications, stock alerts, driver assignments
- [ ] Add Flower for task monitoring
- [ ] Implement task retry policies and dead-letter queues

---

#### 2.3 Connection Pooling & Database Optimization
**Problem:** Default connection pool exhausts under load.

**Files to Modify:**
- `app/db/database.py`
- `app/core/config.py` (add pool settings)

**Tasks:**
- [ ] Configure pool size based on expected concurrency (start: 20)
- [ ] Enable `pool_pre_ping` to handle stale connections
- [ ] Add connection pool metrics to health check
- [ ] Set up query logging for slow queries (>100ms)
- [ ] Create indexes on foreign keys (order.user_id, order.driver_id, etc.)

---

## Phase 3: Observability & Operational Excellence (Weeks 5-6)

### Medium Priority

#### 3.1 Structured Logging with Trace IDs
**Problem:** Logs lack request correlation; hard to debug distributed flows.

**Files to Modify:**
- `app/core/logging.py` (add trace_id injection)
- `app/main.py` (add middleware)

**Pattern Example:**
```python
import uuid
from starlette.middleware.base import BaseHTTPMiddleware

class TraceIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        trace_id = request.headers.get("X-Trace-ID", str(uuid.uuid4()))
        request.state.trace_id = trace_id
        
        # Inject into structlog context
        structlog.contextvars.bind_contextvars(trace_id=trace_id)
        
        response = await call_next(request)
        response.headers["X-Trace-ID"] = trace_id
        return response
```

**Tasks:**
- [ ] Add `TraceIDMiddleware` to `app.main`
- [ ] Update all log calls to include trace_id
- [ ] Propagate trace_id to Celery tasks
- [ ] Configure log aggregation (ELK, Datadog, or CloudWatch)
- [ ] Add trace_id to error responses

---

#### 3.2 Health Check Enhancements
**Problem:** Basic health check doesn't report component status.

**Files to Modify:**
- `app/main.py` (enhance /health endpoints)

**Pattern Example:**
```python
@app.get("/health/readiness")
async def readiness():
    checks = {
        "database": await check_db_connection(),
        "redis": await check_redis_connection(),
        "disk_space": check_disk_space() > 10  # GB
    }
    
    if not all(checks.values()):
        raise HTTPException(503, detail=checks)
    
    return {"status": "ready", "checks": checks}
```

**Tasks:**
- [ ] Add database connection pool status
- [ ] Add Redis connectivity check
- [ ] Add disk space check
- [ ] Implement `/health/startup` for init checks
- [ ] Configure Kubernetes probes to use new endpoints

---

#### 3.3 API Rate Limiting
**Problem:** No protection against abuse or DDoS.

**Files to Modify:**
- `app/main.py` (add slowapi middleware)
- `app/routers/auth.py` (apply limits)

**Pattern Example:**
```python
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address, storage_uri=settings.REDIS_URL)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

@app.post("/auth/login")
@limiter.limit("5/minute")  # 5 login attempts per minute
async def login(request: Request, ...):
    ...
```

**Tasks:**
- [ ] Install `slowapi`
- [ ] Apply limits: auth (5/min), orders (20/min), reads (100/min)
- [ ] Use Redis for distributed rate limit storage
- [ ] Add rate limit headers (X-RateLimit-Remaining)
- [ ] Document rate limits in API docs

---

#### 3.4 Metrics & Monitoring
**Problem:** No visibility into system performance.

**Tasks:**
- [ ] Add Prometheus metrics endpoint (`/metrics`)
- [ ] Track: request latency, DB query time, order throughput
- [ ] Set up Grafana dashboards
- [ ] Configure alerts: high error rate, slow queries, failed orders
- [ ] Add custom business metrics (orders/hour, avg delivery time)

---

## Phase 4: Scalability & Performance (Weeks 7-8)

### Low Priority (Post-MVP)

#### 4.1 Geospatial Queries with PostGIS
**Problem:** Inefficient delivery radius calculations.

**Tasks:**
- [ ] Enable PostGIS extension in PostgreSQL
- [ ] Add `geography` columns to Store model (lat, lng)
- [ ] Create spatial index on store locations
- [ ] Implement radius queries: `ST_DWithin(location, point, radius)`
- [ ] Benchmark: current vs PostGIS performance

---

#### 4.2 Caching Layer with Redis
**Problem:** Repeated queries for static data (product catalog).

**Tasks:**
- [ ] Implement Redis caching for:
  - Product details (TTL: 5 minutes)
  - Store info (TTL: 10 minutes)
  - User sessions
- [ ] Add cache invalidation on updates
- [ ] Use cache-aside pattern with async wrappers
- [ ] Monitor cache hit rate (target: >80%)

---

#### 4.3 API Versioning
**Problem:** Breaking changes will affect existing clients.

**Tasks:**
- [ ] Implement URL-based versioning (`/api/v1/orders`)
- [ ] Set up version negotiation via headers
- [ ] Maintain v1 and v2 in parallel during deprecation
- [ ] Document migration guide in API docs

---

## Testing Strategy

### Per-Phase Testing Requirements

**Phase 1 (Security):**
- [ ] Penetration testing for injection attacks
- [ ] Load test order acceptance with 100 concurrent drivers
- [ ] Chaos testing: kill DB mid-transaction

**Phase 2 (Async):**
- [ ] Benchmark sync vs async (target: 50% latency reduction)
- [ ] Test Celery task failure recovery
- [ ] Verify no event loop blocking with async profiler

**Phase 3 (Observability):**
- [ ] Trace a request through 5 microservices
- [ ] Verify logs aggregated correctly
- [ ] Simulate health check failures

**Phase 4 (Scalability):**
- [ ] Load test: 10,000 concurrent users
- [ ] Test horizontal scaling (2 → 4 instances)
- [ ] Verify cache invalidation correctness

---

## Dependencies & Prerequisites

### Infrastructure
- PostgreSQL 14+ with PostGIS extension
- Redis 6+ for rate limiting and caching
- Docker Compose for local development
- Kubernetes for production orchestration

### Libraries to Add
```txt
# requirements.txt additions
asyncpg>=0.28.0
sqlalchemy[asyncio]>=2.0
celery[redis]>=5.3.0
slowapi>=0.1.9
prometheus-fastapi-instrumentator>=6.1.0
structlog>=23.1.0
```

### Team Skills Needed
- SQLAlchemy async patterns
- Celery task design
- Prometheus/Grafana setup
- Load testing with Locust/k6

---

## Risk Mitigation

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Async migration breaks existing code | High | Incremental rollout per router |
| Celery adds complexity | Medium | Start with 3 simple tasks, expand later |
| Rate limiting too aggressive | Low | Start permissive, tighten based on metrics |
| PostGIS migration downtime | Medium | Run dual-write during transition |

---

## Success Metrics

**Phase 1:** Zero double-bookings in 1 week of production traffic  
**Phase 2:** 99th percentile latency <200ms for order creation  
**Phase 3:** 100% trace coverage for errors; <5min MTTD (Mean Time To Detect)  
**Phase 4:** Support 10K concurrent users with <500ms p99 latency

---

## Next Steps

1. **Week 0:** Review this plan with team, prioritize phases
2. **Week 1:** Start Phase 1.1 (atomic operations) - highest ROI
3. **Continuous:** Run existing tests after each change
4. **Post-Phase 1:** Decision point: proceed to Phase 2 or iterate

---

**Document Version:** 1.0  
**Last Updated:** 2025-01-23  
**Owner:** Backend Team  
**Reviewers:** DevOps, Security, Product
