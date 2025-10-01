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
    db_store = models.Store(**store.dict())
    db.add(db_store)
    db.commit()
    db.refresh(db_store)
    return db_store


@router.get("/", response_model=List[StoreOut])
def list_stores(db: Session = Depends(database.get_db)):
    return db.query(models.Store).all()


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
    for key, value in update.dict(exclude_unset=True).items():
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
    db.delete(db_store)
    db.commit()
    return {"detail": "Store deleted"}
