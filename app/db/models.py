from sqlalchemy import Column, Integer, String, Float, ForeignKey, Enum, UniqueConstraint, DateTime, Text, Boolean
from sqlalchemy.orm import relationship
from app.db.database import Base
import enum
from datetime import datetime, timezone, timedelta

class OrderStatus(str, enum.Enum):
    pending = "pending"
    confirmed = "confirmed"
    assigned = "assigned"
    picked_up = "picked_up"
    in_transit = "in_transit"
    delivered = "delivered"
    cancelled = "cancelled"

class UserRole(enum.Enum):
    customer = "customer"
    driver = "driver"
    admin = "admin"
    store_owner = "store_owner"

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    address = Column(String, nullable=True) 
    role = Column(Enum(UserRole), default=UserRole.customer)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Driver Location & Status
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    is_active = Column(Boolean, default=True)

    # NEW: Push Notification Token (Expo Token)
    notification_token = Column(String, nullable=True)

    # Relationships
    stores = relationship("Store", back_populates="owner")
    orders = relationship("Order", foreign_keys="Order.user_id", back_populates="user")
    deliveries = relationship("Order", foreign_keys="Order.driver_id", back_populates="driver")
    addresses = relationship("Address", back_populates="user", cascade="all, delete-orphan")

class Address(Base):
    __tablename__ = "addresses"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    label = Column(String, default="Home") 
    address_line = Column(String, nullable=False)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    instructions = Column(String, nullable=True)
    is_default = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="addresses")

class Store(Base):
    __tablename__ = "stores"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    category = Column(String)
    description = Column(String, nullable=True)
    image_url = Column(String, nullable=True)
    banner_url = Column(String, nullable=True)
    
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    is_active = Column(Boolean, default=True)

    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    
    orders = relationship("Order", back_populates="store")
    owner = relationship("User", back_populates="stores")
    products = relationship("Product", back_populates="store", cascade="all, delete-orphan")

class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True, index=True)
    store_id = Column(Integer, ForeignKey("stores.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True) 
    category = Column(String, nullable=True)
    price = Column(Float, nullable=False)
    stock = Column(Integer, default=0)
    image_url = Column(String, nullable=True)

    store = relationship("Store", back_populates="products")
    order_items = relationship("OrderItem", back_populates="product") 

class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True) 
    group_id = Column(String, index=True, nullable=True)
    driver_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True) 
    store_id = Column(Integer, ForeignKey("stores.id"), nullable=False, index=True) 
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    
    status = Column(Enum(OrderStatus), default=OrderStatus.pending)
    assigned_at = Column(DateTime(timezone=True), nullable=True)
    total_price = Column(Float, default=0.0)

    delivery_address = Column(String, nullable=True)
    # delivery_instructions = Column(String, nullable=True) # fix later
    
    user = relationship("User", foreign_keys=[user_id], back_populates="orders")
    driver = relationship("User", foreign_keys=[driver_id], back_populates="deliveries")
    store = relationship("Store", back_populates="orders")
    items = relationship(
        "OrderItem",
        back_populates="order",
        cascade="all, delete-orphan",
        lazy="joined"
    )

    @property
    def computed_total_price(self):
        return sum(item.price_at_purchase * item.quantity for item in self.items)

    @property
    def assignment_expired(self) -> bool:
        if self.status != OrderStatus.assigned:
            return False
        if not self.assigned_at:
            return True
        return (datetime.now(timezone.utc) - self.assigned_at) > timedelta(minutes=10)

class OrderItem(Base):
    __tablename__ = "order_items"
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), index=True)
    product_id = Column(Integer, ForeignKey("products.id"), index=True)
    quantity = Column(Integer, nullable=False)
    price_at_purchase = Column(Float, nullable=False)

    order = relationship("Order", back_populates="items")
    product = relationship("Product", back_populates="order_items")

    __table_args__ = (
        UniqueConstraint("order_id", "product_id", name="uq_order_product"),
    )

class IdempotencyKey(Base): # I think it's now obsolete since we're using Redis for idempotency
    __tablename__ = "idempotency_keys"
    key_hash = Column(String(64), primary_key=True, index=True)
    response_payload = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))