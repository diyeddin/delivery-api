-- Initialize the database for Mall Delivery API
-- This script is run when the PostgreSQL container starts for the first time

-- Create the main database (already done by POSTGRES_DB env var)
-- CREATE DATABASE mall_delivery;

-- Enable extensions if needed
-- CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
-- CREATE EXTENSION IF NOT EXISTS "postgis"; -- For location services in the future

-- Grant permissions
GRANT ALL PRIVILEGES ON DATABASE mall_delivery TO postgres;

-- The application will handle table creation via Alembic migrations