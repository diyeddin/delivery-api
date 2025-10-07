from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db import models, database
from app.schemas.store import StoreCreate, StoreUpdate, StoreOut
from typing import List
from app.utils.dependencies import require_role

router = APIRouter(prefix="/stores", tags=["stores"])

@router.post("/", response_model=StoreOut)
def create_store(
    store: StoreCreate,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(require_role([models.UserRole.admin, models.UserRole.store_owner]))
    ):
    store_data = store.model_dump()
    
    # Set the owner_id to the current user if they're a store_owner
    if current_user.role == models.UserRole.store_owner:
        store_data["owner_id"] = current_user.id
    # Admins can create stores without setting ownership (owner_id = None)
    
    db_store = models.Store(**store_data)
    db.add(db_store)
    db.commit()
    db.refresh(db_store)
    return db_store


@router.get("/", response_model=List[StoreOut])
def list_stores(db: Session = Depends(database.get_db)):
    return db.query(models.Store).all()


@router.get("/my-stores", response_model=List[StoreOut])
def get_my_stores(
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(require_role([models.UserRole.store_owner]))
):
    """Get stores owned by the current store owner."""
    return db.query(models.Store).filter(models.Store.owner_id == current_user.id).all()


@router.get("/{store_id}", response_model=StoreOut)
def get_store(store_id: int, db: Session = Depends(database.get_db)):
    store = db.query(models.Store).filter(models.Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    return store


@router.put("/{store_id}", response_model=StoreOut)
def update_store(
    store_id: int,
    update: StoreUpdate,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(require_role([models.UserRole.admin, models.UserRole.store_owner]))
    ):
    db_store = db.query(models.Store).filter(models.Store.id == store_id).first()
    if not db_store:
        raise HTTPException(status_code=404, detail="Store not found")
    
    # Store owners can only update their own stores
    if current_user.role == models.UserRole.store_owner:
        if db_store.owner_id != current_user.id:
            raise HTTPException(status_code=403, detail="You can only update your own stores")
    
    for key, value in update.model_dump(exclude_unset=True).items():
        setattr(db_store, key, value)
    db.commit()
    db.refresh(db_store)
    return db_store


@router.delete("/{store_id}")
def delete_store(
    store_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(require_role([models.UserRole.admin, models.UserRole.store_owner]))
    ):
    db_store = db.query(models.Store).filter(models.Store.id == store_id).first()
    if not db_store:
        raise HTTPException(status_code=404, detail="Store not found")
    
    # Store owners can only delete their own stores
    if current_user.role == models.UserRole.store_owner:
        if db_store.owner_id != current_user.id:
            raise HTTPException(status_code=403, detail="You can only delete your own stores")
    
    db.delete(db_store)
    db.commit()
    return {"detail": "Store deleted"}


@router.get("/{store_id}/products")
def get_store_products(
    store_id: int,
    db: Session = Depends(database.get_db)
):
    """Get all products for a specific store"""
    # Check if store exists
    store = db.query(models.Store).filter(models.Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    
    # Get all products for this store
    products = db.query(models.Product).filter(models.Product.store_id == store_id).all()
    return products
