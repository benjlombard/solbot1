
#!/usr/bin/env python3
"""
Modèles de données pour les wallets Solana
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from datetime import datetime
import time


@dataclass
class WalletPriority:
    """Modèle pour les priorités dynamiques des wallets"""
    wallet_address: str
    priority_score: float = 1.0
    last_scan_time: int = 0
    scan_count_1h: int = 0
    scan_count_24h: int = 0
    activity_score: float = 0.0
    volume_score_1h: float = 0.0
    new_tokens_score_1h: int = 0
    total_scans: int = 0
    avg_scan_duration: float = 0.0
    last_activity_detected: int = 0
    consecutive_empty_scans: int = 0
    best_priority_ever: float = 1.0
    worst_priority_ever: float = 1.0
    priority_history: Optional[str] = None  # JSON string
    updated_at: int = field(default_factory=lambda: int(time.time()))
    created_at: int = field(default_factory=lambda: int(time.time()))

    def __post_init__(self):
        """Validation après initialisation"""
        if not self.wallet_address or len(self.wallet_address) != 44:
            raise ValueError("Invalid wallet address format")
        
        if not 0.1 <= self.priority_score <= 10.0:
            raise ValueError("Priority score must be between 0.1 and 10.0")

    @property
    def wallet_short(self) -> str:
        """Version courte de l'adresse wallet"""
        return f"{self.wallet_address[:8]}...{self.wallet_address[-8:]}"

    @property
    def priority_category(self) -> str:
        """Catégorie de priorité basée sur le score"""
        if self.priority_score >= 4.0:
            return "high"
        elif self.priority_score >= 2.0:
            return "medium"
        else:
            return "low"

    @property
    def scan_interval_seconds(self) -> int:
        """Intervalle de scan recommandé en secondes"""
        if self.priority_score >= 4.0:
            return 30  # Haute priorité: 30s
        elif self.priority_score >= 2.0:
            return 90  # Moyenne: 1.5min
        else:
            return 180  # Basse: 3min

    @property
    def seconds_since_scan(self) -> int:
        """Temps écoulé depuis le dernier scan"""
        return int(time.time()) - self.last_scan_time

    @property
    def is_ready_for_scan(self) -> bool:
        """Détermine si le wallet est prêt pour un scan"""
        return self.seconds_since_scan >= self.scan_interval_seconds

    @property
    def next_scan_in(self) -> int:
        """Temps restant avant le prochain scan (en secondes)"""
        return max(0, self.scan_interval_seconds - self.seconds_since_scan)

    def update_priority(self, discoveries: int, transactions: int, scan_duration: float) -> float:
        """Met à jour la priorité basée sur les résultats du scan"""
        old_score = self.priority_score
        
        # Bonus pour activité
        activity_bonus = min(transactions * 0.3, 2.0)
        discovery_bonus = min(discoveries * 0.5, 1.5)
        
        # Malus pour lenteur
        efficiency_penalty = max(0, (scan_duration - 45) * 0.02)
        
        if transactions > 0 or discoveries > 0:
            # Activité détectée
            new_score = old_score + activity_bonus + discovery_bonus - efficiency_penalty
            self.consecutive_empty_scans = 0
        else:
            # Scan vide
            decay_factor = 0.95
            empty_penalty = min(self.consecutive_empty_scans * 0.1, 1.0)
            new_score = max(0.5, old_score * decay_factor - empty_penalty)
            self.consecutive_empty_scans += 1
        
        # Limiter dans la plage
        self.priority_score = max(0.1, min(10.0, new_score))
        
        # Mettre à jour les extremums
        self.best_priority_ever = max(self.best_priority_ever, self.priority_score)
        self.worst_priority_ever = min(self.worst_priority_ever, self.priority_score)
        
        # Mettre à jour les stats
        self.last_scan_time = int(time.time())
        self.total_scans += 1
        
        # Calculer nouvelle durée moyenne
        if self.total_scans == 1:
            self.avg_scan_duration = scan_duration
        else:
            self.avg_scan_duration = (self.avg_scan_duration * (self.total_scans - 1) + scan_duration) / self.total_scans
        
        # Mettre à jour activité si nécessaire
        if transactions > 0:
            self.activity_score = self.activity_score * 0.8 + float(transactions)
            self.last_activity_detected = int(time.time())
        
        self.updated_at = int(time.time())
        
        return self.priority_score - old_score

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire pour API/JSON"""
        return {
            'wallet_address': self.wallet_address,
            'wallet_short': self.wallet_short,
            'priority_score': round(self.priority_score, 2),
            'priority_category': self.priority_category,
            'last_scan_time': self.last_scan_time,
            'seconds_since_scan': self.seconds_since_scan,
            'is_ready_for_scan': self.is_ready_for_scan,
            'next_scan_in': self.next_scan_in,
            'scan_interval_seconds': self.scan_interval_seconds,
            'total_scans': self.total_scans,
            'consecutive_empty_scans': self.consecutive_empty_scans,
            'activity_score': round(self.activity_score, 2),
            'avg_scan_duration': round(self.avg_scan_duration, 1),
            'best_priority_ever': round(self.best_priority_ever, 2),
            'worst_priority_ever': round(self.worst_priority_ever, 2),
            'last_activity_detected': self.last_activity_detected
        }


@dataclass
class WalletStats:
    """Statistiques globales d'un wallet"""
    wallet_address: str
    balance_sol: float = 0.0
    total_transactions: int = 0
    total_volume: float = 0.0
    pnl: float = 0.0
    largest_transaction: float = 0.0
    token_accounts_count: int = 0
    active_tokens_count: int = 0
    new_tokens_24h: int = 0
    large_transactions_24h: int = 0
    updated_at: int = field(default_factory=lambda: int(time.time()))

    @property
    def wallet_short(self) -> str:
        """Version courte de l'adresse wallet"""
        return f"{self.wallet_address[:8]}...{self.wallet_address[-8:]}"

    @property
    def avg_transaction_size(self) -> float:
        """Taille moyenne des transactions"""
        if self.total_transactions == 0:
            return 0.0
        return self.total_volume / self.total_transactions

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire pour API/JSON"""
        return {
            'wallet_address': self.wallet_address,
            'wallet_short': self.wallet_short,
            'balance_sol': round(self.balance_sol, 4),
            'total_transactions': self.total_transactions,
            'total_volume': round(self.total_volume, 4),
            'pnl': round(self.pnl, 4),
            'largest_transaction': round(self.largest_transaction, 4),
            'avg_transaction_size': round(self.avg_transaction_size, 4),
            'token_accounts_count': self.token_accounts_count,
            'active_tokens_count': self.active_tokens_count,
            'new_tokens_24h': self.new_tokens_24h,
            'large_transactions_24h': self.large_transactions_24h,
            'updated_at': self.updated_at
        }


@dataclass
class WalletActivityMetrics:
    """Métriques d'activité détaillées d'un wallet"""
    wallet_address: str
    timestamp: int
    period_minutes: int = 15
    new_transactions_count: int = 0
    volume_sol: float = 0.0
    new_token_accounts: int = 0
    scan_duration: float = 0.0
    discoveries_count: int = 0
    balance_changes_count: int = 0
    rpc_requests_made: int = 0
    errors_count: int = 0
    efficiency_score: float = 0.0

    @property
    def wallet_short(self) -> str:
        """Version courte de l'adresse wallet"""
        return f"{self.wallet_address[:8]}...{self.wallet_address[-8:]}"

    @property
    def rps(self) -> float:
        """Requêtes par seconde"""
        if self.scan_duration <= 0:
            return 0.0
        return self.rpc_requests_made / self.scan_duration

    @property
    def discoveries_per_rpc(self) -> float:
        """Découvertes par requête RPC"""
        if self.rpc_requests_made == 0:
            return 0.0
        return (self.discoveries_count + self.balance_changes_count) / self.rpc_requests_made

    def calculate_efficiency(self) -> float:
        """Calcule le score d'efficacité"""
        if self.rpc_requests_made == 0:
            return 0.0
        
        # Efficacité basée sur les découvertes par RPC
        base_efficiency = (self.discoveries_count + self.balance_changes_count) / self.rpc_requests_made * 100
        
        # Bonus pour volume détecté
        volume_bonus = min(self.volume_sol * 10, 20)
        
        # Malus pour erreurs
        error_penalty = self.errors_count * 5
        
        self.efficiency_score = max(0, base_efficiency + volume_bonus - error_penalty)
        return self.efficiency_score

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire pour API/JSON"""
        return {
            'wallet_address': self.wallet_address,
            'wallet_short': self.wallet_short,
            'timestamp': self.timestamp,
            'period_minutes': self.period_minutes,
            'new_transactions_count': self.new_transactions_count,
            'volume_sol': round(self.volume_sol, 4),
            'new_token_accounts': self.new_token_accounts,
            'scan_duration': round(self.scan_duration, 2),
            'discoveries_count': self.discoveries_count,
            'balance_changes_count': self.balance_changes_count,
            'rpc_requests_made': self.rpc_requests_made,
            'errors_count': self.errors_count,
            'efficiency_score': round(self.efficiency_score, 1),
            'rps': round(self.rps, 2),
            'discoveries_per_rpc': round(self.discoveries_per_rpc, 3)
        }


@dataclass
class ScanHistory:
    """Historique des scans effectués"""
    id: Optional[int]
    wallet_address: str
    scan_type: str
    total_accounts: int
    new_accounts: int
    scan_duration: float
    completed_at: int
    priority_score_before: float = 1.0
    priority_score_after: float = 1.0
    rpc_requests_count: int = 0
    efficiency_score: float = 0.0
    activity_detected: bool = False
    notes: Optional[str] = None

    @property
    def wallet_short(self) -> str:
        """Version courte de l'adresse wallet"""
        return f"{self.wallet_address[:8]}...{self.wallet_address[-8:]}"

    @property
    def priority_change(self) -> float:
        """Changement de priorité"""
        return self.priority_score_after - self.priority_score_before

    @property
    def change_direction(self) -> str:
        """Direction du changement de priorité"""
        change = self.priority_change
        if change > 0.1:
            return "up"
        elif change < -0.1:
            return "down"
        else:
            return "stable"

    @property
    def discovery_rate(self) -> float:
        """Taux de découverte (nouveaux comptes / total)"""
        if self.total_accounts == 0:
            return 0.0
        return (self.new_accounts / self.total_accounts) * 100

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire pour API/JSON"""
        return {
            'id': self.id,
            'wallet_address': self.wallet_address,
            'wallet_short': self.wallet_short,
            'scan_type': self.scan_type,
            'total_accounts': self.total_accounts,
            'new_accounts': self.new_accounts,
            'scan_duration': round(self.scan_duration, 2),
            'completed_at': self.completed_at,
            'priority_score_before': round(self.priority_score_before, 2),
            'priority_score_after': round(self.priority_score_after, 2),
            'priority_change': round(self.priority_change, 2),
            'change_direction': self.change_direction,
            'rpc_requests_count': self.rpc_requests_count,
            'efficiency_score': round(self.efficiency_score, 1),
            'discovery_rate': round(self.discovery_rate, 1),
            'activity_detected': self.activity_detected,
            'notes': self.notes
        }


# Fonctions utilitaires pour les wallets
def format_wallet_address(address: str, length: int = 8) -> str:
    """Formate une adresse de wallet pour l'affichage"""
    if not address or len(address) < (2 * length + 3):
        return address
    return f"{address[:length]}...{address[-length:]}"


def calculate_wallet_score(priority: WalletPriority, stats: WalletStats) -> float:
    """Calcule un score global pour un wallet"""
    base_score = priority.priority_score
    
    # Bonus pour activité récente
    activity_bonus = min(priority.activity_score * 0.1, 1.0)
    
    # Bonus pour volume
    volume_bonus = min(stats.total_volume * 0.01, 1.0)
    
    # Bonus pour diversité
    diversity_bonus = min(stats.active_tokens_count * 0.05, 1.0)
    
    # Malus pour inactivité
    time_since_activity = int(time.time()) - priority.last_activity_detected
    inactivity_penalty = min(time_since_activity / 86400 * 0.1, 2.0)  # 0.1 par jour
    
    final_score = base_score + activity_bonus + volume_bonus + diversity_bonus - inactivity_penalty
    return max(0.1, min(10.0, final_score))