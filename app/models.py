from sqlalchemy import Column, Integer, String, Numeric, Boolean, DateTime, Text, Index
from sqlalchemy.sql import func
from .database import Base

class Product(Base):
    __tablename__ = "products"
    
    id = Column(Integer, primary_key=True, index=True)
    sku = Column(String(255), unique=True, nullable=False)
    name = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)
    price = Column(Numeric(10, 2), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Create case-insensitive unique index on SKU
    __table_args__ = (
        Index('idx_sku_upper', func.upper(sku), unique=True),
    )
    
    def __repr__(self):
        return f"<Product(sku='{self.sku}', name='{self.name}')>"


class Webhook(Base):
    __tablename__ = "webhooks"
    
    id = Column(Integer, primary_key=True, index=True)
    url = Column(String(500), nullable=False)
    event_type = Column(String(100), nullable=False)  # product.created, product.updated, etc.
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    def __repr__(self):
        return f"<Webhook(url='{self.url}', event='{self.event_type}')>"
