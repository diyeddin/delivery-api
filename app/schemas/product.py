from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Optional

class ProductBase(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, str_strip_whitespace=True)
    
    name: str = Field(..., min_length=1, max_length=200, description="Product name")
    # ADDED: This was missing, causing the crash because smoke_test sends it
    description: Optional[str] = Field(None, description="Product description")
    
    price: float = Field(..., gt=0, description="Product price must be positive")
    stock: int = Field(default=0, ge=0, description="Stock quantity must be non-negative")
    
    @field_validator('name')
    @classmethod
    def validate_name(cls, v):
        if not v or not v.strip():
            raise ValueError('Product name cannot be empty or whitespace only')
        return v.strip()

class ProductCreate(ProductBase):
    model_config = ConfigDict(extra='forbid', frozen=True, str_strip_whitespace=True)
    store_id: int = Field(..., gt=0, description="Store ID must be positive")

class ProductUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, str_strip_whitespace=True)
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None) # Added here too
    price: Optional[float] = Field(None, gt=0)
    stock: Optional[int] = Field(None, ge=0)
    # Usually we don't allow moving a product to a different store via Update, 
    # but if you want to, keep this. Otherwise remove it.
    store_id: Optional[int] = Field(None, gt=0) 
    
    @field_validator('name')
    @classmethod
    def validate_name(cls, v):
        if v is not None and (not v or not v.strip()):
            raise ValueError('Product name cannot be empty or whitespace only')
        return v.strip() if v else v

class ProductOut(ProductBase):
    model_config = ConfigDict(from_attributes=True, extra='ignore', frozen=True)
    
    id: int
    store_id: int