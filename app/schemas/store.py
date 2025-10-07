from pydantic import BaseModel, field_validator, ConfigDict
from typing import List, Optional
from app.schemas.product import ProductOut  # import product schema

class StoreBase(BaseModel):
    name: str
    category: Optional[str] = None
    description: Optional[str] = None
    
    @field_validator('name')
    @classmethod
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
    
    @field_validator('name')
    @classmethod
    def name_must_not_be_empty(cls, v):
        if v is not None and (not v or not v.strip()):
            raise ValueError('Store name cannot be empty')
        return v

class StoreOut(StoreBase):
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    owner_id: Optional[int] = None
    products: List[ProductOut] = []   # include products
