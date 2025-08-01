#!/usr/bin/env python3
"""
🐋 Advanced Whale Tracking System
Track known profitable wallets and copy their moves
"""

import asyncio
import aiohttp
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set
import sqlite3

logger = logging.getLogger('whale_tracker')

class AdvancedWhaleTracker:
    """Système de tracking avancé des whales"""
    
    def __init__(self, database_path: str = "tokens.db"):
        self.database_path = database_path
        self.session: Optional[aiohttp.ClientSession] = None
        
        # Known profitable wallets (à enrichir avec recherche)
        self.known_whales = {
            # Exemple d'adresses (remplacer par vraies adresses)
            "WhaleProfitMaster123456789012345678901234": {
                "label": "Meme Coin Master",
                "success_rate": 85,
                "avg_profit": 4.2,  # Multiplicateur moyen
                "specialty": "early_memecoins",
                "risk_level": "medium",
                "copy_weight": 1.0
            },
            "EarlyGemHunter123456789012345678901234": {
                "label": "Early Gem Hunter", 
                "success_rate": 92,
                "avg_profit": 6.8,
                "specialty": "ultra_early",
                "risk_level": "high",
                "copy_weight": 1.2
            },
            "SafeMoonHunter123456789012345678901234": {
                "label": "Safe Moon Hunter",
                "success_rate": 78,
                "avg_profit": 2.1,
                "specialty": "safe_plays",
                "risk_level": "low", 
                "copy_weight": 0.8
            }
        }
        
        # Tracking des positions actuelles
        self.whale_positions = {}  # whale_address -> {token: position_data}
        self.whale_alerts = []
        
        # Configuration de copy trading
        self.copy_trading_config = {
            "enabled": False,  # ATTENTION: Risqué!
            "max_copy_amount": 1.0,  # Max 1 SOL par copy
            "min_whale_score": 80,
            "blacklisted_whales": set(),
            "auto_sell_follow": True  # Suivre aussi les ventes
        }
        
        self.init_whale_database()
    
    def init_whale_database(self):
        """Initialiser la base de données whale"""
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS whale_transactions_advanced (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signature TEXT UNIQUE,
                whale_address TEXT,
                whale_label TEXT,
                token_address TEXT,
                token_symbol TEXT,
                transaction_type TEXT,
                amount_sol REAL,
                amount_usd REAL,
                token_amount REAL,
                timestamp DATETIME,
                block_time INTEGER,
                whale_score INTEGER,
                copy_executed BOOLEAN DEFAULT FALSE,
                profit_pnl REAL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS whale_performance (
                whale_address TEXT PRIMARY KEY,
                whale_label TEXT,
                total_trades INTEGER DEFAULT 0,
                profitable_trades INTEGER DEFAULT 0,
                total_profit_sol REAL DEFAULT 0,
                success_rate REAL DEFAULT 0,
                avg_profit_multiplier REAL DEFAULT 0,
                last_active DATETIME,
                specialty TEXT,
                risk_level TEXT,
                is_active BOOLEAN DEFAULT TRUE,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        conn.close()
    
    async def start_whale_tracking(self):
        """Démarrer le tracking des whales"""
        await self.start_session()
        
        tasks = [
            self.monitor_whale_transactions(),
            self.analyze_whale_performance(),
            self.detect_new_whales(),
            self.execute_copy_trading(),
            self.update_whale_positions()
        ]
        
        await asyncio.gather(*tasks, return_exceptions=True)
    
    async def start_session(self):
        """Démarrer la session HTTP"""
        if not self.session:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=10)
            )
    
    async def monitor_whale_transactions(self):
        """Monitor les transactions des whales connues"""
        logger.info("🐋 Starting whale transaction monitoring...")
        
        while True:
            try:
                for whale_address, whale_info in self.known_whales.items():
                    # Récupérer transactions récentes de la whale
                    transactions = await self.get_whale_recent_transactions(whale_address)
                    
                    for tx in transactions:
                        await self.process_whale_transaction(tx, whale_address, whale_info)
                
                await asyncio.sleep(15)  # Check toutes les 15 secondes
                
            except Exception as e:
                logger.error(f"Whale monitoring error: {e}")
                await asyncio.sleep(30)
    
    async def get_whale_recent_transactions(self, whale_address: str) -> List[Dict]:
        """Récupérer les transactions récentes d'une whale"""
        try:
            # Helius API pour transactions
            url = "https://rpc.helius.xyz/?api-key=872ddf73-4cfd-4263-a418-521bbde27eb8"
            
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getSignaturesForAddress",
                "params": [
                    whale_address,
                    {"limit": 20}  # 20 transactions récentes
                ]
            }
            
            async with self.session.post(url, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    signatures = data.get("result", [])
                    
                    # Récupérer détails de chaque transaction
                    transactions = []
                    for sig_info in signatures[:10]:  # Analyser les 10 plus récentes
                        tx_detail = await self.get_transaction_detail(sig_info["signature"])
                        if tx_detail:
                            transactions.append(tx_detail)
                    
                    return transactions
        
        except Exception as e:
            logger.debug(f"Error getting whale transactions for {whale_address}: {e}")
        
        return []
    
    async def get_transaction_detail(self, signature: str) -> Optional[Dict]:
        """Récupérer les détails d'une transaction"""
        try:
            url = "https://rpc.helius.xyz/?api-key=872ddf73-4cfd-4263-a418-521bbde27eb8"
            
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getTransaction",
                "params": [
                    signature,
                    {
                        "encoding": "jsonParsed",
                        "maxSupportedTransactionVersion": 0
                    }
                ]
            }
            
            async with self.session.post(url, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("result")
        
        except Exception as e:
            logger.debug(f"Error getting transaction detail {signature}: {e}")
        
        return None
    
    async def process_whale_transaction(self, tx: Dict, whale_address: str, whale_info: Dict):
        """Traiter une transaction de whale"""
        
        if not tx or not tx.get("meta"):
            return
        
        # Parser la transaction pour extraire les infos importantes
        parsed_tx = await self.parse_whale_transaction(tx, whale_address)
        
        if not parsed_tx:
            return
        
        # Vérifier si c'est une nouvelle transaction
        signature = parsed_tx["signature"]
        if await self.transaction_already_processed(signature):
            return
        
        # Calculer le score whale
        whale_score = self.calculate_whale_score(whale_info, parsed_tx)
        
        # Créer l'alerte whale
        whale_alert = {
            **parsed_tx,
            "whale_address": whale_address,
            "whale_label": whale_info["label"],
            "whale_score": whale_score,
            "whale_success_rate": whale_info["success_rate"],
            "whale_specialty": whale_info["specialty"],
            "detection_time": datetime.now()
        }
        
        # Sauvegarder la transaction
        await self.save_whale_transaction(whale_alert)
        
        # Alerte si score élevé
        if whale_score >= 75:
            await self.send_whale_alert(whale_alert)
        
        # Copy trading si activé
        if (self.copy_trading_config["enabled"] and 
            whale_score >= self.copy_trading_config["min_whale_score"] and
            parsed_tx["transaction_type"] == "buy"):
            
            await self.execute_copy_trade(whale_alert)
        
        logger.info(f"🐋 WHALE MOVE: {whale_info['label']} {parsed_tx['transaction_type'].upper()} "
                   f"{parsed_tx.get('token_symbol', 'UNKNOWN')} | Score: {whale_score}")
    
    async def parse_whale_transaction(self, tx: Dict, whale_address: str) -> Optional[Dict]:
        """Parser une transaction pour extraire les infos importantes"""
        
        try:
            meta = tx.get("meta", {})
            transaction = tx.get("transaction", {})
            message = transaction.get("message", {})
            
            # Vérifier si c'est un échec
            if meta.get("err"):
                return None
            
            # Analyser les changements de balance des tokens
            pre_balances = meta.get("preTokenBalances", [])
            post_balances = meta.get("postTokenBalances", [])
            
            # Identifier les mouvements de tokens
            token_movements = self.analyze_token_movements(
                pre_balances, post_balances, whale_address
            )
            
            if not token_movements:
                return None
            
            # Prendre le mouvement le plus significatif
            main_movement = max(token_movements, key=lambda x: abs(x.get("amount_change", 0)))
            
            return {
                "signature": tx.get("transaction", {}).get("signatures", [""])[0],
                "block_time": tx.get("blockTime", 0),
                "transaction_type": "buy" if main_movement["amount_change"] > 0 else "sell",
                "token_address": main_movement["mint"],
                "token_symbol": main_movement.get("symbol", "UNKNOWN"),
                "token_amount": abs(main_movement["amount_change"]),
                "amount_sol": main_movement.get("sol_value", 0),
                "amount_usd": main_movement.get("usd_value", 0)
            }
        
        except Exception as e:
            logger.debug(f"Error parsing whale transaction: {e}")
            return None
    
    def analyze_token_movements(self, pre_balances: List, post_balances: List, 
                               whale_address: str) -> List[Dict]:
        """Analyser les mouvements de tokens"""
        
        movements = []
        
        # Créer un mapping des balances par mint
        pre_by_mint = {}
        post_by_mint = {}
        
        for balance in pre_balances:
            if balance.get("owner") == whale_address:
                mint = balance.get("mint")
                amount = float(balance.get("uiTokenAmount", {}).get("uiAmount", 0))
                pre_by_mint[mint] = amount
        
        for balance in post_balances:
            if balance.get("owner") == whale_address:
                mint = balance.get("mint")
                amount = float(balance.get("uiTokenAmount", {}).get("uiAmount", 0))
                post_by_mint[mint] = amount
        
        # Calculer les changements
        all_mints = set(pre_by_mint.keys()) | set(post_by_mint.keys())
        
        for mint in all_mints:
            pre_amount = pre_by_mint.get(mint, 0)
            post_amount = post_by_mint.get(mint, 0)
            change = post_amount - pre_amount
            
            if abs(change) > 0:  # Il y a eu un changement
                movements.append({
                    "mint": mint,
                    "amount_change": change,
                    "pre_amount": pre_amount,
                    "post_amount": post_amount
                    # TODO: Ajouter valeur SOL/USD
                })
        
        return movements
    
    def calculate_whale_score(self, whale_info: Dict, tx: Dict) -> int:
        """Calculer le score d'une transaction whale"""
        
        base_score = whale_info["success_rate"]
        
        # Bonus selon spécialité
        specialty_bonus = {
            "ultra_early": 20,
            "early_memecoins": 15,
            "safe_plays": 10
        }
        base_score += specialty_bonus.get(whale_info["specialty"], 5)
        
        # Bonus selon le montant (plus gros = plus confiance)
        amount_usd = tx.get("amount_usd", 0)
        if amount_usd >= 50000:
            base_score += 15  # Très gros trade
        elif amount_usd >= 20000:
            base_score += 10
        elif amount_usd >= 5000:
            base_score += 5
        
        # Bonus selon le type de transaction
        if tx["transaction_type"] == "buy":
            base_score += 5  # Les achats sont plus intéressants
        
        # Pénalité pour transactions très anciennes
        block_time = tx.get("block_time", 0)
        if block_time > 0:
            time_diff = datetime.now().timestamp() - block_time
            if time_diff > 3600:  # > 1 heure
                base_score -= 10
            elif time_diff > 1800:  # > 30 minutes
                base_score -= 5
        
        return min(max(base_score, 0), 100)
    
    async def transaction_already_processed(self, signature: str) -> bool:
        """Vérifier si une transaction a déjà été traitée"""
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                "SELECT COUNT(*) FROM whale_transactions_advanced WHERE signature = ?",
                (signature,)
            )
            count = cursor.fetchone()[0]
            return count > 0
        except:
            return False
        finally:
            conn.close()
    
    async def save_whale_transaction(self, whale_alert: Dict):
        """Sauvegarder une transaction whale en base"""
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT OR REPLACE INTO whale_transactions_advanced 
                (signature, whale_address, whale_label, token_address, token_symbol,
                 transaction_type, amount_sol, amount_usd, token_amount, timestamp,
                 block_time, whale_score, copy_executed)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                whale_alert["signature"],
                whale_alert["whale_address"], 
                whale_alert["whale_label"],
                whale_alert["token_address"],
                whale_alert.get("token_symbol"),
                whale_alert["transaction_type"],
                whale_alert.get("amount_sol", 0),
                whale_alert.get("amount_usd", 0),
                whale_alert.get("token_amount", 0),
                whale_alert["detection_time"].strftime('%Y-%m-%d %H:%M:%S'),
                whale_alert.get("block_time", 0),
                whale_alert["whale_score"],
                False
            ))
            
            conn.commit()
        except Exception as e:
            logger.error(f"Error saving whale transaction: {e}")
        finally:
            conn.close()
    
    async def send_whale_alert(self, whale_alert: Dict):
        """Envoyer une alerte whale high-score"""
        
        alert_msg = f"""
🐋 HIGH-SCORE WHALE ALERT 🐋
🏷️ Whale: {whale_alert['whale_label']} ({whale_alert['whale_success_rate']}% success rate)
📊 Score: {whale_alert['whale_score']}/100
🎯 Action: {whale_alert['transaction_type'].upper()}
💰 Token: {whale_alert.get('token_symbol', 'UNKNOWN')} ({whale_alert['token_address'][:8]}...)
💵 Amount: ${whale_alert.get('amount_usd', 0):,.0f} ({whale_alert.get('amount_sol', 0):.2f} SOL)
⚡ Specialty: {whale_alert['whale_specialty']}
🔗 TX: https://solscan.io/tx/{whale_alert['signature']}
        """
        
        logger.warning(alert_msg)
        # TODO: Envoyer via Discord/Telegram
    
    async def execute_copy_trade(self, whale_alert: Dict):
        """Exécuter un copy trade (TRÈS RISQUÉ!)"""
        
        if whale_alert["transaction_type"] != "buy":
            return  # Ne copier que les achats pour l'instant
        
        token_address = whale_alert["token_address"]
        whale_score = whale_alert["whale_score"]
        
        # Calculer le montant à copier
        copy_amount = self.calculate_copy_amount(whale_alert)
        
        if copy_amount <= 0:
            return
        
        logger.warning(f"🤖 COPY TRADING: Copying {whale_alert['whale_label']} - "
                      f"Buying {copy_amount} SOL of {token_address}")
        
        # TODO: Intégrer avec les bots de sniper pour exécuter l'achat
        # await sniper_bot.buy_token(token_address, copy_amount, slippage=12)
        
        # Marquer comme copié
        await self.mark_transaction_copied(whale_alert["signature"])
    
    def calculate_copy_amount(self, whale_alert: Dict) -> float:
        """Calculer le montant à copier selon le score whale"""
        
        max_amount = self.copy_trading_config["max_copy_amount"]
        whale_score = whale_alert["whale_score"]
        
        # Plus le score est haut, plus on copie
        if whale_score >= 95:
            return max_amount  # Copy complet
        elif whale_score >= 85:
            return max_amount * 0.8
        elif whale_score >= 75:
            return max_amount * 0.5
        else:
            return 0  # Ne pas copier
    
    async def mark_transaction_copied(self, signature: str):
        """Marquer une transaction comme copiée"""
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                "UPDATE whale_transactions_advanced SET copy_executed = TRUE WHERE signature = ?",
                (signature,)
            )
            conn.commit()
        except Exception as e:
            logger.error(f"Error marking transaction as copied: {e}")
        finally:
            conn.close()
    
    async def analyze_whale_performance(self):
        """Analyser les performances des whales pour ajuster les scores"""
        
        while True:
            try:
                await asyncio.sleep(3600)  # Analyse toutes les heures
                
                for whale_address, whale_info in self.known_whales.items():
                    performance = await self.calculate_whale_performance(whale_address)
                    
                    if performance:
                        # Mettre à jour les infos de la whale
                        whale_info.update({
                            "success_rate": performance["success_rate"],
                            "avg_profit": performance["avg_profit"],
                            "total_trades": performance["total_trades"]
                        })
                        
                        logger.info(f"📊 Updated {whale_info['label']} performance: "
                                  f"{performance['success_rate']:.1f}% success, "
                                  f"{performance['avg_profit']:.2f}x avg profit")
            
            except Exception as e:
                logger.error(f"Error analyzing whale performance: {e}")
    
    async def calculate_whale_performance(self, whale_address: str) -> Optional[Dict]:
        """Calculer les performances d'une whale"""
        
        # TODO: Analyser les trades historiques et calculer:
        # - Taux de succès (trades profitables / total trades)
        # - Profit moyen par trade
        # - Drawdown maximum
        # - Spécialité (types de tokens préférés)
        
        return {
            "success_rate": 85.0,
            "avg_profit": 3.2,
            "total_trades": 156,
            "profitable_trades": 133
        }
    
    async def detect_new_whales(self):
        """Détecter de nouvelles whales performantes"""
        
        while True:
            try:
                await asyncio.sleep(7200)  # Check toutes les 2 heures
                
                # Analyser les transactions récentes pour identifier les wallets performants
                new_whales = await self.find_new_profitable_wallets()
                
                for whale_data in new_whales:
                    if whale_data["address"] not in self.known_whales:
                        
                        # Ajouter la nouvelle whale
                        self.known_whales[whale_data["address"]] = {
                            "label": f"Auto-detected Whale {len(self.known_whales)+1}",
                            "success_rate": whale_data["success_rate"],
                            "avg_profit": whale_data["avg_profit"],
                            "specialty": "auto_detected",
                            "risk_level": "medium",
                            "copy_weight": 0.8
                        }
                        
                        logger.info(f"🔍 NEW WHALE DETECTED: {whale_data['address'][:8]}... "
                                  f"({whale_data['success_rate']:.1f}% success rate)")
            
            except Exception as e:
                logger.error(f"Error detecting new whales: {e}")
    
    async def find_new_profitable_wallets(self) -> List[Dict]:
        """Trouver de nouveaux wallets profitables"""
        
        # TODO: Analyser les transactions récentes sur les tokens qui ont bien performé
        # pour identifier les wallets qui les ont achetés tôt
        
        return []  # Placeholder
    
    async def execute_copy_trading(self):
        """Boucle principale de copy trading"""
        
        while True:
            try:
                if not self.copy_trading_config["enabled"]:
                    await asyncio.sleep(60)
                    continue
                
                # Vérifier s'il y a des trades à suivre
                pending_copies = await self.get_pending_copy_trades()
                
                for copy_trade in pending_copies:
                    await self.process_copy_trade(copy_trade)
                
                await asyncio.sleep(10)  # Check toutes les 10 secondes
                
            except Exception as e:
                logger.error(f"Error in copy trading loop: {e}")
                await asyncio.sleep(30)
    
    async def get_pending_copy_trades(self) -> List[Dict]:
        """Récupérer les trades en attente de copy"""
        
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                SELECT * FROM whale_transactions_advanced 
                WHERE copy_executed = FALSE 
                AND whale_score >= ? 
                AND transaction_type = 'buy'
                AND timestamp > datetime('now', '-15 minutes', 'localtime')
                ORDER BY whale_score DESC, timestamp DESC
                LIMIT 10
            ''', (self.copy_trading_config["min_whale_score"],))
            
            rows = cursor.fetchall()
            columns = [description[0] for description in cursor.description]
            
            return [dict(zip(columns, row)) for row in rows]
        
        except Exception as e:
            logger.error(f"Error getting pending copy trades: {e}")
            return []
        finally:
            conn.close()
    
    async def process_copy_trade(self, copy_trade: Dict):
        """Traiter un copy trade individuel"""
        
        # Vérifications de sécurité
        if copy_trade["whale_address"] in self.copy_trading_config["blacklisted_whales"]:
            return
        
        # Vérifier que le token n'est pas déjà trop cher
        current_price = await self.get_current_token_price(copy_trade["token_address"])
        if current_price and copy_trade.get("amount_usd", 0) > 0:
            price_change = (current_price - copy_trade["amount_usd"]) / copy_trade["amount_usd"]
            if price_change > 0.5:  # Prix a déjà augmenté de 50%+
                logger.info(f"⚠️ Skipping copy trade - price already up {price_change:.1%}")
                return
        
        # Exécuter le copy trade
        await self.execute_copy_trade(copy_trade)
    
    async def get_current_token_price(self, token_address: str) -> Optional[float]:
        """Récupérer le prix actuel d'un token"""
        
        try:
            # Quick price check via Jupiter
            url = f"https://quote-api.jup.ag/v6/quote?inputMint={token_address}&outputMint=EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v&amount=1000000"
            
            async with self.session.get(url, timeout=5) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if "outAmount" in data:
                        return int(data["outAmount"]) / 1e6
        
        except Exception as e:
            logger.debug(f"Error getting current price for {token_address}: {e}")
        
        return None
    
    async def update_whale_positions(self):
        """Mettre à jour les positions actuelles des whales"""
        
        while True:
            try:
                await asyncio.sleep(300)  # Update toutes les 5 minutes
                
                for whale_address in self.known_whales.keys():
                    positions = await self.get_whale_current_positions(whale_address)
                    self.whale_positions[whale_address] = positions
                
            except Exception as e:
                logger.error(f"Error updating whale positions: {e}")
    
    async def get_whale_current_positions(self, whale_address: str) -> Dict:
        """Récupérer les positions actuelles d'une whale"""
        
        try:
            # Helius API pour les token accounts
            url = "https://rpc.helius.xyz/?api-key=872ddf73-4cfd-4263-a418-521bbde27eb8"
            
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getTokenAccountsByOwner",
                "params": [
                    whale_address,
                    {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"},
                    {"encoding": "jsonParsed"}
                ]
            }
            
            async with self.session.post(url, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    accounts = data.get("result", {}).get("value", [])
                    
                    positions = {}
                    for account in accounts:
                        parsed = account.get("account", {}).get("data", {}).get("parsed", {})
                        info = parsed.get("info", {})
                        
                        mint = info.get("mint")
                        amount = float(info.get("tokenAmount", {}).get("uiAmount", 0))
                        
                        if mint and amount > 0:
                            positions[mint] = {
                                "amount": amount,
                                "account": account.get("pubkey")
                            }
                    
                    return positions
        
        except Exception as e:
            logger.debug(f"Error getting positions for {whale_address}: {e}")
        
        return {}
    
    def get_whale_stats(self) -> Dict:
        """Récupérer les statistiques des whales"""
        
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        try:
            # Stats générales
            cursor.execute("SELECT COUNT(*) FROM whale_transactions_advanced")
            total_transactions = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM whale_transactions_advanced WHERE copy_executed = TRUE")
            copied_transactions = cursor.fetchone()[0]
            
            cursor.execute("""
                SELECT COUNT(*) FROM whale_transactions_advanced 
                WHERE timestamp > datetime('now', '-24 hours', 'localtime')
            """)
            transactions_24h = cursor.fetchone()[0]
            
            # Top whales
            cursor.execute("""
                SELECT whale_label, COUNT(*) as trades, AVG(whale_score) as avg_score
                FROM whale_transactions_advanced 
                GROUP BY whale_address, whale_label
                ORDER BY trades DESC
                LIMIT 5
            """)
            top_whales = cursor.fetchall()
            
            return {
                "total_transactions_tracked": total_transactions,
                "copied_transactions": copied_transactions,
                "transactions_24h": transactions_24h,
                "copy_rate": (copied_transactions / max(total_transactions, 1)) * 100,
                "top_whales": [
                    {"label": row[0], "trades": row[1], "avg_score": row[2]}
                    for row in top_whales
                ],
                "active_whales": len(self.known_whales),
                "copy_trading_enabled": self.copy_trading_config["enabled"]
            }
        
        except Exception as e:
            logger.error(f"Error getting whale stats: {e}")
            return {}
        finally:
            conn.close()


# Configuration et utilisation
async def setup_whale_tracker():
    """Setup du whale tracker"""
    
    tracker = AdvancedWhaleTracker()
    
    # Configuration copy trading (ATTENTION: TRÈS RISQUÉ!)
    tracker.copy_trading_config.update({
        "enabled": False,  # Désactivé par défaut
        "max_copy_amount": 0.5,  # Max 0.5 SOL par copy
        "min_whale_score": 85,
        "auto_sell_follow": True
    })
    
    return tracker


# Exemple d'utilisation
async def main():
    tracker = await setup_whale_tracker()
    
    # Afficher les stats actuelles
    stats = tracker.get_whale_stats()
    print("🐋 Whale Tracker Stats:")
    print(f"   Total transactions tracked: {stats['total_transactions_tracked']}")
    print(f"   Active whales: {stats['active_whales']}")
    print(f"   Copy trading enabled: {stats['copy_trading_enabled']}")
    
    # Démarrer le tracking (en production)
    # await tracker.start_whale_tracking()

if __name__ == "__main__":
    asyncio.run(main())