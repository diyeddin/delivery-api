from pydantic import BaseModel, validator
from typing import List, Optional
from app.schemas.product import ProductOut  # import product schema

class StoreBase(BaseModel):
    name: str
    category: Optional[str] = None
    
    @validator('name')
    def name_must_not_be_empty(cls, v):
        if not v or not v.strip():
            raise ValueError('Store name cannot be empty')
        return v

class StoreCreate(StoreBase):
    pass

class StoreUpdate(StoreBase):
    pass

class StoreOut(StoreBase):
    id: int
    products: List[ProductOut] = []   # include products

    class Config:
        from_attributes = True
