# app/routers/auth.py
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import models, database
from app.schemas.user import UserCreate, UserOut
from app.core import security
from app.core.logging import get_logger, log_auth_event

router = APIRouter(prefix="/auth", tags=["auth"])
logger = get_logger(__name__)

@router.post("/signup", response_model=UserOut)
async def signup(user: UserCreate, db: AsyncSession = Depends(database.get_db)):
    logger.info("User registration attempt", email=user.email)

    # 1. Check if email exists
    result = await db.execute(select(models.User).where(models.User.email == user.email))
    db_user = result.unique().scalar_one_or_none()
    if db_user:
        log_auth_event("registration", user.email, success=False, reason="email_already_exists")
        raise HTTPException(status_code=400, detail="Email already registered")

    hashed = security.hash_password(user.password)
    
    # 2. Create User with Explicit 'customer' Role
    new_user = models.User(
        name=user.name, 
        email=user.email, 
        hashed_password=hashed,
        role=models.UserRole.customer, # <--- EXPLICITLY SET THIS
        is_active=True
    )
    
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    log_auth_event("registration", user.email, success=True, user_id=new_user.id)
    logger.info("User registered successfully", user_id=new_user.id, email=user.email)

    return new_user

@router.post("/login")
async def login(form_data: OAuth2PasswordRequestForm = Depends(), db: AsyncSession = Depends(database.get_db)):
    logger.info("Login attempt", email=form_data.username)

    result = await db.execute(select(models.User).where(models.User.email == form_data.username))
    user = result.unique().scalar_one_or_none()
    if not user or not security.verify_password(form_data.password, user.hashed_password):
        log_auth_event("login", form_data.username, success=False, reason="invalid_credentials")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    # Includes Role in the Token
    token = security.create_access_token({"sub": user.email, "role": user.role.value, "name": user.name, "id": user.id})
    log_auth_event("login", user.email, success=True, user_id=user.id)
    logger.info("User logged in successfully", user_id=user.id, email=user.email)

    return {"access_token": token, "token_type": "bearer"}