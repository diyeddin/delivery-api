from pydantic import BaseModel, ConfigDict, Field
from typing import Optional

class AddressBase(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    
    label: str = Field("Home", min_length=1, max_length=50)
    address_line: str = Field(..., min_length=5, max_length=255)
    instructions: Optional[str] = Field(None, max_length=255)
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    is_default: bool = False
    created_at: Optional[str] = None

class AddressCreate(AddressBase):
    pass

class AddressUpdate(BaseModel):
    label: Optional[str] = None
    address_line: Optional[str] = None
    instructions: Optional[str] = None
    is_default: Optional[bool] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None

class AddressOut(AddressBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int