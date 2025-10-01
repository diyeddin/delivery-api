from sqlalchemy import Column, Integer, String, Float, ForeignKey, Enum, UniqueConstraint
from sqlalchemy.orm import relationship
from app.db.database import Base
import enum

class OrderStatus(str, enum.Enum):
    pending = "pending"
    in_progress = "in_progress"
    delivered = "delivered"

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
    hashed_password = Column(String, nullable=False)  # renamed
    address = Column(String, nullable=True)
    role = Column(Enum(UserRole), default=UserRole.customer)

    stores = relationship("Store", back_populates="owner")
    orders = relationship("Order", back_populates="user")
    deliveries = relationship("Order", foreign_keys="Order.driver_id", back_populates="driver")

class Store(Base):
    __tablename__ = "stores"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    category = Column(String)
    description = Column(String, nullable=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    owner = relationship("User", back_populates="stores")
    products = relationship("Product", back_populates="store", cascade="all, delete-orphan")

class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True, index=True)
    store_id = Column(Integer, ForeignKey("stores.id"), nullable=False)
    name = Column(String, nullable=False)
    price = Column(Float, nullable=False)
    stock = Column(Integer, default=0)

    store = relationship("Store", back_populates="products")

class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id")) # customer
    driver_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # driver
    status = Column(Enum(OrderStatus), default=OrderStatus.pending)
    total_price = Column(Float, default=0.0) # optional, can be computed

    user = relationship("User", foreign_keys=[user_id], back_populates="orders")
    driver = relationship("User", foreign_keys=[driver_id])
    items = relationship(
        "OrderItem",
        back_populates="order",
        cascade="all, delete-orphan",
        lazy="joined"
        )
    
    @property
    def computed_total_price(self):
        return sum(item.price_at_purchase * item.quantity for item in self.items)

class OrderItem(Base):
    __tablename__ = "order_items"
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"))
    product_id = Column(Integer, ForeignKey("products.id"))
    quantity = Column(Integer, nullable=False)
    price_at_purchase = Column(Float, nullable=False)

    order = relationship("Order", back_populates="items")
    product = relationship("Product")

    __table_args__ = (
        UniqueConstraint("order_id", "product_id", name="uq_order_product"),
        )
