# app/utils/dependencies.py
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.services.order_service import AsyncOrderService
from app.core import security
from app.db import models, database
from typing import List, Union

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

credentials_exception = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)

async def get_current_user(token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(database.get_db)):
    payload = security.verify_token(token)
    if not payload:
        raise credentials_exception
    email = payload.get("sub")
    if not email:
        raise credentials_exception
    from sqlalchemy import select
    result = await db.execute(select(models.User).where(models.User.email == email))
    user = result.unique().scalar_one_or_none()
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


def require_scope(required_scope: Union[str, List[str]]):
    """Dependency factory that enforces one or more required scopes.
    If a list is provided, the user must have at least ONE of the scopes (OR logic).
    """
    async def scope_checker(
        token: str = Depends(oauth2_scheme), 
        current_user: models.User = Depends(get_current_user)
    ):
        payload = security.verify_token(token)
        if not payload:
            raise credentials_exception
        
        scopes = payload.get("scopes", []) or []
        
        # 1. Admin wildcard
        if "*" in scopes:
            return current_user
        
        # 2. Handle List vs String
        if isinstance(required_scope, list):
            # OR Logic: User needs at least one of these
            if not any(s in scopes for s in required_scope):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN, 
                    detail=f"Missing one of required scopes: {required_scope}"
                )
        else:
            # Original Single String Logic
            if required_scope not in scopes:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN, 
                    detail=f"Missing scope: {required_scope}"
                )
                
        return current_user
    return scope_checker

async def verify_order_access(
    order_id: int, 
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user)
):
    """
    Ensures the user has the right to access this specific order.
    - Admins: Can access all.
    - Customers: Can access their own.
    - Store Owners: Can access ONLY if order.store_id is in their owned stores.
    """
    svc = AsyncOrderService(db)
    order = await svc.get_order(order_id, current_user) # Logic is partly inside service, but let's reinforce.
    
    if current_user.role == models.UserRole.store_owner:
        # Get user's stores
        result = await db.execute(select(models.Store.id).where(models.Store.owner_id == current_user.id))
        my_store_ids = result.scalars().all()
        
        if order.store_id not in my_store_ids:
            raise HTTPException(status_code=403, detail="Not authorized to access orders from other stores")
            
    return order

async def get_current_user_ws(token: str, db: AsyncSession) -> models.User | None:
    """
    Authenticate WebSocket connections using the query param token.
    Returns None if validation fails, instead of raising HTTPException (which breaks WebSockets).
    """
    if not token:
        return None

    # 1. Verify JWT signature using your existing core security
    payload = security.verify_token(token)
    if not payload:
        return None
    
    # 2. Extract email
    email = payload.get("sub")
    if not email:
        return None
        
    # 3. Check DB (Matches your logic in get_current_user)
    try:
        result = await db.execute(select(models.User).where(models.User.email == email))
        user = result.unique().scalar_one_or_none()
        return user
    except Exception:
        return None