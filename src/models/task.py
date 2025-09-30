from sqlalchemy import Column, String, Integer, DateTime, PrimaryKeyConstraint
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()

class Task(Base):
    __tablename__ = "Task"

    task_id = Column(Integer, primary_key=True)
    name = Column(String)
    status = Column(String)
    created_at = Column(DateTime, default=lambda: datetime.now())
    updated_at = Column(DateTime, default=lambda: datetime.now(), onupdate=lambda: datetime.now())
