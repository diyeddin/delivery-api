from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from app.db import database, models
from app.schemas import order as order_schema
from app.utils.dependencies import get_current_user, require_role

router = APIRouter(prefix="/orders", tags=["orders"])


@router.post("/", response_model=order_schema.OrderOut)
def create_order(
    order: order_schema.OrderCreate,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user)
):
    order_items = []
    total = 0.0

    for item in order.items:
        product = db.query(models.Product).filter(models.Product.id == item.product_id).first()
        if not product:
            raise HTTPException(status_code=404, detail=f"Product {item.product_id} not found")
        if product.stock < item.quantity:
            raise HTTPException(status_code=400, detail=f"Not enough stock for {product.name}")

        # Deduct stock
        product.stock -= item.quantity

        order_item = models.OrderItem(
            product_id=item.product_id,
            quantity=item.quantity,
            price_at_purchase=product.price,
        )
        order_items.append(order_item)
        total += product.price * item.quantity

    new_order = models.Order(
        user_id=current_user.id,
        total_price=total,
        items=order_items,
    )
    db.add(new_order)
    db.commit()
    db.refresh(new_order)
    return new_order


@router.get("/me", response_model=List[order_schema.OrderOut])
def get_my_orders(
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user)
):
    return db.query(models.Order).filter(models.Order.user_id == current_user.id).all()


@router.get("/{order_id}", response_model=order_schema.OrderOut)
def get_order(
    order_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user)
):
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order or order.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


@router.put("/{order_id}/status", response_model=order_schema.OrderOut)
def update_status(
    order_id: int,
    new_status: str,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(require_role(["admin", "driver"]))
):
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    order.status = new_status
    db.commit()
    db.refresh(order)
    return order
