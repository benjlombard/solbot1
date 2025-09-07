#!/usr/bin/env python3
"""
Chargeur de configuration simple pour AutoTrader
Version simplifiée qui charge juste le YAML existant
"""

import os
from pathlib import Path
from typing import Dict, Any, Optional

try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False
    print("⚠️ PyYAML not installed. Install with: pip install PyYAML")

class SimpleConfigLoader:
    """Chargeur de configuration simple"""
    
    def __init__(self, config_file: str = "app/autotrade_config.yaml"):
        self.config_file = Path(config_file)
        self.config: Dict[str, Any] = {}
        self.load_config()
    
    def load_config(self):
        """Charge la configuration depuis le fichier"""
        if not self.config_file.exists():
            print(f"❌ Configuration file not found: {self.config_file}")
            print("📋 Please create the config file first")
            return
        
        if not YAML_AVAILABLE:
            print("❌ Cannot load YAML without PyYAML installed")
            return
        
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                self.config = yaml.safe_load(f) or {}
            print(f"✅ Configuration loaded from {self.config_file}")
        except Exception as e:
            print(f"❌ Error loading configuration: {e}")
            self.config = {}
    
    def get(self, path: str, default: Any = None) -> Any:
        """Récupère une valeur par chemin (ex: 'trading.max_sol_per_trade.mainnet')"""
        keys = path.split('.')
        value = self.config
        
        try:
            for key in keys:
                value = value[key]
            return value
        except (KeyError, TypeError):
            return default
    
    def get_network_type(self) -> str:
        """Récupère le type de réseau configuré"""
        return self.get("network.type", "devnet")
    
    def get_trading_value(self, key: str, network: str = None) -> Any:
        """Récupère une valeur de trading selon le réseau"""
        if network is None:
            network = self.get_network_type()
        
        # Essayer d'abord la valeur spécifique au réseau
        network_value = self.get(f"trading.{key}.{network}")
        if network_value is not None:
            return network_value
        
        # Sinon, valeur générale
        return self.get(f"trading.{key}")
    
    def get_max_sol_per_trade(self) -> float:
        """Récupère le montant max par trade selon le réseau"""
        return self.get_trading_value("max_sol_per_trade", self.get_network_type()) or 0.0001
    
    def get_max_daily_budget(self) -> float:
        """Récupère le budget quotidien selon le réseau"""
        return self.get_trading_value("max_daily_budget", self.get_network_type()) or 0.01
    
    def get_rpc_url(self) -> str:
        """Récupère l'URL RPC selon le réseau"""
        network = self.get_network_type()
        return self.get(f"network.rpc_endpoints.{network}.primary", "https://api.devnet.solana.com")
    
    def get_confirmation_settings(self) -> Dict[str, Any]:
        """Récupère les paramètres de confirmation"""
        network = self.get_network_type()
        return {
            "timeout": self.get("trading.confirmation_timeout", 60),
            "strategy": self.get("trading.confirmation_strategy", "smart"),
            "require_manual": self.get(f"trading.require_manual_confirmation.{network}", True)
        }
    
    def is_notifications_enabled(self) -> Dict[str, bool]:
        """Vérifie si les notifications sont activées"""
        return {
            "discord": self.get("notifications.discord.enabled", False),
            "telegram": self.get("notifications.telegram.enabled", False)
        }
    
    def get_all_trading_config(self) -> Dict[str, Any]:
        """Récupère toute la configuration de trading pour le réseau actuel"""
        network = self.get_network_type()
        
        return {
            "network": network,
            "max_sol_per_trade": self.get_max_sol_per_trade(),
            "max_daily_budget": self.get_max_daily_budget(),
            "max_simultaneous_positions": self.get("trading.max_simultaneous_positions", 2),
            "min_score_to_buy": self.get("trading.min_score_to_buy", 60),
            "min_confidence_level": self.get("trading.min_confidence_level", 40),
            "max_token_age_minutes": self.get("trading.max_token_age_minutes", 10),
            "stop_loss_percentage": self.get("trading.stop_loss_percentage", -40),
            "take_profit_levels": self.get("trading.take_profit_levels", [100, 300, 500]),
            "take_profit_portions": self.get("trading.take_profit_portions", [0.5, 0.3, 0.2]),
            "slippage_bps": self.get("trading.slippage_bps", 200),
            "priority_fee_lamports": self.get_trading_value("priority_fee_lamports", network) or 100,
            "confirmation_timeout": self.get("trading.confirmation_timeout", 60),
            "confirmation_strategy": self.get("trading.confirmation_strategy", "smart"),
            "require_manual_confirmation": self.get(f"trading.require_manual_confirmation.{network}", True),
            "rpc_url": self.get_rpc_url(),
            "jupiter_api": self.get("network.jupiter_api", "https://quote-api.jup.ag/v6"),
            "explorer_base": self.get(f"network.explorer_base.{network}", "https://solscan.io")
        }

# Instance globale simple
config_loader = None

def get_config() -> SimpleConfigLoader:
    """Récupère l'instance globale du chargeur de config"""
    global config_loader
    if config_loader is None:
        config_loader = SimpleConfigLoader()
    return config_loader

def load_trading_config() -> Dict[str, Any]:
    """Fonction simple pour charger la config de trading"""
    return get_config().get_all_trading_config()

# Test si exécuté directement
if __name__ == "__main__":
    print("🧪 Testing Simple Config Loader...")
    
    config = SimpleConfigLoader()
    
    if not config.config:
        print("❌ No configuration loaded")
        print("📋 Please:")
        print("   1. Install PyYAML: pip install PyYAML")
        print("   2. Create app/autotrade_config.yaml file")
    else:
        print("✅ Configuration loaded successfully")
        
        trading_config = config.get_all_trading_config()
        print(f"📊 Trading Config for {trading_config['network']}:")
        print(f"   Max SOL per trade: {trading_config['max_sol_per_trade']}")
        print(f"   Daily budget: {trading_config['max_daily_budget']}")
        print(f"   RPC URL: {trading_config['rpc_url']}")
        print(f"   Manual confirmation: {trading_config['require_manual_confirmation']}")
        
        notifications = config.is_notifications_enabled()
        print(f"📱 Notifications: Discord={notifications['discord']}, Telegram={notifications['telegram']}")
    
    print("✅ Test completed")