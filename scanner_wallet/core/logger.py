#!/usr/bin/env python3
"""
Configuration avancée du logging pour le Solana Wallet Monitor
Système de logging centralisé avec contexte, rotation et formatage intelligent
"""

import logging
import logging.handlers
import sys
import os
import time
import json
import threading
from datetime import datetime
from typing import Any, Dict, Optional, Union, List
from pathlib import Path
from contextlib import contextmanager


def setup_windows_unicode():
    """Configure l'encodage Unicode pour Windows"""
    if sys.platform.startswith('win'):
        try:
            # Forcer UTF-8 pour stdout et stderr
            if hasattr(sys.stdout, 'reconfigure'):
                sys.stdout.reconfigure(encoding='utf-8')
            if hasattr(sys.stderr, 'reconfigure'):
                sys.stderr.reconfigure(encoding='utf-8')
            
            # Alternative pour Python plus ancien
            if not hasattr(sys.stdout, 'reconfigure'):
                import codecs
                sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
                sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')
            
            # Activer le support Unicode dans la console Windows
            os.system('chcp 65001 > nul 2>&1')  # UTF-8 code page
            
            return True
        except Exception:
            return False
    return True

# Import des constantes et helpers
try:
    from utils.constants import LOG_ICONS, LOG_FORMATS, CUSTOM_LOG_LEVELS
    from utils.formatters import format_wallet_address, format_duration
    from utils.helpers import get_current_timestamp, sanitize_filename
except ImportError:
    # Fallbacks si les modules ne sont pas encore disponibles
    LOG_ICONS = {
        'success': '✅', 'error': '❌', 'warning': '⚠️', 'info': 'ℹ️',
        'debug': '🔍', 'critical': '🚨', 'scan': '🔍', 'discovery': '🆕',
        'transaction': '💰', 'batch': '📦', 'priority': '🎯', 'wallet': '👛',
        'token': '🪙', 'rpc': '🔌', 'database': '💾', 'cache': '🗄️',
        'fast': '⚡', 'slow': '🐌', 'optimization': '🚀', 'monitoring': '📊'
    }
    
    LOG_FORMATS = {
        'cycle_start': "🧠 CYCLE INTELLIGENT #{cycle} - {timestamp}",
        'cycle_end': "✅ CYCLE #{cycle} TERMINÉ - Durée: {duration}s",
        'wallet_selected': "🎯 WALLET SÉLECTIONNÉ: {wallet_short}",
        'discovery_result': "📊 Découverte: {total} comptes ({new} nouveaux)",
        'balance_change': "💰 Balance change: {type} {amount} {symbol}",
        'priority_update': "{icon} Priorité: {old} → {new} ({change:+.2f})",
        'batch_result': "📦 Batch {method}: {count} items en {duration:.2f}s",
        'rpc_error': "❌ Erreur RPC {method}: {error}",
        'performance': "📊 Performance - RPS: {rps:.1f}, Succès: {success_rate:.1f}%"
    }
    
    CUSTOM_LOG_LEVELS = {
        'DISCOVERY': 25, 'TRANSACTION': 25, 'PERFORMANCE': 35, 'BATCH': 15
    }
    
    def format_wallet_address(addr, length=8):
        return f"{addr[:length]}...{addr[-length:]}" if addr and len(addr) > length*2 else addr
    
    def format_duration(seconds, compact=True):
        if seconds < 60:
            return f"{seconds:.1f}s"
        elif seconds < 3600:
            return f"{int(seconds//60)}m{int(seconds%60)}s"
        else:
            return f"{int(seconds//3600)}h{int((seconds%3600)//60)}m"
    
    def get_current_timestamp():
        return int(time.time())
    
    def sanitize_filename(filename):
        return "".join(c for c in filename if c.isalnum() or c in (' ', '-', '_', '.')).rstrip()


# =============================================================================
# NIVEAUX DE LOG PERSONNALISÉS
# =============================================================================

# Ajouter les niveaux personnalisés à logging
for level_name, level_value in CUSTOM_LOG_LEVELS.items():
    logging.addLevelName(level_value, level_name)


# =============================================================================
# FORMATTERS PERSONNALISÉS
# =============================================================================

class ColoredFormatter(logging.Formatter):
    """Formatter avec codes couleur ANSI pour la console"""
    
    # Codes couleur ANSI
    COLORS = {
        'DEBUG': '\033[36m',      # Cyan
        'BATCH': '\033[94m',      # Bleu clair
        'INFO': '\033[97m',       # Blanc
        'DISCOVERY': '\033[92m',  # Vert clair
        'TRANSACTION': '\033[93m', # Jaune
        'WARNING': '\033[93m',    # Jaune
        'ERROR': '\033[91m',      # Rouge
        'CRITICAL': '\033[95m',   # Magenta
        'PERFORMANCE': '\033[35m', # Violet
    }
    
    RESET = '\033[0m'
    BOLD = '\033[1m'
    
    def __init__(self, fmt=None, datefmt=None, use_colors=True):
        super().__init__(fmt, datefmt)
        self.use_colors = use_colors and self._supports_color()
        self.unicode_support = self._check_unicode_support()
    
    def _check_unicode_support(self) -> bool:
        """Vérifie si le terminal supporte Unicode"""
        try:
            sys.stdout.write('✓')
            sys.stdout.flush()
            return True
        except UnicodeEncodeError:
            return False

    def _supports_color(self) -> bool:
        """Détecte si le terminal supporte les couleurs"""
        return (
            hasattr(sys.stderr, "isatty") and sys.stderr.isatty() and
            os.environ.get("TERM") != "dumb" and
            os.environ.get("NO_COLOR") is None
        )
    
    def format(self, record: logging.LogRecord) -> str:
        # We need to save the original values because we are modifying the record
        original_levelname = record.levelname
        original_name = record.name

        if self.use_colors:
            # Colorer le nom du niveau
            level_color = self.COLORS.get(record.levelname, '')
            if level_color:
                record.levelname = f"{level_color}{self.BOLD}{record.levelname}{self.RESET}"
            
            # Colorer le nom du logger
            if hasattr(record, 'name') and record.name:
                record.name = f"\033[90m{record.name}{self.RESET}"
        
        result = super().format(record)

        # Restore the original values
        record.levelname = original_levelname
        record.name = original_name
        
        if self.use_colors and not self.unicode_support and sys.platform.startswith('win'):
            # Remplacer les emojis par des équivalents ASCII sur Windows
            emoji_replacements = {
                '🚀': '[START]',
                '✅': '[OK]',
                '❌': '[ERROR]',
                '⚠️': '[WARN]',
                'ℹ️': '[INFO]',
                '🔍': '[DEBUG]',
                '🚨': '[CRITICAL]',
                '📦': '[BATCH]',
                '🆕': '[NEW]',
                '💰': '[TX]',
                '🎯': '[PRIORITY]',
                '👛': '[WALLET]',
                '🪙': '[TOKEN]',
                '🔌': '[RPC]',
                '💾': '[DB]',
                '🗄️': '[CACHE]',
                '⚡': '[FAST]',
                '🐌': '[SLOW]',
                '📊': '[STATS]',
                '🔧': '[CONFIG]',
                '🔄': '[UPDATE]',
                '🧠': '[CYCLE]',
                '📈': '[UP]',
                '📉': '[DOWN]',
                '➡️': '[NEUTRAL]',
                '🔥': '[HOT]',
                '🔵': '[EMPTY]'
            }
            
            for emoji, replacement in emoji_replacements.items():
                result = result.replace(emoji, replacement)
        
        return result


class ContextFormatter(logging.Formatter):
    """Formatter avec contexte enrichi (wallet, cycle, etc.)"""
    
    def format(self, record: logging.LogRecord) -> str:
        # Ajouter des informations de contexte si disponibles
        context_parts = []
        
        if hasattr(record, 'wallet_address'):
            wallet_short = format_wallet_address(record.wallet_address, 6)
            context_parts.append(f"W:{wallet_short}")
        
        if hasattr(record, 'cycle_id'):
            # Extraire juste le numéro de cycle
            cycle_num = record.cycle_id.split('_')[1] if '_' in record.cycle_id else record.cycle_id
            context_parts.append(f"C:{cycle_num}")
        
        if hasattr(record, 'scan_id'):
            context_parts.append(f"S:{record.scan_id[-6:]}")
        
        if hasattr(record, 'batch_id'):
            context_parts.append(f"B:{record.batch_id}")
        
        # Ajouter le contexte au record
        if context_parts:
            record.context = f"[{' '.join(context_parts)}]"
        else:
            record.context = ""
        
        return super().format(record)


class JSONFormatter(logging.Formatter):
    """Formatter JSON pour l'intégration avec des systèmes de monitoring"""
    
    def format(self, record: logging.LogRecord) -> str:
        log_obj = {
            'timestamp': record.created,
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno
        }
        
        # Ajouter les informations de contexte
        context_fields = ['wallet_address', 'cycle_id', 'scan_id', 'batch_id', 
                         'rpc_method', 'token_mint', 'signature']
        
        for field in context_fields:
            if hasattr(record, field):
                log_obj[field] = getattr(record, field)
        
        # Ajouter l'exception si présente
        if record.exc_info:
            log_obj['exception'] = self.formatException(record.exc_info)
        
        # Ajouter des métriques si présentes
        if hasattr(record, 'metrics'):
            log_obj['metrics'] = record.metrics
        
        try:
            return json.dumps(log_obj, default=str, ensure_ascii=False)
        except (TypeError, ValueError):
            # Fallback si la sérialisation JSON échoue
            return json.dumps({
                'timestamp': record.created,
                'level': record.levelname,
                'message': str(record.getMessage()),
                'serialization_error': True
            })


class IconFormatter(logging.Formatter):
    """Formatter avec icônes pour les logs visuels"""
    
    def format(self, record: logging.LogRecord) -> str:
        # Déterminer l'icône appropriée
        icon = LOG_ICONS.get('info', 'ℹ️')  # Icône par défaut
        
        # Icône selon le niveau
        level_icons = {
            'DEBUG': LOG_ICONS.get('debug', '🔍'),
            'BATCH': LOG_ICONS.get('batch', '📦'),
            'INFO': LOG_ICONS.get('info', 'ℹ️'),
            'DISCOVERY': LOG_ICONS.get('discovery', '🆕'),
            'TRANSACTION': LOG_ICONS.get('transaction', '💰'),
            'WARNING': LOG_ICONS.get('warning', '⚠️'),
            'ERROR': LOG_ICONS.get('error', '❌'),
            'CRITICAL': LOG_ICONS.get('critical', '🚨'),
            'PERFORMANCE': LOG_ICONS.get('monitoring', '📊')
        }
        
        icon = level_icons.get(record.levelname, icon)
        
        # Icône selon le contexte du message
        message = record.getMessage().lower()
        if 'rpc' in message:
            icon = LOG_ICONS.get('rpc', '🔌')
        elif 'batch' in message:
            icon = LOG_ICONS.get('batch', '📦')
        elif 'wallet' in message:
            icon = LOG_ICONS.get('wallet', '👛')
        elif 'token' in message:
            icon = LOG_ICONS.get('token', '🪙')
        elif 'database' in message or 'db' in message:
            icon = LOG_ICONS.get('database', '💾')
        elif 'cache' in message:
            icon = LOG_ICONS.get('cache', '🗄️')
        elif 'fast' in message or 'quick' in message:
            icon = LOG_ICONS.get('fast', '⚡')
        elif 'slow' in message or 'timeout' in message:
            icon = LOG_ICONS.get('slow', '🐌')
        
        # Ajouter l'icône au record
        record.icon = icon
        
        return super().format(record)


# =============================================================================
# HANDLERS PERSONNALISÉS
# =============================================================================

class SmartRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """Handler avec rotation intelligente basée sur la taille et le temps"""
    
    def __init__(self, filename, mode='a', maxBytes=0, backupCount=0, encoding=None, delay=False, max_age_days=7):
        super().__init__(filename, mode, maxBytes, backupCount, encoding, delay)
        self.max_age_days = max_age_days
        self.last_cleanup = time.time()
        self.cleanup_interval = 3600  # Nettoyage toutes les heures
    
    def emit(self, record):
        try:
            # Nettoyage périodique des anciens logs
            if time.time() - self.last_cleanup > self.cleanup_interval:
                self._cleanup_old_logs()
                self.last_cleanup = time.time()
            
            super().emit(record)
        except Exception:
            self.handleError(record)
    
    def _cleanup_old_logs(self):
        """Supprime les logs plus anciens que max_age_days"""
        if not self.max_age_days:
            return
        
        try:
            log_dir = Path(self.baseFilename).parent
            cutoff_time = time.time() - (self.max_age_days * 24 * 3600)
            
            # Supprimer les fichiers de log anciens
            for log_file in log_dir.glob(f"{Path(self.baseFilename).stem}*"):
                if log_file.stat().st_mtime < cutoff_time:
                    log_file.unlink()
                    
        except Exception as e:
            # Ne pas lever d'exception pour éviter de casser le logging
            pass


class PerformanceHandler(logging.Handler):
    """Handler spécialisé pour les métriques de performance"""
    
    def __init__(self, metrics_callback=None):
        super().__init__()
        self.metrics_callback = metrics_callback
        self.performance_buffer = []
        self.buffer_size = 100
    
    def emit(self, record):
        # Ne traiter que les logs de performance
        if record.levelname != 'PERFORMANCE':
            return
        
        try:
            # Extraire les métriques du record
            metrics = {}
            if hasattr(record, 'metrics'):
                metrics = record.metrics
            
            # Parser le message pour extraire des métriques
            message = record.getMessage()
            self._extract_metrics_from_message(message, metrics)
            
            # Ajouter au buffer
            self.performance_buffer.append({
                'timestamp': record.created,
                'metrics': metrics,
                'message': message
            })
            
            # Maintenir la taille du buffer
            if len(self.performance_buffer) > self.buffer_size:
                self.performance_buffer.pop(0)
            
            # Appeler le callback si fourni
            if self.metrics_callback:
                self.metrics_callback(metrics)
                
        except Exception:
            self.handleError(record)
    
    def _extract_metrics_from_message(self, message: str, metrics: dict):
        """Extrait des métriques numériques du message de log"""
        import re
        
        # Patterns pour extraire des métriques communes
        patterns = {
            'rps': r'RPS:\s*(\d+(?:\.\d+)?)',
            'success_rate': r'Succès:\s*(\d+(?:\.\d+)?)%',
            'duration': r'(\d+(?:\.\d+)?)s',
            'count': r'(\d+)\s+items',
            'efficiency': r'efficacité:\s*(\d+(?:\.\d+)?)'
        }
        
        for metric_name, pattern in patterns.items():
            match = re.search(pattern, message, re.IGNORECASE)
            if match and metric_name not in metrics:
                try:
                    metrics[metric_name] = float(match.group(1))
                except ValueError:
                    pass
    
    def get_recent_metrics(self, count: int = 10) -> List[Dict]:
        """Retourne les métriques récentes"""
        return self.performance_buffer[-count:] if self.performance_buffer else []


# =============================================================================
# FILTRES PERSONNALISÉS
# =============================================================================

class ContextFilter(logging.Filter):
    """Filtre pour ajouter des informations de contexte automatiquement"""
    
    def __init__(self, context_provider=None):
        super().__init__()
        self.context_provider = context_provider
        self._thread_local = threading.local()
    
    def filter(self, record):
        # Ajouter des informations de thread
        record.thread_name = threading.current_thread().name
        record.process_id = os.getpid()
        
        # Ajouter le contexte du thread local si disponible
        if hasattr(self._thread_local, 'context'):
            for key, value in self._thread_local.context.items():
                setattr(record, key, value)
        
        # Ajouter le contexte global si fourni
        if self.context_provider:
            try:
                global_context = self.context_provider()
                if isinstance(global_context, dict):
                    for key, value in global_context.items():
                        if not hasattr(record, key):  # Ne pas écraser le contexte local
                            setattr(record, key, value)
            except Exception:
                pass
        
        return True
    
    def set_context(self, **kwargs):
        """Définit le contexte pour le thread actuel"""
        if not hasattr(self._thread_local, 'context'):
            self._thread_local.context = {}
        self._thread_local.context.update(kwargs)
    
    def clear_context(self):
        """Efface le contexte du thread actuel"""
        if hasattr(self._thread_local, 'context'):
            self._thread_local.context.clear()


class LevelRangeFilter(logging.Filter):
    """Filtre pour limiter les logs à une plage de niveaux"""
    
    def __init__(self, min_level=logging.DEBUG, max_level=logging.CRITICAL):
        super().__init__()
        self.min_level = min_level
        self.max_level = max_level
    
    def filter(self, record):
        return self.min_level <= record.levelno <= self.max_level


class RateLimitFilter(logging.Filter):
    """Filtre pour limiter le taux de logs similaires"""
    
    def __init__(self, max_per_minute=60):
        super().__init__()
        self.max_per_minute = max_per_minute
        self.message_counts = {}
        self.cleanup_interval = 300  # 5 minutes
        self.last_cleanup = time.time()
    
    def filter(self, record):
        now = time.time()
        
        # Nettoyage périodique
        if now - self.last_cleanup > self.cleanup_interval:
            self._cleanup_old_entries()
            self.last_cleanup = now
        
        # Créer une clé basée sur le message et le niveau
        message_key = f"{record.levelname}:{record.getMessage()[:100]}"
        
        # Initialiser le compteur si nécessaire
        if message_key not in self.message_counts:
            self.message_counts[message_key] = []
        
        # Supprimer les entrées plus anciennes qu'une minute
        cutoff_time = now - 60
        self.message_counts[message_key] = [
            timestamp for timestamp in self.message_counts[message_key]
            if timestamp > cutoff_time
        ]
        
        # Vérifier si on dépasse la limite
        if len(self.message_counts[message_key]) >= self.max_per_minute:
            return False
        
        # Ajouter cette occurrence
        self.message_counts[message_key].append(now)
        return True
    
    def _cleanup_old_entries(self):
        """Nettoie les anciennes entrées pour économiser la mémoire"""
        cutoff_time = time.time() - 300  # 5 minutes
        keys_to_remove = []
        
        for key, timestamps in self.message_counts.items():
            # Filtrer les timestamps récents
            recent_timestamps = [t for t in timestamps if t > cutoff_time]
            
            if recent_timestamps:
                self.message_counts[key] = recent_timestamps
            else:
                keys_to_remove.append(key)
        
        # Supprimer les clés vides
        for key in keys_to_remove:
            del self.message_counts[key]


# =============================================================================
# LOGGER PRINCIPAL ET CONFIGURATION
# =============================================================================
class SafeIconFormatter(logging.Formatter):
    """Formatter sécurisé avec icônes qui gère les champs manquants"""
    
    def __init__(self, fmt=None, datefmt=None):
        super().__init__(fmt, datefmt)
        self.unicode_support = self._check_unicode_support()
        
        # Icônes alternatives pour Windows
        if sys.platform.startswith('win') and not self.unicode_support:
            self.level_icons = {
                'DEBUG': '[DEBUG]',
                'BATCH': '[BATCH]', 
                'INFO': '[INFO]',
                'DISCOVERY': '[NEW]',
                'TRANSACTION': '[TX]',
                'WARNING': '[WARN]',
                'ERROR': '[ERROR]',
                'CRITICAL': '[CRIT]',
                'PERFORMANCE': '[PERF]'
            }
        else:
            self.level_icons = {
                'DEBUG': '🔍',
                'BATCH': '📦', 
                'INFO': 'ℹ️',
                'DISCOVERY': '🆕',
                'TRANSACTION': '💰',
                'WARNING': '⚠️',
                'ERROR': '❌',
                'CRITICAL': '🚨',
                'PERFORMANCE': '📊'
            }
    
    def _check_unicode_support(self) -> bool:
        """Vérifie si le terminal supporte Unicode"""
        if not sys.platform.startswith('win'):
            return True
        
        try:
            # Test simple d'écriture Unicode
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', delete=True) as f:
                f.write('✓')
            return True
        except UnicodeEncodeError:
            return False

    def format(self, record: logging.LogRecord) -> str:
        # S'assurer que l'icône existe
        if not hasattr(record, 'icon'):
            record.icon = self.level_icons.get(record.levelname, '[INFO]' if not self.unicode_support else 'ℹ️')
        
        # S'assurer que le contexte existe
        if not hasattr(record, 'context'):
            record.context = ""
        
        return super().format(record)

class SolanaWalletLogger:
    """Logger principal pour le Solana Wallet Monitor"""
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls, *args, **kwargs):
        """Singleton pattern"""
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, 
                 log_level: str = "INFO",
                 log_file: str = "wallet_monitor.log",
                 console_output: bool = True,
                 json_output: bool = False,
                 max_file_size: int = 10 * 1024 * 1024,  # 10MB
                 backup_count: int = 5,
                 max_age_days: int = 7,
                 force_reconfigure: bool = False):
        
        # Éviter la réinitialisation multiple
        if hasattr(self, '_initialized') and self._initialized and not force_reconfigure:
            return
        
        if hasattr(self, 'logger') and force_reconfigure:
            self.logger.handlers.clear()

        setup_windows_unicode()
        self.log_level = log_level.upper()
        self.log_file = log_file
        self.console_output = console_output
        self.json_output = json_output
        self.max_file_size = max_file_size
        self.backup_count = backup_count
        self.max_age_days = max_age_days
        
        # Créer le logger principal
        self.logger = logging.getLogger("SolanaWalletMonitor")
        self.logger.setLevel(getattr(logging, self.log_level, logging.INFO))
        
        # Vider les handlers existants
        self.logger.handlers.clear()
        
        # Créer le répertoire de logs si nécessaire
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Configuration des handlers
        self._setup_handlers()
        
        # Configuration des filtres
        self.context_filter = ContextFilter()
        self._setup_filters()
        
        # Marquer comme initialisé
        self._initialized = True
        
        # Log initial
        self.logger.info("🚀 Logger SolanaWalletMonitor initialisé")
        self.logger.info(f"📝 Niveau de log: {self.log_level}")
        self.logger.info(f"📁 Fichier de log: {self.log_file}")
    
    def _setup_handlers(self):
        """Configure les différents handlers de log"""
        
        # Handler pour fichier avec rotation
        if self.log_file:
            file_handler = SmartRotatingFileHandler(
                filename=self.log_file,
                maxBytes=self.max_file_size,
                backupCount=self.backup_count,
                max_age_days=self.max_age_days,
                encoding='utf-8'
            )
            
            file_formatter = SafeIconFormatter(
                fmt='%(asctime)s - %(levelname)-8s - %(context)s%(name)s - [%(funcName)s:%(lineno)d] - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            file_handler.setFormatter(file_formatter)
            self.logger.addHandler(file_handler)
        
        # Handler pour console
        if self.console_output:
            console_handler = logging.StreamHandler(sys.stdout)
            
            # Formatter avec couleurs et icônes
            console_formatter = SafeIconFormatter(
                fmt='%(icon)s %(asctime)s - %(levelname)-8s - %(message)s',
                datefmt='%H:%M:%S'
            )
            
            # Appliquer les couleurs si supportées
            colored_formatter = ColoredFormatter(
                fmt='%(icon)s %(asctime)s - %(levelname)-8s - %(message)s',
                datefmt='%H:%M:%S'
            )
            
            console_handler.setFormatter(colored_formatter)
            self.logger.addHandler(console_handler)
        
        # Handler JSON si demandé
        if self.json_output:
            json_file = self.log_file.replace('.log', '_json.log') if self.log_file else 'wallet_monitor_json.log'
            json_handler = SmartRotatingFileHandler(
                filename=json_file,
                maxBytes=self.max_file_size,
                backupCount=self.backup_count,
                encoding='utf-8'
            )
            json_handler.setFormatter(JSONFormatter())
            self.logger.addHandler(json_handler)
        
        # Handler pour les métriques de performance
        self.performance_handler = PerformanceHandler()
        self.logger.addHandler(self.performance_handler)
    
    def _setup_filters(self):
        """Configure les filtres de log"""
        
        # Ajouter le filtre de contexte à tous les handlers
        for handler in self.logger.handlers:
            handler.addFilter(self.context_filter)
        
        # Filtre de rate limiting pour éviter le spam
        rate_limit_filter = RateLimitFilter(max_per_minute=120)
        for handler in self.logger.handlers:
            if not isinstance(handler, PerformanceHandler):  # Pas de limite sur les métriques
                handler.addFilter(rate_limit_filter)
    
    def get_logger(self, name: str = None) -> logging.Logger:
        """Retourne un logger enfant avec un nom spécifique"""
        if name:
            return self.logger.getChild(name)
        return self.logger
    
    def set_context(self, **kwargs):
        """Définit le contexte pour le thread actuel"""
        self.context_filter.set_context(**kwargs)
    
    def clear_context(self):
        """Efface le contexte du thread actuel"""
        self.context_filter.clear_context()
    
    @contextmanager
    def context(self, **kwargs):
        """Context manager pour le contexte temporaire"""
        self.set_context(**kwargs)
        try:
            yield
        finally:
            self.clear_context()
    
    def log_cycle_start(self, cycle_id: str, wallet_address: str = None):
        """Log spécialisé pour le début d'un cycle"""
        with self.context(cycle_id=cycle_id, wallet_address=wallet_address):
            cycle_num = cycle_id.split('_')[1] if '_' in cycle_id else cycle_id
            timestamp = datetime.now().strftime('%H:%M:%S')
            self.logger.info(LOG_FORMATS['cycle_start'].format(
                cycle=cycle_num, 
                timestamp=timestamp
            ))
    
    def log_cycle_end(self, cycle_id: str, duration: float, **stats):
        """Log spécialisé pour la fin d'un cycle"""
        with self.context(cycle_id=cycle_id):
            cycle_num = cycle_id.split('_')[1] if '_' in cycle_id else cycle_id
            self.logger.info(LOG_FORMATS['cycle_end'].format(
                cycle=cycle_num,
                duration=format_duration(duration, compact=True)
            ))
            
            # Ajouter les statistiques si fournies
            if stats:
                stats_str = ", ".join([f"{k}: {v}" for k, v in stats.items()])
                self.logger.info(f"📊 Statistiques: {stats_str}")
    
    def log_wallet_selected(self, wallet_address: str, priority_score: float = None):
        """Log spécialisé pour la sélection de wallet"""
        wallet_short = format_wallet_address(wallet_address)
        message = LOG_FORMATS['wallet_selected'].format(wallet_short=wallet_short)
        
        if priority_score is not None:
            message += f" (priorité: {priority_score:.2f})"
        
        with self.context(wallet_address=wallet_address):
            self.logger.info(message)
    
    def log_discovery_result(self, wallet_address: str, total_accounts: int, new_accounts: int):
        """Log spécialisé pour les résultats de découverte"""
        with self.context(wallet_address=wallet_address):
            self.logger.log(CUSTOM_LOG_LEVELS['DISCOVERY'], 
                          LOG_FORMATS['discovery_result'].format(
                              total=total_accounts,
                              new=new_accounts
                          ))
    
    def log_balance_change(self, wallet_address: str, tx_type: str, amount: float, symbol: str, signature: str = None):
        """Log spécialisé pour les balance changes"""
        with self.context(wallet_address=wallet_address, signature=signature):
            self.logger.log(CUSTOM_LOG_LEVELS['TRANSACTION'],
                          LOG_FORMATS['balance_change'].format(
                              type=tx_type.upper(),
                              amount=f"{amount:,.4f}",
                              symbol=symbol
                          ))
    
    def log_priority_update(self, wallet_address: str, old_priority: float, new_priority: float):
        """Log spécialisé pour les mises à jour de priorité"""
        change = new_priority - old_priority
        icon = "📈" if change > 0 else "📉" if change < 0 else "➡️"
        
        with self.context(wallet_address=wallet_address):
            self.logger.info(LOG_FORMATS['priority_update'].format(
                icon=icon,
                old=old_priority,
                new=new_priority,
                change=change
            ))
    
    def log_batch_result(self, method: str, count: int, duration: float, success: bool = True):
        """Log spécialisé pour les résultats de batch"""
        level = CUSTOM_LOG_LEVELS['BATCH'] if success else logging.WARNING
        icon = "✅" if success else "⚠️"
        
        with self.context(rpc_method=method, batch_id=f"batch_{int(time.time())}"):
            self.logger.log(level, f"{icon} " + LOG_FORMATS['batch_result'].format(
                method=method,
                count=count,
                duration=duration
            ))
    
    def log_rpc_error(self, method: str, error: str, endpoint: str = None):
        """Log spécialisé pour les erreurs RPC"""
        with self.context(rpc_method=method):
            message = LOG_FORMATS['rpc_error'].format(method=method, error=error)
            if endpoint:
                message += f" (endpoint: {endpoint[:50]}...)"
            self.logger.error(message)
    
    def log_performance(self, rps: float, success_rate: float, **metrics):
        """Log spécialisé pour les métriques de performance"""
        performance_record = logging.LogRecord(
            name=self.logger.name,
            level=CUSTOM_LOG_LEVELS['PERFORMANCE'],
            pathname="",
            lineno=0,
            msg=LOG_FORMATS['performance'].format(rps=rps, success_rate=success_rate),
            args=(),
            exc_info=None
        )
        performance_record.metrics = {'rps': rps, 'success_rate': success_rate, **metrics}
        self.logger.handle(performance_record)
    
    def get_recent_performance_metrics(self, count: int = 10) -> List[Dict]:
        """Retourne les métriques de performance récentes"""
        return self.performance_handler.get_recent_metrics(count)
      
    def set_level(self, level: str):
       """Change le niveau de log dynamiquement"""
       self.log_level = level.upper()
       numeric_level = getattr(logging, self.log_level, logging.INFO)
       self.logger.setLevel(numeric_level)
       self.logger.info(f"🔧 Niveau de log changé vers: {self.log_level}")
   
    def add_custom_handler(self, handler: logging.Handler):
       """Ajoute un handler personnalisé"""
       handler.addFilter(self.context_filter)
       self.logger.addHandler(handler)
       self.logger.info(f"➕ Handler personnalisé ajouté: {type(handler).__name__}")
   
    def remove_handler(self, handler_type: type):
       """Supprime tous les handlers d'un type donné"""
       handlers_to_remove = [h for h in self.logger.handlers if isinstance(h, handler_type)]
       for handler in handlers_to_remove:
           self.logger.removeHandler(handler)
           handler.close()
       
       if handlers_to_remove:
           self.logger.info(f"➖ {len(handlers_to_remove)} handlers {handler_type.__name__} supprimés")
   
    def get_log_stats(self) -> Dict[str, Any]:
       """Retourne des statistiques sur le logging"""
       stats = {
           'level': self.log_level,
           'handlers_count': len(self.logger.handlers),
           'handlers': [type(h).__name__ for h in self.logger.handlers],
           'log_file': self.log_file,
           'console_output': self.console_output,
           'json_output': self.json_output
       }
       
       # Ajouter les stats du fichier de log si disponible
       if self.log_file and os.path.exists(self.log_file):
           try:
               file_stat = os.stat(self.log_file)
               stats['log_file_size'] = file_stat.st_size
               stats['log_file_modified'] = file_stat.st_mtime
           except OSError:
               pass
       
       return stats


# =============================================================================
# FONCTIONS D'INITIALISATION ET HELPERS
# =============================================================================
def setup_logger_from_config(config: Optional['SolanaWalletConfig'] = None,
                            context_provider: callable = None) -> SolanaWalletLogger:
    """
    Configure le logging à partir de la configuration
    
    Args:
        config: Instance de configuration (auto-chargée si None)
        context_provider: Fonction pour fournir du contexte global
    
    Returns:
        Instance du logger configuré
    """
    # Charger la config si pas fournie
    if config is None:
        from core.config import get_config
        config = get_config()
    
    logging_config = config.logging
    
    logger_instance = SolanaWalletLogger(
        log_level=logging_config.level.value,
        log_file=logging_config.get_full_path(),  # Utilise le chemin complet avec logs/
        console_output=logging_config.console_output,
        json_output=logging_config.json_output,
        max_file_size=logging_config.max_file_size_mb * 1024 * 1024,
        backup_count=logging_config.backup_count,
        max_age_days=logging_config.max_age_days,
        force_reconfigure=True
    )
    
    # Configurer le context provider si fourni
    if context_provider:
        logger_instance.context_filter.context_provider = context_provider
    
    return logger_instance

def setup_logger(log_level: str = "INFO",
               log_file: str = "wallet_monitor.log",
               console_output: bool = True,
               json_output: bool = False,
               max_file_size: int = 10 * 1024 * 1024,
               backup_count: int = 5,
               max_age_days: int = 7,
               context_provider: callable = None) -> SolanaWalletLogger:
   """
   Fonction principale pour configurer le logging
   
   Args:
       log_level: Niveau de log (DEBUG, INFO, WARNING, ERROR, CRITICAL)
       log_file: Chemin du fichier de log
       console_output: Activer la sortie console
       json_output: Activer la sortie JSON
       max_file_size: Taille max du fichier de log en bytes
       backup_count: Nombre de fichiers de backup à conserver
       max_age_days: Âge maximum des logs en jours
       context_provider: Fonction pour fournir du contexte global
   
   Returns:
       Instance du logger configuré
   """
   logger_instance = SolanaWalletLogger(
       log_level=log_level,
       log_file=log_file,
       console_output=console_output,
       json_output=json_output,
       max_file_size=max_file_size,
       backup_count=backup_count,
       max_age_days=max_age_days
   )
   
   # Configurer le context provider si fourni
   if context_provider:
       logger_instance.context_filter.context_provider = context_provider
   
   return logger_instance


def get_logger(name: str = None) -> logging.Logger:
   """
   Récupère un logger enfant du logger principal
   
   Args:
       name: Nom du logger enfant
   
   Returns:
       Instance du logger
   """
   main_logger = SolanaWalletLogger()
   return main_logger.get_logger(name)


def log_with_context(**context_kwargs):
   """
   Décorateur pour ajouter du contexte automatiquement aux logs d'une fonction
   
   Args:
       **context_kwargs: Contexte à ajouter
   
   Returns:
       Décorateur de fonction
   """
   def decorator(func):
       def wrapper(*args, **kwargs):
           logger_instance = SolanaWalletLogger()
           with logger_instance.context(**context_kwargs):
               return func(*args, **kwargs)
       wrapper.__name__ = func.__name__
       wrapper.__doc__ = func.__doc__
       return wrapper
   return decorator


def setup_development_logging():
   """Configuration de logging optimisée pour le développement"""
   return setup_logger(
       log_level="DEBUG",
       log_file="dev_wallet_monitor.log",
       console_output=True,
       json_output=False,
       max_file_size=5 * 1024 * 1024,  # 5MB
       backup_count=3,
       max_age_days=3
   )


def setup_production_logging():
   """Configuration de logging optimisée pour la production"""
   return setup_logger(
       log_level="INFO",
       log_file="/var/log/wallet_monitor/production.log",
       console_output=False,
       json_output=True,
       max_file_size=50 * 1024 * 1024,  # 50MB
       backup_count=10,
       max_age_days=30
   )


def setup_testing_logging():
   """Configuration de logging pour les tests"""
   return setup_logger(
       log_level="WARNING",
       log_file="test_wallet_monitor.log",
       console_output=False,
       json_output=False,
       max_file_size=1 * 1024 * 1024,  # 1MB
       backup_count=2,
       max_age_days=1
   )


# =============================================================================
# UTILITAIRES DE DEBUGGING ET MONITORING
# =============================================================================

class LogAnalyzer:
   """Analyseur de logs pour identifier les patterns et problèmes"""
   
   def __init__(self, log_file: str):
       self.log_file = log_file
   
   def analyze_error_patterns(self, last_hours: int = 24) -> Dict[str, Any]:
       """Analyse les patterns d'erreur des dernières heures"""
       if not os.path.exists(self.log_file):
           return {}
       
       error_counts = {}
       warning_counts = {}
       cutoff_time = time.time() - (last_hours * 3600)
       
       try:
           with open(self.log_file, 'r', encoding='utf-8') as f:
               for line in f:
                   try:
                       # Parser la ligne de log basique
                       if ' - ERROR - ' in line:
                           # Extraire le timestamp et vérifier s'il est récent
                           timestamp_str = line.split(' - ')[0]
                           timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S').timestamp()
                           
                           if timestamp >= cutoff_time:
                               # Extraire le type d'erreur
                               error_part = line.split(' - ERROR - ')[1].split(' - ')[0]
                               error_counts[error_part] = error_counts.get(error_part, 0) + 1
                       
                       elif ' - WARNING - ' in line:
                           timestamp_str = line.split(' - ')[0]
                           timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S').timestamp()
                           
                           if timestamp >= cutoff_time:
                               warning_part = line.split(' - WARNING - ')[1].split(' - ')[0]
                               warning_counts[warning_part] = warning_counts.get(warning_part, 0) + 1
                   
                   except (ValueError, IndexError):
                       continue
       
       except Exception as e:
           return {'analysis_error': str(e)}
       
       return {
           'period_hours': last_hours,
           'total_errors': sum(error_counts.values()),
           'total_warnings': sum(warning_counts.values()),
           'error_types': error_counts,
           'warning_types': warning_counts,
           'top_errors': sorted(error_counts.items(), key=lambda x: x[1], reverse=True)[:5],
           'top_warnings': sorted(warning_counts.items(), key=lambda x: x[1], reverse=True)[:5]
       }
   
   def get_performance_trends(self, last_hours: int = 24) -> Dict[str, Any]:
       """Analyse les tendances de performance"""
       performance_metrics = []
       
       if not os.path.exists(self.log_file):
           return {}
       
       try:
           with open(self.log_file, 'r', encoding='utf-8') as f:
               for line in f:
                   if 'PERFORMANCE' in line and 'RPS:' in line:
                       try:
                           # Extraire les métriques de performance
                           import re
                           rps_match = re.search(r'RPS:\s*(\d+(?:\.\d+)?)', line)
                           success_match = re.search(r'Succès:\s*(\d+(?:\.\d+)?)%', line)
                           
                           if rps_match and success_match:
                               timestamp_str = line.split(' - ')[0]
                               timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S').timestamp()
                               
                               if timestamp >= time.time() - (last_hours * 3600):
                                   performance_metrics.append({
                                       'timestamp': timestamp,
                                       'rps': float(rps_match.group(1)),
                                       'success_rate': float(success_match.group(1))
                                   })
                       except (ValueError, IndexError):
                           continue
       
       except Exception as e:
           return {'analysis_error': str(e)}
       
       if not performance_metrics:
           return {'no_data': True}
       
       # Calculer les tendances
       avg_rps = sum(m['rps'] for m in performance_metrics) / len(performance_metrics)
       avg_success_rate = sum(m['success_rate'] for m in performance_metrics) / len(performance_metrics)
       
       return {
           'period_hours': last_hours,
           'data_points': len(performance_metrics),
           'avg_rps': round(avg_rps, 2),
           'avg_success_rate': round(avg_success_rate, 2),
           'max_rps': max(m['rps'] for m in performance_metrics),
           'min_rps': min(m['rps'] for m in performance_metrics),
           'latest_metrics': performance_metrics[-5:] if len(performance_metrics) >= 5 else performance_metrics
       }


class HealthChecker:
   """Vérificateur de santé du système de logging"""
   
   def __init__(self, logger_instance: SolanaWalletLogger):
       self.logger_instance = logger_instance
   
   def check_health(self) -> Dict[str, Any]:
       """Effectue un check de santé complet du logging"""
       health_status = {
           'timestamp': get_current_timestamp(),
           'overall_status': 'healthy',
           'checks': {}
       }
       
       # Vérifier que le logger fonctionne
       try:
           test_logger = self.logger_instance.get_logger('health_check')
           test_logger.debug("Health check test message")
           health_status['checks']['logger_functional'] = True
       except Exception as e:
           health_status['checks']['logger_functional'] = False
           health_status['checks']['logger_error'] = str(e)
           health_status['overall_status'] = 'degraded'
       
       # Vérifier l'accès au fichier de log
       if self.logger_instance.log_file:
           try:
               log_path = Path(self.logger_instance.log_file)
               if log_path.exists():
                   # Vérifier les permissions d'écriture
                   test_write = log_path.parent / f"test_write_{int(time.time())}.tmp"
                   test_write.write_text("test")
                   test_write.unlink()
                   
                   health_status['checks']['log_file_writable'] = True
                   health_status['checks']['log_file_size'] = log_path.stat().st_size
               else:
                   health_status['checks']['log_file_exists'] = False
                   health_status['overall_status'] = 'degraded'
           except Exception as e:
               health_status['checks']['log_file_error'] = str(e)
               health_status['overall_status'] = 'degraded'
       
       # Vérifier les handlers
       handler_status = {}
       for handler in self.logger_instance.logger.handlers:
           handler_name = type(handler).__name__
           try:
               # Test basic du handler
               test_record = logging.LogRecord(
                   name="health_check",
                   level=logging.INFO,
                   pathname="",
                   lineno=0,
                   msg="Health check",
                   args=(),
                   exc_info=None
               )
               handler.handle(test_record)
               handler_status[handler_name] = 'ok'
           except Exception as e:
               handler_status[handler_name] = f'error: {e}'
               health_status['overall_status'] = 'degraded'
       
       health_status['checks']['handlers'] = handler_status
       
       # Vérifier l'utilisation de la mémoire (approximative)
       try:
           import sys
           memory_usage = sys.getsizeof(self.logger_instance)
           health_status['checks']['memory_usage_bytes'] = memory_usage
       except Exception:
           pass
       
       return health_status
   
   def get_recommendations(self) -> List[str]:
       """Retourne des recommandations pour optimiser le logging"""
       recommendations = []
       
       health = self.check_health()
       
       if health['overall_status'] != 'healthy':
           recommendations.append("⚠️ Le système de logging présente des problèmes")
       
       # Vérifier la taille du fichier de log
       if 'log_file_size' in health['checks']:
           size_mb = health['checks']['log_file_size'] / (1024 * 1024)
           if size_mb > 50:
               recommendations.append(f"📁 Fichier de log volumineux ({size_mb:.1f}MB), considérer la rotation")
       
       # Vérifier les handlers défaillants
       if 'handlers' in health['checks']:
           failed_handlers = [name for name, status in health['checks']['handlers'].items() if status != 'ok']
           if failed_handlers:
               recommendations.append(f"🔧 Handlers défaillants: {', '.join(failed_handlers)}")
       
       if not recommendations:
           recommendations.append("✅ Système de logging en bonne santé")
       
       return recommendations


# =============================================================================
# INTÉGRATIONS ET EXTENSIONS
# =============================================================================

class SlackLogHandler(logging.Handler):
   """Handler pour envoyer les logs critiques vers Slack"""
   
   def __init__(self, webhook_url: str, min_level: int = logging.ERROR):
       super().__init__()
       self.webhook_url = webhook_url
       self.min_level = min_level
       self.setLevel(min_level)
   
   def emit(self, record):
       if record.levelno < self.min_level:
           return
       
       try:
           import requests
           
           # Déterminer la couleur selon le niveau
           colors = {
               logging.WARNING: '#FFA500',  # Orange
               logging.ERROR: '#FF0000',    # Rouge
               logging.CRITICAL: '#8B0000'  # Rouge foncé
           }
           color = colors.get(record.levelno, '#FF0000')
           
           # Préparer le payload Slack
           payload = {
               'attachments': [{
                   'color': color,
                   'title': f'{record.levelname} - Solana Wallet Monitor',
                   'text': record.getMessage(),
                   'fields': [
                       {'title': 'Module', 'value': record.name, 'short': True},
                       {'title': 'Fonction', 'value': f"{record.funcName}:{record.lineno}", 'short': True},
                       {'title': 'Timestamp', 'value': datetime.fromtimestamp(record.created).isoformat(), 'short': True}
                   ]
               }]
           }
           
           # Ajouter le contexte si disponible
           if hasattr(record, 'wallet_address'):
               payload['attachments'][0]['fields'].append({
                   'title': 'Wallet', 
                   'value': format_wallet_address(record.wallet_address), 
                   'short': True
               })
           
           # Envoyer vers Slack (non-bloquant)
           requests.post(self.webhook_url, json=payload, timeout=5)
           
       except Exception:
           # Ne pas lever d'exception pour éviter de casser le logging
           pass


class DatabaseLogHandler(logging.Handler):
   """Handler pour stocker les logs en base de données"""
   
   def __init__(self, db_connection_factory, table_name: str = "logs", buffer_size: int = 100):
       super().__init__()
       self.db_connection_factory = db_connection_factory
       self.table_name = table_name  
       self.buffer_size = buffer_size
       self.buffer = []
       self.buffer_lock = threading.Lock()
   
   def emit(self, record):
       with self.buffer_lock:
           log_entry = {
               'timestamp': record.created,
               'level': record.levelname,
               'logger_name': record.name,
               'message': record.getMessage(),
               'module': record.module,
               'function_name': record.funcName,
               'line_number': record.lineno
           }
           
           # Ajouter le contexte si disponible
           context_fields = ['wallet_address', 'cycle_id', 'scan_id', 'signature', 'token_mint']
           for field in context_fields:
               if hasattr(record, field):
                   log_entry[field] = getattr(record, field)
           
           self.buffer.append(log_entry)
           
           # Flush si le buffer est plein
           if len(self.buffer) >= self.buffer_size:
               self._flush_buffer()
   
   def _flush_buffer(self):
       """Écrit le buffer en base de données"""
       if not self.buffer:
           return
       
       try:
           with self.db_connection_factory() as conn:
               cursor = conn.cursor()
               
               # Créer la table si elle n'existe pas
               cursor.execute(f'''
                   CREATE TABLE IF NOT EXISTS {self.table_name} (
                       id INTEGER PRIMARY KEY AUTOINCREMENT,
                       timestamp REAL,
                       level TEXT,
                       logger_name TEXT,
                       message TEXT,
                       module TEXT,
                       function_name TEXT,
                       line_number INTEGER,
                       wallet_address TEXT,
                       cycle_id TEXT,
                       scan_id TEXT,
                       signature TEXT,
                       token_mint TEXT,
                       created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                   )
               ''')
               
               # Insérer les logs
               for entry in self.buffer:
                   cursor.execute(f'''
                       INSERT INTO {self.table_name} 
                       (timestamp, level, logger_name, message, module, function_name, 
                        line_number, wallet_address, cycle_id, scan_id, signature, token_mint)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ''', (
                       entry['timestamp'], entry['level'], entry['logger_name'],
                       entry['message'], entry['module'], entry['function_name'],
                       entry['line_number'], entry.get('wallet_address'),
                       entry.get('cycle_id'), entry.get('scan_id'),
                       entry.get('signature'), entry.get('token_mint')
                   ))
               
               conn.commit()
               self.buffer.clear()
               
       except Exception as e:
           # Ne pas lever d'exception, juste vider le buffer pour éviter l'accumulation
           self.buffer.clear()
   
   def close(self):
       """Flush final avant fermeture"""
       self._flush_buffer()
       super().close()


# =============================================================================
# EXPORT ET INITIALISATION PAR DÉFAUT
# =============================================================================

# Instance globale du logger (sera initialisée lors du premier appel)
_default_logger_instance = None

def init_default_logger(**kwargs):
   """Initialise le logger par défaut avec les paramètres donnés"""
   global _default_logger_instance
   _default_logger_instance = setup_logger(**kwargs)
   return _default_logger_instance

def get_default_logger() -> SolanaWalletLogger:
   """Retourne l'instance du logger par défaut"""
   global _default_logger_instance
   if _default_logger_instance is None:
       _default_logger_instance = setup_logger()
   return _default_logger_instance

# Export des classes et fonctions principales
__all__ = [
   # Classes principales
   'SolanaWalletLogger', 'LogAnalyzer', 'HealthChecker',
   
   # Formatters
   'ColoredFormatter', 'ContextFormatter', 'JSONFormatter', 'IconFormatter',
   
   # Handlers
   'SmartRotatingFileHandler', 'PerformanceHandler', 'SlackLogHandler', 'DatabaseLogHandler',
   
   # Filtres
   'ContextFilter', 'LevelRangeFilter', 'RateLimitFilter',
   
   # Fonctions de configuration
   'setup_logger', 'get_logger', 'init_default_logger', 'get_default_logger',
   'setup_development_logging', 'setup_production_logging', 'setup_testing_logging',
   
   # Décorateurs et utilitaires
   'log_with_context'
]

# Initialisation automatique en mode développement si aucune configuration n'est détectée
if __name__ == "__main__":
   # Mode test/développement
   logger = setup_development_logging()
   test_logger = logger.get_logger("test")
   
   # Tests rapides
   test_logger.debug("🔍 Test DEBUG")
   test_logger.info("ℹ️ Test INFO")  
   test_logger.warning("⚠️ Test WARNING")
   test_logger.error("❌ Test ERROR")
   test_logger.critical("🚨 Test CRITICAL")
   
   # Test avec contexte
   with logger.context(wallet_address="4DdrfiDHpmx55i4SPssxVzS9ZaKLb8qr45NKY9Er9nNh", cycle_id="cycle_123_1640995200"):
       test_logger.info("Test avec contexte")
   
   # Test des logs spécialisés
   logger.log_cycle_start("cycle_123_1640995200", "4DdrfiDHpmx55i4SPssxVzS9ZaKLb8qr45NKY9Er9nNh")
   logger.log_discovery_result("4DdrfiDHpmx55i4SPssxVzS9ZaKLb8qr45NKY9Er9nNh", 150, 5)
   logger.log_balance_change("4DdrfiDHpmx55i4SPssxVzS9ZaKLb8qr45NKY9Er9nNh", "buy", 1000.0, "USDC")
   logger.log_priority_update("4DdrfiDHpmx55i4SPssxVzS9ZaKLb8qr45NKY9Er9nNh", 2.5, 3.2)
   logger.log_batch_result("getMultipleAccounts", 50, 1.23)
   logger.log_performance(rps=15.5, success_rate=98.2, batch_efficiency=0.85)
   logger.log_cycle_end("cycle_123_1640995200", 45.6, discoveries=5, transactions=3)
   
   print("✅ Tests de logging terminés - vérifiez le fichier dev_wallet_monitor.log")
