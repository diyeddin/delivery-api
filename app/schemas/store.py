from pydantic import BaseModel
from typing import List, Optional
from app.schemas.product import ProductOut  # import product schema

class StoreBase(BaseModel):
    name: str
    category: Optional[str] = None

class StoreCreate(StoreBase):
    pass

class StoreUpdate(StoreBase):
    pass

class StoreOut(StoreBase):
    id: int
    products: List[ProductOut] = []   # include products

    class Config:
        from_attributes = True
