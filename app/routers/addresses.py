# app/routers/addresses.py
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import models, database
from app.utils.dependencies import get_current_user
from app.schemas import address as address_schema
from app.services.address_service import AsyncAddressService
from app.utils.exceptions import NotFoundError

router = APIRouter(prefix="/addresses", tags=["addresses"])


# --- 1. List My Addresses ---
@router.get("", response_model=List[address_schema.AddressOut])
async def get_my_addresses(
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Get all addresses for the current user, sorted by default first."""
    address_service = AsyncAddressService(db)
    addresses = await address_service.get_user_addresses(current_user.id)
    return addresses


# --- 2. NEW: Get Default Address ---
@router.get("/default", response_model=address_schema.AddressOut)
async def get_default_address(
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Get the user's default address (useful for quick order checkout)."""
    address_service = AsyncAddressService(db)
    address = await address_service.get_default_address(current_user.id)
    
    if not address:
        raise HTTPException(
            status_code=404, 
            detail="No default address found. Please add an address first."
        )
    
    return address


# --- 3. NEW: Get Single Address ---
@router.get("/{address_id}", response_model=address_schema.AddressOut)
async def get_address(
    address_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Get a specific address by ID."""
    address_service = AsyncAddressService(db)
    
    try:
        address = await address_service.get_address(address_id, current_user.id)
        return address
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Address not found")


# --- 4. Add New Address ---
@router.post("/", response_model=address_schema.AddressOut, status_code=status.HTTP_201_CREATED)
async def create_address(
    payload: address_schema.AddressCreate,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Create a new address. First address is automatically set as default."""
    address_service = AsyncAddressService(db)
    
    # Validate coordinates if provided
    if payload.latitude is not None and payload.longitude is not None:
        is_valid = await address_service.validate_coordinates(
            payload.latitude, 
            payload.longitude
        )
        if not is_valid:
            raise HTTPException(
                status_code=400,
                detail="Invalid coordinates. Latitude must be between -90 and 90, longitude between -180 and 180."
            )
    
    address = await address_service.create_address(payload, current_user.id)
    return address


# --- 5. Update Address ---
@router.patch("/{address_id}", response_model=address_schema.AddressOut)
async def update_address(
    address_id: int,
    payload: address_schema.AddressUpdate,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user)
):
    """
    Update an existing address.
    Setting is_default=true will unset all other addresses as default.
    """
    address_service = AsyncAddressService(db)
    
    # Validate coordinates if being updated
    if payload.latitude is not None and payload.longitude is not None:
        is_valid = await address_service.validate_coordinates(
            payload.latitude, 
            payload.longitude
        )
        if not is_valid:
            raise HTTPException(
                status_code=400,
                detail="Invalid coordinates. Latitude must be between -90 and 90, longitude between -180 and 180."
            )
    
    try:
        address = await address_service.update_address(
            address_id, 
            payload, 
            current_user.id
        )
        return address
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Address not found")


# --- 6. Delete Address ---
@router.delete("/{address_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_address(
    address_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Delete an address."""
    address_service = AsyncAddressService(db)
    
    try:
        await address_service.delete_address(address_id, current_user.id)
        return None
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Address not found")