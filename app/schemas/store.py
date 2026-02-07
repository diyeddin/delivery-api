from pydantic import BaseModel, field_validator, ConfigDict, Field
from typing import List, Optional

# Avoid circular imports
from app.schemas.product import ProductOut

class StoreBase(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, str_strip_whitespace=True)
    name: str
    category: Optional[str] = None
    description: Optional[str] = None
    image_url: Optional[str] = None
    banner_url: Optional[str] = None
    
    latitude: Optional[float] = Field(None, ge=-90, le=90)
    longitude: Optional[float] = Field(None, ge=-180, le=180)
    
    @field_validator('name')
    @classmethod
    def name_must_not_be_empty(cls, v):
        if not v or not v.strip():
            raise ValueError('Store name cannot be empty')
        return v

class StoreCreate(StoreBase):
    model_config = ConfigDict(extra='forbid', frozen=True, str_strip_whitespace=True)

class StoreUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, str_strip_whitespace=True)
    name: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    image_url: Optional[str] = None
    banner_url: Optional[str] = None
    latitude: Optional[float] = Field(None, ge=-90, le=90)
    longitude: Optional[float] = Field(None, ge=-180, le=180)
    
    @field_validator('name')
    @classmethod
    def name_must_not_be_empty(cls, v):
        if v is not None and (not v or not v.strip()):
            raise ValueError('Store name cannot be empty')
        return v

# 👇 UPDATED: Used for the Main List (Store Grid)
class StoreListOut(StoreBase):
    id: int
    owner_id: int
    # 👇 NEW FIELDS
    rating: Optional[float] = 0.0
    review_count: Optional[int] = 0

# 👇 UPDATED: Used for Details Screen
class StoreOut(StoreBase):
    model_config = ConfigDict(from_attributes=True, extra='ignore', frozen=True)
    
    id: int
    owner_id: Optional[int] = None
    # 👇 NEW FIELDS
    rating: Optional[float] = 0.0
    review_count: Optional[int] = 0
    
    products: List[ProductOut] = []

class StoreSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra='ignore', frozen=True)
    
    id: int
    name: str
    image_url: Optional[str] = None
    # Optional: Add here if you want ratings in the "Active Order" widget
    rating: Optional[float] = 0.0