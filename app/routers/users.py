# app/routers/users.py
from fastapi import APIRouter, Depends
from app.db import models
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
def admin_only_route(current_user: models.User = Depends(require_role(["admin"]))):
    return {"message": f"Hello Admin {current_user.name}"}

@router.get("/driver-only")
def driver_route(current_user: models.User = Depends(require_role(["driver"]))):
    return {"message": f"Hello Driver {current_user.name}"}
