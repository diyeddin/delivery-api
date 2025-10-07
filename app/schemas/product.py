from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Optional

class ProductBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=200, description="Product name")
    price: float = Field(..., gt=0, description="Product price must be positive")
    stock: int = Field(default=0, ge=0, description="Stock quantity must be non-negative")
    
    @field_validator('name')
    @classmethod
    def validate_name(cls, v):
        if not v or not v.strip():
            raise ValueError('Product name cannot be empty or whitespace only')
        return v.strip()

class ProductCreate(ProductBase):
    store_id: int = Field(..., gt=0, description="Store ID must be positive")

class ProductUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    price: Optional[float] = Field(None, gt=0)
    stock: Optional[int] = Field(None, ge=0)
    store_id: Optional[int] = Field(None, gt=0)
    
    @field_validator('name')
    @classmethod
    def validate_name(cls, v):
        if v is not None and (not v or not v.strip()):
            raise ValueError('Product name cannot be empty or whitespace only')
        return v.strip() if v else v

class ProductOut(ProductBase):
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    store_id: int   # don't include the full store to avoid recursion
