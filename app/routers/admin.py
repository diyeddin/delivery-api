from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Order, OrderStatus, UserRole
from app.schemas.order import OrderOut
from app.utils.dependencies import get_current_user

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/orders", response_model=List[OrderOut])
def get_all_orders(
    status_filter: Optional[OrderStatus] = Query(None, description="Filter orders by status"),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all orders (admin only) with optional status filtering"""
    if current_user.role != UserRole.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can access all orders"
        )
    
    query = db.query(Order)
    if status_filter:
        query = query.filter(Order.status == status_filter)
    
    orders = query.all()
    return orders


@router.patch("/orders/{order_id}/cancel")
def cancel_order(
    order_id: int,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Cancel an order (admin only)"""
    if current_user.role != UserRole.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can cancel orders"
        )
    
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found"
        )
    
    if order.status in [OrderStatus.delivered, OrderStatus.cancelled]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot cancel order that is already delivered or cancelled"
        )
    
    order.status = OrderStatus.cancelled
    
    # If order had assigned driver, remove assignment
    if order.driver_id:
        order.driver_id = None
    
    db.commit()
    db.refresh(order)
    
    return {"message": "Order cancelled successfully", "order_id": order_id}


@router.patch("/orders/{order_id}/confirm")
def confirm_order(
    order_id: int,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Confirm a pending order (admin only)"""
    if current_user.role != UserRole.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can confirm orders"
        )
    
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found"
        )
    
    if order.status != OrderStatus.pending:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only pending orders can be confirmed"
        )
    
    order.status = OrderStatus.confirmed
    db.commit()
    db.refresh(order)
    
    return {"message": "Order confirmed successfully", "order_id": order_id}