from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from app.db import database, models
from app.schemas import order as order_schema
from app.utils.dependencies import get_current_user, require_scope
from app.services.order_service import AsyncOrderService
from app.core.logging import get_logger, log_business_event
from app.utils.exceptions import InvalidOrderStatusError

router = APIRouter(prefix="/orders", tags=["orders"])
logger = get_logger(__name__)


@router.post("/", response_model=List[order_schema.OrderOut])
async def create_order(
    order: order_schema.OrderCreate,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_scope("orders:create"))
    ):
    logger.info("Processing cart", user_id=current_user.id, items_count=len(order.items))

    svc = AsyncOrderService(db)
    # Returns a list of orders (split by store)
    new_orders = await svc.create_order(order, current_user)
    
    for created_order in new_orders:
        log_business_event(
            "order_created", 
            current_user.id,
            order_id=created_order.id, 
            total_price=created_order.total_price, 
            items_count=len(created_order.items)
        )
        logger.info(
            "Sub-order created", 
            order_id=created_order.id,
            store_id=created_order.store_id,
            user_id=current_user.id
        )

    return new_orders


@router.get("/me", response_model=List[order_schema.OrderOut])
async def get_my_orders(
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_scope("orders:read_own"))
    ):
    """Get current user's orders (customers only)"""
    svc = AsyncOrderService(db)
    return await svc.get_user_orders(current_user)


@router.get("/", response_model=List[order_schema.OrderOut])
async def get_all_orders(
    db: AsyncSession = Depends(database.get_db),
    # SECURED: Only Admins have 'orders:read_all' via the wildcard '*'
    current_user: models.User = Depends(require_scope("orders:read_all"))
    ):
    """Get all orders (Admin only)"""
    svc = AsyncOrderService(db)
    return await svc.get_all_orders()


@router.get("/assigned-to-me", response_model=List[order_schema.OrderOut])
async def get_assigned_orders(
    db: AsyncSession = Depends(database.get_db),
    # Drivers have 'orders:read', so they can access this
    current_user: models.User = Depends(require_scope("orders:read"))
    ):
    """Get orders assigned to current driver"""
    svc = AsyncOrderService(db)
    # Optimization: ideally move this filter to the service layer to avoid fetching all orders
    orders = await svc.get_all_orders() 
    return [o for o in orders if o.driver_id == current_user.id]


@router.get("/my-store-orders", response_model=List[order_schema.OrderOut])
async def get_store_orders(
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_scope("orders:read_store"))
    ):
    """Get orders containing products from current store owner's stores"""
    svc = AsyncOrderService(db)
    # Fetch user's stores
    store_result = await db.execute(select(models.Store.id).where(models.Store.owner_id == current_user.id))
    store_ids = store_result.unique().scalars().all()
    
    # In a real production app, you would pass store_ids to the service 
    # to filter in SQL, not Python. Keeping Python filter for now to match current logic.
    orders = await svc.get_all_orders()
    
    # Filter for orders belonging to one of the owner's stores
    # Since we added store_id to Order model, this is now much faster/cleaner
    return [o for o in orders if o.store_id in store_ids]


@router.get("/available-for-pickup", response_model=List[order_schema.OrderOut])
async def get_available_orders(
    db: AsyncSession = Depends(database.get_db),
    # Drivers need this to see the "Job Board"
    current_user: models.User = Depends(require_scope("orders:read"))
    ):
    """Get orders available for pickup (unassigned orders ready for pickup)"""
    svc = AsyncOrderService(db)
    orders = await svc.get_all_orders()
    # Filter for Confirmed orders with no driver
    # Note: Logic might need to check 'confirmed' or 'ready_for_pickup' depending on your flow
    return [o for o in orders if o.status == models.OrderStatus.confirmed and o.driver_id is None]


@router.get("/{order_id}", response_model=order_schema.OrderOut)
async def get_order(
    order_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user)
    ):
    """Get specific order with role-based access control"""
    # Note: The service layer handles the "Owner/Driver" check logic
    # But for Store Owners, we should add the verify_order_access dependency here
    # if you implemented that step.
    svc = AsyncOrderService(db)
    order = await svc.get_order(order_id, current_user)
    return order


@router.put("/{order_id}/status", response_model=order_schema.OrderOut)
async def update_status(
    order_id: int,
    new_status: str,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_scope("orders:update_status"))
    ):
    """Update order status with role-based permissions"""
    svc = AsyncOrderService(db)
    try:
        return await svc.update_order_status(order_id, new_status, current_user)
    except InvalidOrderStatusError:
        # Allow a driver who is assigned to the order to mark it as delivered
        if current_user.role == models.UserRole.driver and new_status == "delivered":
            order = await svc.get_order(order_id, current_user)
            if order.driver_id == current_user.id:
                order.status = models.OrderStatus.delivered
                await db.commit()
                await db.refresh(order)
                return order
                
        # Allow admins to forcibly set delivered status
        if current_user.role == models.UserRole.admin and new_status == "delivered":
            order = await svc.get_order(order_id, current_user)
            order.status = models.OrderStatus.delivered
            await db.commit()
            await db.refresh(order)
            return order
        raise


@router.put("/{order_id}/assign-driver", response_model=order_schema.OrderOut)
async def assign_driver(
    order_id: int,
    driver_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_scope("orders:assign"))
    ):
    """Assign a driver to an order (admin only)"""
    svc = AsyncOrderService(db)
    return await svc.assign_driver_to_order(order_id, driver_id)


@router.put("/{order_id}/accept", response_model=order_schema.OrderOut)
async def accept_order(
    order_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_scope("orders:update_status"))
    ):
    """Driver accepts an available order"""
    svc = AsyncOrderService(db)
    # Use atomic accept flow
    return await svc.accept_order_atomic(order_id, current_user.id)