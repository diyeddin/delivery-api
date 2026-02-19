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
import uuid

class AsyncOrderService:
    """Async service class for order-related business logic using AsyncSession."""
    
    # Cache TTLs (in seconds)
    ORDER_CACHE_TTL = 300  # 5 minutes
    AVAILABLE_ORDERS_CACHE_TTL = 30  # 30 seconds (High velocity data)
    USER_ORDERS_CACHE_TTL = 180  # 3 minutes

    def __init__(self, db: AsyncSession):
        self.db = db

    # --- HELPER: Handle Dict vs Object ---
    def _get_attr(self, obj: Union[dict, Any], key: str):
        """Safely get attribute from either Dict (Cache) or Object (DB)."""
        if isinstance(obj, dict):
            return obj.get(key)
        return getattr(obj, key)

    # --- CACHE HELPERS ---

    def _serialize_order(self, order: models.Order) -> dict:
        return {
            "id": self._get_attr(order, "id"),
            "group_id": self._get_attr(order, "group_id"),
            "user_id": self._get_attr(order, "user_id"),
            "store_id": self._get_attr(order, "store_id"),
            "driver_id": self._get_attr(order, "driver_id"),
            "status": self._get_attr(order, "status").value,
            "total_price": float(self._get_attr(order, "total_price")),
            "delivery_address": self._get_attr(order, "delivery_address"),
            "delivery_latitude": self._get_attr(order, "delivery_latitude"),
            "delivery_longitude": self._get_attr(order, "delivery_longitude"),

            # Driver's current GPS (from relationship property)
            "driver_latitude": getattr(order, "driver_latitude", None), # can these be replaced with _get_attr? Yes, but these are properties so we access them directly
            "driver_longitude": getattr(order, "driver_longitude", None),

            # 👇 NEW: Serialize new fields
            "payment_method": self._get_attr(order, "payment_method").value if hasattr(self._get_attr(order, "payment_method"), "value") else self._get_attr(order, "payment_method"),
            "note": self._get_attr(order, "note"),
            "is_reviewed": getattr(order, "is_reviewed", False),
            
            "assigned_at": self._get_attr(order, "assigned_at").isoformat() if self._get_attr(order, "assigned_at") else None,
            "created_at": self._get_attr(order, "created_at").isoformat() if self._get_attr(order, "created_at") else None,
            
            # Embed Store Details
            "store": {
                "id": order.store.id,
                "name": order.store.name,
                "image_url": order.store.image_url,
                "latitude": getattr(order.store, "latitude", None),
                "longitude": getattr(order.store, "longitude", None),
                "phone_number": getattr(order.store, "phone_number", None),
                "address": getattr(order.store, "address", None),
            } if getattr(order, "store", None) else None,

            "items": [
                {
                    "id": self._get_attr(item, "id"),
                    "product_id": self._get_attr(item, "product_id"),
                    "quantity": self._get_attr(item, "quantity"),
                    "price_at_purchase": float(self._get_attr(item, "price_at_purchase")),
                    "product": {
                        "id": item.product.id,
                        "name": item.product.name,
                        "image_url": item.product.image_url
                    } if getattr(item, "product", None) else None
                }
                for item in order.items
            ] if order.items else []
        }

    async def _cache_set(self, key: str, data: Any, ttl: int):
        """Safe wrapper for Redis SET."""
        try:
            await redis_client.setex(key, ttl, json.dumps(data))
        except Exception:
            pass 

    async def _invalidate_order_flow(self, order_id: int, user_id: int = None):
        """Clear relevant cache keys when an order changes."""
        keys = [f"order:{order_id}", "orders:available", "drivers:available_orders"]
        if user_id:
            keys.append(f"orders:user:{user_id}")
        try:
            await redis_client.delete(*keys)
        except Exception:
            pass
    
    async def _refetch_full_order(self, order_id: int) -> models.Order:
        """Reload order with all relationships."""
        stmt = (
            select(models.Order)
            .options(
                selectinload(models.Order.items).selectinload(models.OrderItem.product),
                selectinload(models.Order.store),
                selectinload(models.Order.driver)
            )
            .where(models.Order.id == order_id)
        )
        result = await self.db.execute(stmt)
        return result.unique().scalar_one()

    # --- SERVICE METHODS ---

    async def create_order(self, order_data: OrderCreate, current_user: models.User) -> List[models.Order]:
        """Create orders from a cart."""
        if not order_data.items:
            raise BadRequestError("Order must contain at least one item")

        from app.services.product_service import AsyncProductService
        product_svc = AsyncProductService(self.db)

        # 1. Validate Items & Stock
        validated_items = []
        for item in order_data.items:
            product = await product_svc.get_product(item.product_id)
            if not await product_svc.check_stock_availability(item.product_id, item.quantity):
                p_name = self._get_attr(product, "name")
                p_stock = self._get_attr(product, "stock")
                raise InsufficientStockError(p_name, item.quantity, p_stock)
            
            p_store_id = self._get_attr(product, "store_id")
            validated_items.append({"schema": item, "product": product, "store_id": p_store_id})

        transaction_group_id = str(uuid.uuid4())
        validated_items.sort(key=lambda x: x["store_id"])
        created_orders = []

        try:
            # 2. Group by Store & Create Orders
            for store_id, group in groupby(validated_items, key=lambda x: x["store_id"]):
                store_items = list(group)
                total_price = 0.0
                db_order_items = []
                
                for item_data in store_items:
                    product = item_data["product"]
                    qty = item_data["schema"].quantity
                    p_id = self._get_attr(product, "id")
                    p_price = self._get_attr(product, "price")
                    
                    order_item = models.OrderItem(
                        product_id=p_id,
                        quantity=qty,
                        price_at_purchase=p_price
                    )
                    db_order_items.append(order_item)
                    total_price += p_price * qty
                    await product_svc.reserve_stock(p_id, qty)

                # 👇 NEW: Map payment_method and note from request to DB
                db_order = models.Order(
                    user_id=current_user.id,
                    group_id=transaction_group_id,
                    store_id=store_id,
                    status=models.OrderStatus.pending,
                    total_price=total_price,
                    delivery_address=order_data.delivery_address or current_user.address or "Default Address",
                    delivery_latitude=order_data.delivery_latitude,
                    delivery_longitude=order_data.delivery_longitude,
                    payment_method=order_data.payment_method,
                    note=order_data.note,
                    items=db_order_items
                )
                self.db.add(db_order)
                created_orders.append(db_order)

            await self.db.commit()
            
            # 3. Refresh & Cache
            await self._invalidate_order_flow(0, current_user.id)
            
            final_orders = []
            for order in created_orders:
                query = select(models.Order).options(
                    selectinload(models.Order.items).selectinload(models.OrderItem.product),
                    selectinload(models.Order.store)
                ).where(models.Order.id == order.id)
                
                res = await self.db.execute(query)
                fresh_order = res.scalar_one()
                final_orders.append(fresh_order)
                
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
        # 1. Try Cache
        try:
            cached = await redis_client.get(f"order:{order_id}")
            if cached:
                order_dict = json.loads(cached)
                # ... (Keep your existing security checks) ...
                if current_user:
                    is_owner = order_dict["user_id"] == current_user.id
                    is_driver = getattr(current_user, "role", None) == models.UserRole.driver
                    if not is_owner and not is_driver and getattr(current_user, "role", None) != models.UserRole.admin:
                         raise NotFoundError("Order", order_id)
                
                # Ensure is_reviewed exists in cached dict (fallback for old cache keys)
                if "is_reviewed" not in order_dict:
                    order_dict["is_reviewed"] = False 
                    
                return order_dict
        except NotFoundError:
            raise
        except Exception:
            pass

        # 2. DB Fallback
        stmt = (
            select(models.Order)
            .options(
                selectinload(models.Order.items).selectinload(models.OrderItem.product),
                selectinload(models.Order.store),
                selectinload(models.Order.driver)
            )
            .where(models.Order.id == order_id)
        )
        result = await self.db.execute(stmt)
        order = result.unique().scalar_one_or_none()
        
        if not order:
            raise NotFoundError("Order", order_id)

        # 3. Security Checks (Keep your existing logic)
        if current_user:
            if current_user.role == models.UserRole.customer:
                if order.user_id != current_user.id:
                    raise NotFoundError("Order", order_id)
            elif current_user.role == models.UserRole.driver:
                is_assigned = order.driver_id == current_user.id
                is_available = order.status in [models.OrderStatus.pending, models.OrderStatus.confirmed]
                if not is_assigned and not is_available:
                    raise NotFoundError("Order", order_id)

        # 4. 👇 NEW: Check if Reviewed
        # We check the Review table to see if an entry exists for this order ID
        review_exists = await self.db.scalar(
            select(models.Review.id).where(models.Review.order_id == order.id)
        )
        # Attach it to the object so Pydantic (and the serializer) can see it
        order.is_reviewed = bool(review_exists)

        # 5. Write to Cache
        await self._cache_set(f"order:{order.id}", self._serialize_order(order), self.ORDER_CACHE_TTL)
        
        return order
    
    async def get_available_orders(self):
        try:
            cached = await redis_client.get("orders:available")
            if cached:
                return json.loads(cached)
        except Exception:
            pass
        
        stmt = (
            select(models.Order)
            .options(
                selectinload(models.Order.items).selectinload(models.OrderItem.product),
                selectinload(models.Order.store)
            )
            .where(models.Order.status == models.OrderStatus.pending)
            .limit(50)
        )
        result = await self.db.execute(stmt)
        orders = result.unique().scalars().all()
        
        serialized_list = [self._serialize_order(o) for o in orders]
        await self._cache_set("orders:available", serialized_list, self.AVAILABLE_ORDERS_CACHE_TTL)
        return orders
    
    async def get_user_orders(self, current_user: models.User):
        cache_key = f"orders:user:{current_user.id}"
        try:
            cached = await redis_client.get(cache_key)
            if cached:
                return json.loads(cached)
        except Exception:
            pass
        
        stmt = (
            select(models.Order)
            .options(
                selectinload(models.Order.items).selectinload(models.OrderItem.product),
                selectinload(models.Order.store),
                selectinload(models.Order.driver)
            )
            .where(models.Order.user_id == current_user.id)
            .order_by(models.Order.created_at.desc())
        )
        result = await self.db.execute(stmt)
        orders = result.unique().scalars().all()
        
        serialized_list = [self._serialize_order(o) for o in orders]
        await self._cache_set(cache_key, serialized_list, self.USER_ORDERS_CACHE_TTL)
        return orders

    async def get_all_orders(self):
        stmt = (
            select(models.Order)
            .options(
                selectinload(models.Order.items).selectinload(models.OrderItem.product),
                selectinload(models.Order.store)
            )
        )
        result = await self.db.execute(stmt)
        return result.unique().scalars().all()
    
    async def update_order_status(self, order_id: int, new_status: str, current_user: models.User):
        stmt = select(models.Order).options(selectinload(models.Order.items)).where(models.Order.id == order_id)
        result = await self.db.execute(stmt)
        order = result.unique().scalar_one_or_none()
        
        if not order:
            raise NotFoundError("Order", order_id)

        try:
            new_status_enum = models.OrderStatus(new_status)
        except ValueError:
            raise BadRequestError(f"Invalid status: {new_status}")

        if new_status_enum == models.OrderStatus.canceled:
             from app.services.product_service import AsyncProductService
             product_svc = AsyncProductService(self.db)
             for item in order.items:
                 await product_svc.release_stock(item.product_id, item.quantity)
             order.driver_id = None
             order.assigned_at = None

        order.status = new_status_enum
        await self.db.commit()
        
        await self._invalidate_order_flow(order_id, order.user_id)
        return await self._refetch_full_order(order_id)

    async def accept_order_atomic(self, order_id: int, driver_id: int) -> models.Order:
        try:
            stmt = (
                select(models.Order)
                .options(selectinload(models.Order.items))
                .with_for_update()
                .where(models.Order.id == order_id)
            )
            result = await self.db.execute(stmt)
            order = result.unique().scalar_one_or_none()
            
            if not order: 
                raise NotFoundError("Order", order_id)
            
            if order.status not in [models.OrderStatus.pending, models.OrderStatus.confirmed]:
                 raise BadRequestError(f"Cannot accept order in status {order.status}")
            
            if order.driver_id and order.driver_id != driver_id:
                 raise BadRequestError("Order already assigned to another driver")

            order.driver_id = driver_id
            order.status = models.OrderStatus.assigned
            order.assigned_at = datetime.now(timezone.utc)
            
            await self.db.commit()
            await self._invalidate_order_flow(order_id, order.user_id)
            return await self._refetch_full_order(order_id)

        except Exception as e:
            await self.db.rollback()
            raise e