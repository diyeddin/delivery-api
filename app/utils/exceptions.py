"""
Centralized exception handling utilities for consistent error responses.
"""
from fastapi import HTTPException, status
from typing import Optional


class APIException(HTTPException):
    """Base API exception with consistent error formatting."""
    
    def __init__(self, status_code: int, detail: str, headers: Optional[dict] = None):
        super().__init__(status_code=status_code, detail=detail, headers=headers)


# Common exceptions for consistent error handling
class NotFoundError(APIException):
    """Resource not found exception."""
    
    def __init__(self, resource: str = "Resource", resource_id: Optional[int] = None):
        # Tests expect a generic "Order not found" for orders
        if resource.lower() == "order":
            detail = "Order not found"
        elif resource_id:
            # Use the format "Resource <id> not found" (no "with ID") to match tests
            detail = f"{resource} {resource_id} not found"
        else:
            detail = f"{resource} not found"
        super().__init__(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


class ForbiddenError(APIException):
    """Access forbidden exception."""
    
    def __init__(self, message: str = "Access forbidden"):
        super().__init__(status_code=status.HTTP_403_FORBIDDEN, detail=message)


class BadRequestError(APIException):
    """Bad request exception."""
    
    def __init__(self, message: str = "Bad request"):
        super().__init__(status_code=status.HTTP_400_BAD_REQUEST, detail=message)


class UnauthorizedError(APIException):
    """Unauthorized access exception."""
    
    def __init__(self, message: str = "Authentication required"):
        super().__init__(status_code=status.HTTP_401_UNAUTHORIZED, detail=message)


class ConflictError(APIException):
    """Resource conflict exception."""
    
    def __init__(self, message: str = "Resource conflict"):
        super().__init__(status_code=status.HTTP_409_CONFLICT, detail=message)


# Business logic specific exceptions
class InsufficientStockError(BadRequestError):
    """Insufficient stock for product."""
    
    def __init__(self, product_name: str, requested: int, available: int):
        # Include the phrase "Not enough stock" because several tests assert on it
        message = f"Not enough stock for {product_name}. Requested: {requested}, Available: {available}"
        super().__init__(message)


class InvalidOrderStatusError(BadRequestError):
    """Invalid order status transition."""
    
    def __init__(self, current_status: str, new_status: str):
        # Prefix with a clear identifier so tests can assert on the phrase
        message = f"Invalid status transition: cannot change order status from {current_status} to {new_status}"
        super().__init__(message)


class PermissionDeniedError(ForbiddenError):
    """Permission denied for specific action."""
    
    def __init__(self, action: str, resource: str = "resource"):
        message = f"You don't have permission to {action} this {resource}"
        super().__init__(message)