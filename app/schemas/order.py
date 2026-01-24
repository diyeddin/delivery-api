from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import List, Optional

class OrderItemCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, str_strip_whitespace=True)
    product_id: int = Field(..., gt=0, description="Product ID must be positive")
    quantity: int = Field(..., gt=0, le=100, description="Quantity must be positive and not exceed 100")

class OrderCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, str_strip_whitespace=True)
    items: List[OrderItemCreate] = Field(..., min_length=1, max_length=20, description="Order must have 1-20 items")
    
    @field_validator('items')
    @classmethod
    def validate_unique_products(cls, v):
        """Ensure no duplicate products in the same order."""
        product_ids = [item.product_id for item in v]
        if len(product_ids) != len(set(product_ids)):
            raise ValueError('Duplicate products are not allowed in the same order')
        return v

class OrderItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra='forbid', frozen=True, str_strip_whitespace=True)
    
    id: int
    product_id: int
    quantity: int
    price_at_purchase: float

class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra='forbid', frozen=True, str_strip_whitespace=True)
    
    id: int
    user_id: int
    driver_id: Optional[int] = None
    status: str
    total_price: float = Field(..., ge=0, description="Total price must be non-negative")
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
