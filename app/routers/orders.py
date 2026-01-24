from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List
from app.db import database, models
from app.schemas import order as order_schema
from app.services.order_service import AsyncOrderService
from app.utils.dependencies import require_scope
from app.utils.exceptions import NotFoundError, BadRequestError, PermissionDeniedError, InvalidOrderStatusError
from app.core.logging import get_logger, log_business_event

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
    
    try:
        new_orders = await svc.create_order(order, current_user)
        
        for created_order in new_orders:
            log_business_event(
                "order_created", 
                current_user.id,
                order_id=created_order.id, 
                total_price=created_order.total_price, 
                items_count=len(created_order.items)
            )
        return new_orders
    except BadRequestError as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- FIXED ENDPOINT ---
@router.get("/available", response_model=List[order_schema.OrderOut])
async def get_available_orders(
    db: AsyncSession = Depends(database.get_db),
    # Drivers have 'orders:read', so they can access this
    current_user: models.User = Depends(require_scope("orders:read"))
):
    """
    Get orders available for pickup.
    Uses efficient DB filtering instead of fetching all orders.
    """
    svc = AsyncOrderService(db)
    # This calls the method that includes .options(selectinload(...))
    return await svc.get_available_orders()
# ----------------------


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
    current_user: models.User = Depends(require_scope("orders:read_all"))
):
    """Get all orders (Admin only)"""
    svc = AsyncOrderService(db)
    return await svc.get_all_orders()


@router.get("/assigned-to-me", response_model=List[order_schema.OrderOut])
async def get_assigned_orders(
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_scope("orders:read"))
):
    """Get orders assigned to current driver"""
    svc = AsyncOrderService(db)
    # Optimization: Filter in SQL via service (You can add get_driver_orders to service later)
    # For now, we filter logically.
    orders = await svc.get_all_orders() 
    return [o for o in orders if o.driver_id == current_user.id]


@router.get("/{order_id}", response_model=order_schema.OrderOut)
async def get_order(
    order_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_scope("orders:read"))
):
    svc = AsyncOrderService(db)
    try:
        return await svc.get_order(order_id, current_user)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Order not found")


@router.put("/{order_id}/status", response_model=order_schema.OrderOut)
async def update_status(
    order_id: int,
    status_update: order_schema.OrderStatusUpdate,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_scope("orders:update_status"))
):
    svc = AsyncOrderService(db)
    try:
        return await svc.update_order_status(order_id, status_update.status, current_user)
    except (NotFoundError, BadRequestError, PermissionDeniedError, InvalidOrderStatusError) as e:
        # Map exceptions to HTTP codes
        code = 400
        if isinstance(e, NotFoundError): code = 404
        if isinstance(e, PermissionDeniedError): code = 403
        raise HTTPException(status_code=code, detail=str(e))


@router.put("/{order_id}/accept", response_model=order_schema.OrderOut)
async def accept_order(
    order_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_scope("orders:update_status"))
):
    """Driver accepts an available order"""
    if current_user.role != models.UserRole.driver:
        raise HTTPException(status_code=403, detail="Only drivers can accept orders")

    svc = AsyncOrderService(db)
    try:
        return await svc.accept_order_atomic(order_id, current_user.id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Order not found")
    except BadRequestError as e:
        raise HTTPException(status_code=400, detail=str(e))