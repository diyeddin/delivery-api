from pydantic import BaseModel
from typing import Optional

class ProductBase(BaseModel):
    name: str
    price: float
    stock: int

class ProductCreate(ProductBase):
    store_id: int

class ProductUpdate(ProductBase):
    pass

class ProductOut(ProductBase):
    id: int
    store_id: int   # don’t include the full store to avoid recursion

    class Config:
        from_attributes = True
