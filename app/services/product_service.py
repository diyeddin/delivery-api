"""
Product service layer for business logic separation.
"""
from sqlalchemy.orm import Session
from typing import List, Optional
from app.db import models
from app.schemas.product import ProductCreate, ProductUpdate
from app.utils.exceptions import NotFoundError, PermissionDeniedError


class ProductService:
    """Service class for product-related business logic."""
    
    def __init__(self, db: Session):
        self.db = db
    
    def create_product(self, product_data: ProductCreate, current_user: models.User) -> models.Product:
        """Create a new product with proper store ownership validation."""
        # Validate store exists
        store = self.db.query(models.Store).filter(models.Store.id == product_data.store_id).first()
        if not store:
            raise NotFoundError("Store", product_data.store_id)
        
        # Permission check: store owners can only create products in their own stores
        if current_user.role == models.UserRole.store_owner:
            if store.owner_id != current_user.id:
                raise PermissionDeniedError("create products in", "store")
        
        db_product = models.Product(**product_data.model_dump())
        self.db.add(db_product)
        self.db.commit()
        self.db.refresh(db_product)
        return db_product
    
    def get_product(self, product_id: int) -> models.Product:
        """Get product by ID or raise NotFoundError."""
        product = self.db.get(models.Product, product_id)
        if not product:
            raise NotFoundError("Product", product_id)
        return product
    
    def get_all_products(self) -> List[models.Product]:
        """Get all products."""
        return self.db.query(models.Product).all()
    
    def get_user_products(self, current_user: models.User) -> List[models.Product]:
        """Get products from stores owned by the current store owner."""
        return self.db.query(models.Product).join(models.Store).filter(
            models.Store.owner_id == current_user.id
        ).all()
    
    def update_product(
        self, 
        product_id: int, 
        update_data: ProductUpdate, 
        current_user: models.User
    ) -> models.Product:
        """Update product with proper permission checking."""
        product = self.get_product(product_id)
        
        # Permission check: store owners can only update products in their own stores
        if current_user.role == models.UserRole.store_owner:
            if product.store.owner_id != current_user.id:
                raise PermissionDeniedError("update", "product")
        
        update_dict = update_data.model_dump(exclude_unset=True)
        
        # Validate new store if store_id is being updated
        if "store_id" in update_dict:
            new_store = self.db.get(models.Store, update_dict["store_id"])
            if not new_store:
                raise NotFoundError("Store", update_dict["store_id"])
            
            # Store owners can only move products to their own stores
            if current_user.role == models.UserRole.store_owner:
                if new_store.owner_id != current_user.id:
                    raise PermissionDeniedError("move products to", "store")
        
        # Apply updates
        for key, value in update_dict.items():
            setattr(product, key, value)
        
        self.db.commit()
        self.db.refresh(product)
        return product
    
    def delete_product(self, product_id: int, current_user: models.User) -> None:
        """Delete product with proper permission checking."""
        product = self.get_product(product_id)
        
        # Permission check: store owners can only delete products from their own stores
        if current_user.role == models.UserRole.store_owner:
            if product.store.owner_id != current_user.id:
                raise PermissionDeniedError("delete", "product")
        
        self.db.delete(product)
        self.db.commit()
    
    def check_stock_availability(self, product_id: int, quantity: int) -> bool:
        """Check if enough stock is available for a product."""
        product = self.get_product(product_id)
        return product.stock >= quantity
    
    def reserve_stock(self, product_id: int, quantity: int) -> models.Product:
        """Reserve stock for an order (decrease available stock)."""
        product = self.get_product(product_id)
        
        if product.stock < quantity:
            from app.utils.exceptions import InsufficientStockError
            raise InsufficientStockError(product.name, quantity, product.stock)
        
        product.stock -= quantity
        self.db.commit()
        self.db.refresh(product)
        return product