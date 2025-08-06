#!/usr/bin/env python3
"""
Script de Monitoring Global pour le Scanner Solana
Vue d'ensemble temps réel avec métriques synthétiques et alertes
Version modifiée avec support du filtrage par wallet
"""

import sqlite3
import time
import os
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import json

# Couleurs pour l'affichage terminal
class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

class SolanaMonitoringDashboard:
    def __init__(self, db_path: str = "solana_wallet.db", target_wallet: str = None):
        self.db_path = db_path
        self.target_wallet = target_wallet
        self.refresh_interval = 30  # secondes
        self.start_time = time.time()
        self.last_stats = {}
        
        # Valider le wallet si fourni
        if self.target_wallet:
            self.target_wallet = self.target_wallet.strip()
            if not self._validate_wallet_exists():
                print(f"{Colors.WARNING}⚠️  Wallet {self.target_wallet} non trouvé en base{Colors.ENDC}")
                print(f"{Colors.OKCYAN}💡 Le monitoring continuera mais avec des données vides{Colors.ENDC}")
    
    def _validate_wallet_exists(self) -> bool:
        """Vérifie que le wallet existe en base"""
        conn = self.get_connection()
        if not conn:
            return False
        
        try:
            cursor = conn.cursor()
            
            # Vérifier dans wallet_priorities
            cursor.execute('SELECT COUNT(*) FROM wallet_priorities WHERE wallet_address = ?', 
                          (self.target_wallet,))
            count = cursor.fetchone()[0]
            
            if count > 0:
                print(f"{Colors.OKGREEN}✅ Wallet {self.target_wallet[:8]}... trouvé en base{Colors.ENDC}")
                return True
            
            # Vérifier dans les transactions si pas dans les priorités
            cursor.execute('SELECT COUNT(*) FROM transactions WHERE wallet_address = ?', 
                          (self.target_wallet,))
            tx_count = cursor.fetchone()[0]
            
            if tx_count > 0:
                print(f"{Colors.OKGREEN}✅ Wallet {self.target_wallet[:8]}... trouvé dans les transactions{Colors.ENDC}")
                return True
            
            return False
            
        except Exception as e:
            print(f"{Colors.FAIL}❌ Erreur validation wallet: {e}{Colors.ENDC}")
            return False
        finally:
            conn.close()
    
    def _get_wallet_filter_clause(self, table_alias: str = "") -> tuple:
        """Retourne la clause WHERE et les paramètres pour filtrer par wallet"""
        if not self.target_wallet:
            return "", ()
        
        prefix = f"{table_alias}." if table_alias else ""
        return f" AND {prefix}wallet_address = ?", (self.target_wallet,)
        
    def clear_screen(self):
        """Efface l'écran du terminal"""
        os.system('cls' if os.name == 'nt' else 'clear')
    
    def get_connection(self):
        """Crée une connexion à la base de données"""
        try:
            return sqlite3.connect(self.db_path)
        except Exception as e:
            print(f"{Colors.FAIL}❌ Erreur connexion DB: {e}{Colors.ENDC}")
            return None
    
    def format_duration(self, seconds: int) -> str:
        """Formate une durée en format lisible"""
        if seconds < 60:
            return f"{seconds}s"
        elif seconds < 3600:
            return f"{seconds//60}m{seconds%60}s"
        elif seconds < 86400:
            return f"{seconds//3600}h{(seconds%3600)//60}m"
        else:
            return f"{seconds//86400}j{(seconds%86400)//3600}h"
    
    def format_number(self, num: float) -> str:
        """Formate un nombre avec des séparateurs"""
        if num >= 1000000:
            return f"{num/1000000:.1f}M"
        elif num >= 1000:
            return f"{num/1000:.1f}K"
        else:
            return f"{num:.0f}"
    
    def get_system_status(self) -> Dict:
        """Récupère le statut général du système"""
        conn = self.get_connection()
        if not conn:
            return {}
        
        try:
            cursor = conn.cursor()
            current_time = int(time.time())
            
            # Obtenir les clauses de filtrage
            wallet_filter, wallet_params = self._get_wallet_filter_clause()
            
            # Vérifier si le système fonctionne (transactions récentes)
            query = '''
                SELECT COUNT(*) FROM transactions 
                WHERE created_at >= datetime('now', '-5 minutes')
            ''' + wallet_filter
            cursor.execute(query, wallet_params)
            recent_activity = cursor.fetchone()[0]
            
            # Dernier scan
            if self.target_wallet:
                cursor.execute('''
                    SELECT MAX(completed_at) FROM scan_history 
                    WHERE wallet_address = ?
                ''', (self.target_wallet,))
            else:
                cursor.execute('SELECT MAX(completed_at) FROM scan_history')
            
            last_scan_result = cursor.fetchone()
            last_scan = last_scan_result[0] if last_scan_result[0] else 0
            
            # Statut des priorités
            if self.target_wallet:
                cursor.execute('''
                    SELECT COUNT(*) as total,
                           COUNT(CASE WHEN priority_score >= 4.0 THEN 1 END) as high,
                           COUNT(CASE WHEN priority_score >= 2.0 AND priority_score < 4.0 THEN 1 END) as medium,
                           COUNT(CASE WHEN priority_score < 2.0 THEN 1 END) as low,
                           AVG(priority_score) as avg_priority
                    FROM wallet_priorities
                    WHERE wallet_address = ?
                ''', (self.target_wallet,))
            else:
                cursor.execute('''
                    SELECT COUNT(*) as total,
                           COUNT(CASE WHEN priority_score >= 4.0 THEN 1 END) as high,
                           COUNT(CASE WHEN priority_score >= 2.0 AND priority_score < 4.0 THEN 1 END) as medium,
                           COUNT(CASE WHEN priority_score < 2.0 THEN 1 END) as low,
                           AVG(priority_score) as avg_priority
                    FROM wallet_priorities
                ''')
            
            priority_stats = cursor.fetchone()
            
            # Wallets prêts à scanner
            ready_query = '''
                SELECT COUNT(*) FROM wallet_priorities
                WHERE (? - last_scan_time) >= 
                    CASE 
                        WHEN priority_score >= 4.0 THEN 30
                        WHEN priority_score >= 2.0 THEN 90
                        ELSE 180
                    END
            ''' + wallet_filter
            
            cursor.execute(ready_query, (current_time,) + wallet_params)
            ready_wallets = cursor.fetchone()[0]
            
            status = {
                'is_active': recent_activity > 0 or (current_time - last_scan) < 300,
                'last_scan_time': last_scan,
                'seconds_since_last_scan': current_time - last_scan if last_scan > 0 else 999999,
                'total_wallets': priority_stats[0] if priority_stats else 0,
                'high_priority_wallets': priority_stats[1] if priority_stats else 0,
                'medium_priority_wallets': priority_stats[2] if priority_stats else 0,
                'low_priority_wallets': priority_stats[3] if priority_stats else 0,
                'avg_priority_score': priority_stats[4] if priority_stats else 0,
                'wallets_ready_for_scan': ready_wallets,
                'recent_activity_5min': recent_activity,
                'filtered_wallet': self.target_wallet
            }
            
            return status
            
        except Exception as e:
            print(f"{Colors.FAIL}Erreur statut système: {e}{Colors.ENDC}")
            return {}
        finally:
            conn.close()
    
    def get_discovery_stats(self) -> Dict:
        """Statistiques de découverte de nouveaux comptes de tokens"""
        conn = self.get_connection()
        if not conn:
            return {}
        
        try:
            cursor = conn.cursor()
            current_time = int(time.time())
            
            # Obtenir les clauses de filtrage
            wallet_filter, wallet_params = self._get_wallet_filter_clause()
            
            stats = {}
            
            # Découvertes par période et par wallet
            periods = [
                ('1h', current_time - 3600),
                ('6h', current_time - 21600),
                ('24h', current_time - 86400)
            ]
            
            for period_name, start_time in periods:
                # Total découvertes
                query = '''
                    SELECT COUNT(*) FROM token_accounts 
                    WHERE first_seen >= ?
                ''' + wallet_filter
                cursor.execute(query, (start_time,) + wallet_params)
                total_discoveries = cursor.fetchone()[0]
                
                # Par wallet (seulement si on ne filtre pas déjà par wallet)
                wallet_discoveries = []
                if not self.target_wallet:
                    cursor.execute('''
                        SELECT wallet_address, COUNT(*) as discoveries
                        FROM token_accounts 
                        WHERE first_seen >= ?
                        GROUP BY wallet_address
                        ORDER BY discoveries DESC
                    ''', (start_time,))
                    
                    for wallet, count in cursor.fetchall():
                        wallet_discoveries.append({
                            'wallet': f"{wallet[:6]}...{wallet[-6:]}",
                            'discoveries': count
                        })
                
                stats[f'discoveries_{period_name}'] = {
                    'total': total_discoveries,
                    'by_wallet': wallet_discoveries[:5]  # Top 5
                }
            
            # Total comptes trackés
            query = 'SELECT COUNT(*) FROM token_accounts WHERE is_active = 1' + wallet_filter
            cursor.execute(query, wallet_params)
            total_tracked = cursor.fetchone()[0]
            
            # Nouveaux comptes aujourd'hui
            today_start = int(datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
            query = 'SELECT COUNT(*) FROM token_accounts WHERE first_seen >= ?' + wallet_filter
            cursor.execute(query, (today_start,) + wallet_params)
            discoveries_today = cursor.fetchone()[0]
            
            stats['total_tracked_accounts'] = total_tracked
            stats['discoveries_today'] = discoveries_today
            
            return stats
            
        except Exception as e:
            print(f"{Colors.FAIL}Erreur stats découvertes: {e}{Colors.ENDC}")
            return {}
        finally:
            conn.close()
    
    def get_balance_change_stats(self) -> Dict:
        """Statistiques des balance changes détectés"""
        conn = self.get_connection()
        if not conn:
            return {}
        
        try:
            cursor = conn.cursor()
            current_time = int(time.time())
            
            # Obtenir les clauses de filtrage
            wallet_filter, wallet_params = self._get_wallet_filter_clause()
            
            stats = {}
            
            # Balance changes par période
            periods = [
                ('1h', current_time - 3600),
                ('6h', current_time - 21600),
                ('24h', current_time - 86400)
            ]
            
            for period_name, start_time in periods:
                # Total balance changes
                query = '''
                    SELECT COUNT(*) FROM transactions 
                    WHERE is_token_transaction = 1 AND block_time >= ?
                ''' + wallet_filter
                cursor.execute(query, (start_time,) + wallet_params)
                total_changes = cursor.fetchone()[0]
                
                # Par type
                query = '''
                    SELECT transaction_type, COUNT(*) as count
                    FROM transactions 
                    WHERE is_token_transaction = 1 AND block_time >= ?
                ''' + wallet_filter + '''
                    GROUP BY transaction_type
                '''
                cursor.execute(query, (start_time,) + wallet_params)
                
                by_type = {}
                for tx_type, count in cursor.fetchall():
                    by_type[tx_type or 'other'] = count
                
                # Par wallet (seulement si on ne filtre pas déjà par wallet)
                by_wallet = []
                if not self.target_wallet:
                    cursor.execute('''
                        SELECT wallet_address, COUNT(*) as changes
                        FROM transactions 
                        WHERE is_token_transaction = 1 AND block_time >= ?
                        GROUP BY wallet_address
                        ORDER BY changes DESC
                        LIMIT 5
                    ''', (start_time,))
                    
                    for wallet, count in cursor.fetchall():
                        by_wallet.append({
                            'wallet': f"{wallet[:6]}...{wallet[-6:]}" if wallet else 'Unknown',
                            'changes': count
                        })
                
                stats[f'balance_changes_{period_name}'] = {
                    'total': total_changes,
                    'by_type': by_type,
                    'by_wallet': by_wallet
                }
            
            # Grosses transactions récentes
            query = '''
                SELECT wallet_address, token_symbol, token_amount, transaction_type, block_time
                FROM transactions 
                WHERE is_large_token_amount = 1 AND block_time >= ?
            ''' + wallet_filter + '''
                ORDER BY block_time DESC
                LIMIT 10
            '''
            cursor.execute(query, (current_time - 86400,) + wallet_params)
            
            large_transactions = []
            for wallet, symbol, amount, tx_type, block_time in cursor.fetchall():
                large_transactions.append({
                    'wallet': f"{wallet[:6]}...{wallet[-6:]}" if wallet else 'Unknown',
                    'symbol': symbol or 'UNKNOWN',
                    'amount': amount or 0,
                    'type': tx_type or 'other',
                    'age_minutes': (current_time - block_time) // 60 if block_time else 999
                })
            
            stats['large_transactions_24h'] = large_transactions
            
            return stats
            
        except Exception as e:
            print(f"{Colors.FAIL}Erreur stats balance changes: {e}{Colors.ENDC}")
            return {}
        finally:
            conn.close()
    
    def get_wallet_priorities(self) -> List[Dict]:
        """Récupère l'état des priorités par wallet"""
        conn = self.get_connection()
        if not conn:
            return []
        
        try:
            cursor = conn.cursor()
            current_time = int(time.time())
            
            # Construire la requête avec filtrage optionnel
            base_query = '''
                SELECT 
                    wallet_address,
                    priority_score,
                    last_scan_time,
                    total_scans,
                    consecutive_empty_scans,
                    activity_score,
                    (? - last_scan_time) as seconds_since_scan,
                    CASE 
                        WHEN priority_score >= 4.0 THEN 30
                        WHEN priority_score >= 2.0 THEN 90
                        ELSE 180
                    END as scan_interval
                FROM wallet_priorities
            '''
            
            if self.target_wallet:
                query = base_query + ' WHERE wallet_address = ? ORDER BY priority_score DESC, last_scan_time ASC'
                cursor.execute(query, (current_time, self.target_wallet))
            else:
                query = base_query + ' ORDER BY priority_score DESC, last_scan_time ASC'
                cursor.execute(query, (current_time,))
            
            wallets = []
            for row in cursor.fetchall():
                wallet_addr = row[0]
                priority = row[1]
                last_scan = row[2]
                total_scans = row[3]
                empty_scans = row[4]
                activity = row[5]
                since_scan = row[6]
                interval = row[7]
                
                # Déterminer le statut
                if since_scan >= interval:
                    status = "READY"
                    status_color = Colors.OKGREEN
                elif since_scan >= interval * 0.8:
                    status = "SOON"
                    status_color = Colors.WARNING
                else:
                    status = "WAIT"
                    status_color = Colors.OKBLUE
                
                # Catégorie de priorité
                if priority >= 4.0:
                    priority_icon = "🔥"
                    priority_color = Colors.FAIL
                elif priority >= 2.0:
                    priority_icon = "🟡"
                    priority_color = Colors.WARNING
                else:
                    priority_icon = "🔵"
                    priority_color = Colors.OKBLUE
                
                wallets.append({
                    'address': wallet_addr,
                    'short_address': f"{wallet_addr[:6]}...{wallet_addr[-6:]}",
                    'priority_score': priority,
                    'priority_icon': priority_icon,
                    'priority_color': priority_color,
                    'status': status,
                    'status_color': status_color,
                    'last_scan_time': last_scan,
                    'seconds_since_scan': since_scan,
                    'scan_interval': interval,
                    'total_scans': total_scans,
                    'empty_scans': empty_scans,
                    'activity_score': activity,
                    'next_scan_eta': max(0, interval - since_scan)
                })
            
            return wallets
            
        except Exception as e:
            print(f"{Colors.FAIL}Erreur priorités wallets: {e}{Colors.ENDC}")
            return []
        finally:
            conn.close()
    
    def get_performance_metrics(self) -> Dict:
        """Métriques de performance du système"""
        conn = self.get_connection()
        if not conn:
            return {}
        
        try:
            cursor = conn.cursor()
            current_time = int(time.time())
            
            # Obtenir les clauses de filtrage pour scan_history
            wallet_filter_scan, wallet_params_scan = self._get_wallet_filter_clause()
            # Pour wallet_activity_metrics
            wallet_filter_activity, wallet_params_activity = self._get_wallet_filter_clause()
            
            # Efficacité des scans (dernières 24h)
            query = '''
                SELECT 
                    COUNT(*) as total_scans,
                    AVG(scan_duration) as avg_duration,
                    SUM(new_accounts) as total_discoveries,
                    AVG(efficiency_score) as avg_efficiency
                FROM scan_history
                WHERE completed_at >= ?
            ''' + wallet_filter_scan
            cursor.execute(query, (current_time - 86400,) + wallet_params_scan)
            scan_stats = cursor.fetchone()
            
            # RPC efficiency (dernières 24h)
            query = '''
                SELECT 
                    SUM(rpc_requests_made) as total_rpc,
                    SUM(discoveries_count + balance_changes_count) as total_findings
                FROM wallet_activity_metrics
                WHERE timestamp >= ?
            ''' + wallet_filter_activity
            cursor.execute(query, (current_time - 86400,) + wallet_params_activity)
            rpc_stats = cursor.fetchone()
            
            # Délais de détection moyens
            wallet_filter_tx, wallet_params_tx = self._get_wallet_filter_clause()
            query = '''
                SELECT AVG(detection_delay) 
                FROM transactions 
                WHERE detection_delay > 0 AND block_time >= ?
            ''' + wallet_filter_tx
            cursor.execute(query, (current_time - 86400,) + wallet_params_tx)
            avg_delay_result = cursor.fetchone()
            avg_detection_delay = avg_delay_result[0] if avg_delay_result[0] else 0
            
            # Taux de réussite
            query = '''
                SELECT 
                    COUNT(CASE WHEN activity_detected = 1 THEN 1 END) as successful_scans,
                    COUNT(*) as total_scans
                FROM scan_history
                WHERE completed_at >= ?
            ''' + wallet_filter_scan
            cursor.execute(query, (current_time - 86400,) + wallet_params_scan)
            success_stats = cursor.fetchone()
            
            metrics = {
                'total_scans_24h': scan_stats[0] if scan_stats[0] else 0,
                'avg_scan_duration': scan_stats[1] if scan_stats[1] else 0,
                'total_discoveries_24h': scan_stats[2] if scan_stats[2] else 0,
                'avg_efficiency': scan_stats[3] if scan_stats[3] else 0,
                'total_rpc_requests_24h': rpc_stats[0] if rpc_stats[0] else 0,
                'total_findings_24h': rpc_stats[1] if rpc_stats[1] else 0,
                'rpc_efficiency': (rpc_stats[1] / max(rpc_stats[0], 1)) * 100 if rpc_stats[0] else 0,
                'avg_detection_delay': avg_detection_delay,
                'success_rate': (success_stats[0] / max(success_stats[1], 1)) * 100 if success_stats[1] else 0
            }
            
            return metrics
            
        except Exception as e:
            print(f"{Colors.FAIL}Erreur métriques performance: {e}{Colors.ENDC}")
            return {}
        finally:
            conn.close()
    
    def get_alerts(self) -> List[Dict]:
        """Génère des alertes intelligentes"""
        alerts = []
        current_time = int(time.time())
        
        try:
            conn = self.get_connection()
            if not conn:
                return alerts
            
            cursor = conn.cursor()
            
            # Obtenir les clauses de filtrage
            wallet_filter, wallet_params = self._get_wallet_filter_clause()
            
            # Alerte: Wallets non scannés depuis longtemps
            query = '''
                SELECT wallet_address, (? - last_scan_time) as minutes_ago
                FROM wallet_priorities
                WHERE (? - last_scan_time) > 600
            ''' + wallet_filter + '''
                ORDER BY last_scan_time ASC
            '''
            cursor.execute(query, (current_time, current_time) + wallet_params)
            
            for wallet, seconds_ago in cursor.fetchall():
                minutes_ago = seconds_ago // 60
                alerts.append({
                    'type': 'warning',
                    'icon': '⚠️',
                    'message': f"Wallet {wallet[:8]}... non scanné depuis {minutes_ago}min",
                    'severity': 'medium' if minutes_ago < 30 else 'high'
                })
            
            # Alerte: Activité récente détectée
            query = '''
                SELECT wallet_address, COUNT(*) as recent_tx
                FROM transactions
                WHERE block_time >= ? AND is_token_transaction = 1
            ''' + wallet_filter + '''
                GROUP BY wallet_address
                HAVING recent_tx >= 3
                ORDER BY recent_tx DESC
            '''
            cursor.execute(query, (current_time - 1800,) + wallet_params)  # Dernières 30 minutes
            
            for wallet, tx_count in cursor.fetchall():
                alerts.append({
                    'type': 'success',
                    'icon': '🔥',
                    'message': f"Wallet CHAUD {wallet[:8]}... - {tx_count} transactions en 30min",
                    'severity': 'info'
                })
            
            # Alerte: Erreurs de scan récentes
            query = '''
                SELECT wallet_address, consecutive_empty_scans
                FROM wallet_priorities
                WHERE consecutive_empty_scans >= 5
            ''' + wallet_filter
            cursor.execute(query, wallet_params)
            
            for wallet, empty_count in cursor.fetchall():
                alerts.append({
                    'type': 'warning',
                    'icon': '💤',
                    'message': f"Wallet {wallet[:8]}... - {empty_count} scans vides consécutifs",
                    'severity': 'low'
                })
            
            # Alerte: Performance dégradée (seulement si on ne filtre pas par wallet)
            if not self.target_wallet:
                cursor.execute('''
                    SELECT AVG(efficiency_score) 
                    FROM wallet_activity_metrics
                    WHERE timestamp >= ?
                ''', (current_time - 3600,))
                
                avg_efficiency = cursor.fetchone()[0]
                if avg_efficiency and avg_efficiency < 10:  # Moins de 10% d'efficacité
                    alerts.append({
                        'type': 'error',
                        'icon': '📉',
                        'message': f"Efficacité système faible: {avg_efficiency:.1f}%",
                        'severity': 'high'
                    })
            
            conn.close()
            
            # Limiter à 10 alertes max
            return alerts[:10]
            
        except Exception as e:
            print(f"{Colors.FAIL}Erreur génération alertes: {e}{Colors.ENDC}")
            return []
    
    def display_header(self):
        """Affiche l'en-tête du dashboard"""
        uptime = int(time.time() - self.start_time)
        current_time = datetime.now().strftime("%H:%M:%S")
        
        print(f"{Colors.HEADER}{Colors.BOLD}")
        print("=" * 100)
        if self.target_wallet:
            print(f"🎯 SOLANA WALLET MONITOR - WALLET FOCUS: {self.target_wallet[:8]}...{self.target_wallet[-8:]}")
        else:
            print("🚀 SOLANA WALLET MONITOR - DASHBOARD GLOBAL")
        print("=" * 100)
        print(f"{Colors.ENDC}")
        print(f"{Colors.OKCYAN}⏰ {current_time} | 🕐 Uptime: {self.format_duration(uptime)} | 🔄 Refresh: {self.refresh_interval}s{Colors.ENDC}")
        if self.target_wallet:
            print(f"{Colors.OKCYAN}🎯 Filtré sur wallet: {self.target_wallet}{Colors.ENDC}")
        print()
    
    def display_system_status(self, status: Dict):
        """Affiche le statut système"""
        print(f"{Colors.BOLD}📊 STATUT SYSTÈME{Colors.ENDC}")
        print("-" * 50)
        
        # Statut principal
        if status.get('is_active', False):
            status_icon = f"{Colors.OKGREEN}🟢 ACTIF{Colors.ENDC}"
        else:
            status_icon = f"{Colors.FAIL}🔴 INACTIF{Colors.ENDC}"
        
        print(f"Status: {status_icon}")
        
        # Dernier scan
        last_scan_ago = status.get('seconds_since_last_scan', 999999)
        if last_scan_ago < 60:
            scan_status = f"{Colors.OKGREEN}{self.format_duration(last_scan_ago)}{Colors.ENDC}"
        elif last_scan_ago < 300:
            scan_status = f"{Colors.WARNING}{self.format_duration(last_scan_ago)}{Colors.ENDC}"
        else:
            scan_status = f"{Colors.FAIL}{self.format_duration(last_scan_ago)}{Colors.ENDC}"
        
        print(f"Dernier scan: {scan_status}")
        
        # Priorités
        total_wallets = status.get('total_wallets', 0)
        high_priority = status.get('high_priority_wallets', 0)
        medium_priority = status.get('medium_priority_wallets', 0)
        low_priority = status.get('low_priority_wallets', 0)
        ready_wallets = status.get('wallets_ready_for_scan', 0)
        
        if self.target_wallet and total_wallets == 0:
            print(f"Wallet: {Colors.WARNING}Non trouvé en base ou pas de données de priorité{Colors.ENDC}")
        else:
            print(f"Wallets: {total_wallets} total | 🔥{high_priority} 🟡{medium_priority} 🔵{low_priority}")
            print(f"Prêts à scanner: {Colors.OKGREEN if ready_wallets > 0 else Colors.WARNING}{ready_wallets}{Colors.ENDC}")
        print()
    
    def display_discoveries(self, discovery_stats: Dict):
        """Affiche les statistiques de découvertes"""
        print(f"{Colors.BOLD}🆕 DÉCOUVERTES DE TOKENS{Colors.ENDC}")
        print("-" * 50)
        
        total_tracked = discovery_stats.get('total_tracked_accounts', 0)
        discoveries_today = discovery_stats.get('discoveries_today', 0)
        
        print(f"Total comptes trackés: {Colors.OKCYAN}{self.format_number(total_tracked)}{Colors.ENDC}")
        print(f"Découvertes aujourd'hui: {Colors.OKGREEN}{discoveries_today}{Colors.ENDC}")
        print()
        
        # Par période
        periods = ['1h', '6h', '24h']
        for period in periods:
            period_data = discovery_stats.get(f'discoveries_{period}', {})
            total = period_data.get('total', 0)
            
            color = Colors.OKGREEN if total > 0 else Colors.WARNING
            print(f"{period.upper()}: {color}{total}{Colors.ENDC} nouveaux comptes")
            
            # Top wallets pour cette période (seulement si on ne filtre pas par wallet)
            if not self.target_wallet:
                top_wallets = period_data.get('by_wallet', [])[:3]
                if top_wallets:
                    for wallet_data in top_wallets:
                        wallet = wallet_data['wallet']
                        count = wallet_data['discoveries']
                        print(f"  └─ {wallet}: {count}")
        print()
    
    def display_balance_changes(self, balance_stats: Dict):
        """Affiche les statistiques de balance changes"""
        print(f"{Colors.BOLD}💰 BALANCE CHANGES{Colors.ENDC}")
        print("-" * 50)
        
        # Par période
        periods = ['1h', '6h', '24h']
        for period in periods:
            period_data = balance_stats.get(f'balance_changes_{period}', {})
            total = period_data.get('total', 0)
            by_type = period_data.get('by_type', {})
            
            color = Colors.OKGREEN if total > 0 else Colors.WARNING
            print(f"{period.upper()}: {color}{total}{Colors.ENDC} balance changes")
            
            # Répartition par type
            if by_type:
                types_str = []
                for tx_type, count in by_type.items():
                    if tx_type == 'buy':
                        types_str.append(f"📈{count}")
                    elif tx_type == 'sell':
                        types_str.append(f"📉{count}")
                    elif tx_type == 'transfer':
                        types_str.append(f"🔄{count}")
                    else:
                        types_str.append(f"⚡{count}")
                
                if types_str:
                    print(f"  └─ {' | '.join(types_str)}")
        
        # Grosses transactions récentes
        large_txs = balance_stats.get('large_transactions_24h', [])
        if large_txs:
            print(f"\n🔥 GROSSES TRANSACTIONS (24h):")
            for tx in large_txs[:5]:
                wallet = tx['wallet']
                symbol = tx['symbol']
                amount = self.format_number(tx['amount'])
                tx_type = tx['type'].upper()
                age = tx['age_minutes']
                
                age_str = f"{age}min" if age < 60 else f"{age//60}h"
                type_icon = "📈" if tx_type == "BUY" else "📉" if tx_type == "SELL" else "🔄"
                
                if self.target_wallet:
                    # Si on filtre par wallet, pas besoin d'afficher l'adresse
                    print(f"  {type_icon} {tx_type} {amount} {symbol} (il y a {age_str})")
                else:
                    print(f"  {type_icon} {wallet}: {tx_type} {amount} {symbol} (il y a {age_str})")
        print()
    
    def display_wallet_priorities(self, wallets: List[Dict]):
        """Affiche l'état des priorités par wallet"""
        print(f"{Colors.BOLD}🎯 PRIORITÉS DES WALLETS{Colors.ENDC}")
        print("-" * 80)
        
        if not wallets:
            if self.target_wallet:
                print(f"Aucune donnée de priorité pour le wallet {self.target_wallet[:8]}...")
            else:
                print("Aucune donnée de priorité disponible")
            return
        
        # En-tête
        if self.target_wallet:
            print(f"{'Priorité':<10} {'Status':<8} {'Scans':<8} {'Activité':<10} {'ETA':<8}")
            print("-" * 50)
        else:
            print(f"{'Wallet':<15} {'Priorité':<10} {'Status':<8} {'Scans':<8} {'Activité':<10} {'ETA':<8}")
            print("-" * 80)
        
        for wallet in wallets:
            short_addr = wallet['short_address']
            priority = f"{wallet['priority_icon']}{wallet['priority_score']:.1f}"
            status = wallet['status']
            status_colored = f"{wallet['status_color']}{status}{Colors.ENDC}"
            total_scans = wallet['total_scans']
            activity = f"{wallet['activity_score']:.1f}"
            
            if wallet['next_scan_eta'] == 0:
                eta = f"{Colors.OKGREEN}NOW{Colors.ENDC}"
            else:
                eta_seconds = wallet['next_scan_eta']
                eta = self.format_duration(eta_seconds)
            
            empty_indicator = f" ({wallet['empty_scans']}💤)" if wallet['empty_scans'] > 0 else ""
            
            if self.target_wallet:
                print(f"{priority:<15} {status_colored:<15} {total_scans:<8} {activity:<10} {eta:<15}{empty_indicator}")
            else:
                print(f"{short_addr:<15} {priority:<15} {status_colored:<15} {total_scans:<8} {activity:<10} {eta:<15}{empty_indicator}")
        print()
    
    def display_performance(self, metrics: Dict):
        """Affiche les métriques de performance"""
        print(f"{Colors.BOLD}📈 PERFORMANCE (24h){Colors.ENDC}")
        print("-" * 50)
        
        total_scans = metrics.get('total_scans_24h', 0)
        avg_duration = metrics.get('avg_scan_duration', 0)
        total_discoveries = metrics.get('total_discoveries_24h', 0)
        rpc_efficiency = metrics.get('rpc_efficiency', 0)
        success_rate = metrics.get('success_rate', 0)
        avg_delay = metrics.get('avg_detection_delay', 0)
        
        print(f"Scans effectués: {Colors.OKCYAN}{total_scans}{Colors.ENDC}")
        print(f"Durée moyenne: {avg_duration:.1f}s")
        print(f"Découvertes totales: {Colors.OKGREEN}{total_discoveries}{Colors.ENDC}")
        
        # Efficacité RPC avec couleur
        if rpc_efficiency >= 20:
            eff_color = Colors.OKGREEN
        elif rpc_efficiency >= 10:
            eff_color = Colors.WARNING
        else:
            eff_color = Colors.FAIL
        
        print(f"Efficacité RPC: {eff_color}{rpc_efficiency:.1f}%{Colors.ENDC}")
        
        # Taux de réussite avec couleur
        if success_rate >= 80:
            success_color = Colors.OKGREEN
        elif success_rate >= 60:
            success_color = Colors.WARNING
        else:
            success_color = Colors.FAIL
        
        print(f"Taux de réussite: {success_color}{success_rate:.1f}%{Colors.ENDC}")
        
        if avg_delay > 0:
            delay_color = Colors.OKGREEN if avg_delay < 30 else Colors.WARNING if avg_delay < 60 else Colors.FAIL
            print(f"Délai détection moyen: {delay_color}{avg_delay:.1f}s{Colors.ENDC}")
        print()
    
    def display_alerts(self, alerts: List[Dict]):
        """Affiche les alertes du système"""
        if not alerts:
            return
        
        print(f"{Colors.BOLD}🚨 ALERTES{Colors.ENDC}")
        print("-" * 50)
        
        # Grouper par sévérité
        high_alerts = [a for a in alerts if a.get('severity') == 'high']
        medium_alerts = [a for a in alerts if a.get('severity') == 'medium']
        low_alerts = [a for a in alerts if a.get('severity') in ['low', 'info']]
        
        # Afficher les alertes par ordre de priorité
        for alert_group, color in [(high_alerts, Colors.FAIL), (medium_alerts, Colors.WARNING), (low_alerts, Colors.OKCYAN)]:
            for alert in alert_group:
                icon = alert.get('icon', '⚠️')
                message = alert.get('message', '')
                print(f"{color}{icon} {message}{Colors.ENDC}")
        print()
    
    def display_dashboard(self):
        """Affiche le dashboard complet"""
        try:
            # Récupération des données
            system_status = self.get_system_status()
            discovery_stats = self.get_discovery_stats()
            balance_stats = self.get_balance_change_stats()
            wallet_priorities = self.get_wallet_priorities()
            performance_metrics = self.get_performance_metrics()
            alerts = self.get_alerts()
            
            # Effacement de l'écran et affichage
            self.clear_screen()
            self.display_header()
            self.display_system_status(system_status)
            self.display_alerts(alerts)
            self.display_discoveries(discovery_stats)
            self.display_balance_changes(balance_stats)
            self.display_wallet_priorities(wallet_priorities)
            self.display_performance(performance_metrics)
            
            # Footer avec instructions
            print(f"{Colors.OKCYAN}{'─' * 100}{Colors.ENDC}")
            print(f"{Colors.OKCYAN}💡 Ctrl+C pour quitter | 🔄 Refresh automatique toutes les {self.refresh_interval}s{Colors.ENDC}")
            print(f"{Colors.OKCYAN}📊 Base de données: {self.db_path}{Colors.ENDC}")
            if self.target_wallet:
                print(f"{Colors.OKCYAN}🎯 Wallet filtré: {self.target_wallet}{Colors.ENDC}")
            
        except Exception as e:
            print(f"{Colors.FAIL}❌ Erreur affichage dashboard: {e}{Colors.ENDC}")
    
    def export_stats(self, filename: str = None):
        """Exporte les statistiques en JSON"""
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            wallet_suffix = f"_{self.target_wallet[:8]}" if self.target_wallet else ""
            filename = f"solana_monitor_stats{wallet_suffix}_{timestamp}.json"
        
        try:
            data = {
                'timestamp': datetime.now().isoformat(),
                'target_wallet': self.target_wallet,
                'system_status': self.get_system_status(),
                'discovery_stats': self.get_discovery_stats(),
                'balance_stats': self.get_balance_change_stats(),
                'wallet_priorities': self.get_wallet_priorities(),
                'performance_metrics': self.get_performance_metrics(),
                'alerts': self.get_alerts()
            }
            
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            print(f"{Colors.OKGREEN}✅ Statistiques exportées: {filename}{Colors.ENDC}")
            return filename
            
        except Exception as e:
            print(f"{Colors.FAIL}❌ Erreur export: {e}{Colors.ENDC}")
            return None
    
    def run_interactive_mode(self):
        """Mode interactif avec commandes"""
        print(f"{Colors.HEADER}🎮 MODE INTERACTIF ACTIVÉ{Colors.ENDC}")
        if self.target_wallet:
            print(f"🎯 Focalisé sur le wallet: {self.target_wallet[:8]}...{self.target_wallet[-8:]}")
        print("Commandes disponibles:")
        print("  📊 'stats' - Afficher le dashboard")
        print("  💾 'export' - Exporter les statistiques")
        print("  🔄 'refresh [secondes]' - Changer l'intervalle de refresh")
        print("  📋 'wallets' - Voir seulement les priorités")
        print("  🚨 'alerts' - Voir seulement les alertes")
        print("  🎯 'wallet [adresse]' - Changer le wallet cible")
        print("  🌐 'global' - Passer en mode global (tous wallets)")
        print("  ❌ 'quit' - Quitter")
        print()
        
        while True:
            try:
                command = input(f"{Colors.OKCYAN}Monitor> {Colors.ENDC}").strip().lower()
                
                if command == 'quit' or command == 'exit':
                    print(f"{Colors.OKGREEN}👋 Au revoir!{Colors.ENDC}")
                    break
                elif command == 'stats':
                    self.display_dashboard()
                elif command == 'export':
                    self.export_stats()
                elif command.startswith('refresh'):
                    parts = command.split()
                    if len(parts) > 1:
                        try:
                            new_interval = int(parts[1])
                            if 5 <= new_interval <= 300:
                                self.refresh_interval = new_interval
                                print(f"{Colors.OKGREEN}✅ Refresh interval: {new_interval}s{Colors.ENDC}")
                            else:
                                print(f"{Colors.FAIL}❌ Interval doit être entre 5 et 300 secondes{Colors.ENDC}")
                        except ValueError:
                            print(f"{Colors.FAIL}❌ Interval invalide{Colors.ENDC}")
                    else:
                        print(f"Refresh interval actuel: {self.refresh_interval}s")
                elif command.startswith('wallet'):
                    parts = command.split()
                    if len(parts) > 1:
                        new_wallet = parts[1].strip()
                        self.target_wallet = new_wallet
                        if self._validate_wallet_exists():
                            print(f"{Colors.OKGREEN}✅ Wallet cible changé: {new_wallet[:8]}...{new_wallet[-8:]}{Colors.ENDC}")
                        else:
                            print(f"{Colors.WARNING}⚠️  Wallet non trouvé en base mais monitoring activé{Colors.ENDC}")
                    else:
                        if self.target_wallet:
                            print(f"Wallet cible actuel: {self.target_wallet}")
                        else:
                            print("Mode global activé (tous wallets)")
                elif command == 'global':
                    self.target_wallet = None
                    print(f"{Colors.OKGREEN}✅ Mode global activé (tous wallets){Colors.ENDC}")
                elif command == 'wallets':
                    wallets = self.get_wallet_priorities()
                    self.clear_screen()
                    print(f"{Colors.HEADER}🎯 PRIORITÉS DES WALLETS{Colors.ENDC}")
                    print("=" * 50)
                    self.display_wallet_priorities(wallets)
                elif command == 'alerts':
                    alerts = self.get_alerts()
                    self.clear_screen()
                    print(f"{Colors.HEADER}🚨 ALERTES SYSTÈME{Colors.ENDC}")
                    print("=" * 50)
                    self.display_alerts(alerts)
                    if not alerts:
                        print(f"{Colors.OKGREEN}✅ Aucune alerte active{Colors.ENDC}")
                elif command == 'help':
                    print("Commandes disponibles:")
                    print("  📊 stats, 💾 export, 🔄 refresh, 📋 wallets, 🚨 alerts")
                    print("  🎯 wallet [adresse], 🌐 global, ❌ quit")
                else:
                    print(f"{Colors.WARNING}❓ Commande inconnue. Tapez 'help' pour l'aide{Colors.ENDC}")
                    
            except KeyboardInterrupt:
                print(f"\n{Colors.OKGREEN}👋 Au revoir!{Colors.ENDC}")
                break
            except Exception as e:
                print(f"{Colors.FAIL}❌ Erreur: {e}{Colors.ENDC}")
    
    def run_continuous_mode(self):
        """Mode de monitoring continu"""
        print(f"{Colors.HEADER}🔄 MONITORING CONTINU ACTIVÉ{Colors.ENDC}")
        if self.target_wallet:
            print(f"🎯 Focalisé sur le wallet: {self.target_wallet[:8]}...{self.target_wallet[-8:]}")
        print(f"Refresh automatique toutes les {self.refresh_interval} secondes")
        print("Appuyez sur Ctrl+C pour arrêter")
        print()
        
        try:
            while True:
                self.display_dashboard()
                time.sleep(self.refresh_interval)
                
        except KeyboardInterrupt:
            print(f"\n{Colors.OKGREEN}👋 Monitoring arrêté{Colors.ENDC}")

def main():
    """Point d'entrée principal"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Dashboard de monitoring global pour Solana Wallet Scanner")
    parser.add_argument('--db', default='solana_wallet.db', help='Chemin vers la base de données SQLite')
    parser.add_argument('--wallet', type=str, help='Adresse du wallet à monitorer spécifiquement')
    parser.add_argument('--refresh', type=int, default=30, help='Intervalle de refresh en secondes (défaut: 30)')
    parser.add_argument('--mode', choices=['continuous', 'interactive', 'once'], default='continuous',
                       help='Mode d\'exécution: continuous (défaut), interactive, ou once')
    parser.add_argument('--export', action='store_true', help='Exporter les stats et quitter')
    
    args = parser.parse_args()
    
    # Vérifier que la base de données existe
    if not os.path.exists(args.db):
        print(f"{Colors.FAIL}❌ Base de données non trouvée: {args.db}{Colors.ENDC}")
        print(f"{Colors.OKCYAN}💡 Assurez-vous que le scanner principal a créé la base de données{Colors.ENDC}")
        sys.exit(1)
    
    # Créer le dashboard avec le wallet cible optionnel
    dashboard = SolanaMonitoringDashboard(args.db, args.wallet)
    dashboard.refresh_interval = args.refresh
    
    try:
        if args.export:
            # Mode export uniquement
            filename = dashboard.export_stats()
            if filename:
                print(f"{Colors.OKGREEN}📊 Statistiques exportées dans {filename}{Colors.ENDC}")
        elif args.mode == 'once':
            # Affichage unique
            dashboard.display_dashboard()
        elif args.mode == 'interactive':
            # Mode interactif
            dashboard.run_interactive_mode()
        else:
            # Mode continu (défaut)
            dashboard.run_continuous_mode()
            
    except Exception as e:
        print(f"{Colors.FAIL}❌ Erreur fatale: {e}{Colors.ENDC}")
        sys.exit(1)

if __name__ == "__main__":
    main()