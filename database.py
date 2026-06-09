from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = "sqlite:///./bewertungen.db"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False}
)
# test

SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()