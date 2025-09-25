# app/core/config.py
from pydantic_settings import BaseSettings  # instead of from pydantic import BaseSettings

class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://diyeddin:28353@localhost/mall_delivery"
    SECRET_KEY: str = "replace-this-with-a-real-secret"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    class Config:
        env_file = ".env"

settings = Settings()
