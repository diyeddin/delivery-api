from pydantic import BaseModel
from typing import List, Optional

class OrderItemCreate(BaseModel):
    product_id: int
    quantity: int

class OrderCreate(BaseModel):
    items: List[OrderItemCreate]

class OrderItemOut(BaseModel):
    id: int
    product_id: int
    quantity: int
    price_at_purchase: float

    class Config:
        from_attributes = True

class OrderOut(BaseModel):
    id: int
    user_id: int
    driver_id: Optional[int] = None  # Make driver_id optional
    status: str
    total_price: float
    items: List[OrderItemOut]

    class Config:
        from_attributes = True
