from fastapi import APIRouter, Depends, HTTPException
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import models, database
from app.services.store_service import AsyncStoreService
from app.utils.exceptions import NotFoundError
from app.schemas.store import StoreCreate, StoreUpdate, StoreOut
from app.utils.dependencies import require_scope

router = APIRouter(prefix="/stores", tags=["stores"])

@router.post("/", response_model=StoreOut)
async def create_store(
    store: StoreCreate,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_scope("stores:manage"))
):
    """Create a new store. Automatically assigns owner_id for Store Owners."""
    svc = AsyncStoreService(db)
    # The service handles the owner assignment logic using current_user
    return await svc.create_store(store, current_user)


@router.get("/me", response_model=List[StoreOut])
async def get_my_stores(
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_scope("stores:manage"))
):
    """Get stores owned by the current user. Matches GET /stores/me"""
    svc = AsyncStoreService(db)
    return await svc.get_stores_by_owner(current_user.id)


@router.get("/", response_model=List[StoreOut])
async def list_stores(db: AsyncSession = Depends(database.get_db)):
    """Public list of all stores"""
    svc = AsyncStoreService(db)
    return await svc.get_all_stores()


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
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_scope("stores:manage"))
):
    svc = AsyncStoreService(db)
    try:
        # Check ownership logic should be inside service or here
        # For simplicity, we assume service handles permission check 
        # (e.g., verifying current_user.id == store.owner_id)
        return await svc.update_store(store_id, update, current_user)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Store not found")


@router.delete("/{store_id}")
async def delete_store(
    store_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_scope("stores:manage"))
):
    svc = AsyncStoreService(db)
    try:
        await svc.delete_store(store_id, current_user)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Store not found")
    return {"detail": "Store deleted"}


@router.get("/{store_id}/products")
async def get_store_products(
    store_id: int,
    db: AsyncSession = Depends(database.get_db)
):
    """Get all products for a specific store"""
    svc = AsyncStoreService(db)
    try:
        # Ensure store exists first
        await svc.get_store(store_id)
        return await svc.get_store_products(store_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Store not found")