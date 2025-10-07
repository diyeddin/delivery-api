"""
Order service layer for complex business logic.
"""
from sqlalchemy.orm import Session
from typing import List, Optional
from app.db import models
from app.schemas.order import OrderCreate
from app.utils.exceptions import NotFoundError, BadRequestError, InsufficientStockError
from app.services.product_service import ProductService


class OrderService:
    """Service class for order-related business logic."""
    
    def __init__(self, db: Session):
        self.db = db
        self.product_service = ProductService(db)
    
    def create_order(self, order_data: OrderCreate, current_user: models.User) -> models.Order:
        """Create a new order with stock validation and reservation."""
        if not order_data.items:
            raise BadRequestError("Order must contain at least one item")
        
        # Validate all products exist and calculate total
        order_items = []
        total_price = 0.0
        
        for item in order_data.items:
            product = self.product_service.get_product(item.product_id)
            
            # Check stock availability
            if not self.product_service.check_stock_availability(item.product_id, item.quantity):
                raise InsufficientStockError(product.name, item.quantity, product.stock)
            
            # Create order item with current price (price at purchase)
            order_item = models.OrderItem(
                product_id=item.product_id,
                quantity=item.quantity,
                price_at_purchase=product.price
            )
            order_items.append(order_item)
            total_price += product.price * item.quantity
        
        # Create the order
        db_order = models.Order(
            user_id=current_user.id,
            status=models.OrderStatus.pending,
            total_price=total_price,
            items=order_items
        )
        
        self.db.add(db_order)
        self.db.flush()  # Get the order ID without committing
        
        # Reserve stock for all items
        for item in order_data.items:
            self.product_service.reserve_stock(item.product_id, item.quantity)
        
        self.db.commit()
        self.db.refresh(db_order)
        return db_order
    
    def get_order(self, order_id: int, current_user: models.User) -> models.Order:
        """Get order by ID with user authorization."""
        order = self.db.query(models.Order).filter(models.Order.id == order_id).first()
        if not order:
            raise NotFoundError("Order", order_id)
        
        # Users can only see their own orders (unless admin/driver)
        if current_user.role == models.UserRole.customer:
            if order.user_id != current_user.id:
                from app.utils.exceptions import PermissionDeniedError
                raise PermissionDeniedError("view", "order")
        
        # Drivers can only see their assigned orders
        elif current_user.role == models.UserRole.driver:
            if order.driver_id != current_user.id and order.user_id != current_user.id:
                from app.utils.exceptions import PermissionDeniedError
                raise PermissionDeniedError("view", "order")
        
        return order
    
    def get_user_orders(self, current_user: models.User) -> List[models.Order]:
        """Get all orders for the current user."""
        return self.db.query(models.Order).filter(
            models.Order.user_id == current_user.id
        ).all()
    
    def get_all_orders(self, status_filter: Optional[str] = None) -> List[models.Order]:
        """Get all orders (admin only) with optional status filter."""
        query = self.db.query(models.Order)
        
        if status_filter:
            # Validate status
            try:
                status_enum = models.OrderStatus(status_filter)
                query = query.filter(models.Order.status == status_enum)
            except ValueError:
                raise BadRequestError(f"Invalid status: {status_filter}")
        
        return query.all()
    
    def update_order_status(
        self, 
        order_id: int, 
        new_status: str, 
        current_user: models.User
    ) -> models.Order:
        """Update order status with business rules validation."""
        order = self.db.query(models.Order).filter(models.Order.id == order_id).first()
        if not order:
            raise NotFoundError("Order", order_id)
        
        # Validate new status
        try:
            new_status_enum = models.OrderStatus(new_status)
        except ValueError:
            raise BadRequestError(f"Invalid status: {new_status}")
        
        # Business rules for status transitions
        self._validate_status_transition(order.status, new_status_enum, current_user)
        
        order.status = new_status_enum
        self.db.commit()
        self.db.refresh(order)
        return order
    
    def _validate_status_transition(
        self, 
        current_status: models.OrderStatus, 
        new_status: models.OrderStatus, 
        user: models.User
    ) -> None:
        """Validate if status transition is allowed based on business rules."""
        from app.utils.exceptions import InvalidOrderStatusError, PermissionDeniedError
        
        # Define allowed transitions based on user roles
        admin_allowed = {
            models.OrderStatus.pending: [models.OrderStatus.confirmed, models.OrderStatus.cancelled],
            models.OrderStatus.confirmed: [models.OrderStatus.assigned, models.OrderStatus.cancelled],
            models.OrderStatus.assigned: [models.OrderStatus.picked_up, models.OrderStatus.cancelled],
            models.OrderStatus.picked_up: [models.OrderStatus.in_transit, models.OrderStatus.cancelled],
            models.OrderStatus.in_transit: [models.OrderStatus.delivered, models.OrderStatus.cancelled],
            models.OrderStatus.delivered: [],  # Final state
            models.OrderStatus.cancelled: []   # Final state
        }
        
        driver_allowed = {
            models.OrderStatus.assigned: [models.OrderStatus.picked_up],
            models.OrderStatus.picked_up: [models.OrderStatus.in_transit],
            models.OrderStatus.in_transit: [models.OrderStatus.delivered]
        }
        
        # Check permissions and allowed transitions
        if user.role == models.UserRole.admin:
            allowed_transitions = admin_allowed.get(current_status, [])
        elif user.role == models.UserRole.driver:
            allowed_transitions = driver_allowed.get(current_status, [])
        else:
            raise PermissionDeniedError("update order status")
        
        if new_status not in allowed_transitions:
            raise InvalidOrderStatusError(current_status.value, new_status.value)
    
    def assign_driver_to_order(self, order_id: int, driver_id: int) -> models.Order:
        """Assign a driver to an order."""
        order = self.db.query(models.Order).filter(models.Order.id == order_id).first()
        if not order:
            raise NotFoundError("Order", order_id)
        
        # Validate driver exists and has driver role
        driver = self.db.query(models.User).filter(models.User.id == driver_id).first()
        if not driver or driver.role != models.UserRole.driver:
            raise BadRequestError("Invalid driver ID")
        
        # Only confirmed orders can be assigned
        if order.status != models.OrderStatus.confirmed:
            raise BadRequestError("Only confirmed orders can be assigned to drivers")
        
        order.driver_id = driver_id
        order.status = models.OrderStatus.assigned
        self.db.commit()
        self.db.refresh(order)
        return order