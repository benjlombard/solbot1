#!/usr/bin/env python3
"""
🚀 Lanceur Optimisé - Scanner Solana Haute Performance
Fix pour les logs whale qui sortent dans la console
"""

import asyncio
import logging
import argparse
import signal
import sys
from datetime import datetime
import threading
import time

# Configuration du logging optimisé CORRIGÉE
def setup_optimized_logging(log_level: str, whale_log_level: str = 'WARNING', disable_whale_logs: bool = False, whale_log_file: str = "whale_detector.log"):
    """Configuration logging optimisée pour haute performance - CORRIGÉE"""
    
    # Format de log plus compact pour réduire l'overhead
    formatter = logging.Formatter(
        '%(asctime)s | %(levelname)s | %(name)s | %(message)s',
        datefmt='%H:%M:%S'
    )
    
    # Handler console avec buffer
    console_handler = logging.StreamHandler()
    console_handler.setLevel(getattr(logging, log_level))
    console_handler.setFormatter(formatter)
    
    # Handler fichier avec rotation pour éviter les gros fichiers
    from logging.handlers import RotatingFileHandler
    file_handler = RotatingFileHandler(
        'solana_scanner_optimized.log',
        maxBytes=50*1024*1024,
        backupCount=3,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    
    # === CORRECTION: Handler séparé pour les whales ===
    whale_file_handler = RotatingFileHandler(
        whale_log_file,
        maxBytes=20*1024*1024,
        backupCount=5,
        encoding='utf-8'
    )
    whale_file_handler.setLevel(getattr(logging, whale_log_level))
    whale_file_handler.setFormatter(logging.Formatter(
        '%(asctime)s | %(levelname)s | 🐋 %(message)s',
        datefmt='%H:%M:%S'
    ))

    # Configuration du logger racine
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
    
    # === CORRECTION PRINCIPALE ===
    # Configurer TOUS les loggers whale possibles
    whale_logger_names = ['whale_detector', 'whale_detection', 'whale', 'whales']
    
    for logger_name in whale_logger_names:
        whale_logger = logging.getLogger(logger_name)
        
        if disable_whale_logs:
            # Complètement désactiver
            whale_logger.setLevel(logging.CRITICAL + 1)  # Au-dessus de CRITICAL
            whale_logger.propagate = False
            whale_logger.handlers.clear()  # Supprimer tous les handlers existants
        else:
            whale_logger.setLevel(getattr(logging, whale_log_level))
            whale_logger.propagate = False  # IMPORTANT: Empêcher la propagation
            
            # Nettoyer les handlers existants pour éviter les doublons
            whale_logger.handlers.clear()
            
            # Ajouter UNIQUEMENT le handler fichier
            whale_logger.addHandler(whale_file_handler)
            
            # Console handler SEULEMENT si explicitement demandé pour DEBUG/INFO
            # ET si ce n'est pas désactivé
            if whale_log_level in ['DEBUG', 'INFO'] and not disable_whale_logs:
                whale_console_handler = logging.StreamHandler()
                whale_console_handler.setLevel(getattr(logging, whale_log_level))
                whale_console_handler.setFormatter(logging.Formatter(
                    '%(asctime)s | %(levelname)s | 🐋 %(message)s',
                    datefmt='%H:%M:%S'
                ))
                whale_logger.addHandler(whale_console_handler)
                logging.info(f"🐋 Whale console logs enabled for {logger_name} (level: {whale_log_level})")
            else:
                # Pas de console pour WARNING/ERROR/CRITICAL - seulement fichier
                logging.info(f"🐋 Whale logs for {logger_name}: file only (level: {whale_log_level})")
    
    # === CORRECTION SUPPLÉMENTAIRE ===
    # Filtre pour empêcher les logs whale dans le handler console principal
    class WhaleLogFilter(logging.Filter):
        def filter(self, record):
            # Bloquer tous les logs contenant des mots-clés whale
            message = record.getMessage().lower()
            logger_name = record.name.lower()
            
            whale_keywords = ['whale', '🐋', 'large transaction', 'big transfer']
            
            # Si c'est un logger whale ou contient des mots-clés whale
            if any(keyword in logger_name for keyword in ['whale']) or \
               any(keyword in message for keyword in whale_keywords):
                return False  # Bloquer ce log pour la console
            
            return True  # Laisser passer les autres logs
    
    # Ajouter le filtre au handler console pour bloquer les whale logs
    if not disable_whale_logs and whale_log_level not in ['DEBUG', 'INFO']:
        console_handler.addFilter(WhaleLogFilter())
        logging.info("🚫 Whale filter applied to console - whales logs go to file only")

    # Réduire les logs des libs externes
    for lib in ['httpx', 'httpcore', 'aiohttp', 'websockets', 'urllib3']:
        logging.getLogger(lib).setLevel(logging.WARNING)
    
    # Filtrer les erreurs de parsing
    logging.getLogger('solana_monitoring').addFilter(ParsingErrorFilter())
    
    # Messages de confirmation
    if disable_whale_logs:
        logging.info("🚫 ALL whale detector logs disabled")
    else:
        logging.info(f"🐋 Whale detector log level: {whale_log_level}")
        logging.info(f"📄 Whale logs file: {whale_log_file}")
        if whale_log_level in ['DEBUG', 'INFO']:
            logging.info("📺 Whale logs: console + file")
        else:
            logging.info("📄 Whale logs: file only (no console)")
    
    logging.info("✅ Optimized logging configured")
    logging.info(f"📄 Main logs: solana_scanner_optimized.log")

class ParsingErrorFilter(logging.Filter):
    """Filtrer les erreurs de parsing fréquentes mais normales"""
    def filter(self, record):
        message = record.getMessage()
        # Filtrer les erreurs de parsing communes
        if any(phrase in message for phrase in [
            "Error parsing signature",
            "Error parsing transaction", 
            "Error parsing Raydium",
            "No valid transaction data",
            "No transaction data for signature"
        ]):
            return False  # Ne pas logger ces erreurs
        return True

# Fonction utilitaire pour tester la configuration
def test_whale_logging():
    """Fonction de test pour vérifier que les logs whale sont bien configurés"""
    import logging
    
    # Tester différents loggers whale
    whale_loggers = [
        logging.getLogger('whale_detector'),
        logging.getLogger('whale_detection'), 
        logging.getLogger('whale'),
        logging.getLogger('whales')
    ]
    
    print("\n=== TEST WHALE LOGGING ===")
    for logger in whale_loggers:
        logger.info(f"🐋 Test INFO from {logger.name}")
        logger.warning(f"🐋 Test WARNING from {logger.name}")
        logger.error(f"🐋 Test ERROR from {logger.name}")
    
    print("=== END TEST ===\n")

# Le reste du code reste identique...
class OptimizedSolanaScanner:
    """Scanner Solana optimisé pour débit maximal"""
    
    def __init__(self, args):
        self.args = args
        self.shutdown_event = asyncio.Event()
        self.tasks = []
        self.stats = {
            'start_time': time.time(),
            'tokens_processed': 0,
            'tokens_enriched': 0,
            'api_calls': 0,
            'errors': 0
        }
        
        # Configuration optimisée basée sur les args
        self.config = {
            'batch_size': args.batch_size,
            'max_concurrent': args.max_concurrent,
            'scan_interval': args.scan_interval,
            'enrichment_interval': args.enrichment_interval,
            'monitoring_interval': args.monitoring_interval
        }

def main():
    """Point d'entrée principal optimisé"""
    parser = argparse.ArgumentParser(description="Optimized Solana Token Scanner")
    
    # Arguments de base
    parser.add_argument("--database", default="tokens.db", help="Database path")
    parser.add_argument("--log-level", choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'], 
                       default='INFO', help="Logging level")
    
    # Arguments whale AMÉLIORÉS
    parser.add_argument("--whale-log-level", 
                   choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
                   default='ERROR',  # CHANGÉ: ERROR par défaut au lieu de WARNING
                   help="Whale detector log level (default: ERROR - file only)")
    parser.add_argument("--disable-whale-logs", action="store_true",
                    help="Completely disable ALL whale detection logging")
    parser.add_argument("--whale-console", action="store_true",
                    help="Force whale logs to appear in console (overrides default file-only)")
    parser.add_argument("--whale-threshold", type=int, default=10000,
                    help="Whale detection threshold in USD (default: 10000)")
    parser.add_argument("--whale-log-file", type=str, default="whale_detector.log",
                    help="Whale detector log file path (default: whale_detector.log)")
    
    # Test option
    parser.add_argument("--test-whale-logs", action="store_true",
                    help="Test whale logging configuration and exit")
    
    args = parser.parse_args()
    
    # Configuration du logging optimisé CORRIGÉ
    setup_optimized_logging(args.log_level, args.whale_log_level, args.disable_whale_logs, args.whale_log_file)
    
    # Test des logs whale si demandé
    if args.test_whale_logs:
        test_whale_logging()
        return
    
    # Information de démarrage
    logging.info("🚀 SOLANA TOKEN SCANNER - HIGH PERFORMANCE MODE")
    logging.info("=" * 60)
    logging.info(f"📊 Configuration:")
    logging.info(f"   Logging: {args.log_level}")
    logging.info(f"   Whale logs: {'DISABLED' if args.disable_whale_logs else args.whale_log_level + ' (file only)'}")
    logging.info("=" * 60)

if __name__ == "__main__":
    main()