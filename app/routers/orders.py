from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from app.db import database, models
from app.schemas import order as order_schema
from app.utils.dependencies import require_role
from app.core.logging import get_logger, log_business_event

router = APIRouter(prefix="/orders", tags=["orders"])
logger = get_logger(__name__)


@router.post("/", response_model=order_schema.OrderOut)
def create_order(
    order: order_schema.OrderCreate,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(require_role([models.UserRole.customer]))
    ):
    logger.info("Creating new order", user_id=current_user.id, items_count=len(order.items))
    
    order_items = []
    total = 0.0

    for item in order.items:
        product = db.query(models.Product).filter(models.Product.id == item.product_id).first()
        if not product:
            logger.warning("Product not found during order creation", 
                         product_id=item.product_id, user_id=current_user.id)
            raise HTTPException(status_code=404, detail=f"Product {item.product_id} not found")
        if product.stock < item.quantity:
            logger.warning("Insufficient stock during order creation", 
                         product_id=item.product_id, requested=item.quantity, 
                         available=product.stock, user_id=current_user.id)
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
    
    # Log successful order creation
    log_business_event("order_created", current_user.id, 
                      order_id=new_order.id, total_price=total, items_count=len(order_items))
    logger.info("Order created successfully", order_id=new_order.id, 
               user_id=current_user.id, total_price=total)
    
    return new_order


@router.get("/me", response_model=List[order_schema.OrderOut])
def get_my_orders(
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(require_role([models.UserRole.customer]))
    ):
    """Get current user's orders (customers only)"""
    return db.query(models.Order).filter(models.Order.user_id == current_user.id).all()


@router.get("/", response_model=List[order_schema.OrderOut])
def get_all_orders(
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(require_role([models.UserRole.admin]))
    ):
    """Get all orders (admin only)"""
    return db.query(models.Order).all()


@router.get("/assigned-to-me", response_model=List[order_schema.OrderOut])
def get_assigned_orders(
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(require_role([models.UserRole.driver]))
    ):
    """Get orders assigned to current driver"""
    return db.query(models.Order).filter(models.Order.driver_id == current_user.id).all()


@router.get("/my-store-orders", response_model=List[order_schema.OrderOut])
def get_store_orders(
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(require_role([models.UserRole.store_owner]))
    ):
    """Get orders containing products from current store owner's stores"""
    # Get all stores owned by current user
    store_ids = [store.id for store in current_user.stores]
    
    # Find orders that contain products from these stores
    orders = db.query(models.Order).join(models.OrderItem).join(models.Product).filter(
        models.Product.store_id.in_(store_ids)
    ).distinct().all()
    
    return orders


@router.get("/{order_id}", response_model=order_schema.OrderOut)
def get_order(
    order_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(require_role([models.UserRole.customer, models.UserRole.admin, models.UserRole.driver, models.UserRole.store_owner]))
    ):
    """Get specific order with role-based access control"""
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    # Role-based access control
    if current_user.role == models.UserRole.customer:
        # Customers can only see their own orders - return 404 for unauthorized access
        if order.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="Order not found")
    elif current_user.role == models.UserRole.admin:
        # Admins can see all orders
        pass
    elif current_user.role == models.UserRole.driver:
        # Drivers can only see orders assigned to them
        if order.driver_id != current_user.id:
            raise HTTPException(status_code=404, detail="Order not found")
    elif current_user.role == models.UserRole.store_owner:
        # Store owners can see orders containing their products
        store_ids = [store.id for store in current_user.stores]
        order_has_store_products = any(
            item.product.store_id in store_ids for item in order.items
        )
        if not order_has_store_products:
            raise HTTPException(status_code=404, detail="Order not found")
    
    return order


@router.put("/{order_id}/status", response_model=order_schema.OrderOut)
def update_status(
    order_id: int,
    new_status: str,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(require_role([models.UserRole.admin, models.UserRole.driver, models.UserRole.store_owner]))
    ):
    """Update order status with role-based permissions"""
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    # Validate status transitions based on role
    if current_user.role == models.UserRole.store_owner:
        # Store owners can only update orders containing products from their stores
        store_ids = [store.id for store in current_user.stores]
        order_has_store_products = any(
            item.product.store_id in store_ids for item in order.items
        )
        if not order_has_store_products:
            raise HTTPException(status_code=403, detail="Access denied")
        
        if new_status not in ['confirmed', 'preparing', 'ready_for_pickup']:
            raise HTTPException(status_code=403, detail="Store owners can only confirm, prepare, or mark orders ready for pickup")
    
    elif current_user.role == models.UserRole.driver:
        # Drivers can only update orders assigned to them
        if order.driver_id != current_user.id:
            raise HTTPException(status_code=403, detail="Access denied")
        
        if new_status not in ['picked_up', 'in_transit', 'delivered']:
            raise HTTPException(status_code=403, detail="Drivers can only pick up, transit, or deliver orders")
    
    # Admins can update to any status

    order.status = new_status
    db.commit()
    db.refresh(order)
    return order


@router.put("/{order_id}/assign-driver", response_model=order_schema.OrderOut)
def assign_driver(
    order_id: int,
    driver_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(require_role([models.UserRole.admin]))
    ):
    """Assign a driver to an order (admin only)"""
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    # Verify driver exists and has driver role
    driver = db.query(models.User).filter(
        models.User.id == driver_id,
        models.User.role == models.UserRole.driver
    ).first()
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    
    order.driver_id = driver_id
    db.commit()
    db.refresh(order)
    return order


@router.get("/available-for-pickup", response_model=List[order_schema.OrderOut])
def get_available_orders(
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(require_role([models.UserRole.driver]))
    ):
    """Get orders available for pickup (unassigned orders ready for pickup)"""
    return db.query(models.Order).filter(
        models.Order.status == 'ready_for_pickup',
        models.Order.driver_id.is_(None)
    ).all()


@router.put("/{order_id}/accept", response_model=order_schema.OrderOut)
def accept_order(
    order_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(require_role([models.UserRole.driver]))
    ):
    """Driver accepts an available order"""
    order = db.query(models.Order).filter(
        models.Order.id == order_id,
        models.Order.status == 'ready_for_pickup',
        models.Order.driver_id.is_(None)
    ).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not available for pickup")
    
    order.driver_id = current_user.id
    db.commit()
    db.refresh(order)
    return order
