from pydantic import BaseModel, ConfigDict
from typing import Optional

class ProductBase(BaseModel):
    name: str
    price: float
    stock: int = 0

class ProductCreate(ProductBase):
    store_id: int

class ProductUpdate(BaseModel):
    name: Optional[str] = None
    price: Optional[float] = None
    stock: Optional[int] = None
    store_id: Optional[int] = None

class ProductOut(ProductBase):
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    store_id: int   # don't include the full store to avoid recursion
