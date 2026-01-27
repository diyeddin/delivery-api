# app/routers/users.py
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import models, database
from app.utils.dependencies import get_current_user, require_scope
from app.schemas import user as user_schema
from app.schemas.user import UserUpdate, PushTokenUpdate
from app.services.user_service import AsyncUserService
from app.utils.exceptions import NotFoundError, BadRequestError
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
    """Get all users with pagination (admin only)."""
    user_service = AsyncUserService(db)
    users = await user_service.get_all_users(skip=skip, limit=limit)
    return users


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
    """Update a user's role (admin only)."""
    user_service = AsyncUserService(db)
    
    try:
        user = await user_service.update_user_role(user_id, role_data.role)
        return user
    except NotFoundError:
        raise HTTPException(status_code=404, detail="User not found")
    except BadRequestError as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- 3. STANDARD: Get Me ---
@router.get("/me", response_model=user_schema.UserOut)
async def get_me(current_user: models.User = Depends(get_current_user)):
    """Get current user's profile."""
    return current_user


# --- 4. STANDARD: Update Me ---
@router.put("/me", response_model=user_schema.UserOut)
async def update_my_profile(
    payload: UserUpdate,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Update current user's profile."""
    user_service = AsyncUserService(db)
    
    try:
        user = await user_service.update_user_profile(current_user.id, payload)
        return user
    except NotFoundError:
        raise HTTPException(status_code=404, detail="User not found")


# --- 5. NEW: Update Push Token ---
@router.post("/me/push-token", status_code=status.HTTP_200_OK)
async def update_push_token(
    payload: PushTokenUpdate,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user)
):
    """
    Save the Expo Push Token for the current user. 
    This allows the backend to send notifications.
    """
    user_service = AsyncUserService(db)
    
    try:
        await user_service.update_push_token(current_user.id, payload.token)
        return {"message": "Token updated successfully"}
    except NotFoundError:
        raise HTTPException(status_code=404, detail="User not found")


# --- 6. DRIVER: Update Location ---
@router.patch("/me/location", response_model=user_schema.UserOut)
async def update_driver_location(
    location_data: user_schema.DriverLocationUpdate,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_scope("location:update"))
):
    """Update driver's current location and active status."""
    user_service = AsyncUserService(db)
    
    try:
        user = await user_service.update_driver_location(
            user_id=current_user.id,
            latitude=location_data.latitude,
            longitude=location_data.longitude,
            is_active=location_data.is_active
        )
        return user
    except NotFoundError:
        raise HTTPException(status_code=404, detail="User not found")
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update location"
        )


# --- 7. NEW: Get Active Drivers (for order assignment) ---
@router.get("/drivers/active", response_model=List[user_schema.UserOut])
async def get_active_drivers(
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Get all currently active drivers (for customers to see availability)."""
    user_service = AsyncUserService(db)
    drivers = await user_service.get_active_drivers()
    return drivers


# --- Test Endpoints ---
@router.get("/admin-only")
async def admin_only_route(current_user: models.User = Depends(require_scope("users:manage"))):
    return {"message": f"Hello Admin {current_user.name}"}

@router.get("/driver-only")
async def driver_route(current_user: models.User = Depends(require_scope("location:update"))):
    return {"message": f"Hello Driver {current_user.name}"}