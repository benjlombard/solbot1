"""
Standalone service to continuously update Rugcheck reports for all tokens in the database.

This script runs in a continuous loop, fetching a batch of tokens at regular intervals,
updating their Rugcheck reports, and ensuring all tokens are updated over time before
starting a new pass.

The cycle interval and batch size are configurable via command-line arguments.

Usage:
    - Run with default settings (30s interval, 50 tokens per batch):
      python early_adopter_mvp1/app/rugcheck_update_service.py

    - Run with custom settings (e.g., 60s interval, 100 tokens per batch):
      python early_adopter_mvp1/app/rugcheck_update_service.py --interval 60 --batch-size 100
"""
"""
Standalone service to continuously update Rugcheck reports for all tokens in the database.

This script runs in a continuous loop, fetching a batch of tokens at regular intervals,
updating their Rugcheck reports, and ensuring all tokens are updated over time before
starting a new pass.

The cycle interval and batch size are configurable via command-line arguments.

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

def get_all_token_addresses():
    """Fetches all token addresses from the rugcheck_reports table."""
    try:
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT token_address FROM rugcheck_reports")
            rows = cursor.fetchall()
            return {row['token_address'] for row in rows}
    except Exception as e:
        logger.error(f"Failed to fetch token addresses from database: {e}")
        return set()

async def update_token(session: aiohttp.ClientSession, token_address: str, client: RugCheckClient, semaphore: asyncio.Semaphore):
    """Fetches a new Rugcheck report and updates the database asynchronously, respecting the semaphore."""
    async with semaphore:
        try:
            logger.info(f"Fetching report for {token_address}...")
            report = await client.get_token_report_async(session, token_address)
            if report:
                # Database operation is synchronous, run it in a thread to avoid blocking
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, db_manager.upsert_rugcheck_report, token_address, report)
                logger.info(f"Successfully updated report for {token_address}.")

                # Extract totalHolders and update pump_tokens
                total_holders = report.get('totalHolders')
                if total_holders is not None:
                    logger.info(f"Found {total_holders} for {token_address}. Updating holders count...")
                    await loop.run_in_executor(None, db_manager.update_token_holders_count, token_address, total_holders)
                else:
                    logger.warning(f"'totalHolders' not found in report for {token_address}.")

                return token_address, True
            else:
                logger.warning(f"No report received for {token_address}.")
                return token_address, False
        except Exception as e:
            logger.error(f"An error occurred while updating {token_address}: {e}")
            return token_address, False

async def main():
    """Main function to run the update service."""
    args = parse_arguments()
    logger.info(f"Starting Rugcheck update service with interval: {args.interval}s, batch size: {args.batch_size}, concurrency: {args.concurrency}")

    rugcheck_client = RugCheckClient(logger=logger)
    semaphore = asyncio.Semaphore(args.concurrency)
    
    processed_in_pass = set()
    all_tokens = get_all_token_addresses()

    if not all_tokens:
        logger.error("No tokens found in the database. Exiting.")
        return

    logger.info(f"Found {len(all_tokens)} tokens to monitor.")

    async with aiohttp.ClientSession() as session:
        while True:
            try:
                # Determine which tokens are left to process in this full pass
                unprocessed_tokens = list(all_tokens - processed_in_pass)

                # If all tokens have been processed, start a new full pass
                if not unprocessed_tokens:
                    logger.info("Full pass complete. All tokens have been updated.")
                    logger.info("Resetting cycle and fetching full token list again.")
                    processed_in_pass.clear()
                    all_tokens = get_all_token_addresses()
                    if not all_tokens:
                        logger.warning("No tokens found for the new pass. Waiting...")
                        await asyncio.sleep(args.interval)
                        continue
                    unprocessed_tokens = list(all_tokens)

                # Select a random batch of tokens to update
                batch_size = min(args.batch_size, len(unprocessed_tokens))
                token_batch = random.sample(unprocessed_tokens, batch_size)
                
                logger.info(f"Starting new cycle. Updating {len(token_batch)} tokens with concurrency {args.concurrency}...")

                tasks = [update_token(session, token_address, rugcheck_client, semaphore) for token_address in token_batch]
                results = await asyncio.gather(*tasks)

                for address, success in results:
                    if success:
                        processed_in_pass.add(address)

                remaining = len(all_tokens) - len(processed_in_pass)
                logger.info(f"Cycle finished. {len(processed_in_pass)}/{len(all_tokens)} tokens processed in this pass. {remaining} remaining.")
                
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
