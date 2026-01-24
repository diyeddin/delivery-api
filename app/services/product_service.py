"""
Product service layer for business logic separation.
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from app.db import models
from app.schemas.product import ProductCreate, ProductUpdate
from app.utils.exceptions import NotFoundError, PermissionDeniedError

class AsyncProductService:
    """Async product service using AsyncSession."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_product(self, product_data: ProductCreate, current_user: models.User) -> models.Product:
        result = await self.db.execute(select(models.Store).where(models.Store.id == product_data.store_id))
        store = result.unique().scalar_one_or_none()
        if not store:
            raise NotFoundError("Store", product_data.store_id)

        if current_user.role == models.UserRole.store_owner:
            if store.owner_id != current_user.id:
                raise PermissionDeniedError("create products in", "store")

        db_product = models.Product(**product_data.model_dump())
        self.db.add(db_product)
        await self.db.commit()
        await self.db.refresh(db_product)
        return db_product

    async def get_product(self, product_id: int) -> models.Product:
        result = await self.db.execute(select(models.Product).where(models.Product.id == product_id))
        product = result.unique().scalar_one_or_none()
        if not product:
            raise NotFoundError("Product", product_id)
        return product

    async def get_all_products(self):
        result = await self.db.execute(select(models.Product))
        return result.unique().scalars().all()

    async def get_user_products(self, current_user: models.User):
        result = await self.db.execute(
            select(models.Product).join(models.Store).where(models.Store.owner_id == current_user.id)
        )
        return result.unique().scalars().all()

    async def update_product(self, product_id: int, update_data: ProductUpdate, current_user: models.User):
        product = await self.get_product(product_id)
        if current_user.role == models.UserRole.store_owner:
            if product.store.owner_id != current_user.id:
                raise PermissionDeniedError("update", "product")

        update_dict = update_data.model_dump(exclude_unset=True)
        if "store_id" in update_dict:
            result = await self.db.execute(select(models.Store).where(models.Store.id == update_dict["store_id"]))
            new_store = result.unique().scalar_one_or_none()
            if not new_store:
                raise NotFoundError("Store", update_dict["store_id"])
            if current_user.role == models.UserRole.store_owner:
                if new_store.owner_id != current_user.id:
                    raise PermissionDeniedError("move products to", "store")

        for key, value in update_dict.items():
            setattr(product, key, value)

        await self.db.commit()
        await self.db.refresh(product)
        return product

    async def delete_product(self, product_id: int, current_user: models.User):
        product = await self.get_product(product_id)
        if current_user.role == models.UserRole.store_owner:
            if product.store.owner_id != current_user.id:
                raise PermissionDeniedError("delete", "product")
        await self.db.delete(product)
        await self.db.commit()

    async def check_stock_availability(self, product_id: int, quantity: int) -> bool:
        product = await self.get_product(product_id)
        return product.stock >= quantity

    async def reserve_stock(self, product_id: int, quantity: int) -> models.Product:
        product = await self.get_product(product_id)
        if product.stock < quantity:
            from app.utils.exceptions import InsufficientStockError
            raise InsufficientStockError(product.name, quantity, product.stock)
        product.stock -= quantity
        await self.db.commit()
        await self.db.refresh(product)
        return product
    
    async def release_stock(self, product_id: int, quantity: int):
        """Re-add stock when an order is cancelled."""
        # Use atomic update to avoid race conditions
        stmt = (
            update(models.Product)
            .where(models.Product.id == product_id)
            .values(stock=models.Product.stock + quantity)
        )
        await self.db.execute(stmt)