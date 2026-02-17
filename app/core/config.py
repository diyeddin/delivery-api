# app/core/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator, PostgresDsn, RedisDsn, AnyHttpUrl
from typing import List, Union, Optional
import warnings

class Settings(BaseSettings):
    """Application settings with environment variable support and validation."""
    
    # CRITICAL FIX: extra="ignore" prevents crashes when Docker passes system env vars
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"
    )
    
    # Security Settings
    SECRET_KEY: str = Field(
        ..., 
        description="Secret key for JWT encoding - MUST be set in production",
        min_length=32
    )
    ALGORITHM: str = Field(default="HS256", description="JWT algorithm")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(
        default=30, # 30 minutes
        ge=1,
        le=20160,  # Max 2 weeks
        description="JWT token expiration time in minutes"
    )
    # Added based on your error logs
    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(
        default=7,
        description="Refresh token expiration in days"
    )
    
    # Database Configuration
    # We allow Union[str, PostgresDsn] to handle both string URLs and Pydantic DSN objects
    DATABASE_URL: Union[str, PostgresDsn] = Field(
        ...,
        description="Database connection URL"
    )
    
    # Database Connection Components (Optional, but good to have defined to avoid errors)
    POSTGRES_USER: Optional[str] = "postgres"
    POSTGRES_PASSWORD: Optional[str] = "postgres"
    POSTGRES_SERVER: Optional[str] = "db"
    POSTGRES_PORT: Optional[str] = "5432"
    POSTGRES_DB: Optional[str] = "mall_delivery"

    # Redis Configuration (Critical for Celery & Idempotency)
    REDIS_URL: Union[str, RedisDsn] = Field(
        default="redis://redis:6379/0",
        description="Redis connection URL"
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
    
    # Pagination (Added based on your error logs)
    DEFAULT_PAGE_SIZE: int = Field(default=20, ge=1, le=100)
    MAX_PAGE_SIZE: int = Field(default=100, ge=1, le=1000)

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

    # Cloudinary Settings for Image Storage
    CLOUDINARY_CLOUD_NAME: str
    CLOUDINARY_API_KEY: str
    CLOUDINARY_API_SECRET: str
    
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
    
    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def validate_database_url(cls, v):
        """Basic validation for database URL format."""
        if v and isinstance(v, str) and not v.startswith(("postgresql", "sqlite")):
             # Relaxed check slightly to allow 'postgresql+asyncpg'
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
    # Convert DSN to string for check if needed
    db_url_str = str(settings.DATABASE_URL)
    if "localhost" in db_url_str and "postgres" in db_url_str:
        warnings.warn("Using localhost database URL in production environment")