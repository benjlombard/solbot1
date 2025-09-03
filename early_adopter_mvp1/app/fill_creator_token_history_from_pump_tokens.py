import sqlite3
import argparse
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
        contributed_to_blacklist, notes, created_at, last_updated_from_api, current_market_cap
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    try:
        cursor = conn.cursor()
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
                0.0                        # current_market_cap
            ))
            print(f"Inserted token: {address} (Name: {name}, Symbol: {symbol})")
        conn.commit()
        print(f"Inserted {len(tokens)} tokens into creator_token_history.")
    except sqlite3.Error as e:
        print(f"Error inserting tokens: {e}")
        conn.rollback()

def main(db_path):
    """Main function to populate creator_token_history from pump_tokens."""
    conn = connect_to_db(db_path)
    
    try:
        # Fetch missing tokens
        missing_tokens = get_missing_tokens(conn)
        if not missing_tokens:
            print("No new tokens found in pump_tokens to insert into creator_token_history.")
        else:
            print(f"Found {len(missing_tokens)} new tokens to insert.")
            # Insert missing tokens
            insert_into_creator_token_history(conn, missing_tokens)
    
    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        conn.close()
        print("Database connection closed.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Populate creator_token_history from pump_tokens.")
    parser.add_argument("--db-path", default="path/to/your/database.db", help="Path to SQLite database file")
    args = parser.parse_args()
    
    main(args.db_path)