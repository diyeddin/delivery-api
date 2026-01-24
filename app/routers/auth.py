# app/routers/auth.py
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from app.db import models, database
from app.schemas.user import UserCreate, UserOut
from app.core import security
from app.core.logging import get_logger, log_auth_event

router = APIRouter(prefix="/auth", tags=["auth"])
logger = get_logger(__name__)

@router.post("/register", response_model=UserOut)
def register(user: UserCreate, db: Session = Depends(database.get_db)):
    logger.info("User registration attempt", email=user.email)
    
    db_user = db.query(models.User).filter(models.User.email == user.email).first()
    if db_user:
        log_auth_event("registration", user.email, success=False, reason="email_already_exists")
        raise HTTPException(status_code=400, detail="Email already registered")
    
    hashed = security.hash_password(user.password)
    new_user = models.User(name=user.name, email=user.email, hashed_password=hashed)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    log_auth_event("registration", user.email, success=True, user_id=new_user.id)
    logger.info("User registered successfully", user_id=new_user.id, email=user.email)
    
    return new_user

@router.post("/login")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(database.get_db)):
    logger.info("Login attempt", email=form_data.username)
    
    user = db.query(models.User).filter(models.User.email == form_data.username).first()
    if not user or not security.verify_password(form_data.password, user.hashed_password):
        log_auth_event("login", form_data.username, success=False, reason="invalid_credentials")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    
    token = security.create_access_token({"sub": user.email, "role": user.role.value})
    log_auth_event("login", user.email, success=True, user_id=user.id)
    logger.info("User logged in successfully", user_id=user.id, email=user.email)
    
    return {"access_token": token, "token_type": "bearer"}
