import sqlite3
import argparse
import time
from datetime import datetime

def connect_to_db(db_path):
    """Connect to the SQLite database."""
    try:
        conn = sqlite3.connect(db_path)
        return conn
    except sqlite3.Error as e:
        print(f"Database connection error: {e}")
        raise

def get_missing_tokens(conn):
    """Fetch tokens from pump_tokens that are not in creator_token_history."""
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT 
                pt.address,
                pt.name,
                pt.symbol,
                pt.creator,
                pt.created_at,
                pt.row_created_at
            FROM pump_tokens pt
            LEFT JOIN creator_token_history cth ON pt.address = cth.token_address
            WHERE cth.token_address IS NULL
            """
        )
        return cursor.fetchall()
    except sqlite3.Error as e:
        print(f"Error fetching missing tokens: {e}")
        return []

def insert_into_creator_token_history(conn, tokens):
    """Insert missing tokens into creator_token_history with specified mappings."""
    insert_query = """
    INSERT INTO creator_token_history (
        creator_address, token_address, token_name, token_symbol, launch_date,
        outcome_type, roi_24h, peak_market_cap, survival_time_hours, is_success,
        contributed_to_blacklist, notes, created_at, last_updated_from_api, current_market_cap, is_complete, bonding_curve_completed_timestamp 
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    try:
        cursor = conn.cursor()
        inserted_count = 0
        for token in tokens:
            address, name, symbol, creator, created_at, row_created_at = token
            cursor.execute(insert_query, (
                creator,                    # creator_address
                address,                   # token_address
                name,                      # token_name
                symbol,                    # token_symbol
                created_at,                # launch_date
                "NEUTRAL",                 # outcome_type
                0.0,                       # roi_24h
                0.0,                       # peak_market_cap
                0.0,                       # survival_time_hours
                0,                         # is_success
                0,                         # contributed_to_blacklist
                None,                      # notes
                row_created_at,            # created_at
                None,                      # last_updated_from_api
                0.0,                       # current_market_cap
                -1,                        # is_complete (-1 = non traité, 0 = non migré, 1 = migré)
                0                          # bonding_curve_completed_timestamp (0 = non migré)
            ))
            print(f"Inserted token: {address} (Name: {name}, Symbol: {symbol})")
            inserted_count += 1
        
        conn.commit()
        print(f"Successfully inserted {inserted_count} tokens into creator_token_history.")
        return inserted_count
    except sqlite3.Error as e:
        print(f"Error inserting tokens: {e}")
        conn.rollback()
        return 0

def run_single_cycle(db_path):
    """Run a single cycle of the population process."""
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Starting population cycle...")
    
    conn = connect_to_db(db_path)
    
    try:
        # Fetch missing tokens
        missing_tokens = get_missing_tokens(conn)
        
        if not missing_tokens:
            print("No new tokens found in pump_tokens to insert into creator_token_history.")
            return 0
        else:
            print(f"Found {len(missing_tokens)} new tokens to insert.")
            # Insert missing tokens
            inserted_count = insert_into_creator_token_history(conn, missing_tokens)
            return inserted_count
    
    except Exception as e:
        print(f"An error occurred during cycle: {e}")
        return 0
    finally:
        conn.close()

def main(db_path, interval_seconds, run_once=False):
    """Main function to populate creator_token_history from pump_tokens continuously."""
    
    if run_once:
        print("Running in single execution mode...")
        inserted = run_single_cycle(db_path)
        print(f"Single cycle completed. Inserted {inserted} tokens.")
        return
    
    print(f"Starting continuous population process...")
    print(f"Database: {db_path}")
    print(f"Interval: {interval_seconds} seconds")
    print("Press Ctrl+C to stop the process.\n")
    
    cycle_count = 0
    total_inserted = 0
    
    try:
        while True:
            cycle_count += 1
            print(f"\n--- Cycle {cycle_count} ---")
            
            inserted = run_single_cycle(db_path)
            total_inserted += inserted
            
            print(f"Cycle {cycle_count} completed. Inserted: {inserted} tokens | Total inserted: {total_inserted}")
            print(f"Next cycle in {interval_seconds} seconds...")
            
            time.sleep(interval_seconds)
    
    except KeyboardInterrupt:
        print(f"\n\nProcess interrupted by user.")
        print(f"Summary:")
        print(f"  - Total cycles: {cycle_count}")
        print(f"  - Total tokens inserted: {total_inserted}")
        print(f"  - Average per cycle: {total_inserted/cycle_count:.1f}" if cycle_count > 0 else "  - Average per cycle: 0")
    except Exception as e:
        print(f"\nUnexpected error: {e}")
    finally:
        print("Process terminated.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Populate creator_token_history from pump_tokens continuously.")
    parser.add_argument("--db-path", default="early_adopter.db", help="Path to SQLite database file")
    parser.add_argument("--interval", type=int, default=300, help="Interval between cycles in seconds (default: 300)")
    parser.add_argument("--run-once", action="store_true", help="Run only once instead of continuously")
    
    args = parser.parse_args()
    
    if args.interval < 1:
        print("Error: Interval must be at least 1 second")
        exit(1)
    
    main(args.db_path, args.interval, args.run_once)