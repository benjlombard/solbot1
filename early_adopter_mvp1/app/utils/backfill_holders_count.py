import logging
import json
import sys
import os
import time
import argparse

# Ensure the app's parent directory is on the Python path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.database import db as db_manager

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def get_all_rugcheck_reports():
    """Fetches all rugcheck reports from the database."""
    try:
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT token_address, raw_report FROM rugcheck_reports")
            rows = cursor.fetchall()
            return rows
    except Exception as e:
        logger.error(f"Failed to fetch rugcheck reports from database: {e}")
        return []

def update_holders_count_cycle():
    """
    Iterates through all rugcheck reports, extracts the 'totalHolders' field,
    and updates the 'holders_count' in the 'pump_tokens' table.
    """
    logger.info("Starting holders_count update cycle...")
    
    reports = get_all_rugcheck_reports()
    if not reports:
        logger.info("No rugcheck reports found to process.")
        return

    logger.info(f"Found {len(reports)} reports to process.")
    
    updated_count = 0
    not_found_count = 0
    error_count = 0

    for report in reports:
        token_address = report['token_address']
        raw_report_str = report['raw_report']
        
        if not raw_report_str:
            logger.warning(f"Raw report is empty for token {token_address}.")
            continue

        try:
            raw_report = json.loads(raw_report_str)
            total_holders = raw_report.get('totalHolders')

            if total_holders is not None:
                logger.info(f"Updating holders count for {token_address} to {total_holders}...")
                success = db_manager.update_token_holders_count(token_address, total_holders)
                if success:
                    updated_count += 1
                else:
                    error_count += 1
            else:
                logger.warning(f"'totalHolders' not found in report for {token_address}.")
                not_found_count += 1
        except json.JSONDecodeError:
            logger.error(f"Failed to parse raw_report JSON for token {token_address}.")
            error_count += 1
        except Exception as e:
            logger.error(f"An unexpected error occurred for token {token_address}: {e}")
            error_count += 1

    logger.info("Update cycle completed.")
    logger.info(f"Summary:")
    logger.info(f"  - Successfully updated tokens: {updated_count}")
    logger.info(f"  - Reports without 'totalHolders': {not_found_count}")
    logger.info(f"  - Errors: {error_count}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Continuously update holders count from rugcheck reports.")
    parser.add_argument(
        "--interval",
        type=int,
        default=60,
        help="The interval in seconds between update cycles. Default is 60 seconds."
    )
    args = parser.parse_args()

    while True:
        try:
            update_holders_count_cycle()
            logger.info(f"Waiting for {args.interval} seconds before the next cycle.")
            time.sleep(args.interval)
        except KeyboardInterrupt:
            logger.info("Service stopped by user.")
            break
        except Exception as e:
            logger.error(f"An unexpected error occurred in the main loop: {e}", exc_info=True)
            logger.info("Restarting loop after 60 seconds...")
            time.sleep(60)
