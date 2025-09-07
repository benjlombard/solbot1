#!/usr/bin/env python3
"""
Système de logging avancé pour AutoTrader
Support logs JSON structurés, rotation automatique, et logging séparé par catégorie
"""

import json
import logging
import logging.handlers
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional
import traceback
import sys
from autotrade_config_manager import get_logging_config, LogLevel

class StructuredFormatter(logging.Formatter):
    """Formatteur pour logs JSON structurés"""
    
    def __init__(self, include_extra: bool = True):
        super().__init__()
        self.include_extra = include_extra
    
    def format(self, record: logging.LogRecord) -> str:
        # Données de base du log
        log_data = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno
        }
        
        # Ajouter l'exception si présente
        if record.exc_info:
            log_data["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                "message": str(record.exc_info[1]) if record.exc_info[1] else None,
                "traceback": traceback.format_exception(*record.exc_info)
            }
        
        # Ajouter les données extra si configuré
        if self.include_extra:
            extra_data = {}
            for key, value in record.__dict__.items():
                if key not in ['name', 'msg', 'args', 'levelname', 'levelno', 'pathname', 
                              'filename', 'module', 'lineno', 'funcName', 'created', 
                              'msecs', 'relativeCreated', 'thread', 'threadName', 
                              'processName', 'process', 'getMessage', 'exc_info', 
                              'exc_text', 'stack_info', 'message']:
                    extra_data[key] = value
            
            if extra_data:
                log_data["extra"] = extra_data
        
        return json.dumps(log_data, ensure_ascii=False, separators=(',', ':'))

class TextFormatter(logging.Formatter):
    """Formatteur pour logs texte lisibles"""
    
    def __init__(self):
        super().__init__(
            fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

class AutoTraderLogger:
    """Gestionnaire de logging centralisé pour AutoTrader"""
    
    def __init__(self, config_path: str = "config.yaml"):
        self.config = get_logging_config()
        self.loggers: Dict[str, logging.Logger] = {}
        self._setup_loggers()
    
    def _setup_loggers(self):
        """Configure tous les loggers"""
        # Logger principal
        self._setup_logger(
            "autotrader", 
            self.config.main_log_file,
            self.config.level
        )
        
        # Logger pour les trades
        self._setup_logger(
            "autotrader.trades", 
            self.config.trades_log_file,
            LogLevel.INFO
        )
        
        # Logger pour les erreurs
        self._setup_logger(
            "autotrader.errors", 
            self.config.errors_log_file,
            LogLevel.ERROR
        )
        
        # Logger pour les performances
        self._setup_logger(
            "autotrader.performance", 
            self.config.performance_log_file,
            LogLevel.INFO
        )
        
        print(f"✅ Logging system initialized with {self.config.format} format")
    
    def _setup_logger(self, name: str, log_file: str, min_level: LogLevel):
        """Configure un logger spécifique"""
        logger = logging.getLogger(name)
        logger.setLevel(getattr(logging, min_level.value))
        logger.handlers.clear()  # Supprimer les handlers existants
        
        # Créer le répertoire de logs si nécessaire
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Handler pour fichier avec rotation
        if self.config.file_rotation_enabled:
            if self.config.rotation_interval == "daily":
                file_handler = logging.handlers.TimedRotatingFileHandler(
                    log_file,
                    when='midnight',
                    interval=1,
                    backupCount=self.config.backup_count,
                    encoding='utf-8'
                )
            else:
                file_handler = logging.handlers.RotatingFileHandler(
                    log_file,
                    maxBytes=self.config.max_size_mb * 1024 * 1024,
                    backupCount=self.config.backup_count,
                    encoding='utf-8'
                )
        else:
            file_handler = logging.FileHandler(log_file, encoding='utf-8')
        
        # Handler pour console
        console_handler = logging.StreamHandler(sys.stdout)
        
        # Choix du formatteur
        if self.config.format == "json":
            formatter = StructuredFormatter()
            console_formatter = TextFormatter()  # Garder texte pour la console
        else:
            formatter = TextFormatter()
            console_formatter = formatter
        
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(console_formatter)
        
        # Ajouter les handlers
        logger.addHandler(file_handler)
        if name == "autotrader":  # Seul le logger principal affiche en console
            logger.addHandler(console_handler)
        
        self.loggers[name] = logger
    
    def get_logger(self, name: str = "autotrader") -> logging.Logger:
        """Récupère un logger par nom"""
        return self.loggers.get(name, self.loggers["autotrader"])
    
    def get_trade_logger(self) -> logging.Logger:
        """Récupère le logger pour les trades"""
        return self.loggers["autotrader.trades"]
    
    def get_error_logger(self) -> logging.Logger:
        """Récupère le logger pour les erreurs"""
        return self.loggers["autotrader.errors"]
    
    def get_performance_logger(self) -> logging.Logger:
        """Récupère le logger pour les performances"""
        return self.loggers["autotrader.performance"]

# Instance globale
_logger_manager: Optional[AutoTraderLogger] = None

def get_logger_manager() -> AutoTraderLogger:
    """Récupère l'instance globale du gestionnaire de logging"""
    global _logger_manager
    if _logger_manager is None:
        _logger_manager = AutoTraderLogger()
    return _logger_manager

def get_logger(name: str = "autotrader") -> logging.Logger:
    """Fonction utilitaire pour récupérer un logger"""
    return get_logger_manager().get_logger(name)

def log_trade(action: str, token_address: str, token_symbol: str, 
              sol_amount: float, token_amount: float, price: float,
              tx_signature: str = None, network: str = None, **kwargs):
    """Log structuré pour les trades"""
    trade_logger = get_logger_manager().get_trade_logger()
    
    trade_data = {
        "action": action,
        "token_address": token_address,
        "token_symbol": token_symbol,
        "sol_amount": sol_amount,
        "token_amount": token_amount,
        "price": price,
        "tx_signature": tx_signature,
        "network": network,
        **kwargs
    }
    
    trade_logger.info(f"{action} trade executed", extra=trade_data)

def log_error(error_type: str, message: str, exception: Exception = None, 
              context: Dict[str, Any] = None, **kwargs):
    """Log structuré pour les erreurs"""
    error_logger = get_logger_manager().get_error_logger()
    
    error_data = {
        "error_type": error_type,
        "context": context or {},
        **kwargs
    }
    
    if exception:
        error_logger.error(message, exc_info=exception, extra=error_data)
    else:
        error_logger.error(message, extra=error_data)

def log_performance(metric_name: str, value: float, unit: str = None,
                   context: Dict[str, Any] = None, **kwargs):
    """Log structuré pour les métriques de performance"""
    perf_logger = get_logger_manager().get_performance_logger()
    
    perf_data = {
        "metric_name": metric_name,
        "value": value,
        "unit": unit,
        "context": context or {},
        **kwargs
    }
    
    perf_logger.info(f"Performance metric: {metric_name}={value}{unit or ''}", extra=perf_data)

def log_position_update(position_id: str, token_symbol: str, entry_price: float,
                       current_price: float, pnl_percentage: float, 
                       sol_amount: float, token_amount: float, **kwargs):
    """Log structuré pour les mises à jour de position"""
    trade_logger = get_logger_manager().get_trade_logger()
    
    position_data = {
        "position_id": position_id,
        "token_symbol": token_symbol,
        "entry_price": entry_price,
        "current_price": current_price,
        "pnl_percentage": pnl_percentage,
        "sol_amount": sol_amount,
        "token_amount": token_amount,
        **kwargs
    }
    
    trade_logger.info(f"Position update: {token_symbol} PnL {pnl_percentage:+.1f}%", 
                     extra=position_data)

# Décorateur pour logging automatique des fonctions
def log_function_call(logger_name: str = "autotrader", log_level: str = "DEBUG"):
    """Décorateur pour logger automatiquement les appels de fonction"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            logger = get_logger(logger_name)
            start_time = datetime.now()
            
            # Log de début
            logger.log(getattr(logging, log_level), 
                      f"Calling {func.__name__}", 
                      extra={
                          "function": func.__name__,
                          "args_count": len(args),
                          "kwargs_count": len(kwargs),
                          "call_type": "start"
                      })
            
            try:
                result = func(*args, **kwargs)
                duration = (datetime.now() - start_time).total_seconds()
                
                # Log de succès
                logger.log(getattr(logging, log_level),
                          f"Completed {func.__name__} in {duration:.3f}s",
                          extra={
                              "function": func.__name__,
                              "duration_seconds": duration,
                              "call_type": "success"
                          })
                
                return result
                
            except Exception as e:
                duration = (datetime.now() - start_time).total_seconds()
                
                # Log d'erreur
                logger.error(f"Error in {func.__name__} after {duration:.3f}s: {e}",
                           exc_info=e,
                           extra={
                               "function": func.__name__,
                               "duration_seconds": duration,
                               "call_type": "error"
                           })
                raise
        
        return wrapper
    return decorator

if __name__ == "__main__":
    # Test du système de logging
    print("🧪 Testing Enhanced Logger...")
    
    # Initialiser le logger
    logger_manager = AutoTraderLogger()
    
    # Test des différents types de logs
    main_logger = logger_manager.get_logger()
    
    # Log normal
    main_logger.info("System started")
    main_logger.debug("Debug information")
    main_logger.warning("Warning message")
    
    # Log de trade
    log_trade(
        action="BUY",
        token_address="So11111111111111111111111111111111111111112",
        token_symbol="SOL",
        sol_amount=0.1,
        token_amount=1000,
        price=0.0001,
        tx_signature="test_signature_123",
        network="devnet",
        slippage=1.5,
        priority_fee=100
    )
    
    # Log d'erreur
    try:
        raise ValueError("Test error")
    except Exception as e:
        log_error(
            error_type="VALIDATION_ERROR",
            message="Test error occurred",
            exception=e,
            context={"token": "TEST", "amount": 100}
        )
    
    # Log de performance
    log_performance(
        metric_name="transaction_time",
        value=2.5,
        unit="seconds",
        context={"network": "devnet", "type": "swap"}
    )
    
    # Log de position
    log_position_update(
        position_id="pos_123",
        token_symbol="TEST",
        entry_price=0.001,
        current_price=0.0015,
        pnl_percentage=50.0,
        sol_amount=0.1,
        token_amount=1000
    )
    
    print("✅ Enhanced Logger test completed")
    print("📁 Check the logs/ directory for output files")