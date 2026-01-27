from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List
from app.db import database, models
from app.schemas import order as order_schema
from app.services.order_service import AsyncOrderService
from app.utils.dependencies import require_scope
from app.utils.exceptions import NotFoundError, BadRequestError, PermissionDeniedError, InvalidOrderStatusError
from app.core.logging import get_logger, log_business_event

# --- NEW: Expo SDK Imports ---
from exponent_server_sdk import PushClient, PushMessage
from requests.exceptions import ConnectionError, HTTPError

router = APIRouter(prefix="/orders", tags=["orders"])
logger = get_logger(__name__)

# --- NEW: Notification Helper ---
def send_expo_push(token: str, message: str):
    """
    Synchronous function to send push notification via Expo.
    (Run this in BackgroundTasks to avoid blocking the event loop)
    """
    try:
        response = PushClient().publish(
            PushMessage(to=token, body=message, data={"type": "order_update"})
        )
        # Check for errors in the response logic from Expo
        if response.status != "ok":
            logger.error(f"Expo Push Error: {response.message}")
    except (ConnectionError, HTTPError) as e:
        logger.error(f"Network Error sending push: {e}")
    except Exception as e:
        logger.error(f"Unknown Push Error: {e}")

async def notify_customer(db: AsyncSession, order_id: int, message: str, bg_tasks: BackgroundTasks):
    """
    Fetches the customer's token and schedules the push notification.
    """
    # 1. Fetch User Token via Order relationship
    result = await db.execute(
        select(models.User.notification_token)
        .join(models.Order, models.Order.user_id == models.User.id)
        .where(models.Order.id == order_id)
    )
    token = result.scalar_one_or_none()

    # 2. Schedule Background Task if token exists
    if token:
        bg_tasks.add_task(send_expo_push, token, message)
        logger.info(f"Notification scheduled for Order #{order_id} -> {token[:10]}...")
    else:
        logger.info(f"No token found for Order #{order_id}, skipping notification.")


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
            log_business_event(
                "order_created", 
                current_user.id,
                order_id=created_order.id, 
                total_price=created_order.total_price, 
                items_count=len(created_order.items)
            )
        return new_orders
    except BadRequestError as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- UPDATED: DRIVER AVAILABILITY ---
@router.get("/available", response_model=List[order_schema.OrderOut])
async def get_available_orders(
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_scope("orders:read"))
):
    """
    Get orders available for pickup.
    Drivers only see orders that are 'confirmed' (ready for pickup/prep).
    """
    query = select(models.Order).where(
        models.Order.status == "confirmed"
    ).order_by(models.Order.created_at.desc())
    
    result = await db.execute(query)
    orders = result.unique().scalars().all()
    
    for o in orders:
        await db.refresh(o, attribute_names=["items"])
        
    return orders


# --- NEW: STORE OWNER ENDPOINTS (KDS) ---

@router.get("/store/all", response_model=List[order_schema.OrderOut])
async def get_store_orders(
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_scope("orders:read_store")) 
):
    if current_user.role != models.UserRole.store_owner:
        raise HTTPException(status_code=403, detail="Only store owners can access KDS")
    
    # 1. Find the store owned by this user
    query_store = select(models.Store).where(models.Store.owner_id == current_user.id)
    result_store = await db.execute(query_store)
    store = result_store.scalars().first()
    
    if not store:
        raise HTTPException(status_code=404, detail="You do not have an active store")

    # 2. Fetch orders for this store
    query_orders = select(models.Order).where(
        models.Order.store_id == store.id
    ).order_by(models.Order.created_at.desc())
    
    result_orders = await db.execute(query_orders)
    orders = result_orders.unique().scalars().all()

    # Refresh items for response schema
    for o in orders:
        await db.refresh(o, attribute_names=["items"])

    return orders


@router.put("/{order_id}/move-status")
async def advance_order_status(
    order_id: int,
    status: str, 
    bg_tasks: BackgroundTasks, # <--- Inject BackgroundTasks
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_scope("orders:update_status"))
):
    """
    KDS Action: Allows Store Owner to move order state.
    """
    if current_user.role != models.UserRole.store_owner:
        raise HTTPException(status_code=403, detail="Only store owners can advance kitchen status")

    # 1. Fetch Order
    order = await db.get(models.Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    # 2. Verify Ownership
    store = await db.get(models.Store, order.store_id)
    if not store or store.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="This order does not belong to your store")

    # 3. Simple State Machine
    if status == "confirmed":
        if order.status != "pending":
             raise HTTPException(status_code=400, detail="Order must be 'pending' to confirm")
        order.status = "confirmed"
    else:
        raise HTTPException(status_code=400, detail="Invalid status. Use 'confirmed'.")

    await db.commit()
    await db.refresh(order)

    # --- TRIGGER NOTIFICATION ---
    await notify_customer(db, order.id, f"Great news! Your order #{order.id} has been confirmed.", bg_tasks)
    # ----------------------------

    log_business_event("order_status_updated", current_user.id, order_id=order.id, new_status=order.status)
    return {"message": f"Order marked as {status}", "status": order.status}


@router.get("/me", response_model=List[order_schema.OrderOut])
async def get_my_orders(
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_scope("orders:read_own"))
):
    """Get current user's orders (customers only)"""
    svc = AsyncOrderService(db)
    return await svc.get_user_orders(current_user)


@router.get("/", response_model=List[order_schema.OrderOut])
async def get_all_orders(
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_scope("orders:read_all"))
):
    """Get all orders (Admin only)"""
    svc = AsyncOrderService(db)
    return await svc.get_all_orders()


@router.get("/assigned-to-me", response_model=List[order_schema.OrderOut])
async def get_assigned_orders(
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_scope("orders:read"))
):
    """Get orders assigned to current driver"""
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
    bg_tasks: BackgroundTasks, # <--- Inject BackgroundTasks
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_scope("orders:update_status"))
):
    """General status update (Admin/Driver usage mainly)"""
    svc = AsyncOrderService(db)
    try:
        order = await svc.update_order_status(order_id, status_update.status, current_user)
        
        # --- TRIGGER NOTIFICATION ---
        friendly_status = status_update.status.replace("_", " ").title()
        await notify_customer(db, order_id, f"Update: Your order is now {friendly_status}", bg_tasks)
        # ----------------------------

        return order
    except (NotFoundError, BadRequestError, PermissionDeniedError, InvalidOrderStatusError) as e:
        code = 400
        if isinstance(e, NotFoundError): code = 404
        if isinstance(e, PermissionDeniedError): code = 403
        raise HTTPException(status_code=code, detail=str(e))


@router.put("/{order_id}/accept", response_model=order_schema.OrderOut)
async def accept_order(
    order_id: int,
    bg_tasks: BackgroundTasks, # <--- Inject BackgroundTasks
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_scope("orders:update_status"))
):
    """Driver accepts an available order"""
    if current_user.role != models.UserRole.driver:
        raise HTTPException(status_code=403, detail="Only drivers can accept orders")

    svc = AsyncOrderService(db)
    try:
        order = await svc.accept_order_atomic(order_id, current_user.id)
        
        # --- TRIGGER NOTIFICATION ---
        await notify_customer(db, order_id, "A driver is on their way to pick up your order!", bg_tasks)
        # ----------------------------

        return order
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Order not found")
    except BadRequestError as e:
        raise HTTPException(status_code=400, detail=str(e))