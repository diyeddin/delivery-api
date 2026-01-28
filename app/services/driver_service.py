"""
Driver service layer for business logic separation with Redis caching.
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from typing import List, Optional, Dict, Union, Any
from app.db import models
from app.utils.exceptions import NotFoundError, BadRequestError, PermissionDeniedError
from app.core.redis import redis_client
import json
from datetime import datetime, timezone

class AsyncDriverService:
    """Async driver service using AsyncSession with Redis caching."""
    
    # Cache TTLs (in seconds)
    AVAILABLE_ORDERS_CACHE_TTL = 30  # 30 seconds - very dynamic
    DRIVER_DELIVERIES_CACHE_TTL = 60  # 1 minute
    DRIVER_STATS_CACHE_TTL = 300  # 5 minutes
    
    def __init__(self, db: AsyncSession):
        self.db = db

    # --- CACHE HELPERS ---

    def _serialize_order(self, order: models.Order) -> dict:
        """
        Safe serialization of Order ORM object to Dict.
        Must match OrderService serialization for consistency.
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
        try:
            await redis_client.setex(key, ttl, json.dumps(data))
        except Exception:
            pass

    async def _invalidate_driver_cache(self, driver_id: int):
        """Invalidate all cache entries related to a driver."""
        keys_to_delete = [
            f"driver:deliveries:{driver_id}",
            f"driver:stats:{driver_id}",
            "drivers:available_orders",
        ]
        try:
            await redis_client.delete(*keys_to_delete)
        except Exception:
            pass

    # --- SERVICE METHODS ---

    async def get_available_orders(self):
        """
        Get orders available for driver assignment.
        (Confirmed status + No Driver).
        """
        # 1. Try Cache (Full List)
        cache_key = "drivers:available_orders"
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
            .where(models.Order.status == models.OrderStatus.confirmed)
            .where(models.Order.driver_id == None)
            .order_by(models.Order.created_at.asc())  # Oldest first
        )
        result = await self.db.execute(stmt)
        orders = result.unique().scalars().all()
        
        # 3. Serialize & Cache
        serialized_list = [self._serialize_order(o) for o in orders]
        await self._cache_set(cache_key, serialized_list, self.AVAILABLE_ORDERS_CACHE_TTL)
        
        return orders

    async def get_driver_deliveries(self, driver_id: int):
        """Get all orders assigned to a specific driver."""
        # 1. Try Cache (Full List)
        cache_key = f"driver:deliveries:{driver_id}"
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
            .where(models.Order.driver_id == driver_id)
            .order_by(models.Order.created_at.desc())
        )
        result = await self.db.execute(stmt)
        orders = result.unique().scalars().all()
        
        # 3. Serialize & Cache
        serialized_list = [self._serialize_order(o) for o in orders]
        await self._cache_set(cache_key, serialized_list, self.DRIVER_DELIVERIES_CACHE_TTL)
        
        return orders

    async def accept_order(self, order_id: int, driver_id: int) -> models.Order:
        """
        Accept an order. Delegates to OrderService for atomic consistency.
        """
        from app.services.order_service import AsyncOrderService
        
        order_service = AsyncOrderService(self.db)
        # This handles DB update + order cache invalidation
        order = await order_service.accept_order_atomic(order_id, driver_id)
        
        # We must ALSO invalidate Driver-specific caches
        await self._invalidate_driver_cache(driver_id)
        
        return order

    async def update_delivery_status(self, order_id: int, new_status: str, driver_id: int) -> models.Order:
        """
        Update delivery status.
        """
        # Fetch order to verify driver assignment
        stmt = select(models.Order).where(models.Order.id == order_id)
        result = await self.db.execute(stmt)
        order = result.unique().scalar_one_or_none()
        
        if not order:
            raise NotFoundError("Order", order_id)
        
        # Verify driver is assigned to this order
        if order.driver_id != driver_id:
            raise PermissionDeniedError("update", "orders not assigned to you")
        
        # Delegate to OrderService
        from app.services.order_service import AsyncOrderService
        order_service = AsyncOrderService(self.db)
        
        # Create mock user for permission check inside OrderService
        mock_driver = models.User(id=driver_id, role=models.UserRole.driver)
        
        updated_order = await order_service.update_order_status(
            order_id,
            new_status,
            mock_driver
        )
        
        # Invalidate driver cache
        await self._invalidate_driver_cache(driver_id)
        
        return updated_order

    async def get_driver_stats(self, driver_id: int) -> Dict:
        """Get statistics for a driver."""
        # 1. Try Cache
        cache_key = f"driver:stats:{driver_id}"
        try:
            cached = await redis_client.get(cache_key)
            if cached:
                return json.loads(cached)
        except Exception:
            pass
        
        # 2. Calculate Stats (DB heavy)
        from sqlalchemy import func
        
        # Total deliveries
        total_deliveries_stmt = (
            select(func.count(models.Order.id))
            .where(models.Order.driver_id == driver_id)
            .where(models.Order.status == models.OrderStatus.delivered)
        )
        total_deliveries = (await self.db.execute(total_deliveries_stmt)).scalar() or 0
        
        # Total earnings
        total_earnings_stmt = (
            select(func.sum(models.Order.total_price))
            .where(models.Order.driver_id == driver_id)
            .where(models.Order.status == models.OrderStatus.delivered)
        )
        total_earnings = float((await self.db.execute(total_earnings_stmt)).scalar() or 0)
        
        # Active deliveries
        active_deliveries_stmt = (
            select(func.count(models.Order.id))
            .where(models.Order.driver_id == driver_id)
            .where(models.Order.status.in_([
                models.OrderStatus.assigned,
                models.OrderStatus.in_transit
            ]))
        )
        active_deliveries = (await self.db.execute(active_deliveries_stmt)).scalar() or 0
        
        stats = {
            "driver_id": driver_id,
            "total_deliveries": total_deliveries,
            "total_earnings": total_earnings,
            "active_deliveries": active_deliveries,
            "average_per_delivery": total_earnings / total_deliveries if total_deliveries > 0 else 0
        }
        
        # 3. Cache
        await self._cache_set(cache_key, stats, self.DRIVER_STATS_CACHE_TTL)
        
        return stats

    async def get_nearby_drivers(self, latitude: float, longitude: float, radius_km: float = 10.0) -> List[Dict]:
        """
        Get active drivers near a location.
        """
        from app.services.user_service import AsyncUserService
        from app.services.address_service import AsyncAddressService
        
        # Optimized: user_service now returns cached list instantly
        user_service = AsyncUserService(self.db)
        active_drivers = await user_service.get_active_drivers()
        
        address_service = AsyncAddressService(self.db)
        
        nearby = []
        # Note: If active_drivers is a list of Dicts (from cache), accessing .latitude works differently
        # We need to handle both Dict and Object
        
        for driver in active_drivers:
            # Handle Dict vs Object
            d_lat = driver["latitude"] if isinstance(driver, dict) else driver.latitude
            d_lng = driver["longitude"] if isinstance(driver, dict) else driver.longitude
            d_id = driver["id"] if isinstance(driver, dict) else driver.id
            d_name = driver["name"] if isinstance(driver, dict) else driver.name
            d_active = driver["is_active"] if isinstance(driver, dict) else driver.is_active

            if d_lat and d_lng:
                distance = await address_service.calculate_distance(latitude, longitude, d_lat, d_lng)
                
                if distance <= radius_km:
                    nearby.append({
                        "driver_id": d_id,
                        "name": d_name,
                        "latitude": d_lat,
                        "longitude": d_lng,
                        "distance_km": round(distance, 2),
                        "is_active": d_active
                    })
        
        nearby.sort(key=lambda x: x["distance_km"])
        return nearby

    async def check_driver_availability(self, driver_id: int) -> bool:
        """Check if a driver is available."""
        from sqlalchemy import func
        
        active_count_stmt = (
            select(func.count(models.Order.id))
            .where(models.Order.driver_id == driver_id)
            .where(models.Order.status.in_([
                models.OrderStatus.assigned,
                models.OrderStatus.in_transit
            ]))
        )
        result = await self.db.execute(active_count_stmt)
        active_count = result.scalar() or 0
        
        MAX_CONCURRENT_DELIVERIES = 3
        return active_count < MAX_CONCURRENT_DELIVERIES

    async def get_delivery_history(self, driver_id: int, status_filter: Optional[str] = None, limit: int = 50):
        """Get delivery history (No caching for filtered history yet)."""
        stmt = (
            select(models.Order)
            .options(selectinload(models.Order.items).selectinload(models.OrderItem.product))
            .where(models.Order.driver_id == driver_id)
            .order_by(models.Order.created_at.desc())
            .limit(limit)
        )
        
        if status_filter:
            try:
                status_enum = models.OrderStatus(status_filter)
                stmt = stmt.where(models.Order.status == status_enum)
            except ValueError:
                raise BadRequestError(f"Invalid status: {status_filter}")
        
        result = await self.db.execute(stmt)
        return result.unique().scalars().all()