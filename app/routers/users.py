# app/routers/users.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db import models, database
from app.utils.dependencies import get_current_user, require_scope

router = APIRouter(prefix="/users", tags=["users"])

@router.get("/me")
def get_me(current_user: models.User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "name": current_user.name,
        "email": current_user.email,
        "role": current_user.role
        }

@router.patch("/{user_id}/role")
def update_user_role(
    user_id: int,
    role: models.UserRole,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(require_scope("users:manage"))
    ):
    # scope enforcement already validated via dependency

    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.role = role
    db.commit()
    db.refresh(user)
    return user

# test endpoints for role-based access control
@router.get("/admin-only")
def admin_only_route(current_user: models.User = Depends(require_scope("users:manage"))):
    return {"message": f"Hello Admin {current_user.name}"}


@router.get("/driver-only")
def driver_route(current_user: models.User = Depends(require_scope("location:update"))):
    return {"message": f"Hello Driver {current_user.name}"}
