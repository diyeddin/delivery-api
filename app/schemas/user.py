# app/schemas/user.py
from pydantic import BaseModel, EmailStr, ConfigDict

class UserCreate(BaseModel):
    email: EmailStr
    password: str
    name: str | None = None

class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    email: EmailStr
    name: str | None = None
    role: str  # make sure your User model has a 'role' field

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
