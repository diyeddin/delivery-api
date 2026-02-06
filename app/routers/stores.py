# app/routers/stores.py
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import models, database
from app.services.store_service import AsyncStoreService
from app.utils.exceptions import NotFoundError, PermissionDeniedError
from app.schemas.store import StoreCreate, StoreUpdate, StoreOut, StoreListOut
from app.utils.dependencies import require_scope

router = APIRouter(prefix="/stores", tags=["stores"])

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


@router.get("/", response_model=List[StoreListOut])
async def list_stores(
    q: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(database.get_db)
):
    """Public list of all stores with Search & Pagination."""
    svc = AsyncStoreService(db)
    return await svc.get_all_stores(q, category, limit, offset)


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