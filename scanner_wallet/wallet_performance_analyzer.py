import sqlite3
import pandas as pd
import time
import sys
import os
import logging
from collections import defaultdict

# HACK: Add parent directory to path to resolve imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from scanner_wallet.core.database import get_database_manager
    from scanner_wallet.core.config import get_config
except ImportError:
    print("Could not import project modules. Make sure to run from the project root.")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class WalletPerformanceAnalyzer:
    def __init__(self, db_manager):
        self.db_manager = db_manager
        self.logger = logging.getLogger(__name__)

    def get_all_wallets(self) -> list[str]:
        """Gets all unique wallet addresses from the transactions table."""
        query = "SELECT DISTINCT wallet_address FROM transactions;"
        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query)
            wallets = [row[0] for row in cursor.fetchall()]
        self.logger.info(f"Found {len(wallets)} unique wallets to analyze.")
        return wallets

    def get_transactions_for_wallet(self, wallet_address: str) -> pd.DataFrame:
        """Fetches and prepares transaction data for a specific wallet."""
        query = """
            SELECT token_mint, transaction_type, token_amount, price_per_token, block_time
            FROM transactions
            WHERE wallet_address = ? AND is_token_transaction = 1 AND status = 'success' AND token_amount > 0 AND price_per_token > 0
            ORDER BY block_time ASC;
        """
        with self.db_manager.get_connection() as conn:
            df = pd.read_sql_query(query, conn, params=(wallet_address,))
        
        df['cost_or_proceeds'] = df['token_amount'] * df['price_per_token']
        return df

    def get_current_token_prices(self, token_mints: list[str]) -> dict[str, float]:
        """Gets current prices for a list of tokens."""
        if not token_mints:
            return {}
        
        placeholders = ','.join('?' for _ in token_mints)
        query = f"SELECT address, price_usd FROM tokens WHERE address IN ({placeholders});"
        
        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, token_mints)
            prices = {row[0]: row[1] for row in cursor.fetchall()}
        return prices

    def calculate_performance_for_wallet(self, wallet_address: str) -> dict:
        """
        Calculates the performance metrics for a single wallet.
        This is a complex financial calculation. We will use a simplified FIFO approach.
        """
        self.logger.info(f"Analyzing performance for wallet: {wallet_address}")
        transactions_df = self.get_transactions_for_wallet(wallet_address)
        
        if transactions_df.empty:
            self.logger.info(f"No valid transactions found for {wallet_address}. Skipping.")
            return None

        # Data structures for tracking
        holdings = defaultdict(lambda: {'amount': 0, 'fifo_queue': []}) # token -> {amount, fifo_queue: [(amount, cost_per_token)]}
        realized_pnl = 0.0
        total_investment = 0.0
        total_divestment = 0.0
        winning_trades = 0
        losing_trades = 0

        for _, tx in transactions_df.iterrows():
            token = tx['token_mint']
            
            if tx['transaction_type'] == 'TransactionType.BUY':
                holdings[token]['amount'] += tx['token_amount']
                holdings[token]['fifo_queue'].append((tx['token_amount'], tx['price_per_token']))
                total_investment += tx['cost_or_proceeds']
            
            elif tx['transaction_type'] == 'TransactionType.SELL':
                sell_amount = tx['token_amount']
                sell_price = tx['price_per_token']
                cost_of_goods_sold = 0.0
                
                total_divestment += tx['cost_or_proceeds']
                
                while sell_amount > 0 and holdings[token]['fifo_queue']:
                    buy_amount, buy_price = holdings[token]['fifo_queue'][0]
                    
                    amount_to_sell = min(sell_amount, buy_amount)
                    cost_of_goods_sold += amount_to_sell * buy_price
                    
                    if amount_to_sell < buy_amount:
                        holdings[token]['fifo_queue'][0] = (buy_amount - amount_to_sell, buy_price)
                    else:
                        holdings[token]['fifo_queue'].pop(0)
                        
                    sell_amount -= amount_to_sell
                
                realized_pnl_for_trade = (tx['token_amount'] * sell_price) - cost_of_goods_sold
                realized_pnl += realized_pnl_for_trade
                
                if realized_pnl_for_trade > 0:
                    winning_trades += 1
                else:
                    losing_trades += 1

                holdings[token]['amount'] -= tx['token_amount']

        # Calculate unrealized P&L
        current_holdings = {token: data['amount'] for token, data in holdings.items() if data['amount'] > 0.00001}
        current_prices = self.get_current_token_prices(list(current_holdings.keys()))
        
        current_portfolio_value = 0.0
        unrealized_pnl = 0.0
        
        for token, amount in current_holdings.items():
            cost_basis = sum(a * p for a, p in holdings[token]['fifo_queue'])
            current_price = current_prices.get(token, 0)
            market_value = amount * current_price
            
            current_portfolio_value += market_value
            unrealized_pnl += market_value - cost_basis

        total_trades = winning_trades + losing_trades
        win_rate = (winning_trades / total_trades) * 100 if total_trades > 0 else 0.0
        
        total_pnl = realized_pnl + unrealized_pnl
        pnl_percentage = (total_pnl / total_investment) * 100 if total_investment > 0 else 0.0

        return {
            'wallet_address': wallet_address,
            'total_investment_usd': total_investment,
            'total_divestment_usd': total_divestment,
            'current_portfolio_value_usd': current_portfolio_value,
            'realized_pnl_usd': realized_pnl,
            'unrealized_pnl_usd': unrealized_pnl,
            'total_pnl_usd': total_pnl,
            'pnl_percentage': pnl_percentage,
            'total_trades': total_trades,
            'winning_trades': winning_trades,
            'losing_trades': losing_trades,
            'win_rate': win_rate,
            'current_token_holdings_count': len(current_holdings),
            'last_calculated_at': int(time.time())
        }

    def save_performance_data(self, performance_data: dict):
        """Saves the calculated performance data to the database."""
        if performance_data is None:
            return

        query = """
            INSERT INTO wallets_performance (
                wallet_address, total_investment_usd, total_divestment_usd, current_portfolio_value_usd,
                realized_pnl_usd, unrealized_pnl_usd, total_pnl_usd, pnl_percentage,
                total_trades, winning_trades, losing_trades, win_rate,
                current_token_holdings_count, last_calculated_at, updated_at
            ) VALUES (
                :wallet_address, :total_investment_usd, :total_divestment_usd, :current_portfolio_value_usd,
                :realized_pnl_usd, :unrealized_pnl_usd, :total_pnl_usd, :pnl_percentage,
                :total_trades, :winning_trades, :losing_trades, :win_rate,
                :current_token_holdings_count, :last_calculated_at, CURRENT_TIMESTAMP
            )
            ON CONFLICT(wallet_address) DO UPDATE SET
                total_investment_usd=excluded.total_investment_usd,
                total_divestment_usd=excluded.total_divestment_usd,
                current_portfolio_value_usd=excluded.current_portfolio_value_usd,
                realized_pnl_usd=excluded.realized_pnl_usd,
                unrealized_pnl_usd=excluded.unrealized_pnl_usd,
                total_pnl_usd=excluded.total_pnl_usd,
                pnl_percentage=excluded.pnl_percentage,
                total_trades=excluded.total_trades,
                winning_trades=excluded.winning_trades,
                losing_trades=excluded.losing_trades,
                win_rate=excluded.win_rate,
                current_token_holdings_count=excluded.current_token_holdings_count,
                last_calculated_at=excluded.last_calculated_at,
                updated_at=CURRENT_TIMESTAMP;
        """
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, performance_data)
                conn.commit()
            self.logger.info(f"Successfully saved performance data for wallet {performance_data['wallet_address']}")
        except Exception as e:
            self.logger.error(f"Failed to save performance data for {performance_data['wallet_address']}: {e}")

    def run_full_analysis(self):
        """Runs the analysis for all wallets."""
        self.logger.info("Starting full wallet performance analysis cycle.")
        wallets = self.get_all_wallets()
        for wallet in wallets:
            performance_data = self.calculate_performance_for_wallet(wallet)
            self.save_performance_data(performance_data)
        self.logger.info("Full wallet performance analysis cycle finished.")


if __name__ == "__main__":
    config = get_config()
    db_manager = get_database_manager(config)
    analyzer = WalletPerformanceAnalyzer(db_manager)
    analyzer.run_full_analysis()
