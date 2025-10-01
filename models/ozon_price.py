from sqlalchemy import Column, String, Float, Date, PrimaryKeyConstraint
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()

class OzonPrice(Base):
    __tablename__ = "OzonPrice"
    
    company_id = Column(String, primary_key=True)
    item_id = Column(String, index=True)
    offer_id = Column(String, primary_key=True)
    date = Column(Date, primary_key=True)
    marketing_seller_price = Column(Float)
    old_price = Column(Float)
    marketing_price = Column(Float)
    marketing_oa_price = Column(Float)
