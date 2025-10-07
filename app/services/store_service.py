"""
Store service layer for business logic separation.
"""
from sqlalchemy.orm import Session
from typing import List, Optional
from app.db import models
from app.schemas.store import StoreCreate, StoreUpdate
from app.utils.exceptions import NotFoundError, PermissionDeniedError


class StoreService:
    """Service class for store-related business logic."""
    
    def __init__(self, db: Session):
        self.db = db
    
    def create_store(self, store_data: StoreCreate, current_user: models.User) -> models.Store:
        """Create a new store with proper ownership assignment."""
        store_dict = store_data.model_dump()
        
        # Set ownership based on user role
        if current_user.role == models.UserRole.store_owner:
            store_dict["owner_id"] = current_user.id
        # Admins can create stores without setting ownership (owner_id = None)
        
        db_store = models.Store(**store_dict)
        self.db.add(db_store)
        self.db.commit()
        self.db.refresh(db_store)
        return db_store
    
    def get_store(self, store_id: int) -> models.Store:
        """Get store by ID or raise NotFoundError."""
        store = self.db.query(models.Store).filter(models.Store.id == store_id).first()
        if not store:
            raise NotFoundError("Store", store_id)
        return store
    
    def get_all_stores(self) -> List[models.Store]:
        """Get all stores."""
        return self.db.query(models.Store).all()
    
    def update_store(
        self, 
        store_id: int, 
        update_data: StoreUpdate, 
        current_user: models.User
    ) -> models.Store:
        """Update store with proper permission checking."""
        store = self.get_store(store_id)
        
        # Permission check: store owners can only update their own stores
        if current_user.role == models.UserRole.store_owner:
            if store.owner_id != current_user.id:
                raise PermissionDeniedError("update", "store")
        
        # Apply updates
        for key, value in update_data.model_dump(exclude_unset=True).items():
            setattr(store, key, value)
        
        self.db.commit()
        self.db.refresh(store)
        return store
    
    def delete_store(self, store_id: int, current_user: models.User) -> None:
        """Delete store with proper permission checking."""
        store = self.get_store(store_id)
        
        # Permission check: store owners can only delete their own stores
        if current_user.role == models.UserRole.store_owner:
            if store.owner_id != current_user.id:
                raise PermissionDeniedError("delete", "store")
        
        self.db.delete(store)
        self.db.commit()
    
    def get_store_products(self, store_id: int) -> List[models.Product]:
        """Get all products for a specific store."""
        store = self.get_store(store_id)  # Validates store exists
        return store.products