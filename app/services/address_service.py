"""
Address service layer for business logic separation with Redis caching.
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete
from typing import List, Optional
from app.db import models
from app.schemas.address import AddressCreate, AddressUpdate
from app.utils.exceptions import NotFoundError, PermissionDeniedError
from app.core.redis import redis_client
import json

class AsyncAddressService:
    """Async address service using AsyncSession with Redis caching."""
    
    # Cache TTLs (in seconds)
    ADDRESS_CACHE_TTL = 3600  # 60 minutes - addresses change infrequently
    USER_ADDRESSES_CACHE_TTL = 1800  # 30 minutes
    
    def __init__(self, db: AsyncSession):
        self.db = db

    # --- CACHE HELPER METHODS ---
    
    async def _invalidate_address_cache(self, address_id: int = None, user_id: int = None):
        """Invalidate all cache entries related to an address."""
        keys_to_delete = []
        
        if address_id:
            keys_to_delete.append(f"address:{address_id}")
        
        if user_id:
            keys_to_delete.append(f"addresses:user:{user_id}")
        
        try:
            if keys_to_delete:
                await redis_client.delete(*keys_to_delete)
        except Exception:
            pass

    async def _cache_address(self, address: models.Address):
        """Cache a single address."""
        try:
            address_data = {
                "id": address.id,
                "user_id": address.user_id,
                "label": address.label,
                "address_line": address.address_line,
                "instructions": address.instructions,
                "latitude": address.latitude,
                "longitude": address.longitude,
                "is_default": address.is_default,
                "created_at": address.created_at.isoformat() if address.created_at else None,
            }
            
            await redis_client.setex(
                f"address:{address.id}",
                self.ADDRESS_CACHE_TTL,
                json.dumps(address_data)
            )
        except Exception:
            pass

    async def _get_cached_address(self, address_id: int) -> Optional[dict]:
        """Get cached address data."""
        try:
            cached = await redis_client.get(f"address:{address_id}")
            if cached:
                return json.loads(cached)
        except Exception:
            pass
        return None

    async def _reconstruct_address_from_cache(self, cached_data: dict) -> models.Address:
        """Reconstruct Address model from cached data."""
        # Parse datetime if present
        if "created_at" in cached_data and cached_data["created_at"]:
            from datetime import datetime
            cached_data["created_at"] = datetime.fromisoformat(cached_data["created_at"])
        
        return models.Address(**cached_data)

    # --- HELPER METHODS ---
    
    async def _unset_other_defaults(self, user_id: int):
        """Sets is_default=False for all addresses belonging to user."""
        await self.db.execute(
            update(models.Address)
            .where(models.Address.user_id == user_id)
            .values(is_default=False)
        )
        # Invalidate user's addresses cache since defaults changed
        await self._invalidate_address_cache(user_id=user_id)

    # --- SERVICE METHODS ---

    async def get_address(self, address_id: int, user_id: int = None) -> models.Address:
        """Get address by ID with ownership check."""
        # Try cache first
        cached_data = await self._get_cached_address(address_id)
        if cached_data:
            address = self._reconstruct_address_from_cache(cached_data)
            # Verify ownership if user_id provided
            if user_id and address.user_id != user_id:
                raise NotFoundError("Address", address_id)
            return address
        
        # Cache miss - fetch from database
        stmt = select(models.Address).where(models.Address.id == address_id)
        if user_id:
            stmt = stmt.where(models.Address.user_id == user_id)
        
        result = await self.db.execute(stmt)
        address = result.scalar_one_or_none()
        
        if not address:
            raise NotFoundError("Address", address_id)
        
        # Cache the address
        await self._cache_address(address)
        
        return address

    async def get_user_addresses(self, user_id: int) -> List[models.Address]:
        """Get all addresses for a user, sorted by default first, then newest."""
        # Try cache first
        cache_key = f"addresses:user:{user_id}"
        try:
            cached = await redis_client.get(cache_key)
            if cached:
                address_ids = json.loads(cached)
                addresses = []
                for address_id in address_ids:
                    try:
                        address = await self.get_address(address_id, user_id)
                        addresses.append(address)
                    except NotFoundError:
                        # Address was deleted, invalidate cache
                        await redis_client.delete(cache_key)
                        break
                else:
                    return addresses
        except Exception:
            pass
        
        # Cache miss - fetch from database
        result = await self.db.execute(
            select(models.Address)
            .where(models.Address.user_id == user_id)
            .order_by(models.Address.is_default.desc(), models.Address.id.desc())
        )
        addresses = result.scalars().all()
        
        # Cache the address IDs (maintaining order)
        try:
            address_ids = [address.id for address in addresses]
            await redis_client.setex(
                cache_key,
                self.USER_ADDRESSES_CACHE_TTL,
                json.dumps(address_ids)
            )
            # Cache individual addresses
            for address in addresses:
                await self._cache_address(address)
        except Exception:
            pass
        
        return addresses

    async def create_address(
        self, 
        address_data: AddressCreate, 
        user_id: int
    ) -> models.Address:
        """Create a new address for a user."""
        # Check if this is the user's first address
        result = await self.db.execute(
            select(models.Address).where(models.Address.user_id == user_id)
        )
        existing_count = len(result.scalars().all())
        
        # If first address, force it to be default
        is_default_value = address_data.is_default
        if existing_count == 0:
            is_default_value = True
        
        # If setting as default, unset others first
        if is_default_value:
            await self._unset_other_defaults(user_id)
        
        # Create the address
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
        
        # Invalidate user's addresses cache
        await self._invalidate_address_cache(user_id=user_id)
        
        # Cache the new address
        await self._cache_address(new_address)
        
        return new_address

    async def update_address(
        self,
        address_id: int,
        address_data: AddressUpdate,
        user_id: int
    ) -> models.Address:
        """Update an existing address."""
        # Fetch and verify ownership
        address = await self.get_address(address_id, user_id)
        
        # If setting as default, clear others
        if address_data.is_default is True:
            await self._unset_other_defaults(user_id)
        
        # Update fields
        for field, value in address_data.model_dump(exclude_unset=True).items():
            setattr(address, field, value)
        
        self.db.add(address)
        await self.db.commit()
        await self.db.refresh(address)
        
        # Invalidate cache
        await self._invalidate_address_cache(address_id, user_id)
        
        # Cache updated address
        await self._cache_address(address)
        
        return address

    async def delete_address(self, address_id: int, user_id: int):
        """Delete an address."""
        # Fetch and verify ownership
        address = await self.get_address(address_id, user_id)
        
        await self.db.delete(address)
        await self.db.commit()
        
        # Invalidate cache
        await self._invalidate_address_cache(address_id, user_id)

    async def get_default_address(self, user_id: int) -> Optional[models.Address]:
        """Get user's default address (useful for orders)."""
        # Check cache first
        cache_key = f"address:default:{user_id}"
        try:
            cached = await redis_client.get(cache_key)
            if cached:
                address_data = json.loads(cached)
                return self._reconstruct_address_from_cache(address_data)
        except Exception:
            pass
        
        # Cache miss - fetch from database
        result = await self.db.execute(
            select(models.Address)
            .where(models.Address.user_id == user_id)
            .where(models.Address.is_default == True)
        )
        address = result.scalar_one_or_none()
        
        if address:
            # Cache default address with shorter TTL (might change)
            try:
                address_data = {
                    "id": address.id,
                    "user_id": address.user_id,
                    "label": address.label,
                    "address_line": address.address_line,
                    "instructions": address.instructions,
                    "latitude": address.latitude,
                    "longitude": address.longitude,
                    "is_default": address.is_default,
                    "created_at": address.created_at.isoformat() if address.created_at else None,
                }
                await redis_client.setex(
                    cache_key,
                    600,  # 10 minutes (shorter TTL for default)
                    json.dumps(address_data)
                )
            except Exception:
                pass
        
        return address

    async def validate_coordinates(
        self, 
        latitude: float, 
        longitude: float
    ) -> bool:
        """Validate that coordinates are within acceptable range."""
        # Basic validation
        if not (-90 <= latitude <= 90):
            return False
        if not (-180 <= longitude <= 180):
            return False
        return True

    async def calculate_distance(
        self,
        lat1: float,
        lon1: float,
        lat2: float,
        lon2: float
    ) -> float:
        """
        Calculate distance between two coordinates in kilometers.
        Uses Haversine formula.
        """
        from math import radians, sin, cos, sqrt, atan2
        
        R = 6371  # Earth's radius in kilometers
        
        lat1_rad = radians(lat1)
        lat2_rad = radians(lat2)
        delta_lat = radians(lat2 - lat1)
        delta_lon = radians(lon2 - lon1)
        
        a = sin(delta_lat / 2)**2 + cos(lat1_rad) * cos(lat2_rad) * sin(delta_lon / 2)**2
        c = 2 * atan2(sqrt(a), sqrt(1 - a))
        
        distance = R * c
        return distance