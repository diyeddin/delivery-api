import json
from typing import List, Optional, Dict
from fastapi import APIRouter, Depends, HTTPException, status, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.database import get_db, AsyncSessionLocal
from app.db import models
from app.db.models import UserRole
from app.services.driver_service import AsyncDriverService
from app.services.user_service import AsyncUserService
from app.schemas.order import OrderOut
from app.utils.dependencies import get_current_user, get_current_user_ws
from app.utils.exceptions import NotFoundError, BadRequestError, PermissionDeniedError
from app.core.logging import get_logger
from pydantic import BaseModel

logger = get_logger(__name__)

router = APIRouter(prefix="/drivers", tags=["drivers"])

# ─── 0. CONNECTION MANAGER (NEW) ───────────────────────
class DriverConnectionManager:
    def __init__(self):
        # Maps driver_id -> WebSocket connection
        self.active_connections: Dict[int, WebSocket] = {}

    async def connect(self, websocket: WebSocket, driver_id: int):
        await websocket.accept()
        self.active_connections[driver_id] = websocket
        logger.info(f"Driver {driver_id} connected. Total: {len(self.active_connections)}")

    def disconnect(self, driver_id: int):
        if driver_id in self.active_connections:
            del self.active_connections[driver_id]
            logger.info(f"Driver {driver_id} disconnected")

    async def send_personal_message(self, message: dict, driver_id: int):
        if driver_id in self.active_connections:
            await self.active_connections[driver_id].send_json(message)

# Global Instance
driver_manager = DriverConnectionManager()

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
    driver_service = AsyncDriverService(db)
    orders = await driver_service.get_available_orders()
    return orders


# --- 2. Accept Order ---
@router.post("/accept-order/{order_id}", response_model=OrderOut)
async def accept_order(
    order_id: int,
    current_user=Depends(require_driver),
    db: AsyncSession = Depends(get_db)
):
    driver_service = AsyncDriverService(db)
    is_available = await driver_service.check_driver_availability(current_user.id)
    if not is_available:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You have reached the maximum number of concurrent deliveries"
        )

    try:
        order = await driver_service.accept_order(order_id, current_user.id)
        return order
    except NotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    except BadRequestError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# --- 3. Get My Deliveries ---
@router.get("/my-deliveries", response_model=List[OrderOut])
async def get_my_deliveries(
    current_user=Depends(require_driver),
    db: AsyncSession = Depends(get_db)
):
    driver_service = AsyncDriverService(db)
    orders = await driver_service.get_driver_deliveries(current_user.id)
    return orders


# --- 4. Update Delivery Status ---
class StatusUpdate(BaseModel):
    new_status: str

@router.patch("/delivery-status/{order_id}", response_model=OrderOut)
async def update_delivery_status(
    order_id: int,
    payload: StatusUpdate,
    current_user=Depends(require_driver),
    db: AsyncSession = Depends(get_db)
):
    driver_service = AsyncDriverService(db)
    try:
        order = await driver_service.update_delivery_status(
            order_id, payload.new_status, current_user.id
        )
        return order
    except NotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    except PermissionDeniedError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except BadRequestError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# --- 5. Get Driver Stats ---
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
    driver_service = AsyncDriverService(db)
    stats = await driver_service.get_driver_stats(current_user.id)
    return DriverStatsResponse(**stats)


# --- 6. Get Delivery History ---
@router.get("/history", response_model=List[OrderOut])
async def get_delivery_history(
    status_filter: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    current_user=Depends(require_driver),
    db: AsyncSession = Depends(get_db)
):
    driver_service = AsyncDriverService(db)
    try:
        orders = await driver_service.get_delivery_history(
            current_user.id, status_filter=status_filter, limit=limit
        )
        return orders
    except BadRequestError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# --- 7. Check Availability ---
class AvailabilityResponse(BaseModel):
    is_available: bool
    message: str

@router.get("/availability", response_model=AvailabilityResponse)
async def check_availability(
    current_user=Depends(require_driver),
    db: AsyncSession = Depends(get_db)
):
    driver_service = AsyncDriverService(db)
    is_available = await driver_service.check_driver_availability(current_user.id)
    if is_available:
        return AvailabilityResponse(is_available=True, message="You can accept more orders")
    else:
        return AvailabilityResponse(is_available=False, message="Max concurrent deliveries reached")


# --- 8. Get Nearby Drivers ---
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
    driver_service = AsyncDriverService(db)
    drivers = await driver_service.get_nearby_drivers(latitude, longitude, radius_km)
    return [NearbyDriverResponse(**driver) for driver in drivers]


# ─── 9. WEBSOCKET ENDPOINT (NEW) ───────────────────────
@router.websocket("/ws")
async def driver_websocket_endpoint(
    websocket: WebSocket,
    token: str = None,
    db: AsyncSession = Depends(get_db)
):
    """
    Real-time WebSocket connection for drivers.
    Requires ?token=JWT_TOKEN in the URL.
    """
    # 1. Authenticate using the specific WS helper
    user = await get_current_user_ws(token, db)

    # 2. Validate User and Role
    if not user or user.role != models.UserRole.driver:
        logger.warning(f"WS Connection Rejected: {user.email if user else 'Invalid Token'}")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # 3. Accept Connection
    await driver_manager.connect(websocket, user.id)

    try:
        while True:
            data = await websocket.receive_text()

            if data == "ping":
                await websocket.send_text("pong")
                continue

            # Parse JSON messages
            try:
                msg = json.loads(data)
            except json.JSONDecodeError:
                continue

            if msg.get("type") == "location_update":
                lat = msg.get("latitude")
                lng = msg.get("longitude")
                if lat is None or lng is None:
                    continue

                # 1. Save location (independent session)
                async with AsyncSessionLocal() as save_session:
                    try:
                        user_service = AsyncUserService(save_session)
                        await user_service.update_driver_location(
                            user_id=user.id,
                            latitude=float(lat),
                            longitude=float(lng),
                        )
                    except Exception as e:
                        logger.error(f"Location update failed for driver {user.id}", exc_info=True)

                # 2. Broadcast to customer rooms (independent session)
                async with AsyncSessionLocal() as broadcast_session:
                    try:
                        from app.routers.orders import manager as orders_manager
                        result = await broadcast_session.execute(
                            select(models.Order.id).where(
                                models.Order.driver_id == user.id,
                                models.Order.status.notin_([
                                    models.OrderStatus.delivered,
                                    models.OrderStatus.canceled
                                ])
                            )
                        )
                        active_order_ids = result.scalars().all()
                        gps_payload = {
                            "type": "gps_update",
                            "latitude": float(lat),
                            "longitude": float(lng),
                        }
                        for order_id in active_order_ids:
                            await orders_manager.broadcast(str(order_id), gps_payload)
                        logger.info(f"GPS broadcast to {len(active_order_ids)} orders for driver {user.id}")
                    except Exception as e:
                        logger.error(f"GPS broadcast failed for driver {user.id}", exc_info=True)
                
    except WebSocketDisconnect:
        driver_manager.disconnect(user.id)
    except Exception as e:
        logger.error(f"Driver WS error for {user.id}", exc_info=True)
        driver_manager.disconnect(user.id)