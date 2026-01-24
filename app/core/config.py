# app/core/config.py
from pydantic_settings import BaseSettings
from pydantic import Field, field_validator, ConfigDict
from typing import List, Union
import os
import warnings


class Settings(BaseSettings):
    """Application settings with environment variable support and validation."""
    
    model_config = ConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False
    )
    
    # Security Settings
    SECRET_KEY: str = Field(
        ..., 
        description="Secret key for JWT encoding - MUST be set in production",
        min_length=32
    )
    ALGORITHM: str = Field(default="HS256", description="JWT algorithm")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(
        default=60, 
        ge=1, 
        le=10080,  # Max 1 week
        description="JWT token expiration time in minutes"
    )
    
    # Database Configuration  
    DATABASE_URL: str = Field(
        ...,
        description="Database connection URL"
    )
    
    # Application Settings
    DEBUG: bool = Field(default=False, description="Debug mode")
    ENVIRONMENT: str = Field(
        default="production", 
        description="Application environment"
    )
    
    # API Settings
    API_V1_STR: str = Field(default="/api/v1", description="API version prefix")
    PROJECT_NAME: str = Field(default="Mall Delivery API", description="Project name")
    
    # CORS Settings
    ALLOWED_ORIGINS: List[str] = Field(
        default=["http://localhost:3000"], 
        description="Allowed CORS origins"
    )
    
    # Logging
    LOG_LEVEL: str = Field(
        default="INFO", 
        description="Logging level"
    )

    # Database pool settings
    DB_POOL_SIZE: int = Field(default=20, description="Database connection pool size")
    DB_MAX_OVERFLOW: int = Field(default=10, description="Database connection pool max overflow")
    DB_POOL_PRE_PING: bool = Field(default=True, description="Enable pool_pre_ping to validate connections")

    # Observability
    SLOW_QUERY_THRESHOLD_MS: int = Field(default=100, description="Slow query threshold in milliseconds")
    
    @field_validator("SECRET_KEY")
    @classmethod
    def validate_secret_key(cls, v):
        """Ensure secret key is secure enough."""
        if v == "replace-this-with-a-real-secret":
            raise ValueError(
                "SECRET_KEY must be changed from default value in production! "
                "Generate a secure secret key using: python -c 'import secrets; print(secrets.token_urlsafe(32))'"
            )
        if len(v) < 32:
            warnings.warn("SECRET_KEY should be at least 32 characters long for security")
        return v
    
    @field_validator("DATABASE_URL")
    @classmethod  
    def validate_database_url(cls, v):
        """Basic validation for database URL format."""
        if not v.startswith(("postgresql://", "sqlite:///")):
            raise ValueError("DATABASE_URL must be a valid database URL")
        return v
    
    @field_validator("ENVIRONMENT")
    @classmethod
    def validate_environment(cls, v):
        """Validate environment value."""
        allowed_envs = ["development", "staging", "production", "testing"]
        if v.lower() not in allowed_envs:
            raise ValueError(f"ENVIRONMENT must be one of {allowed_envs}")
        return v.lower()


# Initialize settings
settings = Settings()

# Security check for production
if settings.ENVIRONMENT == "production":
    if settings.DEBUG:
        warnings.warn("DEBUG should be False in production environment")
    if "localhost" in settings.DATABASE_URL:
        warnings.warn("Using localhost database URL in production environment")
