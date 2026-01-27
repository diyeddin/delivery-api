"""
Store service layer for business logic separation with Redis caching.
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from typing import List, Optional
from app.db import models
from app.schemas.store import StoreCreate, StoreUpdate
from app.utils.exceptions import NotFoundError, PermissionDeniedError
from app.core.redis import redis_client
import json

class AsyncStoreService:
    """Async store service using AsyncSession with Redis caching."""
    
    # Cache TTLs (in seconds)
    STORE_CACHE_TTL = 600  # 10 minutes
    ALL_STORES_CACHE_TTL = 300  # 5 minutes
    OWNER_STORES_CACHE_TTL = 300  # 5 minutes
    
    def __init__(self, db: AsyncSession):
        self.db = db

    # --- CACHE HELPER METHODS ---
    
    async def _invalidate_store_cache(self, store_id: int = None, owner_id: int = None):
        """Invalidate all cache entries related to a store."""
        keys_to_delete = ["stores:all"]
        
        if store_id:
            keys_to_delete.append(f"store:{store_id}")
            keys_to_delete.append(f"store:products:{store_id}")
        
        if owner_id:
            keys_to_delete.append(f"stores:owner:{owner_id}")
        
        try:
            await redis_client.delete(*keys_to_delete)
        except Exception:
            pass

    async def _cache_store(self, store: models.Store):
        """Cache a single store with its products."""
        try:
            store_data = {
                "id": store.id,
                "name": store.name,
                "description": store.description,
                "address": store.address,
                "owner_id": store.owner_id,
                "products": [
                    {
                        "id": product.id,
                        "name": product.name,
                        "description": product.description,
                        "price": float(product.price),
                        "stock": product.stock,
                        "store_id": product.store_id,
                        "category": product.category,
                        "image_url": product.image_url,
                    }
                    for product in store.products
                ] if store.products else []
            }
            await redis_client.setex(
                f"store:{store.id}",
                self.STORE_CACHE_TTL,
                json.dumps(store_data)
            )
        except Exception:
            pass

    async def _get_cached_store(self, store_id: int) -> Optional[dict]:
        """Get cached store data."""
        try:
            cached = await redis_client.get(f"store:{store_id}")
            if cached:
                return json.loads(cached)
        except Exception:
            pass
        return None

    async def _reconstruct_store_from_cache(self, cached_data: dict) -> models.Store:
        """Reconstruct Store model from cached data."""
        # Create detached Store object
        products_data = cached_data.pop("products", [])
        store = models.Store(**{k: v for k, v in cached_data.items() if k != "products"})
        
        # Reconstruct products
        store.products = [models.Product(**product_data) for product_data in products_data]
        
        return store

    # --- SERVICE METHODS ---

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
        store = await self.get_store(db_store.id)
        
        # Invalidate caches
        await self._invalidate_store_cache(store_id=store.id, owner_id=current_user.id)
        
        return store

    async def get_store(self, store_id: int) -> models.Store:
        # Try cache first
        cached_data = await self._get_cached_store(store_id)
        if cached_data:
            return self._reconstruct_store_from_cache(cached_data)
        
        # Cache miss - fetch from database
        # options(selectinload(...)) prevents MissingGreenlet error
        stmt = select(models.Store).options(selectinload(models.Store.products)).where(models.Store.id == store_id)
        result = await self.db.execute(stmt)
        store = result.unique().scalar_one_or_none()
        if not store:
            raise NotFoundError("Store", store_id)
        
        # Cache the store
        await self._cache_store(store)
        
        return store

    async def get_all_stores(self):
        # Try cache first
        try:
            cached = await redis_client.get("stores:all")
            if cached:
                store_ids = json.loads(cached)
                stores = []
                for store_id in store_ids:
                    try:
                        store = await self.get_store(store_id)
                        stores.append(store)
                    except NotFoundError:
                        # Store was deleted, invalidate cache
                        await redis_client.delete("stores:all")
                        break
                else:
                    return stores
        except Exception:
            pass
        
        # Cache miss - fetch from database
        stmt = select(models.Store).options(selectinload(models.Store.products))
        result = await self.db.execute(stmt)
        stores = result.unique().scalars().all()
        
        # Cache the store IDs
        try:
            store_ids = [store.id for store in stores]
            await redis_client.setex(
                "stores:all",
                self.ALL_STORES_CACHE_TTL,
                json.dumps(store_ids)
            )
            # Cache individual stores
            for store in stores:
                await self._cache_store(store)
        except Exception:
            pass
        
        return stores

    async def get_stores_by_owner(self, owner_id: int):
        # Try cache first
        cache_key = f"stores:owner:{owner_id}"
        try:
            cached = await redis_client.get(cache_key)
            if cached:
                store_ids = json.loads(cached)
                stores = []
                for store_id in store_ids:
                    try:
                        store = await self.get_store(store_id)
                        stores.append(store)
                    except NotFoundError:
                        # Store was deleted, invalidate cache
                        await redis_client.delete(cache_key)
                        break
                else:
                    return stores
        except Exception:
            pass
        
        # Cache miss - fetch from database
        stmt = select(models.Store).options(selectinload(models.Store.products)).where(models.Store.owner_id == owner_id)
        result = await self.db.execute(stmt)
        stores = result.unique().scalars().all()
        
        # Cache the store IDs
        try:
            store_ids = [store.id for store in stores]
            await redis_client.setex(
                cache_key,
                self.OWNER_STORES_CACHE_TTL,
                json.dumps(store_ids)
            )
            # Cache individual stores
            for store in stores:
                await self._cache_store(store)
        except Exception:
            pass
        
        return stores

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
        
        # Invalidate cache
        await self._invalidate_store_cache(store_id=store_id, owner_id=store.owner_id)
        
        # Re-fetch to ensure products are loaded and cache it
        updated_store = await self.get_store(store_id)
        
        return updated_store

    async def delete_store(self, store_id: int, current_user: models.User):
        store = await self.get_store(store_id)
        owner_id = store.owner_id
        
        if current_user.role == models.UserRole.store_owner:
            if store.owner_id != current_user.id:
                raise PermissionDeniedError("delete", "store")
        
        await self.db.delete(store)
        await self.db.commit()
        
        # Invalidate cache
        await self._invalidate_store_cache(store_id=store_id, owner_id=owner_id)

    async def get_store_products(self, store_id: int) -> List[models.Product]:
        # Try cache first
        cache_key = f"store:products:{store_id}"
        try:
            cached = await redis_client.get(cache_key)
            if cached:
                products_data = json.loads(cached)
                return [models.Product(**product_data) for product_data in products_data]
        except Exception:
            pass
        
        # Cache miss - fetch from database
        result = await self.db.execute(select(models.Product).where(models.Product.store_id == store_id))
        products = result.unique().scalars().all()
        
        # Cache the products
        try:
            products_data = [
                {
                    "id": product.id,
                    "name": product.name,
                    "description": product.description,
                    "price": float(product.price),
                    "stock": product.stock,
                    "store_id": product.store_id,
                    "category": product.category,
                    "image_url": product.image_url,
                }
                for product in products
            ]
            await redis_client.setex(
                cache_key,
                self.STORE_CACHE_TTL,
                json.dumps(products_data)
            )
        except Exception:
            pass
        
        return products