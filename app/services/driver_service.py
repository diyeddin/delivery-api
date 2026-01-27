"""
Driver service layer for business logic separation with Redis caching.
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional, Dict
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
    NEARBY_DRIVERS_CACHE_TTL = 60  # 1 minute
    
    def __init__(self, db: AsyncSession):
        self.db = db

    # --- CACHE HELPER METHODS ---
    
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

    async def get_available_orders(self) -> List[models.Order]:
        """
        Get orders available for driver assignment.
        These are orders with 'confirmed' status and no assigned driver.
        """
        from sqlalchemy.orm import selectinload
        
        # Try cache first
        cache_key = "drivers:available_orders"
        try:
            cached = await redis_client.get(cache_key)
            if cached:
                order_ids = json.loads(cached)
                
                # Fetch each order (may use order cache)
                orders = []
                for order_id in order_ids:
                    try:
                        # Fetch from DB with items loaded
                        stmt = (
                            select(models.Order)
                            .options(selectinload(models.Order.items))
                            .where(models.Order.id == order_id)
                        )
                        result = await self.db.execute(stmt)
                        order = result.unique().scalar_one_or_none()
                        
                        if order and order.status == models.OrderStatus.confirmed and order.driver_id is None:
                            orders.append(order)
                        else:
                            # Order status changed, invalidate cache
                            await redis_client.delete(cache_key)
                            break
                    except Exception:
                        await redis_client.delete(cache_key)
                        break
                else:
                    return orders
        except Exception:
            pass
        
        # Cache miss - fetch from database
        stmt = (
            select(models.Order)
            .options(selectinload(models.Order.items))
            .where(models.Order.status == models.OrderStatus.confirmed)
            .where(models.Order.driver_id == None)
            .order_by(models.Order.created_at.asc())  # Oldest first
        )
        result = await self.db.execute(stmt)
        orders = result.unique().scalars().all()
        
        # Cache the order IDs with short TTL
        try:
            order_ids = [order.id for order in orders]
            await redis_client.setex(
                cache_key,
                self.AVAILABLE_ORDERS_CACHE_TTL,
                json.dumps(order_ids)
            )
        except Exception:
            pass
        
        return orders

    async def get_driver_deliveries(self, driver_id: int) -> List[models.Order]:
        """Get all orders assigned to a specific driver."""
        from sqlalchemy.orm import selectinload
        
        # Try cache first
        cache_key = f"driver:deliveries:{driver_id}"
        try:
            cached = await redis_client.get(cache_key)
            if cached:
                order_ids = json.loads(cached)
                
                orders = []
                for order_id in order_ids:
                    try:
                        stmt = (
                            select(models.Order)
                            .options(selectinload(models.Order.items))
                            .where(models.Order.id == order_id)
                        )
                        result = await self.db.execute(stmt)
                        order = result.unique().scalar_one_or_none()
                        
                        if order and order.driver_id == driver_id:
                            orders.append(order)
                        else:
                            # Order reassigned or deleted
                            await redis_client.delete(cache_key)
                            break
                    except Exception:
                        await redis_client.delete(cache_key)
                        break
                else:
                    return orders
        except Exception:
            pass
        
        # Cache miss - fetch from database
        stmt = (
            select(models.Order)
            .options(selectinload(models.Order.items))
            .where(models.Order.driver_id == driver_id)
            .order_by(models.Order.created_at.desc())  # Newest first
        )
        result = await self.db.execute(stmt)
        orders = result.unique().scalars().all()
        
        # Cache the order IDs
        try:
            order_ids = [order.id for order in orders]
            await redis_client.setex(
                cache_key,
                self.DRIVER_DELIVERIES_CACHE_TTL,
                json.dumps(order_ids)
            )
        except Exception:
            pass
        
        return orders

    async def accept_order(self, order_id: int, driver_id: int) -> models.Order:
        """
        Accept an order for delivery.
        Delegates to OrderService for atomic assignment.
        """
        from app.services.order_service import AsyncOrderService
        
        order_service = AsyncOrderService(self.db)
        order = await order_service.accept_order_atomic(order_id, driver_id)
        
        # Invalidate driver and available orders caches
        await self._invalidate_driver_cache(driver_id)
        
        return order

    async def update_delivery_status(
        self,
        order_id: int,
        new_status: str,
        driver_id: int
    ) -> models.Order:
        """
        Update delivery status.
        Validates that the driver is assigned to this order.
        """
        from app.services.order_service import AsyncOrderService
        from sqlalchemy.orm import selectinload
        
        # Fetch order to verify driver assignment
        stmt = (
            select(models.Order)
            .options(selectinload(models.Order.items))
            .where(models.Order.id == order_id)
        )
        result = await self.db.execute(stmt)
        order = result.unique().scalar_one_or_none()
        
        if not order:
            raise NotFoundError("Order", order_id)
        
        # Verify driver is assigned to this order
        if order.driver_id != driver_id:
            raise PermissionDeniedError("update", "orders not assigned to you")
        
        # Create a mock user object for the service method
        mock_driver = models.User(id=driver_id, role=models.UserRole.driver)
        
        # Use OrderService to update status (handles all validation)
        order_service = AsyncOrderService(self.db)
        updated_order = await order_service.update_order_status(
            order_id,
            new_status,
            mock_driver
        )
        
        # Invalidate driver cache
        await self._invalidate_driver_cache(driver_id)
        
        return updated_order

    async def get_driver_stats(self, driver_id: int) -> Dict:
        """Get statistics for a driver (deliveries completed, earnings, etc.)."""
        # Try cache first
        cache_key = f"driver:stats:{driver_id}"
        try:
            cached = await redis_client.get(cache_key)
            if cached:
                return json.loads(cached)
        except Exception:
            pass
        
        # Cache miss - calculate stats
        from sqlalchemy import func
        
        # Total deliveries
        total_deliveries_stmt = (
            select(func.count(models.Order.id))
            .where(models.Order.driver_id == driver_id)
            .where(models.Order.status == models.OrderStatus.delivered)
        )
        total_deliveries_result = await self.db.execute(total_deliveries_stmt)
        total_deliveries = total_deliveries_result.scalar() or 0
        
        # Total earnings (sum of all delivered orders)
        total_earnings_stmt = (
            select(func.sum(models.Order.total_price))
            .where(models.Order.driver_id == driver_id)
            .where(models.Order.status == models.OrderStatus.delivered)
        )
        total_earnings_result = await self.db.execute(total_earnings_stmt)
        total_earnings = float(total_earnings_result.scalar() or 0)
        
        # Active deliveries (assigned or in_transit)
        active_deliveries_stmt = (
            select(func.count(models.Order.id))
            .where(models.Order.driver_id == driver_id)
            .where(models.Order.status.in_([
                models.OrderStatus.assigned,
                models.OrderStatus.in_transit
            ]))
        )
        active_deliveries_result = await self.db.execute(active_deliveries_stmt)
        active_deliveries = active_deliveries_result.scalar() or 0
        
        stats = {
            "driver_id": driver_id,
            "total_deliveries": total_deliveries,
            "total_earnings": total_earnings,
            "active_deliveries": active_deliveries,
            "average_per_delivery": total_earnings / total_deliveries if total_deliveries > 0 else 0
        }
        
        # Cache the stats
        try:
            await redis_client.setex(
                cache_key,
                self.DRIVER_STATS_CACHE_TTL,
                json.dumps(stats)
            )
        except Exception:
            pass
        
        return stats

    async def get_nearby_drivers(
        self,
        latitude: float,
        longitude: float,
        radius_km: float = 10.0
    ) -> List[Dict]:
        """
        Get active drivers near a location.
        Uses cached driver locations.
        """
        from app.services.user_service import AsyncUserService
        
        user_service = AsyncUserService(self.db)
        active_drivers = await user_service.get_active_drivers()
        
        nearby = []
        for driver in active_drivers:
            if driver.latitude and driver.longitude:
                # Calculate distance using address service helper
                from app.services.address_service import AsyncAddressService
                address_service = AsyncAddressService(self.db)
                
                distance = await address_service.calculate_distance(
                    latitude,
                    longitude,
                    driver.latitude,
                    driver.longitude
                )
                
                if distance <= radius_km:
                    nearby.append({
                        "driver_id": driver.id,
                        "name": driver.name,
                        "latitude": driver.latitude,
                        "longitude": driver.longitude,
                        "distance_km": round(distance, 2),
                        "is_active": driver.is_active
                    })
        
        # Sort by distance
        nearby.sort(key=lambda x: x["distance_km"])
        
        return nearby

    async def check_driver_availability(self, driver_id: int) -> bool:
        """Check if a driver is available to accept orders."""
        # Check if driver has too many active deliveries
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
        
        # Driver can handle max 3 concurrent deliveries (configurable)
        MAX_CONCURRENT_DELIVERIES = 3
        
        return active_count < MAX_CONCURRENT_DELIVERIES

    async def get_delivery_history(
        self,
        driver_id: int,
        status_filter: Optional[str] = None,
        limit: int = 50
    ) -> List[models.Order]:
        """Get delivery history for a driver with optional status filter."""
        from sqlalchemy.orm import selectinload
        
        stmt = (
            select(models.Order)
            .options(selectinload(models.Order.items))
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
        orders = result.unique().scalars().all()
        
        return orders