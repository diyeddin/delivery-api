from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.db.models import Order, OrderStatus, UserRole
from app.services.order_service import AsyncOrderService
from app.schemas.order import OrderOut
from app.utils.dependencies import get_current_user

router = APIRouter(prefix="/drivers", tags=["drivers"])


@router.get("/available-orders", response_model=List[OrderOut])
async def get_available_orders(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get orders available for driver assignment (confirmed status)"""
    if current_user.role != UserRole.driver:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only drivers can access this endpoint"
        )
    
    svc = AsyncOrderService(db)
    orders = await svc.get_all_orders()
    return [o for o in orders if o.status == OrderStatus.confirmed and o.driver_id is None]


@router.post("/accept-order/{order_id}")
async def accept_order(
    order_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Accept an available order for delivery"""
    if current_user.role != UserRole.driver:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only drivers can accept orders"
        )
    
    svc = AsyncOrderService(db)
    try:
        order = await svc.accept_order_atomic(order_id, current_user.id)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return {"message": "Order accepted successfully", "order_id": order_id}


@router.get("/my-deliveries", response_model=List[OrderOut])
async def get_my_deliveries(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get all orders assigned to the current driver"""
    if current_user.role != UserRole.driver:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only drivers can access this endpoint"
        )
    
    svc = AsyncOrderService(db)
    orders = await svc.get_all_orders()
    return [o for o in orders if o.driver_id == current_user.id]


@router.patch("/delivery-status/{order_id}")
async def update_delivery_status(
    order_id: int,
    new_status: OrderStatus,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update delivery status for assigned orders"""
    if current_user.role != UserRole.driver:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only drivers can update delivery status"
        )
    
    svc = AsyncOrderService(db)
    # Leverage service validation / update
    try:
        order = await svc.update_order_status(order_id, new_status, current_user)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return {"message": "Status updated successfully", "order_id": order_id, "new_status": new_status}