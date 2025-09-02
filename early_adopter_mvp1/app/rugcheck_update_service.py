"""
Standalone service to continuously update Rugcheck reports for all tokens in the database.

This script runs in a continuous loop, fetching a batch of tokens at regular intervals,
updating their Rugcheck reports, and ensuring all tokens are updated over time before
starting a new pass.

The cycle interval and batch size are configurable via command-line arguments.

Enhanced version:
- Only processes tokens where score = -1 (unprocessed)
- Extracts score_normalised from raw_report and updates score column
- Updates totalHolders only for these filtered tokens

Usage:
    - Run with default settings (30s interval, 50 tokens per batch):
      python early_adopter_mvp1/app/rugcheck_update_service.py

    - Run with custom settings (e.g., 60s interval, 100 tokens per batch):
      python early_adopter_mvp1/app/rugcheck_update_service.py --interval 60 --batch-size 100
"""
import argparse
import logging
import random
import time
import sys
import os
import asyncio
import aiohttp
import json

# Ensure the app's parent directory is on the Python path
# to allow for absolute imports
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.database import db as db_manager
from app.rugcheck_client import RugCheckClient
from app.config import settings

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def parse_arguments():
    """Parses command-line arguments."""
    parser = argparse.ArgumentParser(description="Continuously update Rugcheck reports for tokens.")
    parser.add_argument(
        "--interval",
        type=int,
        default=30,
        help="The interval in seconds between update cycles. Default is 30 seconds."
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="The number of tokens to update in each cycle. Default is 50."
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=10,
        help="The number of parallel requests to the API. Default is 10."
    )
    return parser.parse_args()

def get_unprocessed_token_addresses():
    """Fetches token addresses from rugcheck_reports where score = -1 (unprocessed)."""
    try:
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT token_address FROM rugcheck_reports WHERE score = -1")
            rows = cursor.fetchall()
            addresses = {row['token_address'] for row in rows}
            logger.info(f"Found {len(addresses)} unprocessed tokens (score = -1)")
            return addresses
    except Exception as e:
        logger.error(f"Failed to fetch unprocessed token addresses from database: {e}")
        return set()

def update_score_from_raw_report(token_address: str):
    """Extracts score_normalised from raw_report and updates the score column."""
    try:
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            
            # Fetch the raw_report
            cursor.execute("SELECT raw_report FROM rugcheck_reports WHERE token_address = ? AND score = -1", (token_address,))
            row = cursor.fetchone()
            
            if not row or not row['raw_report']:
                logger.warning(f"No raw_report found for {token_address}")
                return False
            
            try:
                # Parse JSON and extract score_normalised
                report = json.loads(row['raw_report'])
                score_normalised = report.get('score_normalised')
                
                if score_normalised is not None and score_normalised != -1:
                    # Update the score column only if it's not -1
                    cursor.execute(
                        "UPDATE rugcheck_reports SET score = ? WHERE token_address = ?",
                        (score_normalised, token_address)
                    )
                    conn.commit()
                    logger.info(f"Updated score for {token_address}: {score_normalised}")
                    return True
                elif score_normalised == -1:
                    logger.warning(f"API failure detected in raw_report for {token_address} (score_normalised = -1). Not updating.")
                    return False
                else:
                    logger.warning(f"No score_normalised found in raw_report for {token_address}")
                    return False
                    
            except (json.JSONDecodeError, TypeError) as e:
                logger.error(f"Error parsing raw_report JSON for {token_address}: {e}")
                return False
                
    except Exception as e:
        logger.error(f"Error updating score for {token_address}: {e}")
        return False

def update_holders_from_raw_report(token_address: str):
    """Extracts totalHolders from raw_report and updates pump_tokens table."""
    try:
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            
            # Fetch the raw_report
            cursor.execute("SELECT raw_report FROM rugcheck_reports WHERE token_address = ?", (token_address,))
            row = cursor.fetchone()
            
            if not row or not row['raw_report']:
                logger.warning(f"No raw_report found for {token_address}")
                return False
            
            try:
                # Parse JSON and extract totalHolders
                report = json.loads(row['raw_report'])
                total_holders = report.get('totalHolders')
                
                if total_holders is not None:
                    # Update pump_tokens table
                    db_manager.update_token_holders_count(token_address, total_holders)
                    logger.info(f"Updated holders count for {token_address}: {total_holders}")
                    return True
                else:
                    logger.warning(f"No totalHolders found in raw_report for {token_address}")
                    return False
                    
            except (json.JSONDecodeError, TypeError) as e:
                logger.error(f"Error parsing raw_report JSON for {token_address}: {e}")
                return False
                
    except Exception as e:
        logger.error(f"Error updating holders for {token_address}: {e}")
        return False

async def update_token(session: aiohttp.ClientSession, token_address: str, client: RugCheckClient, semaphore: asyncio.Semaphore):
    """
    Fetches a new Rugcheck report and updates the database asynchronously, 
    but only processes tokens where score = -1.
    Also extracts score_normalised and totalHolders from existing raw_report.
    
    Returns: (token_address, result_dict)
    result_dict contains: {'success': bool, 'api_success': bool, 'api_failed': bool}
    """
    async with semaphore:
        result = {'success': False, 'api_success': False, 'api_failed': False}
        
        try:
            logger.info(f"Processing token {token_address}...")
            
            # First, try to update score and holders from existing raw_report
            loop = asyncio.get_event_loop()
            score_updated = await loop.run_in_executor(None, update_score_from_raw_report, token_address)
            holders_updated = await loop.run_in_executor(None, update_holders_from_raw_report, token_address)
            
            # If we successfully updated the score from raw_report, we might not need to fetch new data
            if score_updated:
                logger.info(f"Successfully processed existing raw_report for {token_address}")
                result['success'] = True
                result['api_success'] = True
                return token_address, result
            
            # Check if the existing raw_report contains an API failure (score = -1)
            api_failed_in_existing = await loop.run_in_executor(None, check_api_failure_in_raw_report, token_address)
            if api_failed_in_existing:
                logger.info(f"API failure detected in existing raw_report for {token_address}, fetching fresh report...")
            else:
                logger.info(f"No valid score in existing raw_report, fetching fresh report for {token_address}...")
            
            # Fetch a fresh report
            report = await client.get_token_report_async(session, token_address)
            
            if report:
                # Update the raw_report in database
                await loop.run_in_executor(None, db_manager.upsert_rugcheck_report, token_address, report)
                logger.info(f"Successfully fetched and stored new report for {token_address}")

                # Extract and update score_normalised
                score_normalised = report.get('score_normalised')
                if score_normalised is not None:
                    score_success = await loop.run_in_executor(None, update_score_from_new_report, token_address, score_normalised)
                    if score_success:
                        result['api_success'] = True
                    else:
                        result['api_failed'] = True
                        logger.warning(f"Score update failed for {token_address} due to API failure")
                else:
                    result['api_failed'] = True
                    logger.warning(f"'score_normalised' not found in new report for {token_address}")

                # Extract and update totalHolders
                total_holders = report.get('totalHolders')
                if total_holders is not None:
                    logger.info(f"Found {total_holders} holders for {token_address}. Updating holders count...")
                    await loop.run_in_executor(None, db_manager.update_token_holders_count, token_address, total_holders)
                else:
                    logger.warning(f"'totalHolders' not found in new report for {token_address}")

                result['success'] = True
                return token_address, result
            else:
                logger.warning(f"No report received for {token_address}")
                result['api_failed'] = True
                return token_address, result
                
        except Exception as e:
            logger.error(f"An error occurred while updating {token_address}: {e}")
            result['api_failed'] = True
            return token_address, result

def check_api_failure_in_raw_report(token_address: str):
    """Check if the existing raw_report contains an API failure (score_normalised = -1)."""
    try:
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT raw_report FROM rugcheck_reports WHERE token_address = ?", (token_address,))
            row = cursor.fetchone()
            
            if not row or not row['raw_report']:
                return False
            
            try:
                report = json.loads(row['raw_report'])
                score_normalised = report.get('score_normalised')
                return score_normalised == -1
            except (json.JSONDecodeError, TypeError):
                return False
                
    except Exception:
        return False
    """Updates the score column with the score_normalised from a new report."""
    try:
        # Don't update if the API failed (score = -1)
        if score_normalised == -1:
            logger.warning(f"API failure detected for {token_address} (score_normalised = -1). Not updating score.")
            return False
            
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE rugcheck_reports SET score = ? WHERE token_address = ?",
                (score_normalised, token_address)
            )
            conn.commit()
            logger.info(f"Updated score for {token_address} with new report: {score_normalised}")
            return True
    except Exception as e:
        logger.error(f"Error updating score from new report for {token_address}: {e}")
        return False

async def main():
    """Main function to run the update service."""
    args = parse_arguments()
    logger.info(f"Starting Enhanced Rugcheck update service with interval: {args.interval}s, batch size: {args.batch_size}, concurrency: {args.concurrency}")
    logger.info("Only processing tokens where score = -1 (unprocessed)")

    rugcheck_client = RugCheckClient(logger=logger)
    semaphore = asyncio.Semaphore(args.concurrency)
    
    processed_in_pass = set()
    
    # Cumulative statistics
    cumulative_stats = {
        'processed': 0,
        'api_success': 0,
        'api_failed': 0,
        'cycles': 0
    }

    async with aiohttp.ClientSession() as session:
        while True:
            try:
                # Get fresh list of unprocessed tokens (score = -1)
                all_unprocessed_tokens = get_unprocessed_token_addresses()

                if not all_unprocessed_tokens:
                    logger.info("No unprocessed tokens found (all scores have been updated). Waiting...")
                    await asyncio.sleep(args.interval)
                    continue

                # Determine which tokens are left to process in this full pass
                unprocessed_tokens = list(all_unprocessed_tokens - processed_in_pass)

                # If all unprocessed tokens have been processed in this pass, start a new full pass
                if not unprocessed_tokens:
                    logger.info("Full pass complete for current unprocessed tokens.")
                    logger.info("Resetting cycle and checking for new unprocessed tokens...")
                    processed_in_pass.clear()
                    continue

                # Select a random batch of tokens to update
                batch_size = min(args.batch_size, len(unprocessed_tokens))
                token_batch = random.sample(unprocessed_tokens, batch_size)
                
                logger.info(f"Starting new cycle. Processing {len(token_batch)} unprocessed tokens with concurrency {args.concurrency}...")

                tasks = [update_token(session, token_address, rugcheck_client, semaphore) for token_address in token_batch]
                results = await asyncio.gather(*tasks)

                # Cycle statistics
                cycle_stats = {
                    'processed': 0,
                    'api_success': 0,
                    'api_failed': 0
                }

                for address, result_dict in results:
                    cycle_stats['processed'] += 1
                    cumulative_stats['processed'] += 1
                    
                    if result_dict['success']:
                        processed_in_pass.add(address)
                    
                    if result_dict['api_success']:
                        cycle_stats['api_success'] += 1
                        cumulative_stats['api_success'] += 1
                    
                    if result_dict['api_failed']:
                        cycle_stats['api_failed'] += 1
                        cumulative_stats['api_failed'] += 1

                cumulative_stats['cycles'] += 1
                
                # Cycle summary
                logger.info("=" * 80)
                logger.info(f"🔄 CYCLE #{cumulative_stats['cycles']} SUMMARY:")
                logger.info(f"   📊 Processed: {cycle_stats['processed']} tokens")
                logger.info(f"   ✅ API Success: {cycle_stats['api_success']} tokens ({cycle_stats['api_success']/cycle_stats['processed']*100:.1f}%)")
                logger.info(f"   ❌ API Failed: {cycle_stats['api_failed']} tokens ({cycle_stats['api_failed']/cycle_stats['processed']*100:.1f}%)")
                
                # Cumulative summary
                logger.info(f"📈 CUMULATIVE SUMMARY:")
                logger.info(f"   🔢 Total Processed: {cumulative_stats['processed']} tokens")
                logger.info(f"   ✅ Total API Success: {cumulative_stats['api_success']} tokens ({cumulative_stats['api_success']/cumulative_stats['processed']*100:.1f}%)")
                logger.info(f"   ❌ Total API Failed: {cumulative_stats['api_failed']} tokens ({cumulative_stats['api_failed']/cumulative_stats['processed']*100:.1f}%)")
                logger.info(f"   🔄 Total Cycles: {cumulative_stats['cycles']}")

                remaining = len(all_unprocessed_tokens) - len(processed_in_pass)
                logger.info(f"🎯 PROGRESS: {len(processed_in_pass)}/{len(all_unprocessed_tokens)} tokens handled in this pass. {remaining} remaining.")
                logger.info("=" * 80)
                
                logger.info(f"Waiting for {args.interval} seconds...")
                await asyncio.sleep(args.interval)

            except KeyboardInterrupt:
                logger.info("Service stopped by user.")
                break
            except Exception as e:
                logger.error(f"An unexpected error occurred in the main loop: {e}", exc_info=True)
                logger.info("Restarting loop after 60 seconds...")
                await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main())