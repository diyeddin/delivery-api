from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.db import models, database
from app.routers import auth, users, stores, products, orders, drivers, admin
from app.core.logging import setup_logging, get_logger, LoggingMiddleware
from app.middleware.idempotency import IdempotencyMiddleware
import time
import os

# Setup logging
setup_logging()
logger = get_logger(__name__)

# Create app
app = FastAPI(
    title="Mall Delivery API",
    description="A comprehensive API for mall delivery services",
    version="1.0.0"
)

# Add logging middleware
app.add_middleware(LoggingMiddleware)
# Add idempotency middleware (will only act on POST /orders and /payments)
app.add_middleware(IdempotencyMiddleware)

# Log application startup
logger.info("Application starting up", environment=os.getenv("ENVIRONMENT", "unknown"))


@app.get("/health")
def health_check():
    """Enhanced health check endpoint with database connectivity"""
    try:
        # Get current timestamp
        timestamp = int(time.time())
        
        # Basic response
        response = {
            "status": "healthy",
            "message": "Mall Delivery API is running",
            "timestamp": timestamp,
            "environment": os.getenv("ENVIRONMENT", "unknown"),
            "checks": {}
        }
        
        # Test database connectivity
        try:
            db = next(database.get_db())
            result = db.execute(text("SELECT 1")).fetchone()
            if result and result[0] == 1:
                response["checks"]["database"] = "healthy"
            else:
                response["checks"]["database"] = "unhealthy"
                response["status"] = "degraded"
        except Exception as e:
            response["checks"]["database"] = f"unhealthy: {str(e)}"
            response["status"] = "degraded"
        finally:
            db.close()
        
        return response
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Health check failed: {str(e)}")


@app.get("/health/ready")
def readiness_check(db: Session = Depends(database.get_db)):
    """Readiness check for Kubernetes/container orchestration"""
    try:
        # Test database connectivity and basic queries
        db.execute(text("SELECT 1")).fetchone()
        
        # Check if core tables exist
        user_count = db.execute(text("SELECT COUNT(*) FROM users")).fetchone()[0]
        
        return {
            "status": "ready",
            "message": "Service is ready to accept traffic",
            "database": "connected",
            "user_count": user_count
        }
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Service not ready: {str(e)}")


@app.get("/health/live")
def liveness_check():
    """Liveness check for Kubernetes/container orchestration"""
    return {
        "status": "alive",
        "message": "Service is alive",
        "timestamp": int(time.time())
    }


@app.get("/")
def root():
    """Root endpoint with API information"""
    return {
        "message": "Welcome to Mall Delivery API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
        "health_checks": {
            "basic": "/health",
            "readiness": "/health/ready", 
            "liveness": "/health/live"
        }
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
import sys as _sys

# Avoid creating database tables at import time during test runs (pytest imports the package)
if "pytest" not in _sys.modules:
    models.Base.metadata.create_all(bind=database.engine)
else:
    logger.info("Skipping metadata.create_all during pytest import")
