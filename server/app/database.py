"""SQLAlchemy access shared by the API's database-backed routes."""

from database.sqlalchemy_db import create_database_engine

__all__ = ["create_database_engine"]
