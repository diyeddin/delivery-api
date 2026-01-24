# app/utils/dependencies.py
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from app.core import security
from app.db import models, database
from typing import List
from fastapi import Depends

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

credentials_exception = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(database.get_db)):
    payload = security.verify_token(token)
    if not payload:
        raise credentials_exception
    email = payload.get("sub")
    if not email:
        raise credentials_exception
    user = db.query(models.User).filter(models.User.email == email).first()
    if not user:
        raise credentials_exception
    return user

def require_role(allowed_roles: List[models.UserRole]):
    def role_checker(current_user: models.User = Depends(get_current_user)):
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access forbidden. Requires one of: {', '.join([r.value for r in allowed_roles])}"
            )
        return current_user
    return role_checker


def require_scope(required_scope: str):
    """Dependency factory that enforces a single required scope.

    Usage: Depends(require_scope('orders:update_status'))
    """
    def scope_checker(token: str = Depends(oauth2_scheme), current_user: models.User = Depends(get_current_user)):
        payload = security.verify_token(token)
        if not payload:
            raise credentials_exception
        scopes = payload.get("scopes", []) or []
        # admin wildcard
        if "*" in scopes:
            return current_user
        if required_scope not in scopes:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Missing scope: {required_scope}")
        return current_user
    return scope_checker
