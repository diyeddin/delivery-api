"""
Store service layer for business logic separation.
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from typing import List
from app.db import models
from app.schemas.store import StoreCreate, StoreUpdate
from app.utils.exceptions import NotFoundError, PermissionDeniedError

class AsyncStoreService:
    """Async store service using AsyncSession."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_store(self, store_data: StoreCreate, current_user: models.User) -> models.Store:
        # 1. Enforce Single Store Policy
        existing_stores = await self.get_stores_by_owner(current_user.id)
        if len(existing_stores) > 0:
            raise PermissionDeniedError("create", "more than one store. You are limited to 1 store.")
        
        store_dict = store_data.model_dump()
        
        if current_user.role == models.UserRole.store_owner:
            store_dict["owner_id"] = current_user.id
            
        db_store = models.Store(**store_dict)
        self.db.add(db_store)
        await self.db.commit()
        await self.db.refresh(db_store)
        
        # CRITICAL FIX: Return via get_store to ensure products are eager loaded.
        # Returning db_store directly causes MissingGreenlet error because 
        # products relationship is lazy-loaded.
        return await self.get_store(db_store.id)

    async def get_store(self, store_id: int) -> models.Store:
        # options(selectinload(...)) prevents MissingGreenlet error
        stmt = select(models.Store).options(selectinload(models.Store.products)).where(models.Store.id == store_id)
        result = await self.db.execute(stmt)
        store = result.unique().scalar_one_or_none()
        
        if not store:
            raise NotFoundError("Store", store_id)
        return store

    async def get_all_stores(self):
        stmt = select(models.Store).options(selectinload(models.Store.products))
        result = await self.db.execute(stmt)
        return result.unique().scalars().all()

    async def get_stores_by_owner(self, owner_id: int):
        stmt = select(models.Store).options(selectinload(models.Store.products)).where(models.Store.owner_id == owner_id)
        result = await self.db.execute(stmt)
        return result.unique().scalars().all()

    async def update_store(self, store_id: int, update_data: StoreUpdate, current_user: models.User):
        store = await self.get_store(store_id)
        
        if current_user.role == models.UserRole.store_owner:
            if store.owner_id != current_user.id:
                raise PermissionDeniedError("update", "store")

        for key, value in update_data.model_dump(exclude_unset=True).items():
            setattr(store, key, value)

        await self.db.commit()
        # Refresh is usually enough for scalars, but to be safe with relationships, 
        # we return the fully loaded object via get_store if needed, 
        # but here we assume products didn't change.
        await self.db.refresh(store)
        return store

    async def delete_store(self, store_id: int, current_user: models.User):
        store = await self.get_store(store_id)
        
        if current_user.role == models.UserRole.store_owner:
            if store.owner_id != current_user.id:
                raise PermissionDeniedError("delete", "store")
                
        await self.db.delete(store)
        await self.db.commit()

    async def get_store_products(self, store_id: int) -> List[models.Product]:
        result = await self.db.execute(select(models.Product).where(models.Product.store_id == store_id))
        return result.unique().scalars().all()