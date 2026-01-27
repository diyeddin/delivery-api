"""
Product service layer for business logic separation with Redis caching.
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from typing import List, Optional
from app.db import models
from app.schemas.product import ProductCreate, ProductUpdate
from app.utils.exceptions import NotFoundError, PermissionDeniedError, InsufficientStockError
from app.core.redis import redis_client
import json

class AsyncProductService:
    """Async product service using AsyncSession with Redis caching."""
    
    # Cache TTLs (in seconds)
    PRODUCT_CACHE_TTL = 600  # 10 minutes
    ALL_PRODUCTS_CACHE_TTL = 300  # 5 minutes
    USER_PRODUCTS_CACHE_TTL = 300  # 5 minutes

    def __init__(self, db: AsyncSession):
        self.db = db

    # --- CACHE HELPER METHODS ---
    
    async def _invalidate_product_cache(self, product_id: int, store_id: int = None):
        """Invalidate all cache entries related to a product."""
        keys_to_delete = [
            f"product:{product_id}",
            "products:all",
        ]
        if store_id:
            keys_to_delete.append(f"products:store:{store_id}")
        
        try:
            # Also invalidate user products cache for the store owner
            # We can't know the owner_id without a query, so we use a pattern delete
            # Note: This requires redis_client to support pattern deletion
            await redis_client.delete(*keys_to_delete)
        except Exception:
            pass

    async def _cache_product(self, product: models.Product):
        """Cache a single product."""
        try:
            product_data = {
                "id": product.id,
                "name": product.name,
                "description": product.description,
                "price": float(product.price),
                "stock": product.stock,
                "store_id": product.store_id,
                "category": product.category,
                "image_url": product.image_url,
            }
            await redis_client.setex(
                f"product:{product.id}",
                self.PRODUCT_CACHE_TTL,
                json.dumps(product_data)
            )
        except Exception:
            pass

    async def _get_cached_product(self, product_id: int) -> Optional[dict]:
        """Get cached product data."""
        try:
            cached = await redis_client.get(f"product:{product_id}")
            if cached:
                return json.loads(cached)
        except Exception:
            pass
        return None

    # --- SERVICE METHODS ---

    async def create_product(self, product_data: ProductCreate, current_user: models.User) -> models.Product:
        # 1. Verify Store Exists
        result = await self.db.execute(select(models.Store).where(models.Store.id == product_data.store_id))
        store = result.unique().scalar_one_or_none()
        if not store:
            raise NotFoundError("Store", product_data.store_id)

        # 2. Verify Ownership
        if current_user.role == models.UserRole.store_owner:
            if store.owner_id != current_user.id:
                raise PermissionDeniedError("create products for", "this store")

        # 3. Create Product
        db_product = models.Product(**product_data.model_dump())
        self.db.add(db_product)
        await self.db.commit()
        await self.db.refresh(db_product)
        
        # Invalidate relevant caches
        await self._invalidate_product_cache(db_product.id, db_product.store_id)
        # Cache the new product
        await self._cache_product(db_product)
        
        return db_product

    async def get_product(self, product_id: int) -> models.Product:
        # Try cache first
        cached_data = await self._get_cached_product(product_id)
        if cached_data:
            # Reconstruct Product model from cached data
            # Note: This creates a detached object, which is fine for read operations
            product = models.Product(**cached_data)
            return product
        
        # Cache miss - fetch from database
        result = await self.db.execute(select(models.Product).where(models.Product.id == product_id))
        product = result.unique().scalar_one_or_none()
        if not product:
            raise NotFoundError("Product", product_id)
        
        # Cache the product
        await self._cache_product(product)
        
        return product

    async def get_all_products(self) -> List[models.Product]:
        # Try cache first
        try:
            cached = await redis_client.get("products:all")
            if cached:
                product_ids = json.loads(cached)
                products = []
                for product_id in product_ids:
                    try:
                        product = await self.get_product(product_id)
                        products.append(product)
                    except NotFoundError:
                        # Product was deleted, invalidate cache
                        await redis_client.delete("products:all")
                        break
                else:
                    return products
        except Exception:
            pass
        
        # Cache miss - fetch from database
        result = await self.db.execute(select(models.Product))
        products = result.unique().scalars().all()
        
        # Cache the product IDs
        try:
            product_ids = [product.id for product in products]
            await redis_client.setex(
                "products:all",
                self.ALL_PRODUCTS_CACHE_TTL,
                json.dumps(product_ids)
            )
            # Cache individual products
            for product in products:
                await self._cache_product(product)
        except Exception:
            pass
        
        return products

    async def get_user_products(self, current_user: models.User) -> List[models.Product]:
        """Get all products belonging to stores owned by the user."""
        # Try cache first
        cache_key = f"products:user:{current_user.id}"
        try:
            cached = await redis_client.get(cache_key)
            if cached:
                product_ids = json.loads(cached)
                products = []
                for product_id in product_ids:
                    try:
                        product = await self.get_product(product_id)
                        products.append(product)
                    except NotFoundError:
                        # Product was deleted, invalidate cache
                        await redis_client.delete(cache_key)
                        break
                else:
                    return products
        except Exception:
            pass
        
        # Cache miss - fetch from database
        stmt = (
            select(models.Product)
            .join(models.Store)
            .where(models.Store.owner_id == current_user.id)
        )
        result = await self.db.execute(stmt)
        products = result.unique().scalars().all()
        
        # Cache the product IDs
        try:
            product_ids = [product.id for product in products]
            await redis_client.setex(
                cache_key,
                self.USER_PRODUCTS_CACHE_TTL,
                json.dumps(product_ids)
            )
            # Cache individual products
            for product in products:
                await self._cache_product(product)
        except Exception:
            pass
        
        return products

    async def update_product(self, product_id: int, update_data: ProductUpdate, current_user: models.User) -> models.Product:
        product = await self.get_product(product_id)
        
        # Security: Fetch store explicitly to check ownership (avoids Greenlet error on lazy load)
        if current_user.role == models.UserRole.store_owner:
            store_result = await self.db.execute(select(models.Store).where(models.Store.id == product.store_id))
            store = store_result.scalar_one()
            if store.owner_id != current_user.id:
                raise PermissionDeniedError("update", "this product")

        update_dict = update_data.model_dump(exclude_unset=True)
        old_store_id = product.store_id
        
        # If moving product to a new store, verify ownership of NEW store
        if "store_id" in update_dict:
            new_store_result = await self.db.execute(select(models.Store).where(models.Store.id == update_dict["store_id"]))
            new_store = new_store_result.unique().scalar_one_or_none()
            if not new_store:
                raise NotFoundError("Store", update_dict["store_id"])
            
            if current_user.role == models.UserRole.store_owner:
                if new_store.owner_id != current_user.id:
                    raise PermissionDeniedError("move products to", "this store")

        for key, value in update_dict.items():
            setattr(product, key, value)

        await self.db.commit()
        await self.db.refresh(product)
        
        # Invalidate cache for both old and new store if store changed
        await self._invalidate_product_cache(product_id, old_store_id)
        if "store_id" in update_dict and update_dict["store_id"] != old_store_id:
            await self._invalidate_product_cache(product_id, update_dict["store_id"])
        
        # Cache the updated product
        await self._cache_product(product)
        
        return product

    async def delete_product(self, product_id: int, current_user: models.User):
        product = await self.get_product(product_id)
        store_id = product.store_id
        
        if current_user.role == models.UserRole.store_owner:
            # Fetch store explicitly
            store_result = await self.db.execute(select(models.Store).where(models.Store.id == product.store_id))
            store = store_result.scalar_one()
            if store.owner_id != current_user.id:
                raise PermissionDeniedError("delete", "this product")
                
        await self.db.delete(product)
        await self.db.commit()
        
        # Invalidate cache
        await self._invalidate_product_cache(product_id, store_id)

    # --- STOCK MANAGEMENT ---

    async def check_stock_availability(self, product_id: int, quantity: int) -> bool:
        product = await self.get_product(product_id)
        return product.stock >= quantity

    async def reserve_stock(self, product_id: int, quantity: int) -> models.Product:
        """Decrease stock. Raises InsufficientStockError if not enough."""
        # Note: For stock operations, we bypass cache to ensure consistency
        # We fetch directly from DB to avoid race conditions
        result = await self.db.execute(select(models.Product).where(models.Product.id == product_id))
        product = result.unique().scalar_one_or_none()
        if not product:
            raise NotFoundError("Product", product_id)
        
        if product.stock < quantity:
            raise InsufficientStockError(product.name, quantity, product.stock)
        
        product.stock -= quantity
        await self.db.commit()
        await self.db.refresh(product)
        
        # Invalidate and update cache
        await self._invalidate_product_cache(product_id, product.store_id)
        await self._cache_product(product)
        
        return product
    
    async def release_stock(self, product_id: int, quantity: int):
        """Re-add stock (e.g. when an order is cancelled). Uses atomic update."""
        stmt = (
            update(models.Product)
            .where(models.Product.id == product_id)
            .values(stock=models.Product.stock + quantity)
        )
        await self.db.execute(stmt)
        await self.db.commit()
        
        # Invalidate cache - we need to fetch the product to get store_id
        result = await self.db.execute(select(models.Product).where(models.Product.id == product_id))
        product = result.unique().scalar_one_or_none()
        if product:
            await self._invalidate_product_cache(product_id, product.store_id)
            await self._cache_product(product)