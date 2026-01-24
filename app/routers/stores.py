from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import models, database
from app.services.store_service import AsyncStoreService
from app.utils.exceptions import NotFoundError
from app.schemas.store import StoreCreate, StoreUpdate, StoreOut
from typing import List
from app.utils.dependencies import require_scope

router = APIRouter(prefix="/stores", tags=["stores"])

@router.post("/", response_model=StoreOut)
async def create_store(
    store: StoreCreate,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_scope("stores:manage"))
    ):
    store_data = store.model_dump()

    # Set the owner_id to the current user if they're a store_owner
    if current_user.role == models.UserRole.store_owner:
        store_data["owner_id"] = current_user.id
    # Admins can create stores without setting ownership (owner_id = None)

    svc = AsyncStoreService(db)
    return await svc.create_store(store, current_user)


@router.get("/", response_model=List[StoreOut])
async def list_stores(db: AsyncSession = Depends(database.get_db)):
    svc = AsyncStoreService(db)
    return await svc.get_all_stores()


@router.get("/my-stores", response_model=List[StoreOut])
async def get_my_stores(
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_scope("stores:manage"))
):
    """Get stores owned by the current store owner."""
    svc = AsyncStoreService(db)
    return await svc.get_stores_by_owner(current_user.id)


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
    # Check if store exists
    svc = AsyncStoreService(db)
    try:
        await svc.get_store(store_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Store not found")
    return await svc.get_store_products(store_id)
