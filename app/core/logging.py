"""
Logging configuration for Mall Delivery API
Provides structured JSON logging for production environments
"""
import logging
import logging.config
import structlog
import sys
from typing import Any, Dict
from app.core.config import settings


def setup_logging() -> None:
    """Configure structured logging for the application"""
    
    # Configure standard library logging
    logging_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "json": {
                "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
                "format": "%(asctime)s %(name)s %(levelname)s %(message)s %(pathname)s %(lineno)d %(funcName)s %(process)d %(thread)d"
            },
            "console": {
                "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            }
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "json" if settings.ENVIRONMENT == "production" else "console",
                "stream": sys.stdout
            },
            "file": {
                "class": "logging.handlers.RotatingFileHandler",
                "filename": "logs/app.log",
                "maxBytes": 10485760,  # 10MB
                "backupCount": 5,
                "formatter": "json"
            }
        },
        "loggers": {
            "": {  # Root logger
                "handlers": ["console"],
                "level": settings.LOG_LEVEL,
                "propagate": False
            },
            "uvicorn": {
                "handlers": ["console"],
                "level": "INFO",
                "propagate": False
            },
            "uvicorn.access": {
                "handlers": ["console"], 
                "level": "INFO",
                "propagate": False
            },
            "sqlalchemy.engine": {
                "handlers": ["console"],
                "level": "WARNING" if settings.ENVIRONMENT == "production" else "INFO",
                "propagate": False
            },
            "app": {
                "handlers": ["console"],
                "level": settings.LOG_LEVEL,
                "propagate": False
            }
        }
    }
    
    # Add file handler for production
    if settings.ENVIRONMENT == "production":
        logging_config["loggers"][""]["handlers"].append("file")
        logging_config["loggers"]["app"]["handlers"].append("file")
    
    # Apply logging configuration
    logging.config.dictConfig(logging_config)
    
    # Configure structlog
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            add_request_context,
            structlog.processors.JSONRenderer() if settings.ENVIRONMENT == "production" 
            else structlog.dev.ConsoleRenderer()
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


def add_request_context(logger: Any, method_name: str, event_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Add request context to log entries"""
    # This will be enhanced with middleware to add request ID, user ID, etc.
    event_dict["service"] = "mall-delivery-api"
    event_dict["version"] = "1.0.0"
    return event_dict


def get_logger(name: str = None) -> structlog.stdlib.BoundLogger:
    """Get a configured logger instance"""
    return structlog.get_logger(name or "app")


# Create default logger instance
logger = get_logger(__name__)


class LoggingMiddleware:
    """ASGI middleware for request/response logging"""
    
    def __init__(self, app):
        self.app = app
    
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        
        import time
        import uuid
        
        # Generate request ID
        request_id = str(uuid.uuid4())
        
        # Add request context
        request_logger = get_logger("request").bind(
            request_id=request_id,
            method=scope["method"],
            path=scope["path"],
            query_string=scope.get("query_string", b"").decode()
        )
        
        start_time = time.time()
        
        # Log request start
        request_logger.info("Request started")
        
        # Capture response status
        response_status = 500
        
        async def send_wrapper(message):
            nonlocal response_status
            if message["type"] == "http.response.start":
                response_status = message["status"]
            await send(message)
        
        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as e:
            request_logger.error("Request failed", error=str(e), exc_info=True)
            raise
        finally:
            # Log request completion
            duration = time.time() - start_time
            request_logger.info(
                "Request completed",
                status_code=response_status,
                duration_ms=round(duration * 1000, 2)
            )


# Security and audit logging helpers
def log_auth_event(event_type: str, user_email: str = None, success: bool = True, **kwargs):
    """Log authentication/authorization events"""
    auth_logger = get_logger("auth")
    auth_logger.info(
        "Authentication event",
        event_type=event_type,
        user_email=user_email,
        success=success,
        **kwargs
    )


def log_business_event(event_type: str, user_id: int = None, **kwargs):
    """Log business events (orders, payments, etc.)"""
    business_logger = get_logger("business")
    business_logger.info(
        "Business event",
        event_type=event_type,
        user_id=user_id,
        **kwargs
    )


def log_security_event(event_type: str, severity: str = "medium", **kwargs):
    """Log security events"""
    security_logger = get_logger("security")
    
    # Map severity levels to logging methods
    severity_mapping = {
        "low": "info",
        "medium": "warning", 
        "high": "error",
        "critical": "critical"
    }
    
    method_name = severity_mapping.get(severity.lower(), "warning")
    log_method = getattr(security_logger, method_name, security_logger.warning)
    
    log_method(
        "Security event",
        event_type=event_type,
        severity=severity,
        **kwargs
    )