"""
Advanced Multi-Level Logging System
File: logger.py
"""

import logging
import logging.handlers
from datetime import datetime
import time

class AdvancedLogger:
    """
    Advanced multi-level logging system with component-specific log levels
    """
    
    def __init__(self, config, log_level='INFO'):
        self.config = config.get('alerts', {})
        self.log_level = log_level
        self.component_loggers = {}
        self.setup_logging()
        
    def setup_logging(self):
        """Setup comprehensive logging system"""
        # Get log level from command line or config
        log_level = getattr(logging, self.log_level.upper())
        
        # Create main logger
        self.logger = logging.getLogger('DexScreenerBot')
        self.logger.setLevel(logging.DEBUG)  # Capture all levels
        
        # Clear existing handlers
        self.logger.handlers.clear()
        
        # Create formatters
        detailed_formatter = logging.Formatter(
            '%(asctime)s | %(name)s | %(levelname)-8s | %(funcName)s:%(lineno)d | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        simple_formatter = logging.Formatter(
            '%(asctime)s | %(levelname)-8s | %(message)s',
            datefmt='%H:%M:%S'
        )
        
        # Console handler
        if self.config.get('enable_console_alerts', True):
            console_handler = logging.StreamHandler()
            console_handler.setLevel(log_level)
            
            # Use detailed formatter for DEBUG, simple for others
            if log_level == logging.DEBUG:
                console_handler.setFormatter(detailed_formatter)
            else:
                console_handler.setFormatter(simple_formatter)
                
            self.logger.addHandler(console_handler)
        
        # File handler with rotation
        if self.config.get('enable_file_logging', True):
            log_file = self.config.get('log_file', 'solana_bot.log')
            max_size = self.config.get('max_log_file_size_mb', 100) * 1024 * 1024
            backup_count = self.config.get('backup_count', 5)
            
            file_handler = logging.handlers.RotatingFileHandler(
                log_file, maxBytes=max_size, backupCount=backup_count
            )
            file_handler.setLevel(logging.DEBUG)  # File gets all levels
            file_handler.setFormatter(detailed_formatter)
            self.logger.addHandler(file_handler)
        
        # Setup component-specific loggers
        component_levels = self.config.get('component_log_levels', {})
        for component, level in component_levels.items():
            self.setup_component_logger(component, level)
            
        self.logger.info(f"Logging system initialized - Level: {self.log_level}")
        self.logger.debug(f"Component log levels: {component_levels}")
        
    def setup_component_logger(self, component, level):
        """Setup logger for specific component"""
        logger = logging.getLogger(f'DexScreenerBot.{component}')
        logger.setLevel(getattr(logging, level.upper()))
        self.component_loggers[component] = logger
        
    def get_logger(self, component=None):
        """Get logger for specific component or main logger"""
        if component and component in self.component_loggers:
            return self.component_loggers[component]
        return self.logger
        
    def debug_step(self, component, step, message, data=None):
        """Log a debug step with optional data"""
        logger = self.get_logger(component)
        if data:
            logger.debug(f"[STEP] {step}: {message} | Data: {data}")
        else:
            logger.debug(f"[STEP] {step}: {message}")
            
    def log_performance(self, component, operation, duration, success=True):
        """Log performance metrics"""
        logger = self.get_logger(component)
        status = "SUCCESS" if success else "FAILED"
        logger.info(f"[PERF] {operation}: {duration:.3f}s - {status}")
        
    def log_api_call(self, component, url, method, status_code, duration):
        """Log API call details"""
        logger = self.get_logger(component)
        logger.debug(f"[API] {method} {url} -> {status_code} ({duration:.3f}s)")
        
    def log_filter_result(self, component, token_symbol, filter_type, passed, reason=""):
        """Log filtering decisions"""
        logger = self.get_logger(component)
        status = "PASS" if passed else "BLOCK"
        if reason:
            logger.debug(f"[FILTER] {token_symbol} | {filter_type}: {status} - {reason}")
        else:
            logger.debug(f"[FILTER] {token_symbol} | {filter_type}: {status}")
            
    def log_analysis_result(self, component, token_symbol, analysis_type, score, indicators=None):
        """Log analysis results"""
        logger = self.get_logger(component)
        if indicators:
            logger.debug(f"[ANALYSIS] {token_symbol} | {analysis_type}: {score:.3f} | Indicators: {indicators[:3]}")
        else:
            logger.debug(f"[ANALYSIS] {token_symbol} | {analysis_type}: {score:.3f}")
            
    def log_trade_decision(self, component, token_symbol, should_trade, reasons):
        """Log trading decisions"""
        logger = self.get_logger(component)
        decision = "BUY" if should_trade else "SKIP"
        logger.info(f"[TRADE] {token_symbol}: {decision} | Reasons: {reasons}")
        
    def log_notification_sent(self, component, notification_type, platform, success, message=""):
        """Log notification deliveries"""
        logger = self.get_logger(component)
        status = "SENT" if success else "FAILED"
        if message:
            logger.info(f"[NOTIFY] {notification_type} -> {platform}: {status} - {message}")
        else:
            logger.info(f"[NOTIFY] {notification_type} -> {platform}: {status}")
            
    def log_cache_operation(self, component, operation, key, hit=None):
        """Log cache operations"""
        logger = self.get_logger(component)
        if hit is not None:
            hit_status = "HIT" if hit else "MISS"
            logger.debug(f"[CACHE] {operation} {key}: {hit_status}")
        else:
            logger.debug(f"[CACHE] {operation} {key}")
            
    def log_database_operation(self, component, operation, table, count=None, duration=None):
        """Log database operations"""
        logger = self.get_logger(component)
        details = []
        if count is not None:
            details.append(f"count={count}")
        if duration is not None:
            details.append(f"time={duration:.3f}s")
        details_str = f" ({', '.join(details)})" if details else ""
        logger.debug(f"[DB] {operation} {table}{details_str}")