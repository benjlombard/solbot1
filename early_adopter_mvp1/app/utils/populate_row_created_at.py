import sys
import os
import logging

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'app')))

from database import db

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def add_row_created_at_column():
    """
    Migration script to add the row_created_at column to the pump_tokens table
    and populate it with the value of the created_at column for existing rows.
    """
    logger.info("Starting migration to add row_created_at column...")
    
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            
            # Check if the column already exists
            cursor.execute("PRAGMA table_info(pump_tokens)")
            columns = [row['name'] for row in cursor.fetchall()]
            
            if 'row_created_at' in columns:
                
                # Populate the new column with the value of created_at for existing rows
                cursor.execute("UPDATE pump_tokens SET row_created_at = created_at WHERE row_created_at IS NULL")
                logger.info("Populated 'row_created_at' with values from 'created_at' for existing rows.")
                
                conn.commit()
                logger.info("Migration complete.")
            else:
                logger.info("Column 'row_created_at' already exists.")
            
    except Exception as e:
        logger.error(f"An error occurred during the migration: {e}")

if __name__ == "__main__":
    add_row_created_at_column()
