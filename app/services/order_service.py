"""
Order service layer with Optimized Redis Caching (Cache-Aside Pattern).
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from typing import List, Optional, Any, Union
from app.db import models
from app.schemas.order import OrderCreate
from app.utils.exceptions import NotFoundError, BadRequestError, InsufficientStockError
from datetime import datetime, timezone, timedelta
from itertools import groupby
from app.core.redis import redis_client
import json

class AsyncOrderService:
    """Async service class for order-related business logic using AsyncSession."""
    
    # Cache TTLs (in seconds)
    ORDER_CACHE_TTL = 300  # 5 minutes
    AVAILABLE_ORDERS_CACHE_TTL = 30  # 30 seconds (High velocity data)
    USER_ORDERS_CACHE_TTL = 180  # 3 minutes

    def __init__(self, db: AsyncSession):
        self.db = db

    # --- CACHE HELPERS ---

    def _serialize_order(self, order: models.Order) -> dict:
        """
        Converts ORM object to a JSON-serializable dict.
        Crucial because we cannot cache SQLAlchemy objects directly.
        """
        return {
            "id": order.id,
            "user_id": order.user_id,
            "store_id": order.store_id,
            "driver_id": order.driver_id,
            "status": order.status.value,
            "total_price": float(order.total_price),
            "delivery_address": order.delivery_address,
            "assigned_at": order.assigned_at.isoformat() if order.assigned_at else None,
            "created_at": order.created_at.isoformat() if order.created_at else None,
            # Flatten items for caching
            "items": [
                {
                    "id": item.id,
                    "product_id": item.product_id,
                    "product_name": item.product.name if item.product else f"Item {item.product_id}",
                    "quantity": item.quantity,
                    "price_at_purchase": float(item.price_at_purchase)
                }
                for item in order.items
            ] if order.items else []
        }

    async def _cache_set(self, key: str, data: Any, ttl: int):
        """Safe wrapper for Redis SET to prevent crashing if Redis is down."""
        try:
            await redis_client.setex(key, ttl, json.dumps(data))
        except Exception:
            pass 

    async def _invalidate_order_flow(self, order_id: int, user_id: int = None):
        """
        Smart Invalidation:
        When an order changes, we must clear:
        1. The order itself
        2. The 'Available Orders' list (it might have been removed/added)
        3. The specific User's order list
        """
        keys = [f"order:{order_id}", "orders:available"]
        if user_id:
            keys.append(f"orders:user:{user_id}")
        try:
            await redis_client.delete(*keys)
        except Exception:
            pass

    # --- SERVICE METHODS ---

    async def create_order(self, order_data: OrderCreate, current_user: models.User) -> List[models.Order]:
        """Create orders from a cart."""
        if not order_data.items:
            raise BadRequestError("Order must contain at least one item")

        from app.services.product_service import AsyncProductService
        product_svc = AsyncProductService(self.db)

        # 1. Validate & Prepare
        validated_items = []
        for item in order_data.items:
            product = await product_svc.get_product(item.product_id)
            if not await product_svc.check_stock_availability(item.product_id, item.quantity):
                raise InsufficientStockError(product.name, item.quantity, product.stock)
            
            validated_items.append({"schema": item, "product": product, "store_id": product.store_id})

        # 2. Group by Store
        validated_items.sort(key=lambda x: x["store_id"])
        created_orders = []

        try:
            for store_id, group in groupby(validated_items, key=lambda x: x["store_id"]):
                store_items = list(group)
                total_price = 0.0
                db_order_items = []
                
                for item_data in store_items:
                    product = item_data["product"]
                    qty = item_data["schema"].quantity
                    
                    order_item = models.OrderItem(
                        product_id=product.id,
                        quantity=qty,
                        price_at_purchase=product.price
                    )
                    db_order_items.append(order_item)
                    total_price += product.price * qty
                    await product_svc.reserve_stock(product.id, qty)

                db_order = models.Order(
                    user_id=current_user.id,
                    store_id=store_id,
                    status=models.OrderStatus.pending,
                    total_price=total_price,
                    delivery_address=order_data.delivery_address or current_user.address or "Default Address",
                    items=db_order_items
                )
                self.db.add(db_order)
                created_orders.append(db_order)

            await self.db.commit()
            
            # 3. Refresh & Cache
            await self._invalidate_order_flow(0, current_user.id) # Clear lists
            
            final_orders = []
            for order in created_orders:
                # Eager load items to prevent lazy load errors during serialization
                query = select(models.Order).options(
                    selectinload(models.Order.items).selectinload(models.OrderItem.product)
                ).where(models.Order.id == order.id)
                
                res = await self.db.execute(query)
                fresh_order = res.scalar_one()
                final_orders.append(fresh_order)
                
                # Cache the individual order immediately
                await self._cache_set(
                    f"order:{fresh_order.id}", 
                    self._serialize_order(fresh_order), 
                    self.ORDER_CACHE_TTL
                )

            return final_orders

        except Exception as e:
            await self.db.rollback()
            raise e

    async def get_order(self, order_id: int, current_user: models.User = None) -> Union[models.Order, dict]:
        """
        Get single order.
        Strategy: Cache contains raw Dict. We return Dict if cached, ORM Object if DB hit.
        FastAPI/Pydantic handles both seamlessly.
        """
        
        
        # 1. Try Cache
        try:
            cached = await redis_client.get(f"order:{order_id}")
            if cached:
                order_dict = json.loads(cached)
                # Apply Security Checks on Cached Data
                if current_user:
                    is_owner = order_dict["user_id"] == current_user.id
                    is_driver = current_user.role == models.UserRole.driver
                    if not is_owner and not is_driver and current_user.role != models.UserRole.admin:
                         raise NotFoundError("Order", order_id)
                return order_dict # Return Dict (Pydantic will validate)
        except NotFoundError:
            raise
        except Exception:
            pass # Redis fail -> Fallback to DB

        # 2. DB Fallback
        stmt = (
            select(models.Order)
            .options(selectinload(models.Order.items).selectinload(models.OrderItem.product))
            .where(models.Order.id == order_id)
        )
        result = await self.db.execute(stmt)
        order = result.unique().scalar_one_or_none()
        
        if not order:
            raise NotFoundError("Order", order_id)

        # 3. Security Checks (DB Data)
        if current_user:
            if current_user.role == models.UserRole.customer:
                if order.user_id != current_user.id:
                    raise NotFoundError("Order", order_id)
            
            elif current_user.role == models.UserRole.driver:
                # FIX: Added missing security check for drivers
                is_assigned = order.driver_id == current_user.id
                is_available = order.status in [models.OrderStatus.pending, models.OrderStatus.confirmed]
                
                if not is_assigned and not is_available:
                    raise NotFoundError("Order", order_id)

        # 4. Write to Cache
        await self._cache_set(
            f"order:{order.id}", 
            self._serialize_order(order), 
            self.ORDER_CACHE_TTL
        )
        
        return order
    
    async def get_available_orders(self):
        """Fetch orders ready for driver pickup."""
        # 1. Try Cache (Return Full List immediately)
        try:
            cached = await redis_client.get("orders:available")
            if cached:
                return json.loads(cached) # Return list of dicts directly
        except Exception:
            pass
        
        # 2. DB Fallback
        stmt = (
            select(models.Order)
            .options(selectinload(models.Order.items).selectinload(models.OrderItem.product))
            .where(models.Order.status == models.OrderStatus.pending)
            .limit(50) # Safety limit
        )
        result = await self.db.execute(stmt)
        orders = result.unique().scalars().all()
        
        # 3. Serialize & Cache
        serialized_list = [self._serialize_order(o) for o in orders]
        await self._cache_set("orders:available", serialized_list, self.AVAILABLE_ORDERS_CACHE_TTL)
        
        return orders

    async def get_user_orders(self, current_user: models.User):
        cache_key = f"orders:user:{current_user.id}"
        
        # 1. Try Cache
        try:
            cached = await redis_client.get(cache_key)
            if cached:
                return json.loads(cached)
        except Exception:
            pass
        
        # 2. DB Fallback
        stmt = (
            select(models.Order)
            .options(selectinload(models.Order.items).selectinload(models.OrderItem.product))
            .where(models.Order.user_id == current_user.id)
            .order_by(models.Order.created_at.desc())
        )
        result = await self.db.execute(stmt)
        orders = result.unique().scalars().all()
        
        # 3. Serialize & Cache
        serialized_list = [self._serialize_order(o) for o in orders]
        await self._cache_set(cache_key, serialized_list, self.USER_ORDERS_CACHE_TTL)
        
        return orders

    async def get_all_orders(self):
        # Admin tool - No cache needed generally
        stmt = select(models.Order).options(selectinload(models.Order.items))
        result = await self.db.execute(stmt)
        return result.unique().scalars().all()

    async def update_order_status(self, order_id: int, new_status: str, current_user: models.User):
        # Fetch fresh from DB for locking/consistency
        stmt = select(models.Order).options(selectinload(models.Order.items)).where(models.Order.id == order_id)
        result = await self.db.execute(stmt)
        order = result.unique().scalar_one_or_none()
        
        if not order:
            raise NotFoundError("Order", order_id)

        try:
            new_status_enum = models.OrderStatus(new_status)
        except ValueError:
            raise BadRequestError(f"Invalid status: {new_status}")

        # Basic State Machine Validation
        if new_status_enum == models.OrderStatus.cancelled:
             from app.services.product_service import AsyncProductService
             product_svc = AsyncProductService(self.db)
             for item in order.items:
                 await product_svc.release_stock(item.product_id, item.quantity)
             order.driver_id = None
             order.assigned_at = None

        order.status = new_status_enum
        await self.db.commit()
        await self.db.refresh(order)
        
        # Invalidate Cache
        await self._invalidate_order_flow(order_id, order.user_id)
        
        return order

    async def accept_order_atomic(self, order_id: int, driver_id: int) -> models.Order:
        """Atomic assignment."""
        if self.db.in_transaction():
            trans_ctx = self.db.begin_nested()
        else:
            trans_ctx = self.db.begin()

        async with trans_ctx:
            stmt = (
                select(models.Order)
                .options(selectinload(models.Order.items)) # Fix: Load items explicitly
                .with_for_update()
                .where(models.Order.id == order_id)
            )
            result = await self.db.execute(stmt)
            order = result.unique().scalar_one_or_none()
            
            if not order: raise NotFoundError("Order", order_id)
            
            # Simple State Check
            if order.status not in [models.OrderStatus.pending, models.OrderStatus.confirmed]:
                 raise BadRequestError(f"Cannot accept order in status {order.status}")
            
            if order.driver_id and order.driver_id != driver_id:
                 raise BadRequestError("Order already assigned to another driver")

            order.driver_id = driver_id
            order.status = models.OrderStatus.assigned
            order.assigned_at = datetime.now(timezone.utc)
            
            await self.db.commit()
            
            # Refresh to ensure items are loaded before returning
            await self.db.refresh(order, attribute_names=["items"])
            
            # Invalidate Cache
            await self._invalidate_order_flow(order_id, order.user_id)
            
            return order