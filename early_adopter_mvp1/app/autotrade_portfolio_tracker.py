#!/usr/bin/env python3
"""
Portfolio Tracker - Monitoring en temps réel du portefeuille AutoTrader
Affiche le PnL global et par token toutes les 30 secondes
"""

import asyncio
import sqlite3
import logging
import json
import time
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from decimal import Decimal
import aiohttp
from pathlib import Path

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@dataclass
class PositionData:
    """Représente une position dans le portfolio"""
    token_address: str
    token_symbol: str
    network: str
    total_tokens_held: float
    average_entry_price_sol: float
    total_sol_invested: float
    current_price_sol: float
    current_value_sol: float
    unrealized_pnl_sol: float
    unrealized_pnl_percent: float
    total_transactions: int
    total_fees_paid_sol: float
    first_purchase_timestamp: datetime
    last_transaction_timestamp: datetime
    age_minutes: int
    roi_percent: float

@dataclass
class PortfolioSummary:
    """Résumé global du portfolio"""
    total_value_sol: float
    total_invested_sol: float
    total_fees_sol: float
    unrealized_pnl_sol: float
    unrealized_pnl_percent: float
    total_positions: int
    active_positions: int
    best_performer: Optional[PositionData]
    worst_performer: Optional[PositionData]
    daily_trades: int
    daily_spent_sol: float
    daily_fees_sol: float

class DatabaseManager:
    """Gestionnaire de base de données pour le portfolio"""
    
    def __init__(self, db_path: str = "app/data/autotrader.db"):
        self.db_path = Path(db_path)
        self.ensure_database_exists()
    
    def ensure_database_exists(self):
        """Vérifie que la base de données existe"""
        if not self.db_path.exists():
            logger.error(f"❌ Database not found: {self.db_path}")
            logger.info("💡 Please run the SQL schema first to create the database")
            raise FileNotFoundError(f"Database not found: {self.db_path}")
        
        # Vérifier que les tables existent
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            
            required_tables = ['transactions', 'current_positions', 'price_history', 'daily_stats']
            missing_tables = [table for table in required_tables if table not in tables]
            
            if missing_tables:
                logger.error(f"❌ Missing tables: {missing_tables}")
                raise Exception(f"Required tables missing: {missing_tables}")
    
    def get_current_positions(self, network: str = None) -> List[PositionData]:
        """Récupère les positions actuelles depuis la vue portfolio_summary"""
        query = "SELECT * FROM portfolio_summary"
        params = []
        
        if network:
            query += " WHERE network = ?"
            params.append(network)
        
        query += " ORDER BY unrealized_pnl_percent DESC"
        
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(query, params)
            
            positions = []
            for row in cursor.fetchall():
                position = PositionData(
                    token_address=row['token_address'],
                    token_symbol=row['token_symbol'] or 'UNKNOWN',
                    network=row['network'],
                    total_tokens_held=float(row['total_tokens_held'] or 0),
                    average_entry_price_sol=float(row['average_entry_price_sol'] or 0),
                    total_sol_invested=float(row['total_sol_invested'] or 0),
                    current_price_sol=float(row['current_price_sol'] or 0),
                    current_value_sol=float(row['current_value_sol'] or 0),
                    unrealized_pnl_sol=float(row['unrealized_pnl_sol'] or 0),
                    unrealized_pnl_percent=float(row['unrealized_pnl_percent'] or 0),
                    total_transactions=int(row['total_transactions'] or 0),
                    total_fees_paid_sol=float(row['total_fees_paid_sol'] or 0),
                    first_purchase_timestamp=datetime.fromisoformat(row['first_purchase_timestamp']),
                    last_transaction_timestamp=datetime.fromisoformat(row['last_transaction_timestamp']),
                    age_minutes=int(row['age_minutes'] or 0),
                    roi_percent=float(row['roi_percent'] or 0)
                )
                positions.append(position)
            
            return positions
    
    def get_daily_stats(self, date: datetime = None, network: str = None) -> Dict[str, Any]:
        """Récupère les statistiques du jour"""
        if date is None:
            date = datetime.now().date()
        
        query = """
        SELECT 
            COUNT(*) as total_trades,
            SUM(CASE WHEN operation_type = 'BUY' THEN 1 ELSE 0 END) as buy_trades,
            SUM(CASE WHEN operation_type = 'SELL' THEN 1 ELSE 0 END) as sell_trades,
            SUM(sol_amount_spent) as total_spent,
            SUM(sol_amount_received) as total_received,
            SUM(total_fees_sol) as total_fees,
            AVG(confirmation_time_seconds) as avg_confirmation_time
        FROM transactions 
        WHERE DATE(timestamp) = ? AND status = 'CONFIRMED'
        """
        params = [date]
        
        if network:
            query += " AND network = ?"
            params.append(network)
        
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(query, params)
            row = cursor.fetchone()
            
            return {
                'total_trades': row['total_trades'] or 0,
                'buy_trades': row['buy_trades'] or 0,
                'sell_trades': row['sell_trades'] or 0,
                'total_spent': float(row['total_spent'] or 0),
                'total_received': float(row['total_received'] or 0),
                'total_fees': float(row['total_fees'] or 0),
                'avg_confirmation_time': float(row['avg_confirmation_time'] or 0)
            }
    
    def update_position_price(self, token_address: str, new_price_sol: float, network: str):
        """Met à jour le prix d'une position et recalcule le PnL"""
        current_value = new_price_sol * self.get_token_balance(token_address)
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Récupérer la position actuelle
            cursor.execute("""
                SELECT total_tokens_held, total_sol_invested 
                FROM current_positions 
                WHERE token_address = ?
            """, (token_address,))
            
            row = cursor.fetchone()
            if not row:
                return False
            
            total_tokens, total_invested = row
            current_value = new_price_sol * total_tokens
            unrealized_pnl = current_value - total_invested
            unrealized_pnl_percent = (unrealized_pnl / total_invested * 100) if total_invested > 0 else 0
            
            # Mettre à jour la position
            cursor.execute("""
                UPDATE current_positions 
                SET current_price_sol = ?, 
                    current_value_sol = ?,
                    unrealized_pnl_sol = ?,
                    unrealized_pnl_percent = ?,
                    last_price_update = CURRENT_TIMESTAMP
                WHERE token_address = ?
            """, (new_price_sol, current_value, unrealized_pnl, unrealized_pnl_percent, token_address))
            
            conn.commit()
            return True
    
    def get_token_balance(self, token_address: str) -> float:
        """Récupère le solde actuel d'un token"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT total_tokens_held 
                FROM current_positions 
                WHERE token_address = ?
            """, (token_address,))
            
            row = cursor.fetchone()
            return float(row[0]) if row else 0.0

class PriceProvider:
    """Fournisseur de prix pour les tokens"""
    
    def __init__(self):
        self.session = None
        self.sol_price_usd = 0.0
        self.last_sol_price_update = 0
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def get_sol_price_usd(self) -> float:
        """Récupère le prix de SOL en USD"""
        # Cache pendant 5 minutes
        if time.time() - self.last_sol_price_update < 300 and self.sol_price_usd > 0:
            return self.sol_price_usd
        
        try:
            async with self.session.get(
                "https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd"
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    self.sol_price_usd = float(data.get('solana', {}).get('usd', 0))
                    self.last_sol_price_update = time.time()
                    return self.sol_price_usd
        except Exception as e:
            logger.debug(f"Could not fetch SOL price: {e}")
        
        return self.sol_price_usd or 200.0  # Fallback price
    
    async def get_token_price_sol(self, token_address: str, network: str = "mainnet") -> Optional[float]:
        """Récupère le prix d'un token via Jupiter"""
        if network == "devnet":
            # Sur devnet, simuler des prix
            import random
            return random.uniform(0.000001, 0.001)
        
        try:
            # Utiliser Jupiter API pour récupérer un quote
            jupiter_url = "https://quote-api.jup.ag/v6/quote"
            params = {
                "inputMint": "So11111111111111111111111111111111111111112",  # SOL
                "outputMint": token_address,
                "amount": 1000000000,  # 1 SOL en lamports
                "slippageBps": 500
            }
            
            async with self.session.get(jupiter_url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    out_amount = int(data.get('outAmount', 0))
                    if out_amount > 0:
                        # Prix = 1 SOL / nombre de tokens reçus
                        return 1.0 / (out_amount / 10**6)  # Assuming 6 decimals
                
        except Exception as e:
            logger.debug(f"Could not fetch price for {token_address[:8]}...: {e}")
        
        return None

class PortfolioDisplay:
    """Gestionnaire d'affichage du portfolio"""
    
    def __init__(self):
        self.sol_price_usd = 0.0
    
    def format_sol_with_usd(self, sol_amount: float, sol_price_usd: float) -> str:
        """Formate un montant SOL avec équivalent USD"""
        if sol_price_usd > 0:
            usd_amount = sol_amount * sol_price_usd
            return f"{sol_amount:.6f} SOL (${usd_amount:.2f})"
        return f"{sol_amount:.6f} SOL"
    
    def format_percentage(self, percent: float) -> str:
        """Formate un pourcentage avec couleur"""
        if percent > 0:
            return f"\033[92m+{percent:.1f}%\033[0m"  # Vert
        elif percent < 0:
            return f"\033[91m{percent:.1f}%\033[0m"   # Rouge
        else:
            return f"{percent:.1f}%"
    
    def format_pnl(self, pnl_sol: float, sol_price_usd: float) -> str:
        """Formate le PnL avec couleur et USD"""
        color = "\033[92m" if pnl_sol >= 0 else "\033[91m"  # Vert ou Rouge
        reset = "\033[0m"
        
        if sol_price_usd > 0:
            pnl_usd = pnl_sol * sol_price_usd
            return f"{color}{pnl_sol:+.6f} SOL (${pnl_usd:+.2f}){reset}"
        return f"{color}{pnl_sol:+.6f} SOL{reset}"
    
    def clear_screen(self):
        """Efface l'écran"""
        os.system('cls' if os.name == 'nt' else 'clear')
    
    def display_portfolio(self, summary: PortfolioSummary, positions: List[PositionData], 
                         daily_stats: Dict[str, Any], sol_price_usd: float):
        """Affiche le dashboard complet du portfolio"""
        self.clear_screen()
        
        # Header
        print("╔" + "═" * 78 + "╗")
        print(f"║{' ' * 20}🚀 AUTOTRADER PORTFOLIO TRACKER 🚀{' ' * 20}║")
        print("╠" + "═" * 78 + "╣")
        
        # Time and network info
        current_time = datetime.now().strftime("%H:%M:%S")
        print(f"║ Time: {current_time}  │  SOL Price: ${sol_price_usd:.2f}  │  Last Update: {current_time} ║")
        print("╠" + "═" * 78 + "╣")
        
        # Portfolio summary
        total_value_usd = summary.total_value_sol * sol_price_usd if sol_price_usd > 0 else 0
        print(f"║ 💼 PORTFOLIO SUMMARY{' ' * 54}║")
        print(f"║   Total Value: {self.format_sol_with_usd(summary.total_value_sol, sol_price_usd):<45} ║")
        print(f"║   Invested: {summary.total_invested_sol:.6f} SOL{' ' * 35}║")
        print(f"║   Fees Paid: {summary.total_fees_sol:.6f} SOL{' ' * 34}║")
        print(f"║   Unrealized PnL: {self.format_pnl(summary.unrealized_pnl_sol, sol_price_usd):<35} ║")
        print(f"║   Total Return: {self.format_percentage(summary.unrealized_pnl_percent):<35} ║")
        print("╠" + "═" * 78 + "╣")
        
        # Active positions
        print(f"║ 📊 ACTIVE POSITIONS ({summary.active_positions}){' ' * 48}║")
        
        if positions:
            print("║ Symbol    │ Tokens    │ Entry Price │ Current   │ PnL      │ Age     ║")
            print("╠───────────┼───────────┼─────────────┼───────────┼──────────┼─────────╣")
            
            for pos in positions[:10]:  # Limiter à 10 positions
                symbol = pos.token_symbol[:8].ljust(8)
                tokens = f"{pos.total_tokens_held:,.0f}".rjust(8)
                entry_price = f"{pos.average_entry_price_sol:.8f}"[:10].ljust(10)
                current_price = f"{pos.current_price_sol:.8f}"[:8].ljust(8)
                pnl = self.format_percentage(pos.unrealized_pnl_percent)
                age_hours = pos.age_minutes // 60
                age = f"{age_hours}h" if age_hours < 24 else f"{age_hours//24}d"
                
                print(f"║ {symbol} │ {tokens} │ {entry_price} │ {current_price} │ {pnl:<8} │ {age:<6} ║")
        else:
            print("║                           No active positions                          ║")
        
        print("╠" + "═" * 78 + "╣")
        
        # Daily stats
        print(f"║ 📈 TODAY'S TRADING STATS{' ' * 49}║")
        print(f"║   Trades: {daily_stats['total_trades']} (Buy: {daily_stats['buy_trades']}, Sell: {daily_stats['sell_trades']}){' ' * 30}║")
        print(f"║   Spent: {daily_stats['total_spent']:.6f} SOL{' ' * 35}║")
        print(f"║   Fees: {daily_stats['total_fees']:.6f} SOL{' ' * 36}║")
        
        if daily_stats['avg_confirmation_time'] > 0:
            print(f"║   Avg Confirmation: {daily_stats['avg_confirmation_time']:.1f}s{' ' * 32}║")
        
        print("╠" + "═" * 78 + "╣")
        
        # Best/Worst performers
        if summary.best_performer:
            best = summary.best_performer
            print(f"║ 🏆 Best: {best.token_symbol} {self.format_percentage(best.unrealized_pnl_percent):<30} ║")
        
        if summary.worst_performer and summary.worst_performer != summary.best_performer:
            worst = summary.worst_performer
            print(f"║ 📉 Worst: {worst.token_symbol} {self.format_percentage(worst.unrealized_pnl_percent):<29} ║")
        
        print("╚" + "═" * 78 + "╝")
        
        # Footer
        print(f"\n💡 Press Ctrl+C to stop monitoring")
        print(f"🔄 Auto-refresh every 30 seconds")

class PortfolioTracker:
    """Tracker principal du portfolio"""
    
    def __init__(self, db_path: str = "app/data/autotrader.db", network: str = None):
        self.db = DatabaseManager(db_path)
        self.display = PortfolioDisplay()
        self.network = network
        self.running = False
        self.update_interval = 30  # seconds
    
    async def update_all_prices(self, positions: List[PositionData]):
        """Met à jour les prix de toutes les positions"""
        async with PriceProvider() as price_provider:
            tasks = []
            
            for position in positions:
                task = self.update_position_price(price_provider, position)
                tasks.append(task)
            
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
    
    async def update_position_price(self, price_provider: PriceProvider, position: PositionData):
        """Met à jour le prix d'une position individuelle"""
        try:
            new_price = await price_provider.get_token_price_sol(
                position.token_address, 
                position.network
            )
            
            if new_price and new_price > 0:
                self.db.update_position_price(
                    position.token_address, 
                    new_price, 
                    position.network
                )
                logger.debug(f"Updated price for {position.token_symbol}: {new_price:.8f} SOL")
            else:
                logger.debug(f"Could not update price for {position.token_symbol}")
                
        except Exception as e:
            logger.debug(f"Error updating price for {position.token_symbol}: {e}")
    
    def calculate_portfolio_summary(self, positions: List[PositionData], 
                                   daily_stats: Dict[str, Any]) -> PortfolioSummary:
        """Calcule le résumé du portfolio"""
        if not positions:
            return PortfolioSummary(
                total_value_sol=0, total_invested_sol=0, total_fees_sol=0,
                unrealized_pnl_sol=0, unrealized_pnl_percent=0,
                total_positions=0, active_positions=0,
                best_performer=None, worst_performer=None,
                daily_trades=daily_stats['total_trades'],
                daily_spent_sol=daily_stats['total_spent'],
                daily_fees_sol=daily_stats['total_fees']
            )
        
        total_value = sum(pos.current_value_sol for pos in positions)
        total_invested = sum(pos.total_sol_invested for pos in positions)
        total_fees = sum(pos.total_fees_paid_sol for pos in positions)
        unrealized_pnl = total_value - total_invested
        unrealized_pnl_percent = (unrealized_pnl / total_invested * 100) if total_invested > 0 else 0
        
        # Meilleurs et pires performers
        best_performer = max(positions, key=lambda p: p.unrealized_pnl_percent) if positions else None
        worst_performer = min(positions, key=lambda p: p.unrealized_pnl_percent) if positions else None
        
        return PortfolioSummary(
            total_value_sol=total_value,
            total_invested_sol=total_invested,
            total_fees_sol=total_fees,
            unrealized_pnl_sol=unrealized_pnl,
            unrealized_pnl_percent=unrealized_pnl_percent,
            total_positions=len(positions),
            active_positions=len([p for p in positions if p.total_tokens_held > 0]),
            best_performer=best_performer,
            worst_performer=worst_performer,
            daily_trades=daily_stats['total_trades'],
            daily_spent_sol=daily_stats['total_spent'],
            daily_fees_sol=daily_stats['total_fees']
        )
    
    async def run_monitoring_loop(self):
        """Boucle principale de monitoring"""
        self.running = True
        logger.info("🚀 Starting portfolio monitoring...")
        
        while self.running:
            try:
                # Récupérer les données
                positions = self.db.get_current_positions(self.network)
                daily_stats = self.db.get_daily_stats(network=self.network)
                
                # Mettre à jour les prix
                if positions:
                    await self.update_all_prices(positions)
                    # Re-récupérer les positions avec les prix mis à jour
                    positions = self.db.get_current_positions(self.network)
                
                # Calculer le résumé
                summary = self.calculate_portfolio_summary(positions, daily_stats)
                
                # Récupérer le prix de SOL
                async with PriceProvider() as price_provider:
                    sol_price_usd = await price_provider.get_sol_price_usd()
                
                # Afficher le dashboard
                self.display.display_portfolio(summary, positions, daily_stats, sol_price_usd)
                
                # Attendre avant la prochaine mise à jour
                await asyncio.sleep(self.update_interval)
                
            except KeyboardInterrupt:
                self.running = False
                break
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                await asyncio.sleep(5)  # Attendre un peu avant de réessayer
    
    def stop(self):
        """Arrête le monitoring"""
        self.running = False
        logger.info("🛑 Stopping portfolio monitoring...")

async def main():
    """Fonction principale"""
    import argparse
    
    parser = argparse.ArgumentParser(description="AutoTrader Portfolio Tracker")
    parser.add_argument("--network", choices=["mainnet", "devnet"], 
                       help="Filter by network")
    parser.add_argument("--interval", type=int, default=30,
                       help="Update interval in seconds (default: 30)")
    parser.add_argument("--db", default="app/data/autotrader.db",
                       help="Database path (default: app/data/autotrader.db)")
    
    args = parser.parse_args()
    
    # Vérifier que la base de données existe
    if not Path(args.db).exists():
        print(f"❌ Database not found: {args.db}")
        print("💡 Please run the SQL schema first to create the database:")
        print(f"   sqlite3 {args.db} < data/create_database.sql")
        return
    
    # Créer et lancer le tracker
    tracker = PortfolioTracker(db_path=args.db, network=args.network)
    tracker.update_interval = args.interval
    
    try:
        await tracker.run_monitoring_loop()
    except KeyboardInterrupt:
        print("\n\n✅ Portfolio tracking stopped by user")
    except Exception as e:
        print(f"\n\n❌ Error: {e}")
    finally:
        tracker.stop()

if __name__ == "__main__":
    print("🚀 AutoTrader Portfolio Tracker")
    print("=" * 50)
    asyncio.run(main())