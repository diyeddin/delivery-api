from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import models, database
from app.utils.dependencies import get_current_user
from app.schemas import address as address_schema

router = APIRouter(prefix="/addresses", tags=["addresses"])

# --- Helper: Unset other defaults ---
async def unset_other_defaults(user_id: int, db: AsyncSession):
    """Sets is_default=False for all addresses belonging to user."""
    await db.execute(
        update(models.Address)
        .where(models.Address.user_id == user_id)
        .values(is_default=False)
    )

# 1. List My Addresses
@router.get("/", response_model=List[address_schema.AddressOut])
async def get_my_addresses(
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user)
):
    # Sort by ID descending (newest first), or put default at top
    result = await db.execute(
        select(models.Address)
        .where(models.Address.user_id == current_user.id)
        .order_by(models.Address.is_default.desc(), models.Address.id.desc())
    )
    return result.scalars().all()

# 2. Add New Address
@router.post("/", response_model=address_schema.AddressOut, status_code=status.HTTP_201_CREATED)
async def create_address(
    payload: address_schema.AddressCreate,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user)
):
    # If this is the user's FIRST address, force it to be default
    result = await db.execute(select(models.Address).where(models.Address.user_id == current_user.id))
    existing_count = len(result.scalars().all())
    
    is_default_value = payload.is_default
    if existing_count == 0:
        is_default_value = True

    # If setting as default, unset others first
    if is_default_value:
        await unset_other_defaults(current_user.id, db)

    new_address = models.Address(
        user_id=current_user.id,
        label=payload.label,
        address_line=payload.address_line,
        instructions=payload.instructions,
        latitude=payload.latitude,
        longitude=payload.longitude,
        is_default=is_default_value
    )
    
    db.add(new_address)
    await db.commit()
    await db.refresh(new_address)
    return new_address

# 3. Delete Address
@router.delete("/{address_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_address(
    address_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user)
):
    # Check ownership
    result = await db.execute(
        select(models.Address).where(
            models.Address.id == address_id,
            models.Address.user_id == current_user.id
        )
    )
    address = result.scalar_one_or_none()
    
    if not address:
        raise HTTPException(status_code=404, detail="Address not found")

    await db.delete(address)
    await db.commit()
    return None

# 4. Update Address (e.g., Set Default)
@router.patch("/{address_id}", response_model=address_schema.AddressOut)
async def update_address(
    address_id: int,
    payload: address_schema.AddressUpdate,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user)
):
    # Fetch existing
    result = await db.execute(
        select(models.Address).where(
            models.Address.id == address_id,
            models.Address.user_id == current_user.id
        )
    )
    address = result.scalar_one_or_none()
    
    if not address:
        raise HTTPException(status_code=404, detail="Address not found")

    # Logic: If setting as default, clear others
    if payload.is_default is True:
        await unset_other_defaults(current_user.id, db)

    # Update fields
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(address, field, value)

    db.add(address)
    await db.commit()
    await db.refresh(address)
    return address