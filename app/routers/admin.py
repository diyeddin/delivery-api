from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.db.models import Order, OrderStatus, UserRole
from app.schemas.order import OrderOut
from app.utils.dependencies import get_current_user
from app.services.order_service import AsyncOrderService
from app.utils.exceptions import APIException

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/orders", response_model=List[OrderOut])
async def get_all_orders(
    status_filter: Optional[OrderStatus] = Query(None, description="Filter orders by status"),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get all orders (admin only) with optional status filtering"""
    if current_user.role != UserRole.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can access all orders"
        )

    svc = AsyncOrderService(db)
    if status_filter:
        return await svc.get_all_orders(status_filter.value)
    return await svc.get_all_orders()


@router.patch("/orders/{order_id}/cancel")
async def cancel_order(
    order_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Cancel an order (admin only)"""
    if current_user.role != UserRole.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can cancel orders"
        )
    
    svc = AsyncOrderService(db)
    try:
        await svc.update_order_status(order_id, "cancelled", current_user)
    except APIException:
        # Let APIException bubble up with its proper status/detail
        raise
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot cancel order")
    return {"message": "Order cancelled successfully", "order_id": order_id}


@router.patch("/orders/{order_id}/confirm")
async def confirm_order(
    order_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Confirm a pending order (admin only)"""
    if current_user.role != UserRole.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can confirm orders"
        )
    
    svc = AsyncOrderService(db)
    try:
        await svc.update_order_status(order_id, "confirmed", current_user)
    except APIException:
        raise
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot confirm order")
    return {"message": "Order confirmed successfully", "order_id": order_id}