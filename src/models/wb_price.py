from sqlalchemy import Column, String, Float, Date, Integer, BigInteger

from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


class WbPrice(Base):
    __tablename__ = "WbPrice"

    account = Column(String, primary_key=True)
    nm_id = Column(BigInteger, primary_key=True, index=True)
    vendor_code = Column(String, index=True)
    size_id = Column(BigInteger, primary_key=True)
    tech_size_name = Column(String)
    name = Column(String)
    date = Column(Date, primary_key=True)
    price = Column(Float)
    discounted_price = Column(Float)
    club_discounted_price = Column(Float)
    discount = Column(Integer)
    club_discount = Column(Integer)
    wb_discount = Column(Integer)
