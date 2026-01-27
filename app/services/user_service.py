"""
User service layer for business logic separation with Redis caching.
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional
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
    DRIVER_LOCATION_CACHE_TTL = 60  # 1 minute - locations change frequently
    
    def __init__(self, db: AsyncSession):
        self.db = db

    # --- CACHE HELPER METHODS ---
    
    async def _invalidate_user_cache(self, user_id: int, email: str = None):
        """Invalidate all cache entries related to a user."""
        keys_to_delete = [
            f"user:{user_id}",
            "users:all",
        ]
        
        if email:
            keys_to_delete.append(f"user:email:{email}")
        
        try:
            await redis_client.delete(*keys_to_delete)
        except Exception:
            pass

    async def _cache_user(self, user: models.User):
        """Cache a single user."""
        try:
            user_data = {
                "id": user.id,
                "email": user.email,
                "name": user.name,
                "role": user.role.value,
                "address": user.address,
                "phone": user.phone,
                "latitude": user.latitude,
                "longitude": user.longitude,
                "is_active": user.is_active,
                "notification_token": user.notification_token,
                "created_at": user.created_at.isoformat() if user.created_at else None,
            }
            
            # Cache by ID
            await redis_client.setex(
                f"user:{user.id}",
                self.USER_CACHE_TTL,
                json.dumps(user_data)
            )
            
            # Also cache by email for login lookups
            await redis_client.setex(
                f"user:email:{user.email}",
                self.USER_EMAIL_CACHE_TTL,
                json.dumps(user_data)
            )
        except Exception:
            pass

    async def _get_cached_user(self, user_id: int = None, email: str = None) -> Optional[dict]:
        """Get cached user data by ID or email."""
        try:
            cache_key = f"user:{user_id}" if user_id else f"user:email:{email}"
            cached = await redis_client.get(cache_key)
            if cached:
                return json.loads(cached)
        except Exception:
            pass
        return None

    async def _reconstruct_user_from_cache(self, cached_data: dict) -> models.User:
        """Reconstruct User model from cached data."""
        # Convert role string back to enum
        if "role" in cached_data:
            cached_data["role"] = models.UserRole(cached_data["role"])
        
        # Parse datetime if present
        if "created_at" in cached_data and cached_data["created_at"]:
            from datetime import datetime
            cached_data["created_at"] = datetime.fromisoformat(cached_data["created_at"])
        
        return models.User(**cached_data)

    # --- SERVICE METHODS ---

    async def get_user(self, user_id: int) -> models.User:
        """Get user by ID with caching."""
        # Try cache first
        cached_data = await self._get_cached_user(user_id=user_id)
        if cached_data:
            return self._reconstruct_user_from_cache(cached_data)
        
        # Cache miss - fetch from database
        result = await self.db.execute(select(models.User).where(models.User.id == user_id))
        user = result.unique().scalar_one_or_none()
        if not user:
            raise NotFoundError("User", user_id)
        
        # Cache the user
        await self._cache_user(user)
        
        return user

    async def get_user_by_email(self, email: str) -> Optional[models.User]:
        """Get user by email with caching - useful for login."""
        # Try cache first
        cached_data = await self._get_cached_user(email=email)
        if cached_data:
            return self._reconstruct_user_from_cache(cached_data)
        
        # Cache miss - fetch from database
        result = await self.db.execute(select(models.User).where(models.User.email == email))
        user = result.unique().scalar_one_or_none()
        
        if user:
            # Cache the user
            await self._cache_user(user)
        
        return user

    async def get_all_users(self, skip: int = 0, limit: int = 100) -> List[models.User]:
        """Get all users with pagination (admin only)."""
        # For paginated results, caching is complex, so we skip it
        # OR we could cache the first page only
        
        # If it's the first page with default limit, try cache
        if skip == 0 and limit == 100:
            try:
                cached = await redis_client.get("users:all:page1")
                if cached:
                    user_ids = json.loads(cached)
                    users = []
                    for user_id in user_ids:
                        try:
                            user = await self.get_user(user_id)
                            users.append(user)
                        except NotFoundError:
                            # User was deleted, invalidate cache
                            await redis_client.delete("users:all:page1")
                            break
                    else:
                        return users
            except Exception:
                pass
        
        # Cache miss or not first page - fetch from database
        query = select(models.User).offset(skip).limit(limit)
        result = await self.db.execute(query)
        users = result.scalars().all()
        
        # Cache first page only
        if skip == 0 and limit == 100:
            try:
                user_ids = [user.id for user in users]
                await redis_client.setex(
                    "users:all:page1",
                    self.ALL_USERS_CACHE_TTL,
                    json.dumps(user_ids)
                )
                # Cache individual users
                for user in users:
                    await self._cache_user(user)
            except Exception:
                pass
        
        return users

    async def update_user_role(self, user_id: int, role: str) -> models.User:
        """Update user role (admin only)."""
        user = await self.get_user(user_id)
        
        try:
            new_role = models.UserRole(role)
        except ValueError:
            valid_roles = [r.value for r in models.UserRole]
            raise BadRequestError(f"Invalid role. Options: {valid_roles}")
        
        user.role = new_role
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        
        # Invalidate cache
        await self._invalidate_user_cache(user_id, user.email)
        
        # Cache updated user
        await self._cache_user(user)
        
        return user

    async def update_user_profile(self, user_id: int, update_data: UserUpdate) -> models.User:
        """Update user profile."""
        user = await self.get_user(user_id)
        
        # Update fields
        if update_data.name is not None:
            user.name = update_data.name
        
        if update_data.address is not None:
            user.address = update_data.address
        
        if update_data.phone is not None:
            user.phone = update_data.phone
        
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        
        # Invalidate cache
        await self._invalidate_user_cache(user_id, user.email)
        
        # Cache updated user
        await self._cache_user(user)
        
        return user

    async def update_push_token(self, user_id: int, token: str) -> models.User:
        """Update user's push notification token."""
        user = await self.get_user(user_id)
        
        user.notification_token = token
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        
        # Invalidate cache
        await self._invalidate_user_cache(user_id, user.email)
        
        # Cache updated user
        await self._cache_user(user)
        
        return user

    async def update_driver_location(
        self, 
        user_id: int, 
        latitude: float, 
        longitude: float,
        is_active: Optional[bool] = None
    ) -> models.User:
        """Update driver location and active status."""
        # For location updates, we fetch directly from DB to avoid stale cache
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
        
        # Cache driver location separately with short TTL
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
        
        # Invalidate user cache (will refetch with new location)
        await self._invalidate_user_cache(user_id, user.email)
        
        return user

    async def get_active_drivers(self) -> List[models.User]:
        """Get all active drivers (for order assignment)."""
        # Try cache first
        try:
            cached = await redis_client.get("drivers:active")
            if cached:
                driver_ids = json.loads(cached)
                drivers = []
                for driver_id in driver_ids:
                    try:
                        driver = await self.get_user(driver_id)
                        if driver.is_active:  # Double-check they're still active
                            drivers.append(driver)
                    except NotFoundError:
                        # Driver was deleted, invalidate cache
                        await redis_client.delete("drivers:active")
                        break
                else:
                    return drivers
        except Exception:
            pass
        
        # Cache miss - fetch from database
        stmt = (
            select(models.User)
            .where(models.User.role == models.UserRole.driver)
            .where(models.User.is_active == True)
        )
        result = await self.db.execute(stmt)
        drivers = result.unique().scalars().all()
        
        # Cache active driver IDs with short TTL (status changes frequently)
        try:
            driver_ids = [driver.id for driver in drivers]
            await redis_client.setex(
                "drivers:active",
                60,  # 1 minute TTL
                json.dumps(driver_ids)
            )
            # Cache individual drivers
            for driver in drivers:
                await self._cache_user(driver)
        except Exception:
            pass
        
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
        if user.latitude and user.longitude:
            return {
                "user_id": user.id,
                "latitude": user.latitude,
                "longitude": user.longitude,
                "is_active": user.is_active
            }
        
        return None