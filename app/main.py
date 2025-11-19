from fastapi import FastAPI, UploadFile, File, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from typing import List, Optional
import asyncio
import json
import os
import shutil
from pathlib import Path

from .database import get_db, init_db
from .tasks import celery_app, import_products_task
from . import models, schemas, crud
from .config import settings

app = FastAPI(title=settings.APP_NAME, debug=settings.DEBUG)

# Create upload directory
Path(settings.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)

# Setup templates and static files
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

# Initialize database on startup
@app.on_event("startup")
def startup_event():
    init_db()

# Root endpoint - serve UI
@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

# File Upload Endpoint
@app.post("/api/upload", response_model=schemas.UploadResponse)
async def upload_csv(
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """
    Upload CSV file and trigger async import task
    """
    # Validate file type
    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="Only CSV files are allowed")
    
    # Save uploaded file
    file_path = os.path.join(settings.UPLOAD_DIR, file.filename)
    
    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")
    finally:
        file.file.close()
    
    # Trigger Celery task
    task = import_products_task.delay(file_path)
    
    return schemas.UploadResponse(
        task_id=task.id,
        message="Upload started. Track progress using the task ID."
    )

# Server-Sent Events for progress tracking
@app.get("/api/progress/{task_id}")
async def stream_progress(task_id: str):
    """
    Stream real-time progress updates using Server-Sent Events
    """
    async def event_generator():
        while True:
            task = celery_app.AsyncResult(task_id)
            
            data = {
                'task_id': task_id,
                'state': task.state,
            }
            
            if task.state == 'PENDING':
                data.update({
                    'status': 'Waiting to start...',
                    'percent': 0
                })
            elif task.state == 'PROGRESS':
                data.update(task.info)
            elif task.state == 'SUCCESS':
                data.update({
                    'status': 'Complete!',
                    'percent': 100,
                    'result': task.result
                })
                yield f"data: {json.dumps(data)}\n\n"
                break
            elif task.state == 'FAILURE':
                data.update({
                    'status': 'Failed',
                    'error': str(task.info)
                })
                yield f"data: {json.dumps(data)}\n\n"
                break
            
            yield f"data: {json.dumps(data)}\n\n"
            await asyncio.sleep(0.5)
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )

# Product CRUD Endpoints
@app.get("/api/products", response_model=dict)
def list_products(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    search: Optional[str] = None,
    is_active: Optional[bool] = None,
    db: Session = Depends(get_db)
):
    products = crud.get_products(db, skip=skip, limit=limit, search=search, is_active=is_active)
    total = crud.get_products_count(db, search=search, is_active=is_active)
    
    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "items": [schemas.Product.model_validate(p) for p in products]
    }

@app.get("/api/products/{product_id}", response_model=schemas.Product)
def get_product(product_id: int, db: Session = Depends(get_db)):
    product = crud.get_product(db, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product

@app.post("/api/products", response_model=schemas.Product, status_code=201)
def create_product(product: schemas.ProductCreate, db: Session = Depends(get_db)):
    # Check if SKU already exists
    existing = crud.get_product_by_sku(db, product.sku)
    if existing:
        raise HTTPException(status_code=400, detail="SKU already exists")
    
    return crud.create_product(db, product)

@app.put("/api/products/{product_id}", response_model=schemas.Product)
def update_product(
    product_id: int,
    product: schemas.ProductUpdate,
    db: Session = Depends(get_db)
):
    updated = crud.update_product(db, product_id, product)
    if not updated:
        raise HTTPException(status_code=404, detail="Product not found")
    return updated

@app.delete("/api/products/{product_id}")
def delete_product(product_id: int, db: Session = Depends(get_db)):
    success = crud.delete_product(db, product_id)
    if not success:
        raise HTTPException(status_code=404, detail="Product not found")
    return {"message": "Product deleted successfully"}

@app.delete("/api/products")
def delete_all_products(db: Session = Depends(get_db)):
    count = crud.delete_all_products(db)
    return {"message": f"Deleted {count} products"}

# Webhook Endpoints
@app.get("/api/webhooks", response_model=List[schemas.Webhook])
def list_webhooks(db: Session = Depends(get_db)):
    return crud.get_webhooks(db)

@app.post("/api/webhooks", response_model=schemas.Webhook, status_code=201)
def create_webhook(webhook: schemas.WebhookCreate, db: Session = Depends(get_db)):
    return crud.create_webhook(db, webhook)

@app.delete("/api/webhooks/{webhook_id}")
def delete_webhook(webhook_id: int, db: Session = Depends(get_db)):
    success = crud.delete_webhook(db, webhook_id)
    if not success:
        raise HTTPException(status_code=404, detail="Webhook not found")
    return {"message": "Webhook deleted successfully"}

@app.patch("/api/webhooks/{webhook_id}")
def toggle_webhook(
    webhook_id: int,
    is_active: bool,
    db: Session = Depends(get_db)
):
    webhook = crud.update_webhook(db, webhook_id, is_active)
    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")
    return webhook

@app.post("/api/webhooks/{webhook_id}/test")
async def test_webhook(webhook_id: int, db: Session = Depends(get_db)):
    webhook = db.query(models.Webhook).filter(models.Webhook.id == webhook_id).first()
    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")
    
    import httpx
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                str(webhook.url),
                json={'event': 'test', 'data': {'message': 'Test webhook'}}
            )
            return {
                "status_code": response.status_code,
                "response_time_ms": response.elapsed.total_seconds() * 1000,
                "success": response.status_code < 400
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Webhook test failed: {str(e)}")

# Health check
@app.get("/health")
def health_check():
    return {"status": "healthy"}
