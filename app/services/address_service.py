"""
Address service layer for business logic separation with Redis caching.
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select, update
from typing import List, Optional, Union, Any
from app.db import models
from app.schemas.address import AddressCreate, AddressUpdate
from app.utils.exceptions import NotFoundError
from app.core.redis import redis_client
import json

class AsyncAddressService:
    """Async address service using AsyncSession with Redis caching."""
    
    # Cache TTLs (in seconds)
    ADDRESS_CACHE_TTL = 3600  # 60 minutes
    USER_ADDRESSES_CACHE_TTL = 1800  # 30 minutes
    
    def __init__(self, db: AsyncSession):
        self.db = db

    # --- HELPER: Handle Dict vs Object ---
    def _get_attr(self, obj: Union[dict, Any], key: str):
        """Safely get attribute from either Dict (Cache) or Object (DB)."""
        if isinstance(obj, dict):
            return obj.get(key)
        return getattr(obj, key)

    # --- CACHE HELPERS ---

    def _serialize_address(self, address: models.Address) -> dict:
        """Safe serialization of Address ORM object to Dict."""
        return {
            "id": self._get_attr(address, "id"),
            "user_id": self._get_attr(address, "user_id"),
            "label": self._get_attr(address, "label"),
            "address_line": self._get_attr(address, "address_line"),
            "instructions": self._get_attr(address, "instructions"),
            "latitude": self._get_attr(address, "latitude"),
            "longitude": self._get_attr(address, "longitude"),
            "is_default": self._get_attr(address, "is_default"),
            "created_at": self._get_attr(address, "created_at").isoformat() if self._get_attr(address, "created_at") else None,
        }

    async def _cache_set(self, key: str, data: Any, ttl: int):
        try:
            await redis_client.setex(key, ttl, json.dumps(data))
        except Exception:
            pass

    async def _invalidate_address_cache(self, address_id: int = None, user_id: int = None):
        """
        Invalidate single address, user list, and default address pointer.
        """
        keys_to_delete = []
        
        if address_id:
            keys_to_delete.append(f"address:{address_id}")
        
        if user_id:
            keys_to_delete.append(f"addresses:user:{user_id}")
            keys_to_delete.append(f"address:default:{user_id}") 
        
        try:
            if keys_to_delete:
                await redis_client.delete(*keys_to_delete)
        except Exception:
            pass

    # --- HELPER METHODS ---
    
    async def _unset_other_defaults(self, user_id: int):
        """Sets is_default=False for all addresses belonging to user."""
        await self.db.execute(
            update(models.Address)
            .where(models.Address.user_id == user_id)
            .values(is_default=False)
        )

    # --- SERVICE METHODS ---

    async def get_address(self, address_id: int, user_id: int = None) -> Union[models.Address, dict]:
        """Get address by ID. Returns Dict (Cache) or Object (DB)."""
        # 1. Try Cache
        try:
            cached = await redis_client.get(f"address:{address_id}")
            if cached:
                address_dict = json.loads(cached)
                # Verify ownership safely using _get_attr
                if user_id:
                    owner_id = self._get_attr(address_dict, "user_id")
                    if owner_id != user_id:
                        raise NotFoundError("Address", address_id)
                return address_dict
        except NotFoundError:
            raise
        except Exception:
            pass
        
        # 2. DB Fallback
        stmt = select(models.Address).where(models.Address.id == address_id)
        if user_id:
            stmt = stmt.where(models.Address.user_id == user_id)
        
        result = await self.db.execute(stmt)
        address = result.unique().scalar_one_or_none()
        
        if not address:
            raise NotFoundError("Address", address_id)
        
        # 3. Cache
        await self._cache_set(f"address:{address.id}", self._serialize_address(address), self.ADDRESS_CACHE_TTL)
        
        return address

    async def get_user_addresses(self, user_id: int):
        """Get all addresses for a user."""
        cache_key = f"addresses:user:{user_id}"
        
        # 1. Try Cache (Full List)
        try:
            cached = await redis_client.get(cache_key)
            if cached:
                return json.loads(cached)
        except Exception:
            pass
        
        # 2. DB Fallback
        result = await self.db.execute(
            select(models.Address)
            .where(models.Address.user_id == user_id)
            .order_by(models.Address.is_default.desc(), models.Address.id.desc())
        )
        addresses = result.scalars().all()
        
        # 3. Serialize & Cache
        serialized_list = [self._serialize_address(a) for a in addresses]
        await self._cache_set(cache_key, serialized_list, self.USER_ADDRESSES_CACHE_TTL)
        
        return addresses

    async def create_address(self, address_data: AddressCreate, user_id: int) -> models.Address:
        """Create a new address."""
        # Check existing count directly from DB
        # ✅ PERFORMANCE FIX: Use SQL COUNT instead of fetching all rows
        result = await self.db.execute(
            select(func.count()).select_from(models.Address).where(models.Address.user_id == user_id)
        )
        existing_count = result.scalar()
        
        # Logic: First address is always default
        is_default_value = address_data.is_default
        if existing_count == 0:
            is_default_value = True
        
        if is_default_value:
            await self._unset_other_defaults(user_id)
        
        new_address = models.Address(
            user_id=user_id,
            label=address_data.label,
            address_line=address_data.address_line,
            instructions=address_data.instructions,
            latitude=address_data.latitude,
            longitude=address_data.longitude,
            is_default=is_default_value
        )
        
        self.db.add(new_address)
        await self.db.commit()
        await self.db.refresh(new_address)
        
        # Invalidate Cache
        await self._invalidate_address_cache(user_id=user_id)
        
        # Cache specific item
        await self._cache_set(f"address:{new_address.id}", self._serialize_address(new_address), self.ADDRESS_CACHE_TTL)
        
        return new_address

    async def update_address(self, address_id: int, address_data: AddressUpdate, user_id: int) -> models.Address:
        """Update an existing address."""
        # 1. Fetch directly from DB (Locking/Safety)
        stmt = select(models.Address).where(models.Address.id == address_id, models.Address.user_id == user_id)
        result = await self.db.execute(stmt)
        address = result.unique().scalar_one_or_none()
        
        if not address:
            raise NotFoundError("Address", address_id)
        
        # 2. Handle Default Logic
        if address_data.is_default is True:
            await self._unset_other_defaults(user_id)
        
        # 3. Update Fields
        for field, value in address_data.model_dump(exclude_unset=True).items():
            setattr(address, field, value)
        
        await self.db.commit()
        await self.db.refresh(address)
        
        # 4. Invalidate Cache
        await self._invalidate_address_cache(address_id=address_id, user_id=user_id)
        
        return address

    async def delete_address(self, address_id: int, user_id: int):
        """Delete an address."""
        # Fetch directly from DB
        stmt = select(models.Address).where(models.Address.id == address_id, models.Address.user_id == user_id)
        result = await self.db.execute(stmt)
        address = result.unique().scalar_one_or_none()
        
        if not address:
            raise NotFoundError("Address", address_id)
        
        await self.db.delete(address)
        await self.db.commit()
        
        # Invalidate Cache
        await self._invalidate_address_cache(address_id=address_id, user_id=user_id)

    async def get_default_address(self, user_id: int) -> Union[models.Address, dict, None]:
        """Get user's default address."""
        # 1. Try Cache
        cache_key = f"address:default:{user_id}"
        try:
            cached = await redis_client.get(cache_key)
            if cached:
                return json.loads(cached)
        except Exception:
            pass
        
        # 2. DB Fallback
        result = await self.db.execute(
            select(models.Address)
            .where(models.Address.user_id == user_id)
            .where(models.Address.is_default == True)
        )
        address = result.scalar_one_or_none()
        
        # 3. Cache
        if address:
            await self._cache_set(cache_key, self._serialize_address(address), 600)
        
        return address

    # pydantic does validate, remove if unneccessary
    async def validate_coordinates(self, latitude: float, longitude: float) -> bool:
        if not (-90 <= latitude <= 90): return False
        if not (-180 <= longitude <= 180): return False
        return True

    async def calculate_distance(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Haversine formula."""
        from math import radians, sin, cos, sqrt, atan2
        R = 6371
        lat1_rad = radians(lat1)
        lat2_rad = radians(lat2)
        delta_lat = radians(lat2 - lat1)
        delta_lon = radians(lon2 - lon1)
        a = sin(delta_lat / 2)**2 + cos(lat1_rad) * cos(lat2_rad) * sin(delta_lon / 2)**2
        c = 2 * atan2(sqrt(a), sqrt(1 - a))
        return R * c