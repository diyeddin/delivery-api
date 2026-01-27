# app/routers/users.py
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import models, database
from app.utils.dependencies import get_current_user, require_scope
from app.schemas import user as user_schema
from app.schemas.user import UserUpdate, PushTokenUpdate # <--- Import new schema
from pydantic import BaseModel

router = APIRouter(prefix="/users", tags=["users"])

# --- 1. ADMIN: List All Users ---
@router.get("/", response_model=List[user_schema.UserOut])
async def get_all_users(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_scope("users:manage")) 
):
    query = select(models.User).offset(skip).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


# --- 2. ADMIN: Update User Role ---
class RoleUpdate(BaseModel):
    role: str

@router.put("/{user_id}/role", response_model=user_schema.UserOut)
async def update_user_role(
    user_id: int,
    role_data: RoleUpdate,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_scope("users:manage"))
):
    result = await db.execute(select(models.User).where(models.User.id == user_id))
    user = result.unique().scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    try:
        new_role = models.UserRole(role_data.role)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid role. Options: {[r.value for r in models.UserRole]}")

    user.role = new_role
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


# --- 3. STANDARD: Get Me ---
@router.get("/me", response_model=user_schema.UserOut)
async def get_me(current_user: models.User = Depends(get_current_user)):
    return current_user

# --- 4. STANDARD: Update Me ---
@router.put("/me", response_model=user_schema.UserOut)
async def update_my_profile(
    payload: UserUpdate,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user)
):
    if payload.name:
        current_user.name = payload.name
    
    db.add(current_user)
    await db.commit()
    await db.refresh(current_user)
    return current_user

# --- NEW: Update Push Token ---
@router.post("/me/push-token", status_code=status.HTTP_200_OK)
async def update_push_token(
    payload: PushTokenUpdate,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user)
):
    """
    Saves the Expo Push Token for the current user. 
    This allows the backend to send notifications.
    """
    current_user.notification_token = payload.token
    db.add(current_user)
    await db.commit()
    return {"message": "Token updated successfully"}

# --- 5. DRIVER: Update Location ---
@router.patch("/me/location", response_model=user_schema.UserOut)
async def update_driver_location(
    location_data: user_schema.DriverLocationUpdate,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_scope("location:update"))
):
    current_user.latitude = location_data.latitude
    current_user.longitude = location_data.longitude
    
    if location_data.is_active is not None:
        current_user.is_active = location_data.is_active

    try:
        await db.commit()
        await db.refresh(current_user)
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update location"
        )

    return current_user

# --- Test Endpoints ---
@router.get("/admin-only")
async def admin_only_route(current_user: models.User = Depends(require_scope("users:manage"))):
    return {"message": f"Hello Admin {current_user.name}"}

@router.get("/driver-only")
async def driver_route(current_user: models.User = Depends(require_scope("location:update"))):
    return {"message": f"Hello Driver {current_user.name}"}