# app/routers/products.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from app.db import models, database
from app.schemas.product import ProductCreate, ProductOut, ProductUpdate
from app.services.product_service import AsyncProductService
from app.utils.exceptions import NotFoundError, PermissionDeniedError
from app.utils.dependencies import require_scope

router = APIRouter(prefix="/products", tags=["products"])

@router.get("/", response_model=List[ProductOut])
async def get_products(
    q: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    in_stock: bool = False, # Changed default to False so owners see out-of-stock items by default in management
    store_id: Optional[int] = None, # Added store_id filter
    db: AsyncSession = Depends(database.get_db)
):
    """
    Global Product Search & Filter.
    """
    query = select(models.Product) #.where(models.Product.is_active == True)
    
    # 1. Search Logic (Name or Description)
    if q:
        search_text = f"%{q}%"
        query = query.where(
            or_(
                models.Product.name.ilike(search_text),
                models.Product.description.ilike(search_text)
            )
        )
    
    # 2. Filter by Store
    if store_id:
        query = query.where(models.Product.store_id == store_id)

    # 3. Price Filters
    if min_price is not None:
        query = query.where(models.Product.price >= min_price)
    if max_price is not None:
        query = query.where(models.Product.price <= max_price)
        
    # 4. Stock Filter (Optional)
    if in_stock:
        query = query.where(models.Product.stock > 0)

    result = await db.execute(query)
    return result.scalars().all()


@router.get("/store/{store_id}", response_model=List[ProductOut])
async def get_store_products(
    store_id: int, 
    db: AsyncSession = Depends(database.get_db)
):
    """
    Helper endpoint to get all products for a specific store.
    Useful for the Store Manager UI.
    """
    query = select(models.Product).where(
        models.Product.store_id == store_id,
        # models.Product.is_active == True
    )
    result = await db.execute(query)
    return result.scalars().all()


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
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_scope("products:manage"))
):
    """Get products from stores owned by the current store owner."""
    svc = AsyncProductService(db)
    return await svc.get_user_products(current_user)


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
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_scope("products:manage"))
):
    svc = AsyncProductService(db)
    try:
        return await svc.update_product(product_id, payload, current_user)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Product not found")
    except PermissionDeniedError:
        raise HTTPException(status_code=403, detail="You do not own this product")


@router.delete("/{product_id}")
async def delete_product(
    product_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_scope("products:manage"))
):
    svc = AsyncProductService(db)
    try:
        await svc.delete_product(product_id, current_user)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Product not found")
    except PermissionDeniedError:
        raise HTTPException(status_code=403, detail="You do not own this product")
        
    return {"detail": "Product deleted"}