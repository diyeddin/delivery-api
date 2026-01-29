from pydantic import BaseModel, field_validator, ConfigDict, Field
from typing import List, Optional, ForwardRef

# Avoid circular imports by using a string forward reference if needed, 
# or import inside the class if strictly necessary. 
# For now, we assume ProductOut is safe, but we define the list default carefully.
from app.schemas.product import ProductOut

class StoreBase(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, str_strip_whitespace=True)
    name: str
    category: Optional[str] = None
    description: Optional[str] = None
    image_url: Optional[str] = None
    banner_url: Optional[str] = None
    
    # Validation: Coordinates are optional but must be valid if provided
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

class StoreOut(StoreBase):
    model_config = ConfigDict(from_attributes=True, extra='ignore', frozen=True)
    
    id: int
    owner_id: Optional[int] = None
    # We default to empty list to handle cases where products aren't eager loaded
    products: List[ProductOut] = []