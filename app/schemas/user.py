# app/schemas/user.py
from pydantic import BaseModel, EmailStr, ConfigDict, Field, field_validator
from typing import Optional

class UserCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, str_strip_whitespace=True)
    email: EmailStr = Field(..., description="Valid email address")
    password: str = Field(..., min_length=8, max_length=100, description="Password must be 8-100 characters")
    name: Optional[str] = Field(None, min_length=1, max_length=100, description="User full name")
    
    @field_validator('password')
    @classmethod
    def validate_password(cls, v):
        if len(v) < 8:
            raise ValueError('Password must be at least 8 characters long')
        if not any(c.isupper() for c in v):
            raise ValueError('Password must contain at least one uppercase letter')
        if not any(c.islower() for c in v):
            raise ValueError('Password must contain at least one lowercase letter')
        if not any(c.isdigit() for c in v):
            raise ValueError('Password must contain at least one digit')
        return v
    
    @field_validator('name')
    @classmethod
    def validate_name(cls, v):
        if v is not None and (not v or not v.strip()):
            raise ValueError('Name cannot be empty or whitespace only')
        return v.strip() if v else v

class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra='forbid', frozen=True, str_strip_whitespace=True)
    
    id: int
    email: EmailStr
    name: Optional[str] = None
    role: str
    
    # Driver fields
    is_active: bool = True
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    # Optional: You can expose token if debugging, but usually private
    # notification_token: Optional[str] = None 

class UserUpdate(BaseModel):
    """Used for profile updates (Name, Email, etc.)"""
    model_config = ConfigDict(extra='forbid', frozen=True, str_strip_whitespace=True)
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    
    @field_validator('name')
    @classmethod
    def validate_name(cls, v):
        if v is not None and (not v or not v.strip()):
            raise ValueError('Name cannot be empty or whitespace only')
        return v.strip() if v else v

class PushTokenUpdate(BaseModel):
    """NEW: Schema for registering a device for push notifications"""
    token: str = Field(..., min_length=10, max_length=255, description="Expo Push Token")

class DriverLocationUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, str_strip_whitespace=True)
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    is_active: Optional[bool] = None

class Token(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, str_strip_whitespace=True)
    access_token: str
    token_type: str = "bearer"