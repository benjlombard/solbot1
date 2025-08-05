import sqlite3
import time
from datetime import datetime, timedelta
import logging
import threading
import sys
import platform
from config import DB_NAME  # Assurez-vous que DB_NAME est défini dans votre fichier config.py

# Déterminer si on est sous Windows pour gérer les emojis
is_windows = platform.system() == "Windows"

# Configuration du logger
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),  # Utiliser sys.stdout pour la console
        logging.FileHandler('metrics_report.log', encoding='utf-8')  # UTF-8 pour le fichier
    ]
)
logger = logging.getLogger(__name__)

# Fonction pour supprimer les emojis sous Windows
def clean_message(message):
    if is_windows:
        # Remplacer les emojis par des caractères ASCII simples
        emoji_replacements = {
            '🚀': '[START]',
            '📊': '[REPORT]',
            '🔍': '[SCAN]',
            '📋': '[WALLETS]',
            '🆕': '[NEW]',
            '💰': '[BALANCE]',
            '📈': '[METRICS]',
            '🌟': '[ACTIVE]'
        }
        for emoji, replacement in emoji_replacements.items():
            message = message.replace(emoji, replacement)
    return message

class MetricsReport:
    def __init__(self, db_name):
        self.db_name = db_name
        self.current_time = int(time.time())

    def get_time_window(self, minutes):
        """Retourne le timestamp pour une fenêtre temporelle donnée (en minutes)."""
        return self.current_time - (minutes * 60)

    def get_scan_counts(self):
        """Récupère le nombre de scans dans différentes fenêtres temporelles."""
        windows = {
            '5min': self.get_time_window(5),
            '30min': self.get_time_window(30),
            '60min': self.get_time_window(60)
        }
        scan_counts = {}

        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            for window_name, start_time in windows.items():
                cursor.execute("""
                    SELECT COUNT(*) FROM scan_history 
                    WHERE completed_at >= ?
                """, (start_time,))
                scan_counts[window_name] = cursor.fetchone()[0] or 0

        return scan_counts

    def get_last_scanned_wallets(self, limit=10):
        """Récupère la liste des 10 derniers wallets scannés."""
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT wallet_address, completed_at, scan_type, new_accounts, scan_duration
                FROM scan_history 
                ORDER BY completed_at DESC 
                LIMIT ?
                """, (limit,))
            wallets = [
                {
                    'wallet_address': row[0],
                    'completed_at': datetime.fromtimestamp(row[1]).strftime('%Y-%m-%d %H:%M:%S'),
                    'scan_type': row[1],
                    'new_accounts': row[3],
                    'scan_duration': round(row[4], 2) if row[4] else 0
                } for row in cursor.fetchall()
            ]
        return wallets

    def get_token_account_discoveries(self):
        """Récupère le nombre de comptes de tokens découverts dans différentes fenêtres temporelles."""
        windows = {
            '5min': self.get_time_window(5),
            '30min': self.get_time_window(30),
            '60min': self.get_time_window(60)
        }
        discoveries = {}

        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            for window_name, start_time in windows.items():
                cursor.execute("""
                    SELECT SUM(new_accounts) FROM scan_history 
                    WHERE completed_at >= ?
                """, (start_time,))
                result = cursor.fetchone()[0]
                discoveries[window_name] = result or 0

        return discoveries

    def get_balance_changes(self):
        """Récupère le nombre de changements de balance dans différentes fenêtres temporelles."""
        windows = {
            '5min': self.get_time_window(5),
            '30min': self.get_time_window(30),
            '60min': self.get_time_window(60)
        }
        balance_changes = {}

        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            for window_name, start_time in windows.items():
                cursor.execute("""
                    SELECT COUNT(*) FROM transactions 
                    WHERE is_token_transaction = 1 AND block_time >= ?
                """, (start_time,))
                balance_changes[window_name] = cursor.fetchone()[0] or 0

        return balance_changes

    def get_efficiency_metrics(self):
        """Récupère les métriques d'efficacité des scans sur la dernière heure."""
        start_time = self.get_time_window(60)
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 
                    AVG(efficiency_score) as avg_efficiency,
                    SUM(discoveries_count) as total_discoveries,
                    SUM(balance_changes_count) as total_transactions,
                    SUM(rpc_requests_made) as total_rpc_requests
                FROM wallet_activity_metrics 
                WHERE timestamp >= ?
            """, (start_time,))
            result = cursor.fetchone()
            return {
                'avg_efficiency': round(result[0], 2) if result[0] else 0,
                'total_discoveries': result[1] or 0,
                'total_transactions': result[2] or 0,
                'total_rpc_requests': result[3] or 0
            }

    def get_active_wallets(self):
        """Récupère le nombre de wallets actifs (avec activité dans la dernière heure)."""
        start_time = self.get_time_window(60)
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(DISTINCT wallet_address) 
                FROM scan_history 
                WHERE completed_at >= ? AND activity_detected = 1
            """, (start_time,))
            return cursor.fetchone()[0] or 0

    def generate_report(self):
        """Génère un rapport synthétique des métriques."""
        logger.info(clean_message("=" * 80))
        logger.info(clean_message(f"📊 RAPPORT SYNTHÉTIQUE - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"))
        logger.info(clean_message("=" * 80))

        # Nombre de scans
        scan_counts = self.get_scan_counts()
        logger.info(clean_message("🔍 Nombre de scans effectués :"))
        logger.info(clean_message(f"   - 5 dernières minutes : {scan_counts['5min']}"))
        logger.info(clean_message(f"   - 30 dernières minutes : {scan_counts['30min']}"))
        logger.info(clean_message(f"   - Dernière heure : {scan_counts['60min']}"))

        # Derniers wallets scannés
        last_wallets = self.get_last_scanned_wallets()
        logger.info(clean_message("\n📋 10 derniers wallets scannés :"))
        for i, wallet in enumerate(last_wallets, 1):
            logger.info(clean_message(
                f"   {i}. {wallet['wallet_address']} | Type: {wallet['scan_type']} | "
                f"Nouveaux comptes: {wallet['new_accounts']} | "
                f"Durée: {wallet['scan_duration']}s | "
                f"Terminé: {wallet['completed_at']}"
            ))

        # Nouveaux comptes de tokens découverts
        discoveries = self.get_token_account_discoveries()
        logger.info(clean_message("\n🆕 Comptes de tokens découverts :"))
        logger.info(clean_message(f"   - 5 dernières minutes : {discoveries['5min']}"))
        logger.info(clean_message(f"   - 30 dernières minutes : {discoveries['30min']}"))
        logger.info(clean_message(f"   - Dernière heure : {discoveries['60min']}"))

        # Changements de balance
        balance_changes = self.get_balance_changes()
        logger.info(clean_message("\n💰 Changements de balance détectés :"))
        logger.info(clean_message(f"   - 5 dernières minutes : {balance_changes['5min']}"))
        logger.info(clean_message(f"   - 30 dernières minutes : {balance_changes['30min']}"))
        logger.info(clean_message(f"   - Dernière heure : {balance_changes['60min']}"))

        # Métriques d'efficacité
        efficiency = self.get_efficiency_metrics()
        logger.info(clean_message("\n📈 Métriques d'efficacité (dernière heure) :"))
        logger.info(clean_message(f"   - Efficacité moyenne : {efficiency['avg_efficiency']:.2f} (découvertes+transactions/RPC)"))
        logger.info(clean_message(f"   - Total découvertes : {efficiency['total_discoveries']}"))
        logger.info(clean_message(f"   - Total transactions : {efficiency['total_transactions']}"))
        logger.info(clean_message(f"   - Requêtes RPC : {efficiency['total_rpc_requests']}"))

        # Wallets actifs
        active_wallets = self.get_active_wallets()
        logger.info(clean_message("\n🌟 Wallets actifs (avec activité dans la dernière heure) :"))
        logger.info(clean_message(f"   - Nombre : {active_wallets}"))

        logger.info(clean_message("=" * 80))

    def run_periodic_report(self, interval_seconds=300):
        """Exécute le rapport périodiquement."""
        while True:
            try:
                self.generate_report()
                logger.info(clean_message(f"⏳ Prochain rapport dans {interval_seconds} secondes..."))
                time.sleep(interval_seconds)
            except Exception as e:
                logger.error(clean_message(f"❌ Erreur lors de la génération du rapport : {e}"))
                time.sleep(60)  # Pause en cas d'erreur

def main():
    """Point d'entrée principal pour lancer le rapport."""
    try:
        logger.info(clean_message("🚀 Lancement du générateur de rapport synthétique"))
        report = MetricsReport(DB_NAME)
        
        # Lancer le rapport dans un thread séparé pour ne pas bloquer
        report_thread = threading.Thread(target=report.run_periodic_report, args=(300,))
        report_thread.daemon = True
        report_thread.start()
        
        # Garder le script principal en vie
        while True:
            time.sleep(60)
            
    except KeyboardInterrupt:
        logger.info(clean_message("🛑 Arrêt du générateur de rapport"))
    except Exception as e:
        logger.error(clean_message(f"❌ Erreur critique : {e}"))

if __name__ == "__main__":
    main()