# app/services/store_service.py
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from sqlalchemy.orm import selectinload
from typing import List, Optional, Union, Any
from app.db import models
from app.schemas.store import StoreCreate, StoreUpdate
from app.utils.exceptions import NotFoundError, PermissionDeniedError
from app.utils.image_utils import delete_cloudinary_image
from app.core.redis import redis_client
from fastapi import BackgroundTasks
import json

class AsyncStoreService:
    """Async store service using AsyncSession with Redis caching."""
    
    # Cache TTLs (in seconds)
    STORE_CACHE_TTL = 600
    
    def __init__(self, db: AsyncSession):
        self.db = db

    # --- HELPER: Handle Dict vs Object ---
    def _get_attr(self, obj: Union[dict, Any], key: str):
        if isinstance(obj, dict):
            return obj.get(key)
        return getattr(obj, key)

    # --- CACHE HELPERS ---
    def _serialize_store(self, store: models.Store) -> dict:
        products = self._get_attr(store, "products")
        serialized_products = []
        
        if products is not None: 
            try:
                for p in products:
                    serialized_products.append({
                        "id": self._get_attr(p, "id"),
                        "name": self._get_attr(p, "name"),
                        "description": self._get_attr(p, "description"),
                        "price": float(self._get_attr(p, "price")),
                        "stock": self._get_attr(p, "stock"),
                        "store_id": self._get_attr(p, "store_id"),
                        "category": self._get_attr(p, "category"),
                        "image_url": self._get_attr(p, "image_url"),
                    })
            except Exception:
                pass

        return {
            "id": self._get_attr(store, "id"),
            "name": self._get_attr(store, "name"),
            "description": self._get_attr(store, "description"),
            "category": self._get_attr(store, "category"),
            "image_url": self._get_attr(store, "image_url"),
            "banner_url": self._get_attr(store, "banner_url"),
            "owner_id": self._get_attr(store, "owner_id"),
            "products": serialized_products
        }

    async def _cache_set(self, key: str, data: Any, ttl: int):
        try:
            await redis_client.setex(key, ttl, json.dumps(data))
        except Exception:
            pass

    async def _invalidate_store_cache(self, store_id: int = None, owner_id: int = None):
        keys_to_delete = []
        if store_id:
            keys_to_delete.append(f"store:{store_id}")
            # Also invalidate the legacy product list cache
            keys_to_delete.append(f"store:products:{store_id}")
        
        try:
            if keys_to_delete:
                await redis_client.delete(*keys_to_delete)
        except Exception:
            pass

    # --- SERVICE METHODS ---

    async def create_store(self, store_data: StoreCreate, current_user: models.User) -> models.Store:
        stmt = select(models.Store).where(models.Store.owner_id == current_user.id)
        result = await self.db.execute(stmt)
        existing_store = result.scalars().first()
        
        if existing_store:
             raise PermissionDeniedError("create", "more than one store. You are limited to 1 store.")
        
        store_dict = store_data.model_dump()
        if current_user.role == models.UserRole.store_owner:
            store_dict["owner_id"] = current_user.id
        
        db_store = models.Store(**store_dict)
        self.db.add(db_store)
        await self.db.commit()
        await self.db.refresh(db_store)
        
        await self._invalidate_store_cache(store_id=db_store.id)
        return await self.get_store(db_store.id)

    async def get_store(self, store_id: int) -> Union[models.Store, dict]:
        try:
            cached = await redis_client.get(f"store:{store_id}")
            if cached:
                return json.loads(cached)
        except Exception:
            pass
        
        stmt = select(models.Store).options(selectinload(models.Store.products)).where(models.Store.id == store_id)
        result = await self.db.execute(stmt)
        store = result.unique().scalar_one_or_none()
        
        if not store:
            raise NotFoundError("Store", store_id)
        
        await self._cache_set(f"store:{store.id}", self._serialize_store(store), self.STORE_CACHE_TTL)
        return store

    async def get_all_stores(self, q: Optional[str] = None, limit: int = 20, offset: int = 0):
        stmt = select(models.Store)
        if q:
            search_text = f"%{q}%"
            stmt = stmt.where(
                or_(
                    models.Store.name.ilike(search_text),
                    models.Store.description.ilike(search_text)
                )
            )
        stmt = stmt.limit(limit).offset(offset)
        result = await self.db.execute(stmt)
        return result.unique().scalars().all()

    async def get_stores_by_owner(self, owner_id: int, limit: int = 20, offset: int = 0):
        stmt = select(models.Store).where(models.Store.owner_id == owner_id)
        stmt = stmt.limit(limit).offset(offset)
        result = await self.db.execute(stmt)
        return result.unique().scalars().all()

    async def update_store(self, store_id: int, update_data: StoreUpdate, current_user: models.User, bg_tasks: BackgroundTasks):
        stmt = select(models.Store).where(models.Store.id == store_id)
        result = await self.db.execute(stmt)
        store = result.unique().scalar_one_or_none()
        
        if not store:
            raise NotFoundError("Store", store_id)

        if current_user.role == models.UserRole.store_owner:
            if store.owner_id != current_user.id:
                raise PermissionDeniedError("update", "store")
        
        if update_data.image_url and update_data.image_url != store.image_url:
            if store.image_url:
                bg_tasks.add_task(delete_cloudinary_image, store.image_url)

        if update_data.banner_url and update_data.banner_url != store.banner_url:
            if store.banner_url:
                bg_tasks.add_task(delete_cloudinary_image, store.banner_url)

        for key, value in update_data.model_dump(exclude_unset=True).items():
            setattr(store, key, value)
        
        await self.db.commit()
        await self.db.refresh(store)
        
        await self._invalidate_store_cache(store_id=store_id)
        return store

    async def delete_store(self, store_id: int, current_user: models.User, bg_tasks: BackgroundTasks):
        stmt = select(models.Store).where(models.Store.id == store_id)
        result = await self.db.execute(stmt)
        store = result.unique().scalar_one_or_none()
        
        if not store:
            raise NotFoundError("Store", store_id)
            
        if current_user.role == models.UserRole.store_owner:
            if store.owner_id != current_user.id:
                raise PermissionDeniedError("delete", "store")
        
        if store.image_url:
            bg_tasks.add_task(delete_cloudinary_image, store.image_url)
        if store.banner_url:
            bg_tasks.add_task(delete_cloudinary_image, store.banner_url)

        await self.db.delete(store)
        await self.db.commit()
        
        await self._invalidate_store_cache(store_id=store_id)

    # 👇 RESTORED: Legacy method for Website
    async def get_store_products(self, store_id: int) -> List[dict]:
        """Get products for a store (Legacy Optimized)."""
        cache_key = f"store:products:{store_id}"
        try:
            cached = await redis_client.get(cache_key)
            if cached:
                return json.loads(cached)
        except Exception:
            pass
        
        result = await self.db.execute(select(models.Product).where(models.Product.store_id == store_id))
        products = result.unique().scalars().all()
        
        products_data = [
            {
                "id": p.id,
                "name": p.name,
                "description": p.description,
                "price": float(p.price),
                "stock": p.stock,
                "store_id": p.store_id,
                "category": p.category,
                "image_url": p.image_url,
            }
            for p in products
        ]
        
        await self._cache_set(cache_key, products_data, self.STORE_CACHE_TTL)
        
        return products