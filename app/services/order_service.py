"""
Order service layer for complex business logic.
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional
from app.db import models
from app.schemas.order import OrderCreate
from app.utils.exceptions import NotFoundError, BadRequestError, InsufficientStockError
from datetime import datetime, timezone, timedelta
from itertools import groupby

class AsyncOrderService:
    """Async service class for order-related business logic using AsyncSession."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_order(self, order_data: OrderCreate, current_user: models.User) -> List[models.Order]:
        """
        Create orders from a cart. 
        If items belong to multiple stores, split them into separate Order records.
        """
        if not order_data.items:
            raise BadRequestError("Order must contain at least one item")

        from app.services.product_service import AsyncProductService
        product_svc = AsyncProductService(self.db)

        # 1. Fetch and Validate all products first
        # We need to know the store_id for every product to group them
        validated_items = []
        for item in order_data.items:
            product = await product_svc.get_product(item.product_id)
            
            # Stock Check
            if not await product_svc.check_stock_availability(item.product_id, item.quantity):
                raise InsufficientStockError(product.name, item.quantity, product.stock)
            
            validated_items.append({
                "schema": item,
                "product": product,
                "store_id": product.store_id
            })

        # 2. Group items by Store ID
        # Sort first because groupby requires sorted input
        validated_items.sort(key=lambda x: x["store_id"])
        
        created_orders = []

        try:
            for store_id, group in groupby(validated_items, key=lambda x: x["store_id"]):
                store_items = list(group)
                
                # Calculate total for this specific store's order
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

                    # Reserve stock immediately
                    await product_svc.reserve_stock(product.id, qty)

                # Create the Order record for this store
                db_order = models.Order(
                    user_id=current_user.id,
                    store_id=store_id,  # CRITICAL: Link to store
                    status=models.OrderStatus.pending,
                    total_price=total_price,
                    items=db_order_items
                )
                self.db.add(db_order)
                created_orders.append(db_order)

            await self.db.commit()
            
            # Refresh all orders to get IDs
            for order in created_orders:
                await self.db.refresh(order)
                
            return created_orders

        except Exception as e:
            await self.db.rollback()
            raise e

    async def get_order(self, order_id: int, current_user: models.User) -> models.Order:
        result = await self.db.execute(select(models.Order).where(models.Order.id == order_id))
        order = result.unique().scalar_one_or_none()
        if not order:
            raise NotFoundError("Order", order_id)

        if current_user.role == models.UserRole.customer:
            if order.user_id != current_user.id:
                # Hide existence of orders from other customers by returning 404
                raise NotFoundError("Order")
        elif current_user.role == models.UserRole.driver:
            if order.driver_id != current_user.id and order.user_id != current_user.id:
                # Hide existence to unauthorized drivers
                raise NotFoundError("Order")

        return order

    async def get_user_orders(self, current_user: models.User):
        result = await self.db.execute(select(models.Order).where(models.Order.user_id == current_user.id))
        return result.unique().scalars().all()

    async def get_all_orders(self, status_filter: Optional[str] = None):
        stmt = select(models.Order)
        if status_filter:
            try:
                status_enum = models.OrderStatus(status_filter)
                stmt = stmt.where(models.Order.status == status_enum)
            except ValueError:
                raise BadRequestError(f"Invalid status: {status_filter}")
        result = await self.db.execute(stmt)
        return result.unique().scalars().all()

    async def update_order_status(self, order_id: int, new_status: str, current_user: models.User):
        result = await self.db.execute(select(models.Order).where(models.Order.id == order_id))
        order = result.unique().scalar_one_or_none()
        if not order:
            raise NotFoundError("Order", order_id)

        try:
            new_status_enum = models.OrderStatus(new_status)
        except ValueError:
            raise BadRequestError(f"Invalid status: {new_status}")

        self._validate_status_transition(order.status, new_status_enum, current_user)

        # If cancelling, release stock
        if new_status_enum == models.OrderStatus.cancelled:
            # We need to fetch items to know what to release
            # Ensure items are loaded (lazy="joined" in model helps here)
            for item in order.items:
                await self.product_service.release_stock(item.product_id, item.quantity)
            
            order.driver_id = None
            order.assigned_at = None
            
        order.status = new_status_enum
        await self.db.commit()
        await self.db.refresh(order)
        return order

    def _validate_status_transition(
        self,
        current_status: models.OrderStatus,
        new_status: models.OrderStatus,
        user: models.User,
    ) -> None:
        from app.utils.exceptions import InvalidOrderStatusError, PermissionDeniedError

        admin_allowed = {
            models.OrderStatus.pending: [models.OrderStatus.confirmed, models.OrderStatus.cancelled],
            models.OrderStatus.confirmed: [models.OrderStatus.assigned, models.OrderStatus.cancelled],
            models.OrderStatus.assigned: [models.OrderStatus.picked_up, models.OrderStatus.cancelled],
            models.OrderStatus.picked_up: [models.OrderStatus.in_transit, models.OrderStatus.cancelled],
            models.OrderStatus.in_transit: [models.OrderStatus.delivered, models.OrderStatus.cancelled],
            models.OrderStatus.delivered: [],
            models.OrderStatus.cancelled: [],
        }

        driver_allowed = {
            models.OrderStatus.assigned: [models.OrderStatus.picked_up],
            models.OrderStatus.picked_up: [models.OrderStatus.in_transit],
            models.OrderStatus.in_transit: [models.OrderStatus.delivered],
        }

        if user.role == models.UserRole.admin:
            # Admin-specific messages expected by tests
            if new_status == models.OrderStatus.cancelled and current_status in (
                models.OrderStatus.delivered, models.OrderStatus.cancelled
            ):
                from app.utils.exceptions import BadRequestError
                raise BadRequestError("Cannot cancel order that is already delivered or cancelled")
            if new_status == models.OrderStatus.confirmed and current_status != models.OrderStatus.pending:
                from app.utils.exceptions import BadRequestError
                raise BadRequestError("Only pending orders can be confirmed")

            allowed_transitions = admin_allowed.get(current_status, [])
        elif user.role == models.UserRole.driver:
            allowed_transitions = driver_allowed.get(current_status, [])
        else:
            raise PermissionDeniedError("update order status")

        if new_status not in allowed_transitions:
            raise InvalidOrderStatusError(current_status.value, new_status.value)

    async def assign_driver_to_order(self, order_id: int, driver_id: int):
        result = await self.db.execute(select(models.Order).where(models.Order.id == order_id))
        order = result.unique().scalar_one_or_none()
        if not order:
            raise NotFoundError("Order", order_id)

        result = await self.db.execute(select(models.User).where(models.User.id == driver_id))
        driver = result.unique().scalar_one_or_none()
        if not driver or driver.role != models.UserRole.driver:
            raise BadRequestError("Invalid driver ID")

        # Allow admin to assign driver even if order is still pending or already confirmed
        if order.status not in (models.OrderStatus.pending, models.OrderStatus.confirmed):
            raise BadRequestError("Only pending or confirmed orders can be assigned to drivers")

        order.driver_id = driver_id
        order.status = models.OrderStatus.assigned
        order.assigned_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(order)
        return order

    async def accept_order_atomic(self, order_id: int, driver_id: int) -> models.Order:
        # Mirror sync behavior: use nested transaction if a transaction is already active
        if self.db.in_transaction():
            trans_ctx = self.db.begin_nested()
        else:
            trans_ctx = self.db.begin()

        async with trans_ctx:
            result = await self.db.execute(
                select(models.Order).with_for_update().where(models.Order.id == order_id)
            )
            order = result.unique().scalar_one_or_none()
            if not order:
                raise NotFoundError("Order", order_id)

            now = datetime.now(timezone.utc)
            expiry_threshold = now - timedelta(minutes=10)

            modified = False
            if order.status == models.OrderStatus.confirmed and not order.driver_id:
                order.driver_id = driver_id
                order.status = models.OrderStatus.assigned
                order.assigned_at = now
                modified = True
            elif order.status == models.OrderStatus.assigned:
                assigned_at = order.assigned_at
                if assigned_at and assigned_at.tzinfo is None:
                    assigned_at = assigned_at.replace(tzinfo=timezone.utc)
                if not assigned_at or assigned_at <= expiry_threshold:
                    order.driver_id = driver_id
                    order.status = models.OrderStatus.assigned
                    order.assigned_at = now
                    modified = True
                else:
                    from app.utils.exceptions import BadRequestError
                    raise BadRequestError("Order is not available for assignment")
            else:
                from app.utils.exceptions import BadRequestError
                raise BadRequestError("Order is not available for assignment")

        if modified:
            await self.db.commit()
            await self.db.refresh(order)
            return order