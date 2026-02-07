from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

class ReviewCreate(BaseModel):
    # 👇 Added strict validation (1-5 stars only)
    rating: int = Field(..., ge=1, le=5, description="Rating must be between 1 and 5")
    comment: Optional[str] = None

class ReviewOut(BaseModel):
    id: int
    rating: int
    comment: Optional[str]
    created_at: datetime
    user_name: str 

    class Config:
        orm_mode = True