from fastapi import FastAPI
from app.db import models, database
from app.routers import auth, products, stores, users

# Create app
app = FastAPI()

# Include routers
app.include_router(auth.router)
app.include_router(products.router)
app.include_router(stores.router)
app.include_router(users.router)

# Create database tables
models.Base.metadata.create_all(bind=database.engine)
