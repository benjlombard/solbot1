import sqlite3
import requests
import time
import argparse
from datetime import datetime, timedelta

def connect_to_db(db_path):
    """Connect to the SQLite database."""
    try:
        conn = sqlite3.connect(db_path)
        return conn
    except sqlite3.Error as e:
        print(f"Database connection error: {e}")
        raise

def fetch_token_data(token_address):
    """Fetch token data from the pump.fun API."""
    url = f"https://frontend-api-v3.pump.fun/coins/{token_address}"
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Error fetching data for {token_address}: {e}")
        return None

def update_token_data(conn, token_address, ath_market_cap, survival_time_hours, current_market_cap, is_complete, bonding_curve_completed_timestamp):
    """Update peak_market_cap, survival_time_hours, current_market_cap, is_complete, bonding_curve_completed_timestamp, and last_updated_from_api in creator_token_history."""
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE creator_token_history
            SET peak_market_cap = ?, survival_time_hours = ?, current_market_cap = ?, 
                is_complete = ?, bonding_curve_completed_timestamp = ?, last_updated_from_api = ?
            WHERE token_address = ?
            """,
            (ath_market_cap, survival_time_hours, current_market_cap, is_complete, 
             bonding_curve_completed_timestamp, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), token_address)
        )
        conn.commit()
        print(f"Updated {token_address}: peak_market_cap={ath_market_cap}, survival_time_hours={survival_time_hours}, "
              f"current_market_cap={current_market_cap}, is_complete={is_complete}, "
              f"bonding_curve_completed_timestamp={bonding_curve_completed_timestamp}")
    except sqlite3.Error as e:
        print(f"Database update error for {token_address}: {e}")

def get_tokens_to_update(conn, specific_token_address=None, update_interval_hours=24):
    """Fetch token_address from creator_token_history, skipping recently updated tokens unless specified."""
    try:
        cursor = conn.cursor()
        if specific_token_address:
            cursor.execute(
                "SELECT token_address FROM creator_token_history WHERE token_address = ?",
                (specific_token_address,)
            )
        else:
            cursor.execute(
                """
                SELECT token_address
                FROM creator_token_history
                WHERE last_updated_from_api IS NULL
                   OR last_updated_from_api < ?
                """,
                ((datetime.now() - timedelta(hours=update_interval_hours)).strftime('%Y-%m-%d %H:%M:%S'),)
            )
        tokens = [row[0] for row in cursor.fetchall()]
        if specific_token_address and not tokens:
            print(f"No token found with address: {specific_token_address}")
        return tokens
    except sqlite3.Error as e:
        print(f"Error fetching tokens: {e}")
        return []

def main(db_path, cycle_time, calls_per_cycle, token_address, update_interval_hours):
    """Main function to run the update loop."""
    conn = connect_to_db(db_path)
    
    try:
        while True:
            print(f"Starting new cycle at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            tokens = get_tokens_to_update(conn, token_address, update_interval_hours)
            if not tokens:
                print("No tokens to update.")
            else:
                for i, token_addr in enumerate(tokens[:calls_per_cycle]):
                    print(f"Processing token {i+1}/{min(calls_per_cycle, len(tokens))}: {token_addr}")
                    data = fetch_token_data(token_addr)
                    if data:
                        ath_market_cap = data.get('ath_market_cap', 0.0)
                        created_timestamp = data.get('created_timestamp')
                        last_trade_timestamp = data.get('last_trade_timestamp')
                        current_market_cap = data.get('usd_market_cap', 0.0)
                        complete = data.get('complete', False)
                        
                        # Calculer survival_time_hours
                        if created_timestamp and last_trade_timestamp:
                            survival_time_hours = (last_trade_timestamp - created_timestamp) / 3600000
                        else:
                            survival_time_hours = 0.0
                        
                        # Déterminer is_complete et bonding_curve_completed_timestamp
                        if complete:
                            is_complete = 1
                            # Convertir le timestamp en secondes si nécessaire (l'API semble retourner en millisecondes)
                            bonding_curve_completed_timestamp = last_trade_timestamp // 1000 if last_trade_timestamp else 0
                        else:
                            is_complete = 0
                            bonding_curve_completed_timestamp = 0  # Utiliser 0 au lieu de NULL pour respecter la contrainte NOT NULL
                        
                        update_token_data(conn, token_addr, ath_market_cap, survival_time_hours, 
                                        current_market_cap, is_complete, bonding_curve_completed_timestamp)
                    else:
                        print(f"Skipping update for {token_addr} due to API failure.")
                    
                    time.sleep(0.5)  # Avoid overwhelming the API
            
            print(f"Cycle completed. Sleeping for {cycle_time} seconds.")
            if token_address:
                print("Single token processed. Exiting.")
                break
            time.sleep(cycle_time)
    
    except KeyboardInterrupt:
        print("Script terminated by user.")
    finally:
        conn.close()
        print("Database connection closed.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Update creator_token_history with pump.fun API data.")
    parser.add_argument("--db-path", default="early_adopter.db", help="Path to SQLite database file")
    parser.add_argument("--cycle-time", type=int, default=60, help="Cycle time in seconds")
    parser.add_argument("--calls-per-cycle", type=int, default=10, help="Number of API calls per cycle")
    parser.add_argument("--token-address", default=None, help="Specific token address to update (optional)")
    parser.add_argument("--update-interval-hours", type=int, default=24, help="Hours before re-updating a token")
    args = parser.parse_args()
    
    main(args.db_path, args.cycle_time, args.calls_per_cycle, args.token_address, args.update_interval_hours)