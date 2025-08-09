#!/usr/bin/env python3
"""
Modèles de données pour le trading avec Phantom Wallet
Extension pour l'achat/vente de tokens directement depuis l'interface
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Union
from datetime import datetime
import time
from enum import Enum
import json


class TradeType(Enum):
    """Types de trades supportés"""
    BUY = "buy"
    SELL = "sell"
    SWAP = "swap"


class TradeStatus(Enum):
    """Statuts des trades"""
    PENDING = "pending"
    CONFIRMED = "confirmed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


class SlippageLevel(Enum):
    """Niveaux de slippage prédéfinis"""
    LOW = 0.1      # 0.1%
    NORMAL = 0.5   # 0.5%
    HIGH = 1.0     # 1.0%
    VERY_HIGH = 3.0 # 3.0%


@dataclass
class TradingSettings:
    """Paramètres utilisateur pour le trading"""
    wallet_address: str
    default_slippage: float = 0.5  # %
    max_trade_amount_sol: float = 10.0
    max_daily_volume_sol: float = 100.0
    auto_approve_under_sol: float = 1.0
    preferred_dex: str = "jupiter"  # jupiter, raydium, orca
    enable_mev_protection: bool = True
    priority_fee_lamports: int = 5000
    created_at: int = field(default_factory=lambda: int(time.time()))
    updated_at: int = field(default_factory=lambda: int(time.time()))

    @property
    def wallet_short(self) -> str:
        """Version courte de l'adresse wallet"""
        return f"{self.wallet_address[:6]}...{self.wallet_address[-6:]}"

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire pour API/JSON"""
        return {
            'wallet_address': self.wallet_address,
            'wallet_short': self.wallet_short,
            'default_slippage': self.default_slippage,
            'max_trade_amount_sol': self.max_trade_amount_sol,
            'max_daily_volume_sol': self.max_daily_volume_sol,
            'auto_approve_under_sol': self.auto_approve_under_sol,
            'preferred_dex': self.preferred_dex,
            'enable_mev_protection': self.enable_mev_protection,
            'priority_fee_lamports': self.priority_fee_lamports,
            'created_at': self.created_at,
            'updated_at': self.updated_at
        }


@dataclass
class TradeQuote:
    """Devis pour un trade"""
    token_mint: str
    token_symbol: str
    trade_type: TradeType
    amount_in: float
    amount_out: float
    amount_in_decimals: int
    amount_out_decimals: int
    price_impact: float  # %
    slippage: float  # %
    minimum_received: float
    dex: str
    route: List[str]  # Route de swap
    fee_bps: int  # Base points (100 bps = 1%)
    estimated_fee_sol: float
    expires_at: int
    quote_id: str
    created_at: int = field(default_factory=lambda: int(time.time()))

    @property
    def is_expired(self) -> bool:
        """Vérifie si le devis a expiré"""
        return int(time.time()) > self.expires_at

    @property
    def time_to_expiry(self) -> int:
        """Temps restant avant expiration (secondes)"""
        return max(0, self.expires_at - int(time.time()))

    @property
    def effective_price(self) -> float:
        """Prix effectif du trade"""
        if self.trade_type == TradeType.BUY:
            return self.amount_in / self.amount_out if self.amount_out > 0 else 0
        else:
            return self.amount_out / self.amount_in if self.amount_in > 0 else 0

    @property
    def price_impact_level(self) -> str:
        """Niveau d'impact sur le prix"""
        if self.price_impact < 0.1:
            return "minimal"
        elif self.price_impact < 1.0:
            return "low"
        elif self.price_impact < 5.0:
            return "medium"
        else:
            return "high"

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire pour API/JSON"""
        return {
            'token_mint': self.token_mint,
            'token_symbol': self.token_symbol,
            'trade_type': self.trade_type.value,
            'amount_in': self.amount_in,
            'amount_out': self.amount_out,
            'amount_in_decimals': self.amount_in_decimals,
            'amount_out_decimals': self.amount_out_decimals,
            'price_impact': self.price_impact,
            'price_impact_level': self.price_impact_level,
            'slippage': self.slippage,
            'minimum_received': self.minimum_received,
            'dex': self.dex,
            'route': self.route,
            'fee_bps': self.fee_bps,
            'estimated_fee_sol': self.estimated_fee_sol,
            'effective_price': self.effective_price,
            'expires_at': self.expires_at,
            'time_to_expiry': self.time_to_expiry,
            'is_expired': self.is_expired,
            'quote_id': self.quote_id,
            'created_at': self.created_at
        }


@dataclass
class TradeOrder:
    """Ordre de trade"""
    order_id: str
    wallet_address: str
    token_mint: str
    token_symbol: str
    trade_type: TradeType
    amount_sol: float
    amount_tokens: float
    slippage: float
    quote_id: Optional[str] = None
    dex: str = "jupiter"
    status: TradeStatus = TradeStatus.PENDING
    
    # Données d'exécution
    transaction_signature: Optional[str] = None
    actual_amount_received: Optional[float] = None
    actual_price: Optional[float] = None
    gas_used: Optional[float] = None
    
    # Timestamps
    created_at: int = field(default_factory=lambda: int(time.time()))
    submitted_at: Optional[int] = None
    confirmed_at: Optional[int] = None
    
    # Métadonnées
    user_agent: str = "wallet_monitor"
    priority_fee: int = 5000
    notes: Optional[str] = None

    @property
    def wallet_short(self) -> str:
        """Version courte de l'adresse wallet"""
        return f"{self.wallet_address[:6]}...{self.wallet_address[-6:]}"

    @property
    def signature_short(self) -> Optional[str]:
        """Version courte de la signature"""
        if not self.transaction_signature:
            return None
        return f"{self.transaction_signature[:8]}...{self.transaction_signature[-8:]}"

    @property
    def execution_time(self) -> Optional[float]:
        """Temps d'exécution en secondes"""
        if not self.submitted_at or not self.confirmed_at:
            return None
        return self.confirmed_at - self.submitted_at

    @property
    def is_profitable(self) -> Optional[bool]:
        """Trade profitable par rapport au prix attendu"""
        if not self.actual_price or not self.amount_sol or not self.amount_tokens:
            return None
        
        expected_price = self.amount_sol / self.amount_tokens
        if self.trade_type == TradeType.BUY:
            return self.actual_price <= expected_price * (1 + self.slippage / 100)
        else:
            return self.actual_price >= expected_price * (1 - self.slippage / 100)

    @property
    def profit_loss_pct(self) -> Optional[float]:
        """Profit/Loss en pourcentage par rapport à l'attendu"""
        if not self.actual_price or not self.amount_sol or not self.amount_tokens:
            return None
        
        expected_price = self.amount_sol / self.amount_tokens
        return ((self.actual_price - expected_price) / expected_price) * 100

    def update_status(self, new_status: TradeStatus, 
                     signature: Optional[str] = None,
                     actual_received: Optional[float] = None) -> None:
        """Met à jour le statut de l'ordre"""
        self.status = new_status
        
        if signature:
            self.transaction_signature = signature
            self.submitted_at = int(time.time())
        
        if new_status == TradeStatus.CONFIRMED:
            self.confirmed_at = int(time.time())
            if actual_received:
                self.actual_amount_received = actual_received

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire pour API/JSON"""
        return {
            'order_id': self.order_id,
            'wallet_address': self.wallet_address,
            'wallet_short': self.wallet_short,
            'token_mint': self.token_mint,
            'token_symbol': self.token_symbol,
            'trade_type': self.trade_type.value,
            'amount_sol': self.amount_sol,
            'amount_tokens': self.amount_tokens,
            'slippage': self.slippage,
            'quote_id': self.quote_id,
            'dex': self.dex,
            'status': self.status.value,
            'transaction_signature': self.transaction_signature,
            'signature_short': self.signature_short,
            'actual_amount_received': self.actual_amount_received,
            'actual_price': self.actual_price,
            'gas_used': self.gas_used,
            'execution_time': self.execution_time,
            'is_profitable': self.is_profitable,
            'profit_loss_pct': self.profit_loss_pct,
            'created_at': self.created_at,
            'submitted_at': self.submitted_at,
            'confirmed_at': self.confirmed_at,
            'priority_fee': self.priority_fee,
            'notes': self.notes
        }


@dataclass
class TradingPortfolio:
    """Portfolio de trading d'un wallet"""
    wallet_address: str
    total_trades: int = 0
    successful_trades: int = 0
    failed_trades: int = 0
    total_volume_sol: float = 0.0
    total_fees_paid: float = 0.0
    total_pnl_sol: float = 0.0
    avg_trade_size_sol: float = 0.0
    largest_trade_sol: float = 0.0
    best_trade_pnl: float = 0.0
    worst_trade_pnl: float = 0.0
    favorite_tokens: List[str] = field(default_factory=list)
    preferred_dex: str = "jupiter"
    risk_score: float = 1.0  # 1-10
    updated_at: int = field(default_factory=lambda: int(time.time()))

    @property
    def wallet_short(self) -> str:
        """Version courte de l'adresse wallet"""
        return f"{self.wallet_address[:6]}...{self.wallet_address[-6:]}"

    @property
    def success_rate(self) -> float:
        """Taux de succès des trades"""
        if self.total_trades == 0:
            return 0.0
        return (self.successful_trades / self.total_trades) * 100

    @property
    def avg_fee_per_trade(self) -> float:
        """Frais moyen par trade"""
        if self.total_trades == 0:
            return 0.0
        return self.total_fees_paid / self.total_trades

    @property
    def roi_percentage(self) -> float:
        """ROI en pourcentage"""
        if self.total_volume_sol == 0:
            return 0.0
        return (self.total_pnl_sol / self.total_volume_sol) * 100

    @property
    def risk_level(self) -> str:
        """Niveau de risque"""
        if self.risk_score <= 3:
            return "conservative"
        elif self.risk_score <= 6:
            return "moderate"
        elif self.risk_score <= 8:
            return "aggressive"
        else:
            return "very_high"

    def add_trade(self, trade_order: TradeOrder) -> None:
        """Ajoute un trade au portfolio"""
        self.total_trades += 1
        
        if trade_order.status == TradeStatus.CONFIRMED:
            self.successful_trades += 1
            self.total_volume_sol += trade_order.amount_sol
            
            if trade_order.gas_used:
                self.total_fees_paid += trade_order.gas_used
            
            if trade_order.profit_loss_pct:
                pnl = (trade_order.profit_loss_pct / 100) * trade_order.amount_sol
                self.total_pnl_sol += pnl
                self.best_trade_pnl = max(self.best_trade_pnl, pnl)
                self.worst_trade_pnl = min(self.worst_trade_pnl, pnl)
            
            self.largest_trade_sol = max(self.largest_trade_sol, trade_order.amount_sol)
            
            # Mettre à jour moyenne
            self.avg_trade_size_sol = self.total_volume_sol / self.successful_trades
            
            # Ajouter token aux favoris s'il fait partie du top
            if trade_order.token_mint not in self.favorite_tokens:
                self.favorite_tokens.append(trade_order.token_mint)
                if len(self.favorite_tokens) > 10:  # Garder top 10
                    self.favorite_tokens = self.favorite_tokens[-10:]
        
        elif trade_order.status == TradeStatus.FAILED:
            self.failed_trades += 1
        
        self.updated_at = int(time.time())

    def calculate_risk_score(self) -> float:
        """Calcule le score de risque basé sur l'historique"""
        score = 1.0
        
        # Volume de trading
        if self.avg_trade_size_sol > 10:
            score += 2
        elif self.avg_trade_size_sol > 5:
            score += 1
        
        # Fréquence de trading
        if self.total_trades > 100:
            score += 2
        elif self.total_trades > 50:
            score += 1
        
        # Performance
        if self.success_rate < 60:
            score += 1
        elif self.success_rate < 80:
            score += 0.5
        
        # Volatilité
        pnl_range = self.best_trade_pnl - self.worst_trade_pnl
        if pnl_range > self.avg_trade_size_sol:
            score += 1
        
        self.risk_score = min(10.0, score)
        return self.risk_score

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire pour API/JSON"""
        return {
            'wallet_address': self.wallet_address,
            'wallet_short': self.wallet_short,
            'total_trades': self.total_trades,
            'successful_trades': self.successful_trades,
            'failed_trades': self.failed_trades,
            'success_rate': round(self.success_rate, 2),
            'total_volume_sol': round(self.total_volume_sol, 4),
            'total_fees_paid': round(self.total_fees_paid, 4),
            'total_pnl_sol': round(self.total_pnl_sol, 4),
            'avg_trade_size_sol': round(self.avg_trade_size_sol, 4),
            'avg_fee_per_trade': round(self.avg_fee_per_trade, 4),
            'largest_trade_sol': round(self.largest_trade_sol, 4),
            'best_trade_pnl': round(self.best_trade_pnl, 4),
            'worst_trade_pnl': round(self.worst_trade_pnl, 4),
            'roi_percentage': round(self.roi_percentage, 2),
            'risk_score': round(self.risk_score, 1),
            'risk_level': self.risk_level,
            'favorite_tokens': self.favorite_tokens,
            'preferred_dex': self.preferred_dex,
            'updated_at': self.updated_at
        }


@dataclass
class MarketData:
    """Données de marché pour un token"""
    token_mint: str
    price_usd: float
    price_sol: float
    volume_24h_usd: float
    market_cap_usd: Optional[float] = None
    liquidity_usd: Optional[float] = None
    price_change_24h: float = 0.0
    price_change_1h: float = 0.0
    fdv: Optional[float] = None  # Fully Diluted Valuation
    source: str = "jupiter"
    updated_at: int = field(default_factory=lambda: int(time.time()))

    @property
    def is_liquid(self) -> bool:
        """Token a-t-il une liquidité suffisante"""
        if not self.liquidity_usd:
            return self.volume_24h_usd > 10000  # Fallback sur volume
        return self.liquidity_usd > 50000

    @property
    def volatility_level(self) -> str:
        """Niveau de volatilité"""
        abs_change = abs(self.price_change_24h)
        if abs_change < 5:
            return "low"
        elif abs_change < 15:
            return "medium"
        elif abs_change < 30:
            return "high"
        else:
            return "extreme"

    @property
    def trend(self) -> str:
        """Tendance du prix"""
        if self.price_change_24h > 2:
            return "bullish"
        elif self.price_change_24h < -2:
            return "bearish"
        else:
            return "neutral"

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire pour API/JSON"""
        return {
            'token_mint': self.token_mint,
            'price_usd': self.price_usd,
            'price_sol': self.price_sol,
            'volume_24h_usd': self.volume_24h_usd,
            'market_cap_usd': self.market_cap_usd,
            'liquidity_usd': self.liquidity_usd,
            'price_change_24h': self.price_change_24h,
            'price_change_1h': self.price_change_1h,
            'fdv': self.fdv,
            'source': self.source,
            'updated_at': self.updated_at,
            'is_liquid': self.is_liquid,
            'volatility_level': self.volatility_level,
            'trend': self.trend
        }


# Fonctions utilitaires pour le trading

def validate_trade_amount(amount_sol: float, max_amount: float = 100.0) -> bool:
    """Valide un montant de trade"""
    return 0.001 <= amount_sol <= max_amount


def calculate_slippage_tolerance(amount_sol: float, volatility: str) -> float:
    """Calcule la tolérance de slippage recommandée"""
    base_slippage = 0.5  # 0.5% par défaut
    
    # Ajustement selon le montant
    if amount_sol > 10:
        base_slippage += 0.3
    elif amount_sol > 5:
        base_slippage += 0.1
    
    # Ajustement selon la volatilité
    volatility_multipliers = {
        "low": 1.0,
        "medium": 1.5,
        "high": 2.0,
        "extreme": 3.0
    }
    
    return base_slippage * volatility_multipliers.get(volatility, 1.0)


def estimate_trade_fee(amount_sol: float, dex: str = "jupiter") -> float:
    """Estime les frais de transaction"""
    # Frais de base Solana
    base_fee = 0.000005  # 5000 lamports
    
    # Frais DEX (en pourcentage)
    dex_fees = {
        "jupiter": 0.0025,  # 0.25%
        "raydium": 0.003,   # 0.3%
        "orca": 0.003,      # 0.3%
        "serum": 0.0022     # 0.22%
    }
    
    dex_fee_rate = dex_fees.get(dex, 0.003)
    dex_fee = amount_sol * dex_fee_rate
    
    return base_fee + dex_fee


def get_recommended_dex(token_mint: str, amount_sol: float) -> str:
    """Recommande le meilleur DEX pour un trade"""
    # Logique de recommandation simplifiée
    # En réalité, cela devrait comparer les prix en temps réel
    
    if amount_sol > 50:
        return "jupiter"  # Meilleur routing pour gros montants
    elif amount_sol > 10:
        return "raydium"  # Bon compromis
    else:
        return "orca"     # Efficace pour petits montants


def create_trade_order_id() -> str:
    """Crée un ID unique pour un ordre de trade"""
    import uuid
    return f"trade_{int(time.time())}_{str(uuid.uuid4())[:8]}"


def create_quote_id() -> str:
    """Crée un ID unique pour un devis"""
    import uuid
    return f"quote_{int(time.time())}_{str(uuid.uuid4())[:8]}"


# Export des classes principales
__all__ = [
    'TradeType', 'TradeStatus', 'SlippageLevel',
    'TradingSettings', 'TradeQuote', 'TradeOrder', 'TradingPortfolio', 'MarketData',
    'validate_trade_amount', 'calculate_slippage_tolerance', 'estimate_trade_fee',
    'get_recommended_dex', 'create_trade_order_id', 'create_quote_id'
]