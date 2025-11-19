from sqlalchemy.orm import Session
from sqlalchemy import func, or_
from typing import List, Optional
from . import models, schemas

def get_product(db: Session, product_id: int) -> Optional[models.Product]:
    return db.query(models.Product).filter(models.Product.id == product_id).first()

def get_product_by_sku(db: Session, sku: str) -> Optional[models.Product]:
    return db.query(models.Product).filter(
        func.upper(models.Product.sku) == sku.upper()
    ).first()

def get_products(
    db: Session, 
    skip: int = 0, 
    limit: int = 100,
    search: Optional[str] = None,
    is_active: Optional[bool] = None
) -> List[models.Product]:
    query = db.query(models.Product)
    
    if search:
        search_filter = f"%{search}%"
        query = query.filter(
            or_(
                models.Product.sku.ilike(search_filter),
                models.Product.name.ilike(search_filter),
                models.Product.description.ilike(search_filter)
            )
        )
    
    if is_active is not None:
        query = query.filter(models.Product.is_active == is_active)
    
    return query.offset(skip).limit(limit).all()

def get_products_count(
    db: Session,
    search: Optional[str] = None,
    is_active: Optional[bool] = None
) -> int:
    query = db.query(func.count(models.Product.id))
    
    if search:
        search_filter = f"%{search}%"
        query = query.filter(
            or_(
                models.Product.sku.ilike(search_filter),
                models.Product.name.ilike(search_filter),
                models.Product.description.ilike(search_filter)
            )
        )
    
    if is_active is not None:
        query = query.filter(models.Product.is_active == is_active)
    
    return query.scalar()

def create_product(db: Session, product: schemas.ProductCreate) -> models.Product:
    db_product = models.Product(**product.model_dump())
    db.add(db_product)
    db.commit()
    db.refresh(db_product)
    return db_product

def update_product(
    db: Session, 
    product_id: int, 
    product: schemas.ProductUpdate
) -> Optional[models.Product]:
    db_product = get_product(db, product_id)
    if db_product:
        update_data = product.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(db_product, field, value)
        db.commit()
        db.refresh(db_product)
    return db_product

def delete_product(db: Session, product_id: int) -> bool:
    db_product = get_product(db, product_id)
    if db_product:
        db.delete(db_product)
        db.commit()
        return True
    return False

def delete_all_products(db: Session) -> int:
    count = db.query(models.Product).delete()
    db.commit()
    return count

# Webhook CRUD operations
def create_webhook(db: Session, webhook: schemas.WebhookCreate) -> models.Webhook:
    db_webhook = models.Webhook(**webhook.model_dump())
    db.add(db_webhook)
    db.commit()
    db.refresh(db_webhook)
    return db_webhook

def get_webhooks(db: Session) -> List[models.Webhook]:
    return db.query(models.Webhook).all()

def delete_webhook(db: Session, webhook_id: int) -> bool:
    db_webhook = db.query(models.Webhook).filter(models.Webhook.id == webhook_id).first()
    if db_webhook:
        db.delete(db_webhook)
        db.commit()
        return True
    return False

def update_webhook(
    db: Session, 
    webhook_id: int, 
    is_active: bool
) -> Optional[models.Webhook]:
    db_webhook = db.query(models.Webhook).filter(models.Webhook.id == webhook_id).first()
    if db_webhook:
        db_webhook.is_active = is_active
        db.commit()
        db.refresh(db_webhook)
    return db_webhook
