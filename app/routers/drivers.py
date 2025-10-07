from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Order, OrderStatus, UserRole
from app.schemas.order import OrderOut
from app.utils.dependencies import get_current_user

router = APIRouter(prefix="/drivers", tags=["drivers"])


@router.get("/available-orders", response_model=List[OrderOut])
def get_available_orders(
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get orders available for driver assignment (confirmed status)"""
    if current_user.role != UserRole.driver:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only drivers can access this endpoint"
        )
    
    orders = db.query(Order).filter(
        Order.status == OrderStatus.confirmed,
        Order.driver_id.is_(None)
    ).all()
    
    return orders


@router.post("/accept-order/{order_id}")
def accept_order(
    order_id: int,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Accept an available order for delivery"""
    if current_user.role != UserRole.driver:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only drivers can accept orders"
        )
    
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found"
        )
    
    if order.status != OrderStatus.confirmed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Order is not available for assignment"
        )
    
    if order.driver_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Order already assigned to another driver"
        )
    
    order.driver_id = current_user.id
    order.status = OrderStatus.assigned
    db.commit()
    db.refresh(order)
    
    return {"message": "Order accepted successfully", "order_id": order_id}


@router.get("/my-deliveries", response_model=List[OrderOut])
def get_my_deliveries(
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all orders assigned to the current driver"""
    if current_user.role != UserRole.driver:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only drivers can access this endpoint"
        )
    
    orders = db.query(Order).filter(Order.driver_id == current_user.id).all()
    return orders


@router.patch("/delivery-status/{order_id}")
def update_delivery_status(
    order_id: int,
    new_status: OrderStatus,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update delivery status for assigned orders"""
    if current_user.role != UserRole.driver:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only drivers can update delivery status"
        )
    
    order = db.query(Order).filter(
        Order.id == order_id,
        Order.driver_id == current_user.id
    ).first()
    
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found or not assigned to you"
        )
    
    # Validate status transitions
    valid_transitions = {
        OrderStatus.assigned: [OrderStatus.picked_up, OrderStatus.cancelled],
        OrderStatus.picked_up: [OrderStatus.in_transit, OrderStatus.cancelled],
        OrderStatus.in_transit: [OrderStatus.delivered, OrderStatus.cancelled],
    }
    
    if order.status not in valid_transitions or new_status not in valid_transitions[order.status]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status transition from {order.status} to {new_status}"
        )
    
    order.status = new_status
    db.commit()
    db.refresh(order)
    
    return {"message": "Status updated successfully", "order_id": order_id, "new_status": new_status}