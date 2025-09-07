#!/usr/bin/env python3
"""
Système de notifications pour AutoTrader
Support Discord et Telegram avec filtrage par niveau et type
"""

import asyncio
import aiohttp
import json
from datetime import datetime
from typing import Dict, Any, Optional, List
from enum import Enum
from dataclasses import dataclass
from autotrade_config_manager import get_notification_config, NotificationConfig

class NotificationLevel(Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"

class NotificationType(Enum):
    TRADE = "trades"
    ERROR = "errors"
    PERFORMANCE = "performance"
    SYSTEM = "system"

@dataclass
class Notification:
    """Structure d'une notification"""
    title: str
    message: str
    level: NotificationLevel
    type: NotificationType
    timestamp: datetime
    data: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.data is None:
            self.data = {}

class DiscordNotifier:
    """Gestionnaire de notifications Discord"""
    
    def __init__(self, webhook_url: str, config: NotificationConfig):
        self.webhook_url = webhook_url
        self.config = config
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    def _get_embed_color(self, level: NotificationLevel) -> int:
        """Retourne la couleur selon le niveau"""
        colors = {
            NotificationLevel.DEBUG: 0x808080,      # Gris
            NotificationLevel.INFO: 0x0099FF,       # Bleu
            NotificationLevel.WARNING: 0xFF9900,    # Orange
            NotificationLevel.ERROR: 0xFF0000,      # Rouge
            NotificationLevel.CRITICAL: 0x8B0000    # Rouge foncé
        }
        return colors.get(level, 0x0099FF)
    
    def _get_emoji(self, level: NotificationLevel, type: NotificationType) -> str:
        """Retourne l'emoji selon le niveau et type"""
        if type == NotificationType.TRADE:
            if level == NotificationLevel.INFO:
                return "💰"
            elif level == NotificationLevel.WARNING:
                return "⚠️"
            elif level == NotificationLevel.ERROR:
                return "❌"
        elif type == NotificationType.PERFORMANCE:
            return "📊"
        elif type == NotificationType.ERROR:
            return "🚨"
        elif type == NotificationType.SYSTEM:
            return "🤖"
        
        # Par défaut selon le niveau
        emojis = {
            NotificationLevel.DEBUG: "🔍",
            NotificationLevel.INFO: "ℹ️",
            NotificationLevel.WARNING: "⚠️",
            NotificationLevel.ERROR: "❌",
            NotificationLevel.CRITICAL: "🚨"
        }
        return emojis.get(level, "ℹ️")
    
    def _format_data(self, data: Dict[str, Any]) -> str:
        """Formate les données additionnelles"""
        if not data:
            return ""
        
        formatted_lines = []
        for key, value in data.items():
            if isinstance(value, float):
                if abs(value) < 0.000001:
                    formatted_lines.append(f"**{key}**: {value:.9f}")
                elif abs(value) < 0.01:
                    formatted_lines.append(f"**{key}**: {value:.6f}")
                else:
                    formatted_lines.append(f"**{key}**: {value:.4f}")
            elif isinstance(value, dict):
                # Affichage simplifié pour les objets
                formatted_lines.append(f"**{key}**: {len(value)} items")
            else:
                formatted_lines.append(f"**{key}**: {value}")
        
        return "\n".join(formatted_lines)
    
    async def send_notification(self, notification: Notification) -> bool:
        """Envoie une notification Discord"""
        if not self.session or not self.webhook_url:
            return False
        
        try:
            emoji = self._get_emoji(notification.level, notification.type)
            
            # Construction de l'embed Discord
            embed = {
                "title": f"{emoji} {notification.title}",
                "description": notification.message,
                "color": self._get_embed_color(notification.level),
                "timestamp": notification.timestamp.isoformat(),
                "footer": {
                    "text": f"AutoTrader • {notification.type.value.title()} • {notification.level.value}"
                }
            }
            
            # Ajouter les données si présentes
            if notification.data:
                formatted_data = self._format_data(notification.data)
                if formatted_data:
                    embed["fields"] = [{
                        "name": "Details",
                        "value": formatted_data[:1024],  # Limite Discord
                        "inline": False
                    }]
            
            payload = {"embeds": [embed]}
            
            async with self.session.post(self.webhook_url, json=payload) as response:
                if response.status == 204:
                    return True
                else:
                    print(f"Discord notification failed: {response.status}")
                    return False
                    
        except Exception as e:
            print(f"Error sending Discord notification: {e}")
            return False

class TelegramNotifier:
    """Gestionnaire de notifications Telegram"""
    
    def __init__(self, bot_token: str, chat_id: str, config: NotificationConfig):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.config = config
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    def _get_emoji(self, level: NotificationLevel, type: NotificationType) -> str:
        """Retourne l'emoji selon le niveau et type"""
        if type == NotificationType.TRADE:
            if level == NotificationLevel.INFO:
                return "💰"
            elif level == NotificationLevel.WARNING:
                return "⚠️"
            elif level == NotificationLevel.ERROR:
                return "❌"
        elif type == NotificationType.PERFORMANCE:
            return "📊"
        elif type == NotificationType.ERROR:
            return "🚨"
        elif type == NotificationType.SYSTEM:
            return "🤖"
        
        emojis = {
            NotificationLevel.DEBUG: "🔍",
            NotificationLevel.INFO: "ℹ️",
            NotificationLevel.WARNING: "⚠️",
            NotificationLevel.ERROR: "❌",
            NotificationLevel.CRITICAL: "🚨"
        }
        return emojis.get(level, "ℹ️")
    
    def _format_message(self, notification: Notification) -> str:
        """Formate le message pour Telegram"""
        emoji = self._get_emoji(notification.level, notification.type)
        
        message_lines = [
            f"{emoji} *{notification.title}*",
            "",
            notification.message
        ]
        
        if notification.data:
            message_lines.append("")
            message_lines.append("*Details:*")
            for key, value in notification.data.items():
                if isinstance(value, float):
                    if abs(value) < 0.000001:
                        message_lines.append(f"• {key}: {value:.9f}")
                    elif abs(value) < 0.01:
                        message_lines.append(f"• {key}: {value:.6f}")
                    else:
                        message_lines.append(f"• {key}: {value:.4f}")
                else:
                    message_lines.append(f"• {key}: {value}")
        
        message_lines.append("")
        message_lines.append(f"_Time: {notification.timestamp.strftime('%Y-%m-%d %H:%M:%S')}_")
        message_lines.append(f"_Level: {notification.level.value} | Type: {notification.type.value.title()}_")
        
        return "\n".join(message_lines)
    
    async def send_notification(self, notification: Notification) -> bool:
        """Envoie une notification Telegram"""
        if not self.session or not self.bot_token or not self.chat_id:
            return False
        
        try:
            message = self._format_message(notification)
            
            payload = {
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True
            }
            
            url = f"{self.base_url}/sendMessage"
            
            async with self.session.post(url, json=payload) as response:
                if response.status == 200:
                    return True
                else:
                    error_text = await response.text()
                    print(f"Telegram notification failed: {response.status} - {error_text}")
                    return False
                    
        except Exception as e:
            print(f"Error sending Telegram notification: {e}")
            return False

class NotificationManager:
    """Gestionnaire principal des notifications"""
    
    def __init__(self, config_path: str = "config.yaml"):
        self.config = get_notification_config()
        self.discord_notifier: Optional[DiscordNotifier] = None
        self.telegram_notifier: Optional[TelegramNotifier] = None
        self.notification_queue: List[Notification] = []
        self.is_running = False
        self._task: Optional[asyncio.Task] = None
        
        self._initialize_notifiers()
    
    def _initialize_notifiers(self):
        """Initialise les notificateurs selon la configuration"""
        if self.config.discord_enabled and self.config.discord_webhook_url:
            self.discord_notifier = DiscordNotifier(
                self.config.discord_webhook_url, 
                self.config
            )
            print("✅ Discord notifier initialized")
        
        if (self.config.telegram_enabled and 
            self.config.telegram_bot_token and 
            self.config.telegram_chat_id):
            self.telegram_notifier = TelegramNotifier(
                self.config.telegram_bot_token,
                self.config.telegram_chat_id,
                self.config
            )
            print("✅ Telegram notifier initialized")
        
        if not self.discord_notifier and not self.telegram_notifier:
            print("⚠️ No notification services configured")
    
    def _should_send_notification(self, notification: Notification, 
                                service: str) -> bool:
        """Détermine si une notification doit être envoyée"""
        if service == "discord":
            if not self.config.discord_enabled:
                return False
            
            # Vérifier le niveau minimum
            min_level = getattr(NotificationLevel, self.config.discord_min_level)
            if notification.level.value < min_level.value:
                return False
            
            # Vérifier le canal
            return self.config.discord_channels.get(notification.type.value, False)
        
        elif service == "telegram":
            if not self.config.telegram_enabled:
                return False
            
            min_level = getattr(NotificationLevel, self.config.telegram_min_level)
            if notification.level.value < min_level.value:
                return False
            
            return self.config.telegram_channels.get(notification.type.value, False)
        
        return False
    
    async def send_notification(self, notification: Notification) -> Dict[str, bool]:
        """Envoie une notification via tous les services configurés"""
        results = {"discord": False, "telegram": False}
        
        # Discord
        if (self.discord_notifier and 
            self._should_send_notification(notification, "discord")):
            async with self.discord_notifier as notifier:
                results["discord"] = await notifier.send_notification(notification)
        
        # Telegram
        if (self.telegram_notifier and 
            self._should_send_notification(notification, "telegram")):
            async with self.telegram_notifier as notifier:
                results["telegram"] = await notifier.send_notification(notification)
        
        return results
    
    def queue_notification(self, notification: Notification):
        """Ajoute une notification à la queue"""
        self.notification_queue.append(notification)
    
    async def _process_queue(self):
        """Traite la queue de notifications"""
        while self.is_running:
            if self.notification_queue:
                notification = self.notification_queue.pop(0)
                try:
                    await self.send_notification(notification)
                except Exception as e:
                    print(f"Error processing notification: {e}")
            
            await asyncio.sleep(1)  # Éviter le spam
    
    async def start_processing(self):
        """Démarre le traitement des notifications"""
        if self.is_running:
            return
        
        self.is_running = True
        self._task = asyncio.create_task(self._process_queue())
        print("✅ Notification processing started")
    
    async def stop_processing(self):
        """Arrête le traitement des notifications"""
        self.is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        print("🛑 Notification processing stopped")

# Instance globale
_notification_manager: Optional[NotificationManager] = None

def get_notification_manager() -> NotificationManager:
    """Récupère l'instance globale du gestionnaire de notifications"""
    global _notification_manager
    if _notification_manager is None:
        _notification_manager = NotificationManager()
    return _notification_manager

# Fonctions utilitaires pour envoyer des notifications
async def notify_trade(action: str, token_symbol: str, amount: float, 
                      price: float, pnl: float = None, **kwargs):
    """Notification de trade"""
    level = NotificationLevel.INFO
    if pnl is not None:
        if pnl < -20:
            level = NotificationLevel.ERROR
        elif pnl < -10:
            level = NotificationLevel.WARNING
        elif pnl > 50:
            level = NotificationLevel.INFO
    
    notification = Notification(
        title=f"{action.upper()} {token_symbol}",
        message=f"{action} {amount:.6f} SOL worth of {token_symbol} at {price:.8f} SOL per token",
        level=level,
        type=NotificationType.TRADE,
        timestamp=datetime.now(),
        data={
            "action": action,
            "token": token_symbol,
            "amount_sol": amount,
            "price": price,
            "pnl_percentage": pnl,
            **kwargs
        }
    )
    
    await get_notification_manager().send_notification(notification)

async def notify_error(title: str, message: str, error_details: Dict[str, Any] = None):
    """Notification d'erreur"""
    notification = Notification(
        title=title,
        message=message,
        level=NotificationLevel.ERROR,
        type=NotificationType.ERROR,
        timestamp=datetime.now(),
        data=error_details or {}
    )
    
    await get_notification_manager().send_notification(notification)

async def notify_performance(metric_name: str, value: float, 
                           context: Dict[str, Any] = None):
    """Notification de performance"""
    notification = Notification(
        title=f"Performance: {metric_name}",
        message=f"{metric_name}: {value}",
        level=NotificationLevel.INFO,
        type=NotificationType.PERFORMANCE,
        timestamp=datetime.now(),
        data={"metric": metric_name, "value": value, **(context or {})}
    )
    
    await get_notification_manager().send_notification(notification)

async def notify_system(title: str, message: str, level: NotificationLevel = NotificationLevel.INFO,
                       data: Dict[str, Any] = None):
    """Notification système"""
    notification = Notification(
        title=title,
        message=message,
        level=level,
        type=NotificationType.SYSTEM,
        timestamp=datetime.now(),
        data=data or {}
    )
    
    await get_notification_manager().send_notification(notification)

if __name__ == "__main__":
    # Test du système de notifications
    async def test_notifications():
        print("🧪 Testing Notification System...")
        
        # Initialiser le gestionnaire
        manager = NotificationManager()
        
        # Test des différents types de notifications
        await notify_trade(
            action="BUY",
            token_symbol="TEST",
            amount=0.1,
            price=0.001,
            pnl=None,
            tx_signature="test_sig_123"
        )
        
        await notify_error(
            title="Transaction Failed",
            message="Failed to execute trade due to insufficient balance",
            error_details={"balance": 0.001, "required": 0.1}
        )
        
        await notify_performance(
            metric_name="daily_pnl",
            value=15.5,
            context={"trades_count": 5, "win_rate": 80}
        )
        
        await notify_system(
            title="System Started",
            message="AutoTrader started successfully on devnet",
            level=NotificationLevel.INFO,
            data={"network": "devnet", "balance": 1.0}
        )
        
        print("✅ Notification test completed")
        print("📱 Check your Discord/Telegram for messages")
    
    asyncio.run(test_notifications())