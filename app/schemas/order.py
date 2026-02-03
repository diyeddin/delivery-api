from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import List, Optional
from datetime import datetime
from app.schemas.store import StoreSummary

class OrderItemCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, str_strip_whitespace=True)
    product_id: int = Field(..., gt=0, description="Product ID must be positive")
    quantity: int = Field(..., gt=0, le=100, description="Quantity must be positive and not exceed 100")

class OrderCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, str_strip_whitespace=True)
    items: List[OrderItemCreate] = Field(..., min_length=1, max_length=20, description="Order must have 1-20 items")
    
    # Existing Field
    delivery_address: Optional[str] = Field(None, min_length=5, max_length=255, description="Delivery address if different from profile")
    
    # 👇 NEW FIELDS
    payment_method: str = Field("cash", pattern="^(cash|transfer)$", description="Payment method: 'cash' or 'transfer'")
    note: Optional[str] = Field(None, max_length=500, description="Delivery instructions")
    
    # Store ID is usually inferred from products, but allowed if passed explicitly
    store_id: Optional[int] = None

    @field_validator('items')
    @classmethod
    def validate_unique_products(cls, v):
        """Ensure no duplicate products in the same order."""
        product_ids = [item.product_id for item in v]
        if len(product_ids) != len(set(product_ids)):
            raise ValueError('Duplicate products are not allowed in the same order')
        return v

class ProductSummary(BaseModel):
    id: int
    name: str
    image_url: Optional[str] = None
    class Config:
        from_attributes = True

class OrderItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra='forbid', frozen=True, str_strip_whitespace=True)
    id: int
    product_id: int
    quantity: int
    price_at_purchase: float
    product: Optional[ProductSummary] = None

class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra='forbid', frozen=True, str_strip_whitespace=True)
    
    id: int
    user_id: int
    group_id: Optional[str] = None
    store_id: int 
    driver_id: Optional[int] = None
    status: str
    total_price: float = Field(..., ge=0, description="Total price must be non-negative")
    created_at: datetime
    assigned_at: Optional[datetime] = None 
    store: Optional['StoreSummary'] = None
    
    delivery_address: Optional[str] = None
    
    # 👇 NEW FIELDS IN RESPONSE
    payment_method: str = "cash"
    note: Optional[str] = None
    
    items: List[OrderItemOut] = Field(..., min_length=1, description="Order must have at least one item")

class OrderStatusUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, str_strip_whitespace=True)
    status: str = Field(..., description="New order status")
    
    @field_validator('status')
    @classmethod
    def validate_status(cls, v):
        from app.db.models import OrderStatus
        try:
            OrderStatus(v)
        except ValueError:
            valid_statuses = [status.value for status in OrderStatus]
            raise ValueError(f'Invalid status. Must be one of: {", ".join(valid_statuses)}')
        return v