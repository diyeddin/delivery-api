# app/routers/stores.py
import datetime
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from typing import Generic, List, Optional, TypeVar
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.db import models, database
from app.schemas.review import ReviewCreate, ReviewOut
from app.services.store_service import AsyncStoreService
from app.utils.exceptions import NotFoundError, PermissionDeniedError
from app.schemas.store import StoreCreate, StoreUpdate, StoreOut, StoreListOut
from app.utils.dependencies import get_current_user, require_scope

router = APIRouter(prefix="/stores", tags=["stores"])

T = TypeVar("T")
class Page(BaseModel, Generic[T]):
    data: List[T]
    total: int

@router.post("/", response_model=StoreOut)
async def create_store(
    store: StoreCreate,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_scope("stores:manage"))
):
    """Create a new store."""
    svc = AsyncStoreService(db)
    return await svc.create_store(store, current_user)


@router.get("/me", response_model=List[StoreListOut])
async def get_my_stores(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_scope("stores:manage"))
):
    """Get stores owned by the current user (Paginated)."""
    svc = AsyncStoreService(db)
    return await svc.get_stores_by_owner(current_user.id, limit, offset)


@router.get("/", response_model=Page[StoreListOut]) # 👈 Returns { data: [...], total: 10 }
async def list_stores(
    q: Optional[str] = None,
    category: Optional[str] = None,
    # 👇 NEW: Sorting Parameter
    sort_by: Optional[str] = Query("newest", pattern="^(newest|rating|name)$"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(database.get_db)
):
    """Public list of all stores with Search, Filtering & Pagination."""
    svc = AsyncStoreService(db)
    # Pass sort_by to the service
    return await svc.get_all_stores(q, category, sort_by, limit, offset)

@router.get("/{store_id}", response_model=StoreOut)
async def get_store(store_id: int, db: AsyncSession = Depends(database.get_db)):
    svc = AsyncStoreService(db)
    try:
        return await svc.get_store(store_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Store not found")


@router.put("/{store_id}", response_model=StoreOut)
async def update_store(
    store_id: int,
    update: StoreUpdate,
    bg_tasks: BackgroundTasks,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_scope("stores:manage"))
):
    svc = AsyncStoreService(db)
    try:
        return await svc.update_store(store_id, update, current_user, bg_tasks)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Store not found")
    except PermissionDeniedError:
        raise HTTPException(status_code=403, detail="You do not own this store")


@router.delete("/{store_id}")
async def delete_store(
    store_id: int,
    bg_tasks: BackgroundTasks,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_scope("stores:manage"))
):
    svc = AsyncStoreService(db)
    try:
        await svc.delete_store(store_id, current_user, bg_tasks)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Store not found")
    except PermissionDeniedError:
        raise HTTPException(status_code=403, detail="You do not own this store")
    
    return {"detail": "Store deleted"}

# 👇 RESTORED: Legacy endpoint for Website
@router.get("/{store_id}/products")
async def get_store_products(
    store_id: int,
    db: AsyncSession = Depends(database.get_db)
):
    """Get all products for a specific store (Legacy/Website use)."""
    svc = AsyncStoreService(db)
    try:
        # Ensure store exists first
        await svc.get_store(store_id)
        return await svc.get_store_products(store_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Store not found")

@router.post("/{store_id}/review", response_model=ReviewOut)
async def create_review(
    store_id: int,
    payload: ReviewCreate,
    order_id: int = Query(..., description="The ID of the order being reviewed"), 
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user)
):
    """
    Submit a review via the Service Layer.
    """
    svc = AsyncStoreService(db)
    
    # Delegate all logic to the service
    new_review = await svc.create_review(
        store_id=store_id,
        order_id=order_id,
        payload=payload,
        current_user=current_user
    )
    
    # Return formatted response
    return {
        "id": new_review.id,
        "rating": new_review.rating,
        "comment": new_review.comment,
        "created_at": new_review.created_at,
        "user_name": current_user.name or "Anonymous"
    }

@router.get("/{store_id}/reviews", response_model=List[ReviewOut])
async def get_store_reviews(
    store_id: int,
    limit: int = 20,
    offset: int = 0,
    db: AsyncSession = Depends(database.get_db)
):
    """Get a paginated list of reviews for a store."""
    
    # 1. Fetch Reviews + User Data (Optimized)
    stmt = (
        select(models.Review)
        .options(selectinload(models.Review.user)) # Load user to get names
        .where(models.Review.store_id == store_id)
        .order_by(models.Review.created_at.desc()) # Newest first
        .limit(limit)
        .offset(offset)
    )
    
    result = await db.execute(stmt)
    reviews = result.scalars().all()

    # 2. Format Response (Map user.name to user_name)
    return [
        {
            "id": r.id,
            "rating": r.rating,
            "comment": r.comment,
            "created_at": r.created_at,
            "user_name": r.user.name if r.user else "Anonymous"
        }
        for r in reviews
    ]