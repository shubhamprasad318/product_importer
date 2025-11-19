from pydantic import BaseModel, Field, HttpUrl
from typing import Optional
from datetime import datetime
from decimal import Decimal

class ProductBase(BaseModel):
    sku: str = Field(..., max_length=255)
    name: str = Field(..., max_length=500)
    description: Optional[str] = None
    price: Optional[Decimal] = Field(None, ge=0, decimal_places=2)
    is_active: bool = True

class ProductCreate(ProductBase):
    pass

class ProductUpdate(ProductBase):
    sku: Optional[str] = None
    name: Optional[str] = None

class Product(ProductBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True

class WebhookBase(BaseModel):
    url: HttpUrl
    event_type: str
    is_active: bool = True

class WebhookCreate(WebhookBase):
    pass

class Webhook(WebhookBase):
    id: int
    created_at: datetime
    
    class Config:
        from_attributes = True

class UploadResponse(BaseModel):
    task_id: str
    message: str

class TaskStatus(BaseModel):
    task_id: str
    state: str
    current: int = 0
    total: int = 0
    percent: int = 0
    result: Optional[dict] = None
    error: Optional[str] = None
