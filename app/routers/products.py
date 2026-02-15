# app/routers/products.py
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from sqlalchemy import select, or_, func
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional, Generic, TypeVar
from pydantic import BaseModel
from app.db import models, database
from app.schemas.product import ProductCreate, ProductOut, ProductUpdate
from app.services.product_service import AsyncProductService
from app.utils.exceptions import NotFoundError, PermissionDeniedError
from app.utils.dependencies import require_scope

router = APIRouter(prefix="/products", tags=["products"])

# 👇 NEW: Generic Pagination Schema
T = TypeVar("T")

class Page(BaseModel, Generic[T]):
    data: List[T]
    total: int

@router.get("/", response_model=Page[ProductOut]) # 👈 Updated Response Model
async def get_products(
    q: Optional[str] = None,
    category: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    sort_by: Optional[str] = Query("newest", pattern="^(newest|price_asc|price_desc)$"),
    in_stock: bool = False,
    store_id: Optional[int] = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(database.get_db)
):
    """
    Global Product Search & Filter with Pagination + Total Count.
    """
    query = select(models.Product)
    
    # --- FILTERS (Same as before) ---
    if q:
        search_text = f"%{q}%"
        query = query.where(
            or_(
                models.Product.name.ilike(search_text),
                models.Product.description.ilike(search_text)
            )
        )

    if category and category != "All": # Added check for "All" string just in case
        query = query.where(models.Product.category.ilike(category))
    
    if store_id:
        query = query.where(models.Product.store_id == store_id)

    if min_price is not None:
        query = query.where(models.Product.price >= min_price)
    if max_price is not None:
        query = query.where(models.Product.price <= max_price)
        
    if in_stock:
        query = query.where(models.Product.stock > 0)

    # 👇 STEP 1: Get Total Count (Before Pagination)
    # We wrap the filtered query in a subquery to count rows efficiently
    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query)

    # 👇 DYNAMIC SORTING LOGIC
    if sort_by == 'price_asc':
        query = query.order_by(models.Product.price.asc())
    elif sort_by == 'price_desc':
        query = query.order_by(models.Product.price.desc())
    else:
        # Default to "newest" (ID desc)
        query = query.order_by(models.Product.id.desc())

    # 👇 STEP 2: Apply Pagination & Fetch Data
    query = query.limit(limit).offset(offset)
    result = await db.execute(query)
    data = result.scalars().all()

    # Return Object
    return {"data": data, "total": total or 0}


@router.get("/store/{store_id}", response_model=Page[ProductOut]) # 👈 Updated Response Model
async def get_store_products(
    store_id: int, 
    limit: int = Query(50, ge=1, le=100), 
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(database.get_db)
):
    """
    Get products for a specific store (Paginated + Total).
    """
    # Base Query
    query = select(models.Product).where(models.Product.store_id == store_id)

    # 1. Count
    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query)

    # 2. Fetch
    query = query.limit(limit).offset(offset)
    result = await db.execute(query)
    data = result.scalars().all()
    
    return {"data": data, "total": total or 0}


@router.post("/", response_model=ProductOut)
async def create_product(
    payload: ProductCreate,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_scope("products:manage"))
):
    svc = AsyncProductService(db)
    try:
        return await svc.create_product(payload, current_user)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Store not found")
    except PermissionDeniedError:
        raise HTTPException(status_code=403, detail="You do not own this store")


@router.get("/my-products", response_model=List[ProductOut])
async def get_my_products(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_scope("products:manage"))
):
    """Get products from stores owned by the current store owner (Paginated)."""
    # Note: If you want pagination on the dashboard too, you'd update this similarly
    # But for now I left it as List[ProductOut] to minimize breaking dashboard changes
    svc = AsyncProductService(db)
    return await svc.get_user_products(current_user, limit, offset)


@router.get("/{product_id}", response_model=ProductOut)
async def get_product(product_id: int, db: AsyncSession = Depends(database.get_db)):
    svc = AsyncProductService(db)
    try:
        return await svc.get_product(product_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Product not found")


@router.put("/{product_id}", response_model=ProductOut)
async def update_product(
    product_id: int,
    payload: ProductUpdate,
    bg_tasks: BackgroundTasks,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_scope("products:manage"))
):
    svc = AsyncProductService(db)
    try:
        return await svc.update_product(product_id, payload, current_user, bg_tasks)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Product not found")
    except PermissionDeniedError:
        raise HTTPException(status_code=403, detail="You do not own this product")


@router.delete("/{product_id}")
async def delete_product(
    product_id: int,
    bg_tasks: BackgroundTasks,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_scope("products:manage"))
):
    svc = AsyncProductService(db)
    try:
        await svc.delete_product(product_id, current_user, bg_tasks)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Product not found")
    except PermissionDeniedError:
        raise HTTPException(status_code=403, detail="You do not own this product")
        
    return {"detail": "Product deleted"}