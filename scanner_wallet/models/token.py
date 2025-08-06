
#!/usr/bin/env python3
"""
Modèles de données pour les tokens Solana
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from datetime import datetime
import time


@dataclass
class Token:
    """Métadonnées d'un token Solana"""
    address: str  # Mint address
    symbol: str = 'UNKNOWN'
    name: str = 'Unknown Token'
    decimals: int = 9
    price_usd: Optional[float] = None
    logo_uri: Optional[str] = None
    coingecko_id: Optional[str] = None
    is_verified: bool = False
    market_cap: Optional[float] = None
    volume_24h: Optional[float] = None
    price_change_24h: Optional[float] = None
    last_price_update: Optional[int] = None
    metadata_source: str = 'unknown'
    updated_at: int = field(default_factory=lambda: int(time.time()))

    def __post_init__(self):
        """Validation après initialisation"""
        if not self.address or len(self.address) != 44:
            raise ValueError("Invalid token mint address format")
        
        if self.decimals < 0 or self.decimals > 18:
            raise ValueError("Decimals must be between 0 and 18")

    @property
    def mint_short(self) -> str:
        """Version courte du mint address"""
        return f"{self.address[:6]}...{self.address[-6:]}"

    @property
    def is_stablecoin(self) -> bool:
        """Détermine si c'est un stablecoin"""
        stablecoin_symbols = ['USDC', 'USDT', 'BUSD', 'DAI', 'FRAX', 'UST']
        return self.symbol.upper() in stablecoin_symbols

    @property
    def is_wrapped_sol(self) -> bool:
        """Détermine si c'est du SOL wrappé"""
        return self.address == "So11111111111111111111111111111111111111112"

    @property
    def price_age_hours(self) -> float:
        """Âge du prix en heures"""
        if not self.last_price_update:
            return 999999
        return (int(time.time()) - self.last_price_update) / 3600

    @property
    def is_price_fresh(self) -> bool:
        """Prix est-il récent (< 1h)"""
        return self.price_age_hours < 1.0

    def format_amount(self, raw_amount: float, compact: bool = False) -> str:
        """Formate un montant de ce token"""
        if raw_amount == 0:
            return "0"
        
        # Convertir selon les décimales
        display_amount = raw_amount / (10 ** self.decimals) if raw_amount > 1 else raw_amount
        
        if compact and display_amount >= 1000:
            if display_amount >= 1_000_000:
                return f"{display_amount / 1_000_000:.2f}M"
            elif display_amount >= 1000:
                return f"{display_amount / 1000:.2f}K"
        
        # Adaptation des décimales selon le montant
        if display_amount < 0.001:
            return f"{display_amount:.8f}"
        elif display_amount < 1:
            return f"{display_amount:.6f}"
        else:
            return f"{display_amount:,.4f}"

    def get_usd_value(self, token_amount: float) -> Optional[float]:
        """Calcule la valeur USD d'un montant de token"""
        if not self.price_usd or not self.is_price_fresh:
            return None
        
        display_amount = token_amount / (10 ** self.decimals) if token_amount > 1 else token_amount
        return display_amount * self.price_usd

    def update_price(self, new_price: float, source: str = 'unknown') -> bool:
        """Met à jour le prix du token"""
        try:
            old_price = self.price_usd
            self.price_usd = new_price
            self.last_price_update = int(time.time())
            self.metadata_source = source
            self.updated_at = int(time.time())
            
            # Calculer le changement 24h si on a l'ancien prix
            if old_price and old_price > 0:
                self.price_change_24h = ((new_price - old_price) / old_price) * 100
            
            return True
        except Exception:
            return False

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire pour API/JSON"""
        return {
            'address': self.address,
            'mint_short': self.mint_short,
            'symbol': self.symbol,
            'name': self.name,
            'decimals': self.decimals,
            'price_usd': self.price_usd,
            'logo_uri': self.logo_uri,
            'coingecko_id': self.coingecko_id,
            'is_verified': self.is_verified,
            'is_stablecoin': self.is_stablecoin,
            'is_wrapped_sol': self.is_wrapped_sol,
            'market_cap': self.market_cap,
            'volume_24h': self.volume_24h,
            'price_change_24h': self.price_change_24h,
            'last_price_update': self.last_price_update,
            'price_age_hours': round(self.price_age_hours, 1),
            'is_price_fresh': self.is_price_fresh,
            'metadata_source': self.metadata_source,
            'updated_at': self.updated_at
        }


@dataclass
class TokenAccount:
    """Compte de token associé (ATA) d'un wallet"""
    wallet_address: str
    ata_pubkey: str
    token_mint: str
    balance: float = 0.0
    decimals: int = 9
    first_seen: int = field(default_factory=lambda: int(time.time()))
    last_updated: int = field(default_factory=lambda: int(time.time()))
    last_scanned: Optional[int] = None
    is_active: bool = True
    scan_priority: int = 1
    activity_score: float = 0.0
    last_activity_time: Optional[int] = None
    total_transactions: int = 0

    def __post_init__(self):
        """Validation après initialisation"""
        if not self.wallet_address or len(self.wallet_address) != 44:
            raise ValueError("Invalid wallet address format")
        
        if not self.ata_pubkey or len(self.ata_pubkey) != 44:
            raise ValueError("Invalid ATA pubkey format")
        
        if not self.token_mint or len(self.token_mint) != 44:
            raise ValueError("Invalid token mint format")

    @property
    def wallet_short(self) -> str:
        """Version courte de l'adresse wallet"""
        return f"{self.wallet_address[:6]}...{self.wallet_address[-6:]}"

    @property
    def ata_short(self) -> str:
        """Version courte de l'ATA pubkey"""
        return f"{self.ata_pubkey[:6]}...{self.ata_pubkey[-6:]}"

    @property
    def mint_short(self) -> str:
        """Version courte du mint address"""
        return f"{self.token_mint[:6]}...{self.token_mint[-6:]}"

    @property
    def display_balance(self) -> float:
        """Balance formatée selon les décimales"""
        return self.balance / (10 ** self.decimals) if self.balance > 1 else self.balance

    @property
    def has_balance(self) -> bool:
        """A une balance non-nulle"""
        return self.balance > 0

    @property
    def hours_since_scan(self) -> float:
        """Heures depuis le dernier scan"""
        if not self.last_scanned:
            return 999999
        return (int(time.time()) - self.last_scanned) / 3600

    @property
    def needs_scan(self) -> bool:
        """Détermine si le compte a besoin d'être scanné"""
        # Jamais scanné
        if not self.last_scanned:
            return True
        
        # Haute priorité (nouveaux comptes)
        if self.scan_priority >= 3:
            return True
        
        # Plus de 30 minutes
        if self.hours_since_scan > 0.5:
            return True
        
        return False

    @property
    def priority_label(self) -> str:
        """Label de priorité"""
        if self.scan_priority >= 4:
            return "CRITICAL"
        elif self.scan_priority >= 3:
            return "HIGH"
        elif self.scan_priority >= 2:
            return "MEDIUM"
        else:
            return "LOW"

    def update_balance(self, new_balance: float) -> float:
        """Met à jour la balance et retourne le changement"""
        old_balance = self.balance
        self.balance = new_balance
        self.last_updated = int(time.time())
        
        # Si la balance a changé, c'est une activité
        if abs(new_balance - old_balance) > 0.000001:
            self.last_activity_time = int(time.time())
            self.activity_score = min(self.activity_score + 1, 10)
            self.total_transactions += 1
        
        return new_balance - old_balance

    def mark_scanned(self) -> None:
        """Marque le compte comme scanné"""
        self.last_scanned = int(time.time())
        
        # Réduire progressivement la priorité si pas d'activité
        if self.scan_priority > 1:
            self.scan_priority = max(1, self.scan_priority - 1)

    def boost_priority(self, reason: str = "activity") -> None:
        """Augmente la priorité du compte"""
        if reason == "new_account":
            self.scan_priority = 5
        elif reason == "activity":
            self.scan_priority = min(self.scan_priority + 1, 4)
        elif reason == "large_balance":
            self.scan_priority = min(self.scan_priority + 2, 4)

    def deactivate(self) -> None:
        """Désactive le compte (balance nulle depuis longtemps)"""
        self.is_active = False
        self.scan_priority = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire pour API/JSON"""
        return {
            'wallet_address': self.wallet_address,
            'wallet_short': self.wallet_short,
            'ata_pubkey': self.ata_pubkey,
            'ata_short': self.ata_short,
            'token_mint': self.token_mint,
            'mint_short': self.mint_short,
            'balance': self.balance,
            'display_balance': round(self.display_balance, 6),
            'decimals': self.decimals,
            'has_balance': self.has_balance,
            'first_seen': self.first_seen,
            'last_updated': self.last_updated,
            'last_scanned': self.last_scanned,
            'hours_since_scan': round(self.hours_since_scan, 1),
            'is_active': self.is_active,
            'scan_priority': self.scan_priority,
            'priority_label': self.priority_label,
            'needs_scan': self.needs_scan,
            'activity_score': self.activity_score,
            'last_activity_time': self.last_activity_time,
            'total_transactions': self.total_transactions
        }


@dataclass
class TokenDiscovery:
    """Modèle pour une découverte de token"""
    token_mint: str
    wallet_address: str
    discovered_at: int
    ata_pubkey: str
    initial_balance: float
    decimals: int = 9
    symbol: Optional[str] = None
    name: Optional[str] = None
    discovery_method: str = "balance_scan"
    confidence_score: float = 1.0

    def __post_init__(self):
        """Génère des métadonnées par défaut si manquantes"""
        if not self.symbol:
            self.symbol = f"TOKEN_{self.token_mint[:6]}"
        
        if not self.name:
            self.name = f"Token {self.token_mint[:6]}"

    @property
    def age_hours(self) -> float:
        """Âge de la découverte en heures"""
        return (int(time.time()) - self.discovered_at) / 3600

    @property
    def is_recent(self) -> bool:
        """Découverte récente (< 24h)"""
        return self.age_hours < 24

    @property
    def display_balance(self) -> float:
        """Balance initiale formatée"""
        return self.initial_balance / (10 ** self.decimals) if self.initial_balance > 1 else self.initial_balance

    @property
    def wallet_short(self) -> str:
        """Version courte de l'adresse wallet"""
        return f"{self.wallet_address[:6]}...{self.wallet_address[-6:]}"

    @property
    def mint_short(self) -> str:
        """Version courte du mint address"""
        return f"{self.token_mint[:6]}...{self.token_mint[-6:]}"

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire pour API/JSON"""
        return {
            'token_mint': self.token_mint,
            'mint_short': self.mint_short,
            'wallet_address': self.wallet_address,
            'wallet_short': self.wallet_short,
            'discovered_at': self.discovered_at,
            'age_hours': round(self.age_hours, 1),
            'is_recent': self.is_recent,
            'ata_pubkey': self.ata_pubkey,
            'initial_balance': self.initial_balance,
            'display_balance': round(self.display_balance, 6),
            'decimals': self.decimals,
            'symbol': self.symbol,
            'name': self.name,
            'discovery_method': self.discovery_method,
            'confidence_score': self.confidence_score
        }


# Fonctions utilitaires pour les tokens

def validate_token_mint(mint_address: str) -> bool:
    """Valide une adresse de mint token Solana"""
    if not mint_address or len(mint_address) != 44:
        return False
    
    # Validation Base58 basique
    try:
        import base58
        decoded = base58.b58decode(mint_address)
        return len(decoded) == 32
    except:
        # Fallback sans base58
        import re
        base58_pattern = r'^[1-9A-HJ-NP-Za-km-z]{44}$'
        return bool(re.match(base58_pattern, mint_address))


def is_large_token_amount(amount: float, decimals: int) -> bool:
    """Détermine si un montant de token est considéré comme important"""
    # Montant brut important
    if amount >= 100000:
        return True
    
    # Selon les décimales
    if decimals <= 2 and amount >= 10:
        return True
    elif decimals <= 6 and amount >= 1000:
        return True
    elif decimals <= 9 and amount >= 10000:
        return True
    
    return False


def get_token_program_id(mint_address: str) -> str:
    """Retourne le Program ID approprié pour un token"""
    # Pour l'instant, retourne toujours le Token Program standard
    # Futur: Support Token-2022
    return "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"


def format_token_symbol(symbol: str) -> str:
    """Nettoie et formate un symbole de token"""
    if not symbol:
        return "UNKNOWN"
    
    # Nettoyer et limiter
    clean_symbol = symbol.upper().strip()
    
    # Remplacer les caractères invalides
    import re
    clean_symbol = re.sub(r'[^A-Z0-9_]', '', clean_symbol)
    
    # Limiter la longueur
    if len(clean_symbol) > 10:
        clean_symbol = clean_symbol[:10]
    
    return clean_symbol or "UNKNOWN"


def create_fallback_token_metadata(mint_address: str) -> Token:
    """Crée des métadonnées de fallback pour un token"""
    short_mint = mint_address[:6].upper()
    
    return Token(
        address=mint_address,
        symbol=f"TOKEN_{short_mint}",
        name=f"Token {short_mint}",
        decimals=9,
        metadata_source="fallback"
    )


def calculate_token_importance_score(token_account: TokenAccount, token_meta: Optional[Token] = None) -> float:
    """Calcule un score d'importance pour un token compte"""
    score = 0.0
    
    # Score basé sur la balance
    if token_account.has_balance:
        score += 3.0
        
        # Bonus pour grosse balance
        if token_account.display_balance > 1000:
            score += 2.0
        elif token_account.display_balance > 100:
            score += 1.0
    
    # Score basé sur l'activité
    score += min(token_account.activity_score * 0.5, 3.0)
    
    # Score basé sur le nombre de transactions
    score += min(token_account.total_transactions * 0.1, 2.0)
    
    # Bonus pour tokens vérifiés
    if token_meta and token_meta.is_verified:
        score += 1.0
    
    # Bonus pour stablecoins
    if token_meta and token_meta.is_stablecoin:
        score += 1.5
    
    # Malus pour ancienneté sans activité
    if token_account.last_activity_time:
        hours_inactive = (int(time.time()) - token_account.last_activity_time) / 3600
        if hours_inactive > 168:  # 1 semaine
            score -= min(hours_inactive / 168, 2.0)
    
    return max(0.0, min(10.0, score))


def get_token_risk_level(token: Token, token_account: TokenAccount) -> str:
    """Évalue le niveau de risque d'un token"""
    risk_score = 0
    
    # Facteurs de risque
    if not token.is_verified:
        risk_score += 2
    
    if not token.price_usd:
        risk_score += 1
    
    if token.market_cap and token.market_cap < 100000:  # < 100K market cap
        risk_score += 2
    
    if token_account.age_hours < 24:  # Nouveau token
        risk_score += 1
    
    if token.metadata_source == "fallback":
        risk_score += 2
    
    # Classification
    if risk_score >= 6:
        return "HIGH"
    elif risk_score >= 3:
        return "MEDIUM" 
    else:
        return "LOW"


def detect_potential_scam_tokens(tokens: List[Token]) -> List[str]:
    """Détecte les tokens potentiellement frauduleux"""
    suspicious_tokens = []
    
    for token in tokens:
        suspicion_score = 0
        
        # Nom/symbole suspect
        suspicious_words = ['MOON', 'LAMBO', 'DOGE', 'ELON', 'SAFEMOON', 'BABY']
        if any(word in token.symbol.upper() for word in suspicious_words):
            suspicion_score += 1
        
        # Pas de métadonnées vérifiées
        if not token.is_verified and token.metadata_source == "fallback":
            suspicion_score += 2
        
        # Pas de prix ou market cap
        if not token.price_usd or not token.market_cap:
            suspicion_score += 1
        
        # Market cap anormalement basse ou haute
        if token.market_cap:
            if token.market_cap < 1000:  # < 1K
                suspicion_score += 2
            elif token.market_cap > 1000000000000:  # > 1T (irréaliste)
                suspicion_score += 3
        
        if suspicion_score >= 3:
            suspicious_tokens.append(token.address)
    
    return suspicious_tokens


def calculate_token_portfolio_diversity(token_accounts: List[TokenAccount]) -> Dict[str, Any]:
    """Calcule la diversité du portefeuille de tokens"""
    if not token_accounts:
        return {'diversity_score': 0, 'categories': {}}
    
    # Compter les tokens actifs
    active_tokens = [ta for ta in token_accounts if ta.has_balance]
    total_balance_value = sum(ta.display_balance for ta in active_tokens)
    
    # Calculer la distribution
    balance_distribution = []
    for ta in active_tokens:
        if total_balance_value > 0:
            percentage = (ta.display_balance / total_balance_value) * 100
            balance_distribution.append(percentage)
    
    # Score de diversité (basé sur l'entropie)
    diversity_score = 0
    if balance_distribution:
        import math
        for percentage in balance_distribution:
            if percentage > 0:
                p = percentage / 100
                diversity_score -= p * math.log2(p)
        
        # Normaliser (0-10)
        max_entropy = math.log2(len(balance_distribution))
        if max_entropy > 0:
            diversity_score = (diversity_score / max_entropy) * 10
    
    return {
        'diversity_score': round(diversity_score, 2),
        'total_tokens': len(token_accounts),
        'active_tokens': len(active_tokens),
        'concentration_risk': 'HIGH' if max(balance_distribution or [0]) > 50 else 'LOW',
        'balance_distribution': balance_distribution
    }


def recommend_token_actions(token_account: TokenAccount, token: Token) -> List[str]:
    """Recommande des actions basées sur l'analyse du token"""
    recommendations = []
    
    # Recommandations basées sur l'activité
    if token_account.hours_since_scan > 24:
        recommendations.append("Schedule priority scan - no recent activity check")
    
    # Recommandations basées sur la balance
    if token_account.has_balance and not token.price_usd:
        recommendations.append("Fetch price data for valuation")
    
    # Recommandations de sécurité
    if not token.is_verified and token_account.display_balance > 100:
        recommendations.append("Verify token authenticity - large unverified holding")
    
    # Recommandations de diversification
    importance_score = calculate_token_importance_score(token_account, token)
    if importance_score > 8:
        recommendations.append("Consider partial profit-taking - high concentration risk")
    
    # Recommandations de monitoring
    if token_account.activity_score > 5:
        recommendations.append("Monitor closely - high activity token")
    
    return recommendations