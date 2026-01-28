from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.params import Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Dict
from app.core.security import verify_token
from app.db import database, models
from app.schemas import order as order_schema
from app.services.order_service import AsyncOrderService
from app.utils.dependencies import require_scope
from app.utils.exceptions import NotFoundError, BadRequestError, PermissionDeniedError, InvalidOrderStatusError
from app.core.logging import get_logger, log_business_event

# --- Expo SDK Imports ---
from exponent_server_sdk import PushClient, PushMessage
from requests.exceptions import ConnectionError, HTTPError

router = APIRouter(prefix="/orders", tags=["orders"])
logger = get_logger(__name__)

# --- 1. WEBSOCKET CONNECTION MANAGER ---
class ConnectionManager:
    def __init__(self):
        # Maps order_id -> List of active WebSocket connections
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, order_id: str):
        await websocket.accept()
        if order_id not in self.active_connections:
            self.active_connections[order_id] = []
        self.active_connections[order_id].append(websocket)
        logger.info(f"WebSocket connected to Order {order_id}")

    def disconnect(self, websocket: WebSocket, order_id: str):
        if order_id in self.active_connections:
            self.active_connections[order_id].remove(websocket)
            if not self.active_connections[order_id]:
                del self.active_connections[order_id]

    async def broadcast(self, order_id: str, message: dict):
        """Send a message to all devices watching this order."""
        if order_id in self.active_connections:
            for connection in self.active_connections[order_id]:
                try:
                    await connection.send_json(message)
                except Exception as e:
                    logger.error(f"Failed to send WS message: {e}")

manager = ConnectionManager()

# --- 2. NOTIFICATION HELPERS ---
def send_expo_push(token: str, message: str):
    try:
        response = PushClient().publish(
            PushMessage(to=token, body=message, data={"type": "order_update"})
        )
        if response.status != "ok":
            logger.error(f"Expo Push Error: {response.message}")
    except (ConnectionError, HTTPError) as e:
        logger.error(f"Network Error sending push: {e}")
    except Exception as e:
        logger.error(f"Unknown Push Error: {e}")

async def notify_customer(db: AsyncSession, order_id: int, message: str, bg_tasks: BackgroundTasks):
    result = await db.execute(
        select(models.User.notification_token)
        .join(models.Order, models.Order.user_id == models.User.id)
        .where(models.Order.id == order_id)
    )
    token = result.scalar_one_or_none()
    if token:
        bg_tasks.add_task(send_expo_push, token, message)


# --- 3. WEBSOCKET ENDPOINT ---
@router.websocket("/{order_id}/ws")
async def websocket_endpoint(
    websocket: WebSocket, 
    order_id: int, 
    token: str = Query(None) # <--- 1. Capture token from URL
):
    """
    Real-time channel. Requires ?token=jwt_token
    """
    # --- STEP 1: AUTHENTICATION ---
    if not token:
        # Close with "Policy Violation" if no token
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    try:
        # Verify the token (reuse your auth logic here)
        # This decoding logic depends on your specific verify_token implementation
        payload = verify_token(token) 
        user_id = payload.get("sub") # or payload.get("id")
        user_role = payload.get("role")
        
        # (Optional Step 2: Check if this user actually owns this order)
        # For now, we just ensure they are a valid user.
        if not user_id:
            raise Exception("Invalid user")
            
    except Exception as e:
        print(f"WS Auth Failed: {e}")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # --- STEP 3: CONNECTION ---
    order_room = str(order_id)
    await manager.connect(websocket, order_room)
    
    try:
        while True:
            # We listen to keep the connection open
            data = await websocket.receive_json()
            
            # Example: If a driver sends GPS, verify they are actually a driver
            if data.get("type") == "location_update":
                if user_role != "driver":
                    # Ignore fake GPS data from customers
                    continue 

                # Broadcast to the room
                payload = {
                    "type": "gps_update", 
                    "latitude": data.get("latitude"),
                    "longitude": data.get("longitude")
                }
                await manager.broadcast(order_room, payload)
                
    except WebSocketDisconnect:
        manager.disconnect(websocket, order_room)


# --- 4. STANDARD ENDPOINTS ---

@router.post("/", response_model=List[order_schema.OrderOut])
async def create_order(
    order: order_schema.OrderCreate,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_scope("orders:create"))
):
    logger.info("Processing cart", user_id=current_user.id, items_count=len(order.items))
    svc = AsyncOrderService(db)
    try:
        new_orders = await svc.create_order(order, current_user)
        for created_order in new_orders:
            log_business_event("order_created", current_user.id, order_id=created_order.id)
            # Notify store owners via WS if they are online? (Future feature)
        return new_orders
    except BadRequestError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/available", response_model=List[order_schema.OrderOut])
async def get_available_orders(
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_scope("orders:read"))
):
    query = select(models.Order).where(models.Order.status == "confirmed").order_by(models.Order.created_at.desc())
    result = await db.execute(query)
    orders = result.unique().scalars().all()
    for o in orders: await db.refresh(o, attribute_names=["items"])
    return orders

@router.get("/store/all", response_model=List[order_schema.OrderOut])
async def get_store_orders(
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_scope("orders:read_store")) 
):
    if current_user.role != models.UserRole.store_owner:
        raise HTTPException(status_code=403, detail="Only store owners can access KDS")
    
    query_store = select(models.Store).where(models.Store.owner_id == current_user.id)
    result_store = await db.execute(query_store)
    store = result_store.scalars().first()
    if not store: raise HTTPException(status_code=404, detail="You do not have an active store")

    query_orders = select(models.Order).where(models.Order.store_id == store.id).order_by(models.Order.created_at.desc())
    result_orders = await db.execute(query_orders)
    orders = result_orders.unique().scalars().all()
    for o in orders: await db.refresh(o, attribute_names=["items"])
    return orders

@router.put("/{order_id}/move-status")
async def advance_order_status(
    order_id: int,
    status: str, 
    bg_tasks: BackgroundTasks,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_scope("orders:update_status"))
):
    if current_user.role != models.UserRole.store_owner:
        raise HTTPException(status_code=403, detail="Only store owners can advance kitchen status")

    order = await db.get(models.Order, order_id)
    if not order: raise HTTPException(status_code=404, detail="Order not found")

    store = await db.get(models.Store, order.store_id)
    if not store or store.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Order not found in your store")

    if status == "confirmed":
        if order.status != "pending": raise HTTPException(status_code=400, detail="Order must be 'pending'")
        order.status = "confirmed"
    else:
        raise HTTPException(status_code=400, detail="Invalid status")

    await db.commit()
    await db.refresh(order)

    # --- NOTIFY & BROADCAST ---
    await notify_customer(db, order.id, f"Order #{order.id} confirmed!", bg_tasks)
    await manager.broadcast(str(order.id), {"type": "status_update", "status": order.status})
    # --------------------------

    return {"message": f"Order marked as {status}", "status": order.status}

@router.get("/me", response_model=List[order_schema.OrderOut])
async def get_my_orders(
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_scope("orders:read_own"))
):
    svc = AsyncOrderService(db)
    return await svc.get_user_orders(current_user)

@router.get("/", response_model=List[order_schema.OrderOut])
async def get_all_orders(
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_scope("orders:read_all"))
):
    svc = AsyncOrderService(db)
    return await svc.get_all_orders()

@router.get("/assigned-to-me", response_model=List[order_schema.OrderOut])
async def get_assigned_orders(
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_scope("orders:read"))
):
    svc = AsyncOrderService(db)
    orders = await svc.get_all_orders() 
    return [o for o in orders if o.driver_id == current_user.id]

@router.get("/{order_id}", response_model=order_schema.OrderOut)
async def get_order(
    order_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_scope(["orders:read", "orders:read_own"]))
):
    svc = AsyncOrderService(db)
    try:
        return await svc.get_order(order_id, current_user)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Order not found")

@router.put("/{order_id}/status", response_model=order_schema.OrderOut)
async def update_status(
    order_id: int,
    status_update: order_schema.OrderStatusUpdate,
    bg_tasks: BackgroundTasks,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_scope("orders:update_status"))
):
    svc = AsyncOrderService(db)
    try:
        order = await svc.update_order_status(order_id, status_update.status, current_user)
        
        # --- NOTIFY & BROADCAST ---
        friendly = status_update.status.replace("_", " ").title()
        await notify_customer(db, order_id, f"Your order is now {friendly}", bg_tasks)
        await manager.broadcast(str(order_id), {"type": "status_update", "status": order.status.value})
        # --------------------------

        return order
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.put("/{order_id}/accept", response_model=order_schema.OrderOut)
async def accept_order(
    order_id: int,
    bg_tasks: BackgroundTasks,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_scope("orders:update_status"))
):
    if current_user.role != models.UserRole.driver:
        raise HTTPException(status_code=403, detail="Only drivers can accept orders")

    svc = AsyncOrderService(db)
    try:
        order = await svc.accept_order_atomic(order_id, current_user.id)
        
        # --- NOTIFY & BROADCAST ---
        await notify_customer(db, order_id, "A driver is on their way!", bg_tasks)
        await manager.broadcast(str(order_id), {"type": "status_update", "status": "assigned"})
        # --------------------------

        return order
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))