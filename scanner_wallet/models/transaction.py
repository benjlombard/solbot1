
#!/usr/bin/env python3
"""
Modèles de données pour les transactions Solana
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Union
from datetime import datetime
import time
from enum import Enum


class TransactionType(Enum):
    """Types de transactions supportés"""
    BUY = "buy"
    SELL = "sell"
    TRANSFER = "transfer"
    TRANSFER_IN = "transfer_in"
    TRANSFER_OUT = "transfer_out"
    SWAP = "swap"
    STAKE = "stake"
    UNSTAKE = "unstake"
    LIQUIDITY_ADD = "liquidity_add"
    LIQUIDITY_REMOVE = "liquidity_remove"
    OTHER = "other"


class TransactionStatus(Enum):
    """Statuts de transactions"""
    SUCCESS = "success"
    FAILED = "failed"
    PENDING = "pending"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass
class Transaction:
    """Modèle principal pour une transaction Solana"""
    signature: str
    wallet_address: str
    slot: int
    block_time: Optional[int] = None
    amount: float = 0.0  # Changement SOL
    fee: float = 0.0
    status: TransactionStatus = TransactionStatus.SUCCESS
    
    # Données token
    token_mint: Optional[str] = None
    token_symbol: Optional[str] = None
    token_name: Optional[str] = None
    token_amount: float = 0.0
    price_per_token: float = 0.0
    
    # Classification
    transaction_type: TransactionType = TransactionType.OTHER
    is_token_transaction: bool = False
    is_large_token_amount: bool = False
    
    # Métadonnées de détection
    detection_delay: float = 0.0
    wallet_priority_at_detection: float = 1.0
    scan_cycle_id: Optional[str] = None
    source: str = "unknown"
    
    # Timestamps
    created_at: int = field(default_factory=lambda: int(time.time()))
    updated_at: int = field(default_factory=lambda: int(time.time()))

    def __post_init__(self):
        """Validation après initialisation"""
        if not validate_transaction_signature(self.signature):
            raise ValueError(f"Invalid transaction signature format: {self.signature}")
        
        if not self.wallet_address or len(self.wallet_address) != 44:
            raise ValueError("Invalid wallet address format")
        
        # Convertir les enums si nécessaire
        if isinstance(self.transaction_type, str):
            try:
                self.transaction_type = TransactionType(self.transaction_type)
            except ValueError:
                self.transaction_type = TransactionType.OTHER
        
        if isinstance(self.status, str):
            try:
                self.status = TransactionStatus(self.status)
            except ValueError:
                self.status = TransactionStatus.SUCCESS

    @property
    def signature_short(self) -> str:
        """Version courte de la signature"""
        return f"{self.signature[:8]}...{self.signature[-8:]}"

    @property
    def wallet_short(self) -> str:
        """Version courte de l'adresse wallet"""
        return f"{self.wallet_address[:6]}...{self.wallet_address[-6:]}"

    @property
    def mint_short(self) -> Optional[str]:
        """Version courte du mint address"""
        if not self.token_mint:
            return None
        return f"{self.token_mint[:6]}...{self.token_mint[-6:]}"

    @property
    def age_hours(self) -> float:
        """Âge de la transaction en heures"""
        if not self.block_time:
            return 0
        return (int(time.time()) - self.block_time) / 3600

    @property
    def is_recent(self) -> bool:
        """Transaction récente (< 24h)"""
        return self.age_hours < 24

    @property
    def is_buy_transaction(self) -> bool:
        """Est-ce un achat de token"""
        return self.transaction_type == TransactionType.BUY

    @property
    def is_sell_transaction(self) -> bool:
        """Est-ce une vente de token"""
        return self.transaction_type == TransactionType.SELL

    @property
    def is_transfer_transaction(self) -> bool:
        """Est-ce un transfert"""
        return self.transaction_type in [
            TransactionType.TRANSFER,
            TransactionType.TRANSFER_IN,
            TransactionType.TRANSFER_OUT
        ]

    @property
    def net_sol_change(self) -> float:
        """Changement net en SOL (incluant les frais)"""
        return self.amount - self.fee

    @property
    def total_usd_value(self) -> Optional[float]:
        """Valeur USD totale si prix disponible"""
        if self.price_per_token <= 0 or self.token_amount <= 0:
            return None
        return self.token_amount * self.price_per_token

    @property
    def profit_loss_sol(self) -> float:
        """P&L en SOL pour cette transaction"""
        if self.is_buy_transaction:
            return -abs(self.amount)  # Dépense
        elif self.is_sell_transaction:
            return abs(self.amount)   # Gain
        else:
            return self.amount        # Autre (peut être positif ou négatif)

    def get_display_amount(self, decimals: Optional[int] = None) -> float:
        """Montant token formaté pour affichage"""
        if not self.is_token_transaction:
            return 0.0
        
        if decimals is None:
            decimals = 9  # Défaut Solana
        
        # Si le montant semble déjà formaté
        if self.token_amount < 1000:
            return self.token_amount
        
        # Sinon, le diviser par 10^decimals
        return self.token_amount / (10 ** decimals)

    def calculate_detection_delay(self, scan_time: Optional[int] = None) -> float:
        """Calcule le délai de détection"""
        if not self.block_time:
            return 0.0
        
        scan_timestamp = scan_time or int(time.time())
        self.detection_delay = max(0, scan_timestamp - self.block_time)
        return self.detection_delay

    def get_transaction_icon(self) -> str:
        """Retourne l'icône appropriée pour le type de transaction"""
        icons = {
            TransactionType.BUY: "🟢",
            TransactionType.SELL: "🔴",
            TransactionType.TRANSFER: "🔵",
            TransactionType.TRANSFER_IN: "🟢",
            TransactionType.TRANSFER_OUT: "🟡",
            TransactionType.SWAP: "🟣",
            TransactionType.STAKE: "🔷",
            TransactionType.UNSTAKE: "🔶",
            TransactionType.LIQUIDITY_ADD: "💧",
            TransactionType.LIQUIDITY_REMOVE: "🔥",
            TransactionType.OTHER: "⚪"
        }
        return icons.get(self.transaction_type, "⚪")

    def get_status_icon(self) -> str:
        """Retourne l'icône appropriée pour le statut"""
        icons = {
            TransactionStatus.SUCCESS: "✅",
            TransactionStatus.FAILED: "❌",
            TransactionStatus.PENDING: "⏳",
            TransactionStatus.TIMEOUT: "⏰",
            TransactionStatus.CANCELLED: "🚫"
        }
        return icons.get(self.status, "❓")

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire pour API/JSON"""
        return {
            'signature': self.signature,
            'signature_short': self.signature_short,
            'wallet_address': self.wallet_address,
            'wallet_short': self.wallet_short,
            'slot': self.slot,
            'block_time': self.block_time,
            'age_hours': round(self.age_hours, 1),
            'is_recent': self.is_recent,
            'amount': round(self.amount, 6),
            'fee': round(self.fee, 6),
            'net_sol_change': round(self.net_sol_change, 6),
            'status': self.status.value,
            'status_icon': self.get_status_icon(),
            
            # Données token
            'token_mint': self.token_mint,
            'mint_short': self.mint_short,
            'token_symbol': self.token_symbol,
            'token_name': self.token_name,
            'token_amount': self.token_amount,
            'display_amount': round(self.get_display_amount(), 6),
            'price_per_token': self.price_per_token,
            'total_usd_value': self.total_usd_value,
            
            # Classification
            'transaction_type': self.transaction_type.value,
            'transaction_icon': self.get_transaction_icon(),
            'is_token_transaction': self.is_token_transaction,
            'is_large_token_amount': self.is_large_token_amount,
            'is_buy_transaction': self.is_buy_transaction,
            'is_sell_transaction': self.is_sell_transaction,
            'is_transfer_transaction': self.is_transfer_transaction,
            'profit_loss_sol': round(self.profit_loss_sol, 6),
            
            # Métadonnées
            'detection_delay': round(self.detection_delay, 1),
            'wallet_priority_at_detection': self.wallet_priority_at_detection,
            'scan_cycle_id': self.scan_cycle_id,
            'source': self.source,
            'created_at': self.created_at,
            'updated_at': self.updated_at
        }


@dataclass
class BalanceChange:
    """Modèle pour un changement de balance détecté"""
    wallet_address: str
    token_mint: str
    ata_pubkey: str
    pre_balance: float
    post_balance: float
    balance_change: float
    transaction_signature: Optional[str] = None
    block_time: Optional[int] = None
    decimals: int = 9
    
    # Métadonnées du token
    token_symbol: Optional[str] = None
    token_name: Optional[str] = None
    
    # Classification automatique
    change_type: Optional[TransactionType] = None
    confidence: float = 1.0
    detected_at: int = field(default_factory=lambda: int(time.time()))

    @property
    def wallet_short(self) -> str:
        """Version courte de l'adresse wallet"""
        return f"{self.wallet_address[:6]}...{self.wallet_address[-6:]}"

    @property
    def mint_short(self) -> str:
        """Version courte du mint address"""
        return f"{self.token_mint[:6]}...{self.token_mint[-6:]}"

    @property
    def display_pre_balance(self) -> float:
        """Balance pré formatée"""
        return self.pre_balance / (10 ** self.decimals) if self.pre_balance > 1 else self.pre_balance

    @property
    def display_post_balance(self) -> float:
        """Balance post formatée"""
        return self.post_balance / (10 ** self.decimals) if self.post_balance > 1 else self.post_balance

    @property
    def display_change(self) -> float:
        """Changement formaté"""
        return self.balance_change / (10 ** self.decimals) if abs(self.balance_change) > 1 else self.balance_change

    @property
    def is_increase(self) -> bool:
        """La balance a-t-elle augmenté"""
        return self.balance_change > 0

    @property
    def is_decrease(self) -> bool:
        """La balance a-t-elle diminué"""
        return self.balance_change < 0

    @property
    def is_significant_change(self) -> bool:
        """Le changement est-il significatif"""
        return abs(self.display_change) > 0.000001

    def classify_change_type(self, sol_change: float = 0.0) -> TransactionType:
        """Classifie automatiquement le type de changement"""
        if not self.is_significant_change:
            return TransactionType.OTHER
        
        SOL_THRESHOLD = 0.001
        
        if self.is_increase:
            if sol_change < -SOL_THRESHOLD:
                return TransactionType.BUY
            else:
                return TransactionType.TRANSFER_IN
        else:
            if sol_change > SOL_THRESHOLD:
                return TransactionType.SELL
            else:
                return TransactionType.TRANSFER_OUT

    def to_transaction(self, sol_change: float = 0.0, fee: float = 0.0) -> Transaction:
        """Convertit en objet Transaction"""
        change_type = self.classify_change_type(sol_change)
        
        return Transaction(
            signature=self.transaction_signature or "unknown",
            wallet_address=self.wallet_address,
            slot=0,  # À remplir si disponible
            block_time=self.block_time,
            amount=sol_change,
            fee=fee,
            status=TransactionStatus.SUCCESS,
            
            token_mint=self.token_mint,
            token_symbol=self.token_symbol,
            token_name=self.token_name,
            token_amount=abs(self.display_change),
            
            transaction_type=change_type,
            is_token_transaction=True,
            is_large_token_amount=abs(self.display_change) > 1000,
            
            source="balance_change"
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire pour API/JSON"""
        return {
            'wallet_address': self.wallet_address,
            'wallet_short': self.wallet_short,
            'token_mint': self.token_mint,
            'mint_short': self.mint_short,
            'ata_pubkey': self.ata_pubkey,
            'pre_balance': self.pre_balance,
            'post_balance': self.post_balance,
            'balance_change': self.balance_change,
            'display_pre_balance': round(self.display_pre_balance, 6),
            'display_post_balance': round(self.display_post_balance, 6),
            'display_change': round(self.display_change, 6),
            'is_increase': self.is_increase,
            'is_decrease': self.is_decrease,
            'is_significant_change': self.is_significant_change,
            'transaction_signature': self.transaction_signature,
            'block_time': self.block_time,
            'decimals': self.decimals,
            'token_symbol': self.token_symbol,
            'token_name': self.token_name,
            'change_type': self.change_type.value if self.change_type else None,
            'confidence': self.confidence,
            'detected_at': self.detected_at
        }


# Fonctions utilitaires pour les transactions

def validate_transaction_signature(signature: str) -> bool:
    """Valide une signature de transaction Solana"""
    if not isinstance(signature, str) or not signature:
        return False
    
    # Validation Base58 basique
    try:
        import base58
        decoded = base58.b58decode(signature)
        return len(decoded) == 64
    except:
        
        return False


def classify_transaction_from_amounts(token_change: float, sol_change: float, 
                                    threshold: float = 0.001) -> TransactionType:
    """Classifie une transaction basée sur les changements de montants"""
    if abs(token_change) < 0.000001:
        return TransactionType.OTHER
    
    if token_change > 0:  # Réception de tokens
        if sol_change < -threshold:
            return TransactionType.BUY
        else:
            return TransactionType.TRANSFER_IN
    else:  # Envoi de tokens
        if sol_change > threshold:
            return TransactionType.SELL
        else:
            return TransactionType.TRANSFER_OUT


def calculate_transaction_importance(transaction: Transaction) -> float:
    """Calcule un score d'importance pour une transaction"""
    score = 1.0
    
    # Bonus pour gros montants SOL
    if abs(transaction.amount) > 1.0:
        score += min(abs(transaction.amount), 5.0)
    
    # Bonus pour gros montants token
    if transaction.is_large_token_amount:
        score += 3.0
    
    # Bonus pour activité de trading
    if transaction.is_buy_transaction or transaction.is_sell_transaction:
        score += 2.0
    
    # Bonus pour tokens avec prix
    if transaction.price_per_token > 0:
        score += 1.0
        
        # Bonus pour valeur USD élevée
        if transaction.total_usd_value and transaction.total_usd_value > 100:
            score += min(transaction.total_usd_value / 100, 3.0)
    
    # Bonus pour détection rapide
    if transaction.detection_delay < 60:  # < 1 minute
        score += 1.0
    elif transaction.detection_delay < 300:  # < 5 minutes
        score += 0.5
    
    # Malus pour transactions échouées
    if transaction.status != TransactionStatus.SUCCESS:
        score *= 0.5
    
    return min(10.0, score)


def group_transactions_by_type(transactions: List[Transaction]) -> Dict[TransactionType, List[Transaction]]:
    """Groupe les transactions par type"""
    groups = {}
    for tx in transactions:
        if tx.transaction_type not in groups:
            groups[tx.transaction_type] = []
        groups[tx.transaction_type].append(tx)
    return groups


def calculate_portfolio_pnl(transactions: List[Transaction]) -> Dict[str, float]:
    """Calcule le P&L par token à partir des transactions"""
    pnl_by_token = {}
    
    for tx in transactions:
        if not tx.is_token_transaction or not tx.token_mint:
            continue
        
        if tx.token_mint not in pnl_by_token:
            pnl_by_token[tx.token_mint] = 0.0
        
        pnl_by_token[tx.token_mint] += tx.profit_loss_sol
    
    return pnl_by_token