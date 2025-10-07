# app/routers/products.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from app.db import models, database
from app.schemas.product import ProductCreate, ProductOut, ProductUpdate
from app.utils.dependencies import require_role

router = APIRouter(prefix="/products", tags=["products"])

@router.post("/", response_model=ProductOut)
def create_product(
    payload: ProductCreate,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(require_role([models.UserRole.admin, models.UserRole.store_owner]))
    ):
    store = db.query(models.Store).filter(models.Store.id == payload.store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    
    # Store owners can only create products in their own stores
    if current_user.role == models.UserRole.store_owner:
        if store.owner_id != current_user.id:
            raise HTTPException(status_code=403, detail="You can only create products in your own stores")
    
    p = models.Product(**payload.model_dump())
    db.add(p); db.commit(); db.refresh(p)
    return p

@router.get("/", response_model=List[ProductOut])
def list_products(db: Session = Depends(database.get_db)):
    return db.query(models.Product).all()


@router.get("/my-products", response_model=List[ProductOut])
def get_my_products(
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(require_role([models.UserRole.store_owner]))
):
    """Get products from stores owned by the current store owner."""
    return db.query(models.Product).join(models.Store).filter(
        models.Store.owner_id == current_user.id
    ).all()


@router.get("/{product_id}", response_model=ProductOut)
def get_product(product_id: int, db: Session = Depends(database.get_db)):
    p = db.get(models.Product, product_id)
    if not p:
        raise HTTPException(status_code=404, detail="Product not found")
    return p

@router.put("/{product_id}", response_model=ProductOut)
def update_product(
    product_id: int,
    payload: ProductUpdate,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(require_role([models.UserRole.admin, models.UserRole.store_owner]))
    ):
    p = db.get(models.Product, product_id)
    if not p:
        raise HTTPException(status_code=404, detail="Product not found")
    
    # Store owners can only update products in their own stores
    if current_user.role == models.UserRole.store_owner:
        if p.store.owner_id != current_user.id:
            raise HTTPException(status_code=403, detail="You can only update products in your own stores")
    
    update_data = payload.model_dump(exclude_unset=True)
    if "store_id" in update_data:
        s = db.get(models.Store, update_data["store_id"])
        if not s:
            raise HTTPException(status_code=404, detail="New store not found")
        
        # Store owners can only move products to their own stores
        if current_user.role == models.UserRole.store_owner:
            if s.owner_id != current_user.id:
                raise HTTPException(status_code=403, detail="You can only move products to your own stores")
    
    for k, v in update_data.items():
        setattr(p, k, v)
    db.commit(); db.refresh(p)
    return p

@router.delete("/{product_id}")
def delete_product(
    product_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(require_role([models.UserRole.admin, models.UserRole.store_owner]))
    ):
    p = db.get(models.Product, product_id)
    if not p:
        raise HTTPException(status_code=404, detail="Product not found")
    
    # Store owners can only delete products from their own stores
    if current_user.role == models.UserRole.store_owner:
        if p.store.owner_id != current_user.id:
            raise HTTPException(status_code=403, detail="You can only delete products from your own stores")
    
    db.delete(p); db.commit()
    return {"detail": "Product deleted"}
