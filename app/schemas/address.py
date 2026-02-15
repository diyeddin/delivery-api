from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Optional

# 1. Base contains ONLY shared fields (Validation rules apply to Input)
class AddressBase(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    
    label: str = Field("Home", min_length=1, max_length=50)
    # 👇 Changed min_length to 3 so "test" or "Apt" works
    address_line: str = Field(..., min_length=3, max_length=255)
    instructions: Optional[str] = Field(None, max_length=255)
    
    # 👇 Add validation ranges here directly!
    latitude: Optional[float] = Field(None, ge=-90, le=90)  # ge=Greater/Equal, le=Less/Equal
    longitude: Optional[float] = Field(None, ge=-180, le=180)
    
    is_default: bool = False

# 2. Create inherits Base (Clean, no created_at)
class AddressCreate(AddressBase):
    pass

# 3. Update is usually different (Everything optional)
class AddressUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    
    label: Optional[str] = Field(None, min_length=1, max_length=50)
    address_line: Optional[str] = Field(None, min_length=3, max_length=255)
    instructions: Optional[str] = Field(None, max_length=255)
    is_default: Optional[bool] = None
    latitude: Optional[float] = Field(None, ge=-90, le=90)
    longitude: Optional[float] = Field(None, ge=-180, le=180)

# 4. Out inherits Base AND adds DB-only fields
class AddressOut(AddressBase):
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    user_id: int
    created_at: datetime  # 👈 Now strictly an Output field