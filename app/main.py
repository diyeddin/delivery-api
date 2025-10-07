from fastapi import FastAPI
from app.db import models, database
from app.routers import auth, users, stores, products, orders, drivers, admin

# Create app
app = FastAPI()


@app.get("/health")
def health_check():
    """Basic health check endpoint"""
    return {"status": "healthy", "message": "Mall Delivery API is running"}


@app.get("/")
def root():
    """Root endpoint with API information"""
    return {
        "message": "Welcome to Mall Delivery API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health"
    }

# Include routers
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(products.router)
app.include_router(stores.router)
app.include_router(orders.router)
app.include_router(drivers.router)
app.include_router(admin.router)

# Create database tables
models.Base.metadata.create_all(bind=database.engine)
