import sys
import os
import json
import logging

# Add project root to path
# This is a bit of a hack, but it's necessary to import the db module
# when running the script from the root of the project.
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.database import db

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def fix_rugcheck_scores():
    """
    Migration script to fix the rugcheck scores in the database.
    This script reads the raw_report from the rugcheck_reports table,
    extracts the score_normalised, and updates the score column.
    """
    logger.info("Starting rugcheck score migration...")
    
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            
            # Fetch all reports
            cursor.execute("SELECT token_address, raw_report FROM rugcheck_reports WHERE raw_report IS NOT NULL")
            reports = cursor.fetchall()
            
            logger.info(f"Found {len(reports)} reports to process.")
            
            updated_count = 0
            for row in reports:
                token_address = row['token_address']
                raw_report_json = row['raw_report']
                
                try:
                    report = json.loads(raw_report_json)
                    score_normalised = report.get('score_normalised')
                    
                    if score_normalised is not None:
                        # Update the score column
                        cursor.execute(
                            "UPDATE rugcheck_reports SET score = ? WHERE token_address = ?",
                            (score_normalised, token_address)
                        )
                        updated_count += 1
                        logger.info(f"Updated score for {token_address} to {score_normalised}")
                    else:
                        logger.warning(f"No score_normalised found for {token_address}")
                        
                except (json.JSONDecodeError, TypeError) as e:
                    logger.error(f"Error processing report for {token_address}: {e}")
                    continue
            
            conn.commit()
            logger.info(f"Migration complete. Updated {updated_count} scores.")
            
    except Exception as e:
        logger.error(f"An error occurred during the migration: {e}")

if __name__ == "__main__":
    fix_rugcheck_scores()
