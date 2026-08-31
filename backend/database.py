import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker


load_dotenv(dotenv_path=".env")

DATABASE_URL = os.getenv("DATABASE_URL")


engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base()

if __name__ == "__main__":
    try:
        with engine.connect():
            print("Database connection successful")
    except Exception as error:
        print("Database connection failed")
        print(error)

def get_db():
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()