"""
User service layer for business logic separation with Redis caching.
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional, Union, Any
from app.db import models
from app.schemas.user import UserUpdate, PushTokenUpdate, DriverLocationUpdate
from app.utils.exceptions import NotFoundError, BadRequestError
from app.core.redis import redis_client
import json

class AsyncUserService:
    """Async user service using AsyncSession with Redis caching."""
    
    # Cache TTLs (in seconds)
    USER_CACHE_TTL = 1800  # 30 minutes - users change infrequently
    USER_EMAIL_CACHE_TTL = 1800  # 30 minutes
    ALL_USERS_CACHE_TTL = 600  # 10 minutes
    ACTIVE_DRIVERS_TTL = 10 # 10 seconds (Drivers come online/offline often)
    DRIVER_LOCATION_CACHE_TTL = 60  # 1 minute - locations change frequently
    
    def __init__(self, db: AsyncSession):
        self.db = db

    # --- CACHE HELPER METHODS ---
    
    def _serialize_user(self, user: models.User) -> dict:
        """Safe serialization of User ORM object to Dict."""
        return {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "role": user.role.value,
            "address": user.address,
            # "phone": user.phone,
            "latitude": user.latitude,
            "longitude": user.longitude,
            "is_active": user.is_active,
            "notification_token": user.notification_token,
            # "created_at": user.created_at.isoformat() if user.created_at else None,
        }

    async def _cache_set(self, key: str, data: Any, ttl: int):
        """Safe wrapper for Redis SET."""
        try:
            await redis_client.setex(key, ttl, json.dumps(data))
        except Exception:
            pass

    async def _invalidate_user_cache(self, user_id: int, email: str = None):
        """
        Invalidate user profile, email lookup, and driver lists.
        """
        keys_to_delete = [
            f"user:{user_id}",
            "users:all:page1", # Assuming we only cache page 1 for now
            "drivers:active"
        ]
        
        if email:
            keys_to_delete.append(f"user:email:{email}")
        
        try:
            await redis_client.delete(*keys_to_delete)
        except Exception:
            pass

    # --- SERVICE METHODS ---

    async def get_user(self, user_id: int) -> Union[models.User, dict]:
        """Get user by ID. Returns Dict (Cache) or Object (DB)."""
        # 1. Try Cache
        try:
            cached = await redis_client.get(f"user:{user_id}")
            if cached:
                return json.loads(cached)
        except Exception:
            pass
        
        # 2. DB Fallback
        result = await self.db.execute(select(models.User).where(models.User.id == user_id))
        user = result.unique().scalar_one_or_none()
        
        if not user:
            raise NotFoundError("User", user_id)
        
        # 3. Cache
        await self._cache_set(f"user:{user.id}", self._serialize_user(user), self.USER_CACHE_TTL)
        
        return user

    async def get_user_by_email(self, email: str) -> Union[models.User, dict, None]:
        """Get user by email - useful for login."""
        # 1. Try Cache
        try:
            cached = await redis_client.get(f"user:email:{email}")
            if cached:
                return json.loads(cached)
        except Exception:
            pass
        
        # 2. DB Fallback
        result = await self.db.execute(select(models.User).where(models.User.email == email))
        user = result.unique().scalar_one_or_none()
        
        if user:
            await self._cache_set(f"user:email:{user.email}", self._serialize_user(user), self.USER_EMAIL_CACHE_TTL)
        
        return user

    async def get_all_users(self, skip: int = 0, limit: int = 100):
        """Get all users (Admin)."""
        # Only cache the first page (standard pattern)
        is_first_page = (skip == 0 and limit == 100)

        if is_first_page:
            try:
                cached = await redis_client.get("users:all:page1")
                if cached:
                    return json.loads(cached) # Return full list immediately
            except Exception:
                pass
        
        # DB Fetch
        query = select(models.User).offset(skip).limit(limit)
        result = await self.db.execute(query)
        users = result.scalars().all()
        
        # Cache First Page
        if is_first_page:
            serialized_list = [self._serialize_user(u) for u in users]
            await self._cache_set("users:all:page1", serialized_list, self.ALL_USERS_CACHE_TTL)
        
        return users

    async def update_user_role(self, user_id: int, role: str) -> models.User:
        """Update user role (admin only)."""
        # Fetch fresh object for locking
        result = await self.db.execute(select(models.User).where(models.User.id == user_id))
        user = result.unique().scalar_one_or_none()
        if not user:
            raise NotFoundError("User", user_id)
        
        try:
            new_role = models.UserRole(role)
        except ValueError:
            valid_roles = [r.value for r in models.UserRole]
            raise BadRequestError(f"Invalid role. Options: {valid_roles}")
        
        user.role = new_role
        await self.db.commit()
        await self.db.refresh(user)
        
        await self._invalidate_user_cache(user_id, user.email)
        return user

    async def update_user_profile(self, user_id: int, update_data: UserUpdate) -> models.User:
        """Update user profile."""
        result = await self.db.execute(select(models.User).where(models.User.id == user_id))
        user = result.unique().scalar_one_or_none()
        if not user:
            raise NotFoundError("User", user_id)
        
        if update_data.name is not None:
            user.name = update_data.name
        if update_data.address is not None:
            user.address = update_data.address
        # if update_data.phone is not None:
        #     user.phone = update_data.phone
        
        await self.db.commit()
        await self.db.refresh(user)
        
        await self._invalidate_user_cache(user_id, user.email)
        return user

    async def update_push_token(self, user_id: int, token: str) -> models.User:
        result = await self.db.execute(select(models.User).where(models.User.id == user_id))
        user = result.unique().scalar_one_or_none()
        if not user:
            raise NotFoundError("User", user_id)
        
        user.notification_token = token
        await self.db.commit()
        await self.db.refresh(user)
        
        await self._invalidate_user_cache(user_id, user.email)
        return user

    async def update_driver_location(
        self, 
        user_id: int, 
        latitude: float, 
        longitude: float,
        is_active: Optional[bool] = None
    ) -> models.User:
        """Update driver location."""
        result = await self.db.execute(select(models.User).where(models.User.id == user_id))
        user = result.unique().scalar_one_or_none()
        if not user:
            raise NotFoundError("User", user_id)
        
        user.latitude = latitude
        user.longitude = longitude
        
        if is_active is not None:
            user.is_active = is_active
        
        try:
            await self.db.commit()
            await self.db.refresh(user)
        except Exception as e:
            await self.db.rollback()
            raise e
        
        # Cache purely the location data (Lightweight)
        try:
            location_data = {
                "user_id": user_id,
                "latitude": latitude,
                "longitude": longitude,
                "is_active": user.is_active
            }
            await redis_client.setex(
                f"driver:location:{user_id}",
                self.DRIVER_LOCATION_CACHE_TTL,
                json.dumps(location_data)
            )
        except Exception:
            pass
        
        # Note: We do NOT invalidate the full user profile cache here.
        # Why? Because GPS updates happen every 3 seconds. 
        # If we invalidated 'user:{id}' every 3s, we'd destroy the cache hit rate for profile info.
        
        return user

    async def get_active_drivers(self):
        """Get all active drivers (for order assignment)."""
        # 1. Try Cache (Full List)
        try:
            cached = await redis_client.get("drivers:active")
            if cached:
                return json.loads(cached)
        except Exception:
            pass
        
        # 2. DB Fallback
        stmt = (
            select(models.User)
            .where(models.User.role == models.UserRole.driver)
            .where(models.User.is_active == True)
        )
        result = await self.db.execute(stmt)
        drivers = result.unique().scalars().all()
        
        # 3. Serialize & Cache
        serialized_list = [self._serialize_user(d) for d in drivers]
        await self._cache_set("drivers:active", serialized_list, self.ACTIVE_DRIVERS_TTL)
        
        return drivers

    async def get_driver_location(self, driver_id: int) -> Optional[dict]:
        """Get cached driver location (fast lookup)."""
        try:
            cached = await redis_client.get(f"driver:location:{driver_id}")
            if cached:
                return json.loads(cached)
        except Exception:
            pass
        
        # Fallback to database
        user = await self.get_user(driver_id)
        # Handle if we got a dict back from get_user
        if isinstance(user, dict):
            if user.get("latitude") and user.get("longitude"):
                return {
                    "user_id": user["id"],
                    "latitude": user["latitude"],
                    "longitude": user["longitude"],
                    "is_active": user["is_active"]
                }
        else:
            if user.latitude and user.longitude:
                return {
                    "user_id": user.id,
                    "latitude": user.latitude,
                    "longitude": user.longitude,
                    "is_active": user.is_active
                }
        
        return None