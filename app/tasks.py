from celery import Celery, Task
from celery.utils.log import get_task_logger
import pandas as pd
from io import StringIO
import psycopg2
from sqlalchemy import text
from .config import settings
from .database import SessionLocal
import os
import httpx

logger = get_task_logger(__name__)

celery_app = Celery(
    "tasks",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND
)

celery_app.conf.update(
    task_track_started=True,
    task_serializer='json',
    result_serializer='json',
    accept_content=['json'],
    timezone='UTC',
    enable_utc=True,
)


@celery_app.task(bind=True, name='tasks.import_products')
def import_products_task(self: Task, file_path: str) -> dict:
    """
    Import products from CSV file with progress tracking
    Uses PostgreSQL COPY for optimal performance
    """
    try:
        logger.info(f"Starting import from {file_path}")
        
        # Validate file exists
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        
        # Count total rows for progress tracking
        total_rows = sum(1 for _ in open(file_path, 'r', encoding='utf-8')) - 1
        logger.info(f"Total rows to process: {total_rows}")
        
        # Read and process CSV in chunks
        chunk_size = 10000
        processed = 0
        inserted = 0
        updated = 0
        
        # Get database connection string
        db_url = settings.DATABASE_URL.replace('postgresql://', '').replace('postgres://', '')
        
        for chunk_num, chunk in enumerate(pd.read_csv(file_path, chunksize=chunk_size, encoding='utf-8')):
            logger.info(f"Processing chunk {chunk_num + 1}")
            
            # Data cleaning and normalization
            chunk = chunk.fillna('')  # Replace NaN with empty string
            
            # Normalize SKU (case-insensitive, strip whitespace)
            if 'sku' in chunk.columns:
                chunk['sku'] = chunk['sku'].astype(str).str.upper().str.strip()
            
            # Remove duplicates within chunk (keep last)
            chunk = chunk.drop_duplicates(subset=['sku'], keep='last')
            
            # Prepare data for PostgreSQL COPY with UPSERT
            # We'll use a temp table approach for better performance
            with psycopg2.connect(settings.DATABASE_URL) as conn:
                with conn.cursor() as cursor:
                    # Create temporary table
                    cursor.execute("""
                        CREATE TEMP TABLE temp_products (
                            sku VARCHAR(255),
                            name VARCHAR(500),
                            description TEXT,
                            price NUMERIC(10, 2)
                        ) ON COMMIT DROP;
                    """)
                    
                    # Prepare data buffer
                    buffer = StringIO()
                    # Select only relevant columns
                    columns_to_import = ['sku', 'name', 'description', 'price']
                    chunk_subset = chunk[columns_to_import] if all(col in chunk.columns for col in columns_to_import) else chunk
                    
                    chunk_subset.to_csv(buffer, index=False, header=False, sep='\t')
                    buffer.seek(0)
                    
                    # COPY data to temp table (extremely fast)
                    cursor.copy_from(buffer, 'temp_products', sep='\t', null='')
                    
                    # UPSERT from temp table to main table
                    cursor.execute("""
                        INSERT INTO products (sku, name, description, price, is_active, created_at)
                        SELECT sku, name, description, price, TRUE, NOW()
                        FROM temp_products
                        ON CONFLICT (sku) 
                        DO UPDATE SET
                            name = EXCLUDED.name,
                            description = EXCLUDED.description,
                            price = EXCLUDED.price,
                            updated_at = NOW();
                    """)
                    
                    inserted += cursor.rowcount
                    conn.commit()
            
            processed += len(chunk)
            percent = min(int((processed / total_rows) * 100), 100)
            
            # Update task progress
            self.update_state(
                state='PROGRESS',
                meta={
                    'current': processed,
                    'total': total_rows,
                    'percent': percent,
                    'status': f'Processing... {processed}/{total_rows} rows'
                }
            )
            
            logger.info(f"Progress: {percent}% ({processed}/{total_rows})")
        
        # Cleanup uploaded file
        try:
            os.remove(file_path)
            logger.info(f"Removed temporary file: {file_path}")
        except Exception as e:
            logger.warning(f"Could not remove file: {e}")
        
        # Trigger webhooks
        trigger_webhooks_async.delay('product.bulk_import', {
            'total_processed': processed,
            'total_inserted': inserted
        })
        
        result = {
            'status': 'success',
            'total_processed': processed,
            'total_inserted': inserted,
            'message': f'Successfully imported {processed} products'
        }
        
        logger.info(f"Import completed: {result}")
        return result
        
    except Exception as e:
        logger.error(f"Import failed: {str(e)}", exc_info=True)
        self.update_state(
            state='FAILURE',
            meta={'error': str(e), 'status': 'Import failed'}
        )
        raise


@celery_app.task(name='tasks.trigger_webhooks')
def trigger_webhooks_async(event_type: str, payload: dict):
    """Trigger configured webhooks asynchronously"""
    try:
        db = SessionLocal()
        from .models import Webhook
        
        webhooks = db.query(Webhook).filter(
            Webhook.event_type == event_type,
            Webhook.is_active == True
        ).all()
        
        for webhook in webhooks:
            try:
                with httpx.Client(timeout=5.0) as client:
                    response = client.post(
                        str(webhook.url),
                        json={'event': event_type, 'data': payload}
                    )
                    logger.info(f"Webhook {webhook.url} responded with {response.status_code}")
            except Exception as e:
                logger.error(f"Failed to trigger webhook {webhook.url}: {e}")
        
        db.close()
    except Exception as e:
        logger.error(f"Webhook trigger failed: {e}")
