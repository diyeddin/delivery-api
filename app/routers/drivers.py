# app/routers/drivers.py
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.database import get_db
from app.db.models import UserRole, OrderStatus
from app.services.driver_service import AsyncDriverService
from app.schemas.order import OrderOut
from app.utils.dependencies import get_current_user
from app.utils.exceptions import NotFoundError, BadRequestError, PermissionDeniedError
from pydantic import BaseModel

router = APIRouter(prefix="/drivers", tags=["drivers"])


# --- Helper: Require Driver Role ---
def require_driver(current_user=Depends(get_current_user)):
    """Dependency to ensure user is a driver."""
    if current_user.role != UserRole.driver:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only drivers can access this endpoint"
        )
    return current_user


# --- 1. Get Available Orders ---
@router.get("/available-orders", response_model=List[OrderOut])
async def get_available_orders(
    current_user=Depends(require_driver),
    db: AsyncSession = Depends(get_db)
):
    """
    Get orders available for driver assignment.
    Returns orders with 'confirmed' status and no assigned driver.
    """
    driver_service = AsyncDriverService(db)
    orders = await driver_service.get_available_orders()
    return orders


# --- 2. Accept Order ---
class AcceptOrderResponse(BaseModel):
    message: str
    order_id: int
    status: str

@router.post("/accept-order/{order_id}", response_model=AcceptOrderResponse)
async def accept_order(
    order_id: int,
    current_user=Depends(require_driver),
    db: AsyncSession = Depends(get_db)
):
    """
    Accept an available order for delivery.
    Uses atomic operation to prevent race conditions.
    """
    driver_service = AsyncDriverService(db)
    
    # Check if driver is available (not overloaded)
    is_available = await driver_service.check_driver_availability(current_user.id)
    if not is_available:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You have reached the maximum number of concurrent deliveries"
        )
    
    try:
        order = await driver_service.accept_order(order_id, current_user.id)
        return AcceptOrderResponse(
            message="Order accepted successfully",
            order_id=order.id,
            status=order.status.value
        )
    except NotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found"
        )
    except BadRequestError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


# --- 3. Get My Deliveries ---
@router.get("/my-deliveries", response_model=List[OrderOut])
async def get_my_deliveries(
    current_user=Depends(require_driver),
    db: AsyncSession = Depends(get_db)
):
    """Get all orders assigned to the current driver."""
    driver_service = AsyncDriverService(db)
    orders = await driver_service.get_driver_deliveries(current_user.id)
    return orders


# --- 4. Update Delivery Status ---
class StatusUpdate(BaseModel):
    new_status: str

class StatusUpdateResponse(BaseModel):
    message: str
    order_id: int
    new_status: str

@router.patch("/delivery-status/{order_id}", response_model=StatusUpdateResponse)
async def update_delivery_status(
    order_id: int,
    payload: StatusUpdate,
    current_user=Depends(require_driver),
    db: AsyncSession = Depends(get_db)
):
    """
    Update delivery status for assigned orders.
    Only the assigned driver can update the status.
    """
    driver_service = AsyncDriverService(db)
    
    try:
        order = await driver_service.update_delivery_status(
            order_id,
            payload.new_status,
            current_user.id
        )
        return StatusUpdateResponse(
            message="Status updated successfully",
            order_id=order.id,
            new_status=order.status.value
        )
    except NotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found"
        )
    except PermissionDeniedError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e)
        )
    except BadRequestError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


# --- 5. NEW: Get Driver Stats ---
class DriverStatsResponse(BaseModel):
    driver_id: int
    total_deliveries: int
    total_earnings: float
    active_deliveries: int
    average_per_delivery: float

@router.get("/stats", response_model=DriverStatsResponse)
async def get_driver_stats(
    current_user=Depends(require_driver),
    db: AsyncSession = Depends(get_db)
):
    """Get statistics for the current driver."""
    driver_service = AsyncDriverService(db)
    stats = await driver_service.get_driver_stats(current_user.id)
    return DriverStatsResponse(**stats)


# --- 6. NEW: Get Delivery History ---
@router.get("/history", response_model=List[OrderOut])
async def get_delivery_history(
    status_filter: Optional[str] = Query(None, description="Filter by order status"),
    limit: int = Query(50, ge=1, le=100, description="Number of orders to return"),
    current_user=Depends(require_driver),
    db: AsyncSession = Depends(get_db)
):
    """
    Get delivery history for the current driver.
    Optionally filter by status (e.g., 'delivered', 'canceled').
    """
    driver_service = AsyncDriverService(db)
    
    try:
        orders = await driver_service.get_delivery_history(
            current_user.id,
            status_filter=status_filter,
            limit=limit
        )
        return orders
    except BadRequestError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


# --- 7. NEW: Check Availability ---
class AvailabilityResponse(BaseModel):
    is_available: bool
    message: str

@router.get("/availability", response_model=AvailabilityResponse)
async def check_availability(
    current_user=Depends(require_driver),
    db: AsyncSession = Depends(get_db)
):
    """Check if the driver can accept more orders."""
    driver_service = AsyncDriverService(db)
    is_available = await driver_service.check_driver_availability(current_user.id)
    
    if is_available:
        return AvailabilityResponse(
            is_available=True,
            message="You can accept more orders"
        )
    else:
        return AvailabilityResponse(
            is_available=False,
            message="You have reached the maximum number of concurrent deliveries"
        )


# --- 8. NEW: Get Nearby Drivers (Admin/Customer View) ---
class NearbyDriverResponse(BaseModel):
    driver_id: int
    name: str
    latitude: float
    longitude: float
    distance_km: float
    is_active: bool

@router.get("/nearby", response_model=List[NearbyDriverResponse])
async def get_nearby_drivers(
    latitude: float = Query(..., ge=-90, le=90),
    longitude: float = Query(..., ge=-180, le=180),
    radius_km: float = Query(10.0, ge=0.1, le=50.0),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """
    Get active drivers near a location.
    Useful for customers to see nearby drivers or for admin dashboards.
    """
    driver_service = AsyncDriverService(db)
    drivers = await driver_service.get_nearby_drivers(latitude, longitude, radius_km)
    return [NearbyDriverResponse(**driver) for driver in drivers]