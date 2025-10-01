from pydantic import BaseModel, validator
from typing import List, Optional
from app.schemas.product import ProductOut  # import product schema

class StoreBase(BaseModel):
    name: str
    category: Optional[str] = None
    description: Optional[str] = None
    
    @validator('name')
    def name_must_not_be_empty(cls, v):
        if not v or not v.strip():
            raise ValueError('Store name cannot be empty')
        return v

class StoreCreate(StoreBase):
    # owner_id will be set automatically from the current user
    pass

class StoreUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    
    @validator('name')
    def name_must_not_be_empty(cls, v):
        if v is not None and (not v or not v.strip()):
            raise ValueError('Store name cannot be empty')
        return v

class StoreOut(StoreBase):
    id: int
    owner_id: Optional[int] = None
    products: List[ProductOut] = []   # include products

    class Config:
        from_attributes = True
