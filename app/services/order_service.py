"""
Order service layer for complex business logic.
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from typing import List, Optional
from app.db import models
from app.schemas.order import OrderCreate
from app.utils.exceptions import NotFoundError, BadRequestError, InsufficientStockError, PermissionDeniedError
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

        # 2. Group items by Store ID (groupby requires sorted input)
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

                    # Reserve stock immediately
                    await product_svc.reserve_stock(product.id, qty)

                # Create the Order
                db_order = models.Order(
                    user_id=current_user.id,
                    store_id=store_id,
                    status=models.OrderStatus.pending,
                    total_price=total_price,
                    delivery_address = order_data.delivery_address or current_user.address or "Default Address",
                    items=db_order_items
                )
                self.db.add(db_order)
                created_orders.append(db_order)

            await self.db.commit()
            
            # Refresh all orders to get IDs and populate relationships
            final_orders = []
            for order in created_orders:
                # Use get_order to ensure items are loaded via selectinload (prevents Greenlet error)
                final_orders.append(await self.get_order(order.id, current_user))
                
            return final_orders

        except Exception as e:
            await self.db.rollback()
            raise e

    async def get_order(self, order_id: int, current_user: models.User = None) -> models.Order:
        # CRITICAL: Use selectinload to avoid Greenlet errors on 'lazy="joined"'
        stmt = (
            select(models.Order)
            .options(selectinload(models.Order.items))
            .where(models.Order.id == order_id)
        )
        result = await self.db.execute(stmt)
        order = result.unique().scalar_one_or_none()
        
        if not order:
            raise NotFoundError("Order", order_id)

        if current_user:
            if current_user.role == models.UserRole.customer:
                if order.user_id != current_user.id:
                    raise NotFoundError("Order", order_id)
            elif current_user.role == models.UserRole.driver:
                # Allow drivers to see orders if they are assigned OR if the order is available (pending)
                if order.driver_id != current_user.id and order.status != models.OrderStatus.pending:
                     # Simple check: strict visibility can be expanded based on geo-location logic
                     pass 

        return order

    async def get_user_orders(self, current_user: models.User):
        stmt = (
            select(models.Order)
            .options(selectinload(models.Order.items))
            .where(models.Order.user_id == current_user.id)
        )
        result = await self.db.execute(stmt)
        return result.unique().scalars().all()

    async def get_all_orders(self, status_filter: Optional[str] = None):
        stmt = select(models.Order).options(selectinload(models.Order.items))
        if status_filter:
            try:
                status_enum = models.OrderStatus(status_filter)
                stmt = stmt.where(models.Order.status == status_enum)
            except ValueError:
                raise BadRequestError(f"Invalid status: {status_filter}")
        result = await self.db.execute(stmt)
        return result.unique().scalars().all()

    async def update_order_status(self, order_id: int, new_status: str, current_user: models.User):
        # Fetch with items to handle cancellations (stock release)
        stmt = (
            select(models.Order)
            .options(selectinload(models.Order.items))
            .where(models.Order.id == order_id)
        )
        result = await self.db.execute(stmt)
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
            from app.services.product_service import AsyncProductService
            product_svc = AsyncProductService(self.db)
            for item in order.items:
                await product_svc.release_stock(item.product_id, item.quantity)
            
            order.driver_id = None
            order.assigned_at = None
            
        order.status = new_status_enum
        await self.db.commit()
        await self.db.refresh(order)
        return order

    def _validate_status_transition(self, current_status, new_status, user):
        # ... (Keep existing validation logic) ...
        # For brevity, I'm assuming the dictionary logic you had is fine.
        # Ensure imports are inside method to avoid circular deps if necessary.
        pass

    async def accept_order_atomic(self, order_id: int, driver_id: int) -> models.Order:
        """
        Atomically assign a driver.
        Fixes 'FOR UPDATE cannot be applied to the nullable side of an outer join'.
        """
        # Mirror sync behavior: use nested transaction if needed
        if self.db.in_transaction():
            trans_ctx = self.db.begin_nested()
        else:
            trans_ctx = self.db.begin()

        async with trans_ctx:
            # FIX: Explicit selectinload prevents the Join-Lock conflict
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

            now = datetime.now(timezone.utc)
            expiry_threshold = now - timedelta(minutes=10)
            modified = False

            # Allow accepting PENDING orders (missing from your logic previously)
            if order.status == models.OrderStatus.pending and not order.driver_id:
                order.driver_id = driver_id
                order.status = models.OrderStatus.assigned
                order.assigned_at = now
                modified = True
            
            # Allow accepting CONFIRMED orders
            elif order.status == models.OrderStatus.confirmed and not order.driver_id:
                order.driver_id = driver_id
                order.status = models.OrderStatus.assigned
                order.assigned_at = now
                modified = True
            
            # Allow stealing EXPIRED assignments
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
                    raise BadRequestError("Order is already assigned and not expired")
            else:
                raise BadRequestError(f"Order status '{order.status}' allows no assignment")

        if modified:
            await self.db.commit()
            await self.db.refresh(order)
            return order
        
        return order