# app/routers/users.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import models, database
from app.utils.dependencies import get_current_user, require_scope
from app.schemas import user as user_schema

router = APIRouter(prefix="/users", tags=["users"])

@router.get("/me", response_model=user_schema.UserOut)
async def get_me(current_user: models.User = Depends(get_current_user)):
    # Pydantic's 'from_attributes=True' will handle mapping the model to the schema,
    # including the new latitude/longitude fields.
    return current_user

@router.patch("/me/location", response_model=user_schema.UserOut)
async def update_driver_location(
    location_data: user_schema.DriverLocationUpdate,
    db: AsyncSession = Depends(database.get_db),
    # Critical: Only drivers (or those with this scope) can hit this.
    current_user: models.User = Depends(require_scope("location:update"))
):
    """
    High-frequency endpoint for drivers to update their GPS coordinates and availability.
    """
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

@router.patch("/{user_id}/role", response_model=user_schema.UserOut)
async def update_user_role(
    user_id: int,
    role: models.UserRole,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_scope("users:manage"))
):
    result = await db.execute(select(models.User).where(models.User.id == user_id))
    user = result.unique().scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.role = role
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user

# Test endpoints
@router.get("/admin-only")
async def admin_only_route(current_user: models.User = Depends(require_scope("users:manage"))):
    return {"message": f"Hello Admin {current_user.name}"}

@router.get("/driver-only")
async def driver_route(current_user: models.User = Depends(require_scope("location:update"))):
    return {"message": f"Hello Driver {current_user.name}"}
