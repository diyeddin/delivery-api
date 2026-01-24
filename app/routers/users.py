# app/routers/users.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import models, database
from app.utils.dependencies import get_current_user, require_scope

router = APIRouter(prefix="/users", tags=["users"])

@router.get("/me")
async def get_me(current_user: models.User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "name": current_user.name,
        "email": current_user.email,
        "role": current_user.role
        }

@router.patch("/{user_id}/role")
@router.patch("/{user_id}/role")
async def update_user_role(
    user_id: int,
    role: models.UserRole,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_scope("users:manage"))
    ):
    # scope enforcement already validated via dependency
    result = await db.execute(select(models.User).where(models.User.id == user_id))
    user = result.unique().scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.role = role
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user

# test endpoints for role-based access control
@router.get("/admin-only")
async def admin_only_route(current_user: models.User = Depends(require_scope("users:manage"))):
    return {"message": f"Hello Admin {current_user.name}"}


@router.get("/driver-only")
async def driver_route(current_user: models.User = Depends(require_scope("location:update"))):
    return {"message": f"Hello Driver {current_user.name}"}
