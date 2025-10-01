# app/routers/users.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db import models, database
from app.utils.dependencies import get_current_user, require_role

router = APIRouter(prefix="/users", tags=["users"])

@router.get("/me")
def get_me(current_user: models.User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "name": current_user.name,
        "email": current_user.email,
        "role": current_user.role
        }

@router.get("/admin-only")
def admin_only_route(current_user: models.User = Depends(require_role([models.UserRole.admin]))):
    return {"message": f"Hello Admin {current_user.name}"}

@router.get("/driver-only")
def driver_route(current_user: models.User = Depends(require_role([models.UserRole.driver]))):
    return {"message": f"Hello Driver {current_user.name}"}

@router.patch("/{user_id}/role")
def update_user_role(
    user_id: int,
    role: models.UserRole,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(require_role([models.UserRole.admin]))
    ):
    if current_user.role != models.UserRole.admin:
        raise HTTPException(status_code=403, detail="Only admins can update roles")

    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.role = role
    db.commit()
    db.refresh(user)
    return user
