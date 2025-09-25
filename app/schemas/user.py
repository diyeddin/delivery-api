# app/schemas/user.py
from pydantic import BaseModel, EmailStr

class UserCreate(BaseModel):
    email: EmailStr
    password: str
    name: str | None = None

class UserOut(BaseModel):
    id: int
    email: EmailStr
    name: str | None = None
    role: str  # make sure your User model has a 'role' field

    class Config:
        from_attributes = True  # <-- fix typo: should be from_attributes, not from_attributes

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
