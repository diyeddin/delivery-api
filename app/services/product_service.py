"""
Product service layer for business logic separation with Redis caching.
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from typing import List, Optional, Union, Any
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

    # --- HELPER: Handle Dict vs Object ---
    def _get_attr(self, obj: Union[dict, Any], key: str):
        """Safely get attribute from either Dict (Cache) or Object (DB)."""
        if isinstance(obj, dict):
            return obj.get(key)
        return getattr(obj, key)

    # --- CACHE HELPERS ---

    def _serialize_product(self, product: models.Product) -> dict:
        """Safe serialization of Product ORM object."""
        return {
            "id": self._get_attr(product, "id"),
            "name": self._get_attr(product, "name"),
            "description": self._get_attr(product, "description"),
            "price": float(self._get_attr(product, "price")),
            "stock": self._get_attr(product, "stock"),
            "store_id": self._get_attr(product, "store_id"),
            "category": self._get_attr(product, "category") ,
            "image_url": self._get_attr(product, "image_url"),
        }

    async def _cache_set(self, key: str, data: Any, ttl: int):
        try:
            await redis_client.setex(key, ttl, json.dumps(data))
        except Exception:
            pass
    
    async def _invalidate_product_cache(self, product_id: int, store_id: int = None, owner_id: int = None):
        """Invalidate single product and lists."""
        keys_to_delete = [
            f"product:{product_id}",
            "products:all",
        ]
        if store_id:
            keys_to_delete.append(f"products:store:{store_id}")
        
        # If we know the owner, invalidate their list too. 
        # (This is tricky without an Owner ID, usually handled by wider expiry)
        if owner_id:
            keys_to_delete.append(f"products:user:{owner_id}")
        
        try:
            await redis_client.delete(*keys_to_delete)
        except Exception:
            pass

    # --- SERVICE METHODS ---

    async def create_product(self, product_data: ProductCreate, current_user: models.User) -> models.Product:
        # 1. Verify Store Exists & Ownership (DB Direct)
        result = await self.db.execute(select(models.Store).where(models.Store.id == product_data.store_id))
        store = result.unique().scalar_one_or_none()
        if not store:
            raise NotFoundError("Store", product_data.store_id)

        if current_user.role == models.UserRole.store_owner:
            if store.owner_id != current_user.id:
                raise PermissionDeniedError("create products for", "this store")

        # 2. Create Product
        db_product = models.Product(**product_data.model_dump())
        self.db.add(db_product)
        await self.db.commit()
        await self.db.refresh(db_product)
        
        # 3. Cache
        await self._invalidate_product_cache(db_product.id, db_product.store_id, store.owner_id)
        await self._cache_set(f"product:{db_product.id}", self._serialize_product(db_product), self.PRODUCT_CACHE_TTL)
        
        return db_product

    async def get_product(self, product_id: int) -> Union[models.Product, dict]:
        """Get product by ID. Returns Dict (Cache) or Object (DB)."""
        # 1. Try Cache
        try:
            cached = await redis_client.get(f"product:{product_id}")
            if cached:
                return json.loads(cached)
        except Exception:
            pass
        
        # 2. DB Fallback
        result = await self.db.execute(select(models.Product).where(models.Product.id == product_id))
        product = result.unique().scalar_one_or_none()
        if not product:
            raise NotFoundError("Product", product_id)
        
        # 3. Cache
        await self._cache_set(f"product:{product.id}", self._serialize_product(product), self.PRODUCT_CACHE_TTL)
        
        return product

    async def get_all_products(self):
        """Get all products."""
        # 1. Try Cache (Full List)
        try:
            cached = await redis_client.get("products:all")
            if cached:
                return json.loads(cached)
        except Exception:
            pass
        
        # 2. DB Fallback
        result = await self.db.execute(select(models.Product))
        products = result.unique().scalars().all()
        
        # 3. Serialize & Cache
        serialized_list = [self._serialize_product(p) for p in products]
        await self._cache_set("products:all", serialized_list, self.ALL_PRODUCTS_CACHE_TTL)
        
        return products

    async def get_user_products(self, current_user: models.User):
        """Get all products for a store owner."""
        cache_key = f"products:user:{current_user.id}"
        
        # 1. Try Cache
        try:
            cached = await redis_client.get(cache_key)
            if cached:
                return json.loads(cached)
        except Exception:
            pass
        
        # 2. DB Fallback
        stmt = (
            select(models.Product)
            .join(models.Store)
            .where(models.Store.owner_id == current_user.id)
        )
        result = await self.db.execute(stmt)
        products = result.unique().scalars().all()
        
        # 3. Serialize & Cache
        serialized_list = [self._serialize_product(p) for p in products]
        await self._cache_set(cache_key, serialized_list, self.USER_PRODUCTS_CACHE_TTL)
        
        return products

    async def update_product(self, product_id: int, update_data: ProductUpdate, current_user: models.User) -> models.Product:
        # 1. Fetch from DB directly (Locking/Safety)
        # We assume products table does NOT have owner_id, so we must join store to check permission
        stmt = (
            select(models.Product, models.Store.owner_id)
            .join(models.Store, models.Product.store_id == models.Store.id)
            .where(models.Product.id == product_id)
        )
        result = await self.db.execute(stmt)
        row = result.first()
        
        if not row:
            raise NotFoundError("Product", product_id)
            
        product, owner_id = row

        # 2. Permission Check
        if current_user.role == models.UserRole.store_owner:
            if owner_id != current_user.id:
                raise PermissionDeniedError("update", "this product")

        update_dict = update_data.model_dump(exclude_unset=True)
        old_store_id = product.store_id
        
        # 3. Handle Store Move logic (if changing store_id)
        if "store_id" in update_dict:
            new_store_res = await self.db.execute(select(models.Store).where(models.Store.id == update_dict["store_id"]))
            new_store = new_store_res.scalar_one_or_none()
            if not new_store:
                raise NotFoundError("Store", update_dict["store_id"])
            
            if current_user.role == models.UserRole.store_owner and new_store.owner_id != current_user.id:
                raise PermissionDeniedError("move products to", "this store")

        # 4. Apply Updates
        for key, value in update_dict.items():
            setattr(product, key, value)

        await self.db.commit()
        await self.db.refresh(product)
        
        # 5. Invalidate
        await self._invalidate_product_cache(product_id, old_store_id, owner_id)
        if "store_id" in update_dict:
            await self._invalidate_product_cache(product_id, update_dict["store_id"], owner_id)
        
        return product

    async def delete_product(self, product_id: int, current_user: models.User):
        # Join Store to check owner
        stmt = (
            select(models.Product, models.Store.owner_id)
            .join(models.Store, models.Product.store_id == models.Store.id)
            .where(models.Product.id == product_id)
        )
        result = await self.db.execute(stmt)
        row = result.first()
        
        if not row:
            raise NotFoundError("Product", product_id)
            
        product, owner_id = row
        
        if current_user.role == models.UserRole.store_owner:
            if owner_id != current_user.id:
                raise PermissionDeniedError("delete", "this product")
                
        store_id = product.store_id
        await self.db.delete(product)
        await self.db.commit()
        
        await self._invalidate_product_cache(product_id, store_id, owner_id)

    # --- ATOMIC STOCK MANAGEMENT ---

    async def check_stock_availability(self, product_id: int, quantity: int) -> bool:
        """Fast check (Read Only)."""
        # Can use cache here safely for a "soft" check
        product = await self.get_product(product_id)
        # Handle dict vs object safely
        stock = self._get_attr(product, "stock")
        return stock >= quantity

    async def reserve_stock(self, product_id: int, quantity: int) -> models.Product:
        """
        Atomically decrease stock. 
        PREVENTS RACE CONDITIONS (Overselling).
        """
        # Execute UPDATE statement directly
        # "UPDATE products SET stock = stock - qty WHERE id = id AND stock >= qty"
        stmt = (
            update(models.Product)
            .where(models.Product.id == product_id)
            .where(models.Product.stock >= quantity) # Critical: The Condition
            .values(stock=models.Product.stock - quantity)
            .execution_options(synchronize_session="fetch")
        )
        
        result = await self.db.execute(stmt)
        
        # Check if a row was actually updated
        if result.rowcount == 0:
            # Either product doesn't exist OR stock was insufficient
            # We need to distinguish which one for the error message
            p_check = await self.db.execute(select(models.Product.stock, models.Product.name).where(models.Product.id == product_id))
            row = p_check.first()
            if not row:
                raise NotFoundError("Product", product_id)
            current_stock, name = row
            raise InsufficientStockError(name, quantity, current_stock)

        await self.db.commit()
        
        # Return the fresh object
        product_res = await self.db.execute(select(models.Product).where(models.Product.id == product_id))
        product = product_res.scalar_one()
        
        # Invalidate Cache
        await self._invalidate_product_cache(product_id, product.store_id)
        await self._cache_set(f"product:{product.id}", self._serialize_product(product), self.PRODUCT_CACHE_TTL)
        
        return product
    
    async def release_stock(self, product_id: int, quantity: int):
        """Re-add stock (e.g. cancelled order)."""
        stmt = (
            update(models.Product)
            .where(models.Product.id == product_id)
            .values(stock=models.Product.stock + quantity)
            .execution_options(synchronize_session="fetch")
        )
        await self.db.execute(stmt)
        await self.db.commit()
        
        # Invalidate cache
        # Need to fetch product to find store_id for invalidation keys
        result = await self.db.execute(select(models.Product).where(models.Product.id == product_id))
        product = result.unique().scalar_one_or_none()
        if product:
            await self._invalidate_product_cache(product_id, product.store_id)
            await self._cache_set(f"product:{product.id}", self._serialize_product(product), self.PRODUCT_CACHE_TTL)