from pydantic import BaseModel, field_validator, ConfigDict, Field
from typing import List, Optional
from app.schemas.product import ProductOut  # import product schema

class StoreBase(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, str_strip_whitespace=True)
    name: str
    category: Optional[str] = None
    description: Optional[str] = None
    # NEW: Location fields
    latitude: Optional[float] = Field(None, ge=-90, le=90)
    longitude: Optional[float] = Field(None, ge=-180, le=180)
    
    @field_validator('name')
    @classmethod
    def name_must_not_be_empty(cls, v):
        if not v or not v.strip():
            raise ValueError('Store name cannot be empty')
        return v

class StoreCreate(StoreBase):
    # owner_id will be set automatically from the current user
    model_config = ConfigDict(extra='forbid', frozen=True, str_strip_whitespace=True)
    pass

class StoreUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, str_strip_whitespace=True)
    name: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    latitude: Optional[float] = Field(None, ge=-90, le=90)
    longitude: Optional[float] = Field(None, ge=-180, le=180)
    
    @field_validator('name')
    @classmethod
    def name_must_not_be_empty(cls, v):
        if v is not None and (not v or not v.strip()):
            raise ValueError('Store name cannot be empty')
        return v

class StoreOut(StoreBase):
    model_config = ConfigDict(from_attributes=True, extra='forbid', frozen=True, str_strip_whitespace=True)
    
    id: int
    owner_id: Optional[int] = None
    products: List[ProductOut] = []   # include products