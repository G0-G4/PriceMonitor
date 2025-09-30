from sqlalchemy import Column, String, Integer, Date, PrimaryKeyConstraint
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

class Parameter(Base):
    __tablename__ = "Parameter"

    parameter_id = Column(Integer, primary_key=True)
    name = Column(String, index=True)
    value = Column(String)
