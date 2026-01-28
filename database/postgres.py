import os
import dotenv
from loguru import logger
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    async_sessionmaker,
    AsyncSession,
    AsyncEngine
)
from core.config import DATABASE_URL
try:
    from schemas.schemas import Base
except ImportError as e:
    logger.error("Could not import 'Base' from 'schemas.schemas'. Check your file structure.")
    raise e

dotenv.load_dotenv()

# Global variables
engine: AsyncEngine 
AsyncSessionLocal: async_sessionmaker 

async def init_postgres() -> None:
    """
    Initialize SQLAlchemy AsyncEngine and create tables if they don't exist.
    """
    global engine, AsyncSessionLocal

    db_url = DATABASE_URL
    if not db_url:
        logger.error("DATABASE_URL not found in .env")
        raise ValueError("DATABASE_URL not set")
    
    # Fix protocol for AsyncPG
    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    try:
        logger.info("Initializing PostgreSQL (SQLAlchemy) connection...")

        engine = create_async_engine(
            db_url,
            echo=False,        
            pool_size=10,        
            max_overflow=20,     
            pool_pre_ping=True   
        )

        AsyncSessionLocal = async_sessionmaker(
            bind=engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False
        )

        logger.info("PostgreSQL connection engine created successfully.")

        # Create Tables
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        
        logger.info("Database tables verified/created successfully.")

    except Exception as e:
        logger.error(f"Error initializing Database: {e}")
        raise

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency for FastAPI Routes.
    """
    if AsyncSessionLocal is None:
        raise ConnectionError("Database is not initialized. Call init_postgres() first.")
    
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()

async def close_postgres() -> None:
    global engine
    if engine:
        try:
            logger.info("Closing Database connection...")
            await engine.dispose()
            logger.info("Database connection closed successfully.")
        except Exception as e:
            logger.error(f"Error closing Database connection: {e}")
            raise
    else:
        logger.warning("Database was not initialized.")