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
        store_dict = store_data.model_dump()
        if current_user.role == models.UserRole.store_owner:
            store_dict["owner_id"] = current_user.id
        db_store = models.Store(**store_dict)
        self.db.add(db_store)
        await self.db.commit()
        # Ensure relationships (products) are eagerly loaded for response serialization
        await self.db.refresh(db_store)
        return await self.get_store(db_store.id)

    async def get_store(self, store_id: int) -> models.Store:
        result = await self.db.execute(select(models.Store).options(selectinload(models.Store.products)).where(models.Store.id == store_id))
        store = result.unique().scalar_one_or_none()
        if not store:
            raise NotFoundError("Store", store_id)
        return store

    async def get_all_stores(self):
        result = await self.db.execute(select(models.Store).options(selectinload(models.Store.products)))
        return result.unique().scalars().all()

    async def get_stores_by_owner(self, owner_id: int):
        result = await self.db.execute(
            select(models.Store).options(selectinload(models.Store.products)).where(models.Store.owner_id == owner_id)
        )
        return result.unique().scalars().all()

    async def update_store(self, store_id: int, update_data: StoreUpdate, current_user: models.User):
        store = await self.get_store(store_id)
        if current_user.role == models.UserRole.store_owner:
            if store.owner_id != current_user.id:
                raise PermissionDeniedError("update", "store")

        for key, value in update_data.model_dump(exclude_unset=True).items():
            setattr(store, key, value)

        await self.db.commit()
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