
#!/usr/bin/env python3
"""
Formateurs utilitaires pour le Solana Wallet Monitor
Centralise tous les formatages d'affichage, de données et de logs
"""

import re
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Union
from decimal import Decimal, ROUND_HALF_UP


# =============================================================================
# FORMATAGE DES ADRESSES ET IDENTIFIANTS
# =============================================================================

def format_wallet_address(address: str, length: int = 8, show_full: bool = False) -> str:
    """
    Formate une adresse de wallet pour l'affichage
    
    Args:
        address: Adresse complète du wallet
        length: Nombre de caractères à afficher de chaque côté
        show_full: Si True, retourne l'adresse complète
    
    Returns:
        Adresse formatée (ex: "4Ddrf...9Er9n")
    """
    if not address or not isinstance(address, str):
        return "Invalid Address"
    
    if show_full or len(address) <= (length * 2 + 3):
        return address
    
    if len(address) < length * 2:
        return address
    
    return f"{address[:length]}...{address[-length:]}"


def format_token_mint(mint: str, length: int = 6) -> str:
    """
    Formate une adresse de mint de token
    
    Args:
        mint: Adresse du mint
        length: Nombre de caractères à afficher de chaque côté
    
    Returns:
        Mint formaté (ex: "EPjFWd...")
    """
    if not mint or not isinstance(mint, str):
        return "Unknown"
    
    if len(mint) <= length:
        return mint
    
    return f"{mint[:length]}..."


def format_signature(signature: str, length: int = 16) -> str:
    """
    Formate une signature de transaction
    
    Args:
        signature: Signature complète
        length: Nombre de caractères à afficher
    
    Returns:
        Signature formatée (ex: "5VhKQ3a4j1pK6xWy...")
    """
    if not signature or not isinstance(signature, str):
        return "No Signature"
    
    if len(signature) <= length:
        return signature
    
    return f"{signature[:length]}..."


def format_ata_pubkey(ata_pubkey: str, length: int = 8) -> str:
    """
    Formate une clé publique ATA (Associated Token Account)
    
    Args:
        ata_pubkey: Clé publique ATA complète
        length: Nombre de caractères de chaque côté
    
    Returns:
        ATA formatée (ex: "B1aF2C...8x9Y0Z")
    """
    return format_wallet_address(ata_pubkey, length)


def format_program_id(program_id: str, length: int = 12) -> str:
    """
    Formate un Program ID Solana
    
    Args:
        program_id: Program ID complet
        length: Nombre de caractères à afficher
    
    Returns:
        Program ID formaté
    """
    if not program_id:
        return "Unknown Program"
    
    # Gestion des program IDs connus
    known_programs = {
        "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA": "Token Program",
        "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL": "Associated Token Program",
        "11111111111111111111111111111111111111111111": "System Program",
        "So11111111111111111111111111111111111111112": "Wrapped SOL"
    }
    
    if program_id in known_programs:
        return known_programs[program_id]
    
    return format_token_mint(program_id, length)


# =============================================================================
# FORMATAGE DES MONTANTS ET VALEURS FINANCIÈRES
# =============================================================================

def format_sol_amount(amount: Union[float, int, Decimal], 
                     decimals: int = 4, 
                     show_symbol: bool = True,
                     compact: bool = False) -> str:
    """
    Formate un montant en SOL
    
    Args:
        amount: Montant en SOL
        decimals: Nombre de décimales à afficher
        show_symbol: Inclure le symbole SOL
        compact: Format compact (K, M, B)
    
    Returns:
        Montant formaté (ex: "1.2345 SOL" ou "1.23K SOL")
    """
    if amount is None:
        return "0 SOL" if show_symbol else "0"
    
    try:
        amount = float(amount)
    except (ValueError, TypeError):
        return "Invalid SOL" if show_symbol else "Invalid"
    
    if compact and abs(amount) >= 1000:
        formatted = format_compact_number(amount, decimals)
    else:
        formatted = f"{amount:,.{decimals}f}"
    
    return f"{formatted} SOL" if show_symbol else formatted


def format_token_amount(amount: Union[float, int, Decimal], 
                       symbol: str = "",
                       decimals: int = 4,
                       token_decimals: int = 9,
                       compact: bool = False) -> str:
    """
    Formate un montant de token avec gestion des décimales
    
    Args:
        amount: Montant de token
        symbol: Symbole du token
        decimals: Décimales d'affichage
        token_decimals: Décimales du token sur la blockchain
        compact: Format compact
    
    Returns:
        Montant formaté (ex: "1,234.5678 USDC")
    """
    if amount is None:
        return f"0 {symbol}" if symbol else "0"
    
    try:
        amount = float(amount)
    except (ValueError, TypeError):
        return f"Invalid {symbol}" if symbol else "Invalid"
    
    # Ajuster les décimales d'affichage selon le montant
    if abs(amount) < 0.001:
        display_decimals = min(8, token_decimals)
    elif abs(amount) < 1:
        display_decimals = min(6, decimals + 2)
    else:
        display_decimals = decimals
    
    if compact and abs(amount) >= 1000:
        formatted = format_compact_number(amount, display_decimals)
    else:
        formatted = f"{amount:,.{display_decimals}f}"
    
    return f"{formatted} {symbol}" if symbol else formatted


def format_lamports(lamports: int, decimals: int = 9) -> str:
    """
    Convertit et formate des lamports en SOL
    
    Args:
        lamports: Montant en lamports
        decimals: Décimales pour l'affichage
    
    Returns:
        Montant en SOL formaté
    """
    if lamports is None:
        return "0 SOL"
    
    try:
        sol_amount = lamports / 1_000_000_000
        return format_sol_amount(sol_amount, decimals)
    except (ValueError, TypeError):
        return "Invalid SOL"


def format_compact_number(number: Union[float, int], decimals: int = 2) -> str:
    """
    Formate un nombre en notation compacte (K, M, B, T)
    
    Args:
        number: Nombre à formater
        decimals: Décimales à conserver
    
    Returns:
        Nombre formaté (ex: "1.23K", "4.56M")
    """
    if number is None:
        return "0"
    
    try:
        number = float(number)
    except (ValueError, TypeError):
        return "Invalid"
    
    abs_number = abs(number)
    sign = "-" if number < 0 else ""
    
    if abs_number >= 1_000_000_000_000:  # Trillions
        formatted = f"{abs_number / 1_000_000_000_000:.{decimals}f}T"
    elif abs_number >= 1_000_000_000:  # Billions
        formatted = f"{abs_number / 1_000_000_000:.{decimals}f}B"
    elif abs_number >= 1_000_000:  # Millions
        formatted = f"{abs_number / 1_000_000:.{decimals}f}M"
    elif abs_number >= 1_000:  # Thousands
        formatted = f"{abs_number / 1_000:.{decimals}f}K"
    else:
        formatted = f"{abs_number:.{decimals}f}"
    
    return f"{sign}{formatted}"


def format_percentage(value: Union[float, int], decimals: int = 2, show_sign: bool = True) -> str:
    """
    Formate un pourcentage
    
    Args:
        value: Valeur en pourcentage (ex: 12.5 pour 12.5%)
        decimals: Nombre de décimales
        show_sign: Afficher le signe + pour les valeurs positives
    
    Returns:
        Pourcentage formaté (ex: "+12.50%", "-5.25%")
    """
    if value is None:
        return "0.00%"
    
    try:
        value = float(value)
    except (ValueError, TypeError):
        return "Invalid%"
    
    sign = "+" if show_sign and value > 0 else ""
    return f"{sign}{value:.{decimals}f}%"


def format_price_usd(price: Union[float, int], decimals: int = 6) -> str:
    """
    Formate un prix en USD
    
    Args:
        price: Prix en USD
        decimals: Nombre de décimales
    
    Returns:
        Prix formaté (ex: "$1.234567", "$0.000123")
    """
    if price is None or price == 0:
        return "$0.00"
    
    try:
        price = float(price)
    except (ValueError, TypeError):
        return "$Invalid"
    
    # Ajuster les décimales selon la valeur
    if abs(price) < 0.01:
        display_decimals = min(8, decimals)
    elif abs(price) < 1:
        display_decimals = min(4, decimals)
    else:
        display_decimals = 2
    
    return f"${price:,.{display_decimals}f}"


# =============================================================================
# FORMATAGE DU TEMPS ET DES DURÉES
# =============================================================================

def format_timestamp(timestamp: Union[int, float], 
                    format_type: str = "datetime",
                    timezone: str = "local") -> str:
    """
    Formate un timestamp Unix
    
    Args:
        timestamp: Timestamp Unix
        format_type: Type de format ("datetime", "date", "time", "relative")
        timezone: Timezone ("local", "utc")
    
    Returns:
        Timestamp formaté
    """
    if timestamp is None or timestamp == 0:
        return "Never"
    
    try:
        timestamp = float(timestamp)
        dt = datetime.fromtimestamp(timestamp)
        
        if format_type == "datetime":
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        elif format_type == "date":
            return dt.strftime("%Y-%m-%d")
        elif format_type == "time":
            return dt.strftime("%H:%M:%S")
        elif format_type == "relative":
            return format_time_ago(timestamp)
        elif format_type == "iso":
            return dt.isoformat()
        else:
            return dt.strftime("%Y-%m-%d %H:%M:%S")
            
    except (ValueError, TypeError, OSError):
        return "Invalid Time"


def format_time_ago(timestamp: Union[int, float]) -> str:
    """
    Formate un timestamp en temps relatif (ex: "5 minutes ago")
    
    Args:
        timestamp: Timestamp Unix
    
    Returns:
        Temps relatif formaté
    """
    if timestamp is None or timestamp == 0:
        return "Never"
    
    try:
        timestamp = float(timestamp)
        now = time.time()
        diff = now - timestamp
        
        if diff < 0:
            return "In the future"
        elif diff < 60:
            return f"{int(diff)}s ago"
        elif diff < 3600:
            minutes = int(diff / 60)
            return f"{minutes}m ago"
        elif diff < 86400:
            hours = int(diff / 3600)
            return f"{hours}h ago"
        elif diff < 2592000:  # 30 jours
            days = int(diff / 86400)
            return f"{days}d ago"
        else:
            return format_timestamp(timestamp, "date")
            
    except (ValueError, TypeError):
        return "Invalid"


def format_duration(seconds: Union[float, int], 
                   precision: str = "auto",
                   compact: bool = False) -> str:
    """
    Formate une durée en secondes
    
    Args:
        seconds: Durée en secondes
        precision: Précision ("auto", "seconds", "minutes", "hours")
        compact: Format compact (ex: "1h30m" vs "1 hour 30 minutes")
    
    Returns:
        Durée formatée
    """
    if seconds is None:
        return "0s"
    
    try:
        seconds = float(seconds)
    except (ValueError, TypeError):
        return "Invalid"
    
    if seconds < 0:
        return "Invalid duration"
    
    # Conversion en unités
    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    
    # Format compact
    if compact:
        parts = []
        if days > 0:
            parts.append(f"{days}d")
        if hours > 0:
            parts.append(f"{hours}h")
        if minutes > 0:
            parts.append(f"{minutes}m")
        if secs > 0 or not parts:
            if secs == int(secs):
                parts.append(f"{int(secs)}s")
            else:
                parts.append(f"{secs:.1f}s")
        return "".join(parts)
    
    # Format détaillé
    parts = []
    if days > 0:
        parts.append(f"{days} day{'s' if days != 1 else ''}")
    if hours > 0:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    if minutes > 0:
        parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
    if secs > 0 or not parts:
        if secs == int(secs):
            parts.append(f"{int(secs)} second{'s' if int(secs) != 1 else ''}")
        else:
            parts.append(f"{secs:.1f} seconds")
    
    if len(parts) == 1:
        return parts[0]
    elif len(parts) == 2:
        return f"{parts[0]} and {parts[1]}"
    else:
        return ", ".join(parts[:-1]) + f", and {parts[-1]}"


def format_eta(timestamp: Union[int, float]) -> str:
    """
    Formate un ETA (Estimated Time of Arrival)
    
    Args:
        timestamp: Timestamp futur
    
    Returns:
        ETA formaté (ex: "in 5m30s", "now")
    """
    if timestamp is None or timestamp == 0:
        return "Unknown"
    
    try:
        timestamp = float(timestamp)
        now = time.time()
        diff = timestamp - now
        
        if diff <= 0:
            return "Now"
        elif diff < 60:
            return f"in {int(diff)}s"
        elif diff < 3600:
            minutes = int(diff / 60)
            seconds = int(diff % 60)
            return f"in {minutes}m{seconds}s"
        elif diff < 86400:
            hours = int(diff / 3600)
            minutes = int((diff % 3600) / 60)
            return f"in {hours}h{minutes}m"
        else:
            return format_timestamp(timestamp, "datetime")
            
    except (ValueError, TypeError):
        return "Invalid"


# =============================================================================
# FORMATAGE DES ÉTATS ET STATUTS
# =============================================================================

def format_transaction_type(tx_type: str, colored: bool = False) -> str:
    """
    Formate un type de transaction avec couleurs optionnelles
    
    Args:
        tx_type: Type de transaction brut
        colored: Ajouter des codes couleur ANSI
    
    Returns:
        Type de transaction formaté
    """
    if not tx_type:
        return "UNKNOWN"
    
    # Normalisation
    tx_type = tx_type.upper().strip()
    
    # Mapping des types
    type_mapping = {
        'BUY': ('BUY', '🟢' if not colored else '\033[92mBUY\033[0m'),
        'SELL': ('SELL', '🔴' if not colored else '\033[91mSELL\033[0m'),
        'TRANSFER': ('TRANSFER', '🔵' if not colored else '\033[94mTRANSFER\033[0m'),
        'TRANSFER_IN': ('RECEIVE', '🟢' if not colored else '\033[92mRECEIVE\033[0m'),
        'TRANSFER_OUT': ('SEND', '🟡' if not colored else '\033[93mSEND\033[0m'),
        'SWAP': ('SWAP', '🟣' if not colored else '\033[95mSWAP\033[0m'),
        'STAKE': ('STAKE', '🔷' if not colored else '\033[96mSTAKE\033[0m'),
        'UNSTAKE': ('UNSTAKE', '🔶' if not colored else '\033[96mUNSTAKE\033[0m'),
        'OTHER': ('OTHER', '⚪' if not colored else '\033[97mOTHER\033[0m')
    }
    
    formatted_type, display = type_mapping.get(tx_type, ('UNKNOWN', '❓'))
    return display if not colored or '🟢' in display else formatted_type


def format_transaction_status(status: str, colored: bool = False) -> str:
    """
    Formate un statut de transaction
    
    Args:
        status: Statut brut
        colored: Ajouter des couleurs
    
    Returns:
        Statut formaté
    """
    if not status:
        return "UNKNOWN"
    
    status = status.upper().strip()
    
    status_mapping = {
        'SUCCESS': ('✅ SUCCESS', '\033[92m✅ SUCCESS\033[0m'),
        'FAILED': ('❌ FAILED', '\033[91m❌ FAILED\033[0m'),
        'PENDING': ('⏳ PENDING', '\033[93m⏳ PENDING\033[0m'),
        'TIMEOUT': ('⏰ TIMEOUT', '\033[91m⏰ TIMEOUT\033[0m'),
        'CANCELLED': ('🚫 CANCELLED', '\033[90m🚫 CANCELLED\033[0m')
    }
    
    normal, colored_version = status_mapping.get(status, ('❓ UNKNOWN', '\033[97m❓ UNKNOWN\033[0m'))
    return colored_version if colored else normal


def format_priority_level(priority: Union[float, int], 
                         format_type: str = "badge") -> str:
    """
    Formate un niveau de priorité
    
    Args:
        priority: Valeur de priorité
        format_type: Type de format ("badge", "text", "emoji", "color")
    
    Returns:
        Priorité formatée
    """
    if priority is None:
        return "UNKNOWN"
    
    try:
        priority = float(priority)
    except (ValueError, TypeError):
        return "INVALID"
    
    # Détermination du niveau
    if priority >= 4.0:
        level = "HIGH"
        emoji = "🔥"
        color = "\033[91m"  # Rouge
    elif priority >= 2.0:
        level = "MEDIUM" 
        emoji = "🟡"
        color = "\033[93m"  # Jaune
    elif priority >= 1.0:
        level = "LOW"
        emoji = "🔵"
        color = "\033[94m"  # Bleu
    else:
        level = "VERY_LOW"
        emoji = "⚪"
        color = "\033[90m"  # Gris
    
    if format_type == "badge":
        return f"{emoji} {level} ({priority:.2f})"
    elif format_type == "text":
        return f"{level} ({priority:.2f})"
    elif format_type == "emoji":
        return emoji
    elif format_type == "color":
        return f"{color}{level} ({priority:.2f})\033[0m"
    else:
        return f"{priority:.2f}"


def format_scan_status(status: str, details: Dict[str, Any] = None) -> str:
    """
    Formate un statut de scan
    
    Args:
        status: Statut du scan
        details: Détails additionnels
    
    Returns:
        Statut formaté avec contexte
    """
    if not status:
        return "UNKNOWN"
    
    status = status.upper().strip()
    details = details or {}
    
    status_icons = {
        'RUNNING': '🔄',
        'COMPLETED': '✅',
        'FAILED': '❌',
        'PENDING': '⏳',
        'CANCELLED': '🚫',
        'TIMEOUT': '⏰'
    }
    
    icon = status_icons.get(status, '❓')
    base_status = f"{icon} {status}"
    
    # Ajouter des détails si disponibles
    if details:
        detail_parts = []
        if 'duration' in details:
            detail_parts.append(f"Duration: {format_duration(details['duration'], compact=True)}")
        if 'discoveries' in details:
            detail_parts.append(f"Discoveries: {details['discoveries']}")
        if 'accounts_scanned' in details:
            detail_parts.append(f"Accounts: {details['accounts_scanned']}")
        
        if detail_parts:
            base_status += f" ({', '.join(detail_parts)})"
    
    return base_status


# =============================================================================
# FORMATAGE DES DONNÉES TECHNIQUES
# =============================================================================

def format_rpc_method(method: str, params_count: int = None) -> str:
    """
    Formate un nom de méthode RPC
    
    Args:
        method: Nom de la méthode
        params_count: Nombre de paramètres
    
    Returns:
        Méthode formatée
    """
    if not method:
        return "Unknown Method"
    
    # Améliorer la lisibilité des méthodes courantes
    method_names = {
        'getTokenAccountsByOwner': 'Get Token Accounts',
        'getMultipleAccounts': 'Get Multiple Accounts',
        'getSignaturesForAddress': 'Get Signatures',
        'getTransaction': 'Get Transaction',
        'getBalance': 'Get Balance',
        'getAccountInfo': 'Get Account Info'
    }
    
    display_name = method_names.get(method, method)
    
    if params_count is not None:
        display_name += f" ({params_count} params)"
    
    return display_name


def format_batch_info(method: str, size: int, duration: float = None) -> str:
    """
    Formate des informations de batch RPC
    
    Args:
        method: Méthode RPC
        size: Taille du batch
        duration: Durée d'exécution
    
    Returns:
        Information de batch formatée
    """
    base_info = f"📦 Batch {format_rpc_method(method)}: {size} items"
    
    if duration is not None:
        base_info += f" in {format_duration(duration, compact=True)}"
        
        # Calcul du débit
        if duration > 0:
            throughput = size / duration
            base_info += f" ({throughput:.1f} items/s)"
    
    return base_info


def format_error_summary(error: Exception, context: str = None) -> str:
    """
    Formate un résumé d'erreur pour les logs
    
    Args:
        error: Exception à formater
        context: Contexte de l'erreur
    
    Returns:
        Résumé d'erreur formaté
    """
    error_type = type(error).__name__
    error_message = str(error)
    
    # Truncate long error messages
    if len(error_message) > 100:
        error_message = error_message[:100] + "..."
    
    summary = f"❌ {error_type}: {error_message}"
    
    if context:
        summary = f"❌ {error_type} in {context}: {error_message}"
    
    return summary


def format_memory_usage(bytes_used: int) -> str:
    """
    Formate l'utilisation mémoire
    
    Args:
        bytes_used: Bytes utilisés
    
    Returns:
        Usage mémoire formaté (ex: "125.4 MB")
    """
    if bytes_used is None or bytes_used < 0:
        return "Unknown"
    
    units = ['B', 'KB', 'MB', 'GB', 'TB']
    size = float(bytes_used)
    unit_index = 0
    
    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1
    
    if unit_index == 0:
        return f"{int(size)} {units[unit_index]}"
    else:
        return f"{size:.1f} {units[unit_index]}"


# =============================================================================
# FORMATAGE DES TABLEAUX ET LISTES
# =============================================================================

def format_table_row(data: List[Any], 
                     widths: List[int], 
                     alignments: List[str] = None) -> str:
    """
    Formate une ligne de tableau avec alignement
    
    Args:
        data: Données de la ligne
        widths: Largeurs des colonnes
        alignments: Alignements ('left', 'right', 'center')
    
    Returns:
        Ligne formatée
    """
    if not data or not widths:
        return ""
    
    alignments = alignments or ['left'] * len(data)
    formatted_cells = []
    
    for i, (cell, width) in enumerate(zip(data, widths)):
        cell_str = str(cell) if cell is not None else ""
        
        # Tronquer si trop long
        if len(cell_str) > width:
            cell_str = cell_str[:width-3] + "..."
        
        # Appliquer l'alignement
        alignment = alignments[i] if i < len(alignments) else 'left'
        
        if alignment == 'right':
            formatted_cell = cell_str.rjust(width)
        elif alignment == 'center':
            formatted_cell = cell_str.center(width)
        else:  # left
            formatted_cell = cell_str.ljust(width)
        
        formatted_cells.append(formatted_cell)
    
    return " | ".join(formatted_cells)


def format_key_value_pairs(data: Dict[str, Any], 
                          indent: int = 2,
                          max_key_width: int = 20) -> str:
    """
    Formate un dictionnaire en paires clé-valeur alignées
    
    Args:
        data: Dictionnaire à formater
        indent: Indentation
        max_key_width: Largeur maximum des clés
    
    Returns:
        Paires clé-valeur formatées
    """
    if not data:
        return ""
    
    # Calculer la largeur optimale des clés
    key_width = min(max(len(str(k)) for k in data.keys()), max_key_width)
    indent_str = " " * indent
    
    lines = []
    for key, value in data.items():
        key_str = str(key)[:max_key_width]
        value_str = str(value) if value is not None else "None"
        
        # Traitement spécial pour les valeurs longues
        if len(value_str) > 60:
            lines.append(f"{indent_str}{key_str.ljust(key_width)}: {value_str[:60]}...")
        else:
            lines.append(f"{indent_str}{key_str.ljust(key_width)}: {value_str}")
    
    return "\n".join(lines)


# =============================================================================
# FORMATAGE SPÉCIALISÉ POUR LES LOGS
# =============================================================================

def format_log_header(title: str, 
                     level: int = 1, 
                     width: int = 80,
                     char: str = "=") -> str:
    """
    Formate un en-tête de log
    
    Args:
        title: Titre de la section
        level: Niveau d'en-tête (1-3)
        width: Largeur totale
        char: Caractère de décoration
    
    Returns:
        En-tête formaté
    """
    if level == 1:
        # Titre principal
        title_line = f" {title} "
        padding = (width - len(title_line)) // 2
        header = char * padding + title_line + char * padding
        if len(header) < width:
            header += char
        return header
    elif level == 2:
        # Sous-titre
        return f"{char * 10} {title} {char * 10}"
    else:
        # Section simple
        return f"{char * 5} {title}"


def format_progress_bar(current: int, 
                       total: int, 
                       width: int = 30,
                       show_percentage: bool = True) -> str:
    """
    Formate une barre de progression
    
    Args:
        current: Valeur actuelle
        total: Valeur totale
        width: Largeur de la barre
        show_percentage: Afficher le pourcentage
    
    Returns:
        Barre de progression formatée
    """
    if total == 0:
        return f"[{'=' * width}] 100%" if show_percentage else f"[{'=' * width}]"
    
    progress = min(current / total, 1.0)
    filled_width = int(progress * width)
    bar = '=' * filled_width + '-' * (width - filled_width)
   
    if show_percentage:
       percentage = progress * 100
       return f"[{bar}] {percentage:5.1f}%"
    else:
       return f"[{bar}]"


def format_cycle_summary(cycle_id: str, 
                       stats: Dict[str, Any],
                       width: int = 100) -> str:
   """
   Formate un résumé de cycle de monitoring
   
   Args:
       cycle_id: Identifiant du cycle
       stats: Statistiques du cycle
       width: Largeur du résumé
   
   Returns:
       Résumé formaté
   """
   lines = []
   
   # En-tête
   header = format_log_header(f"CYCLE SUMMARY - {cycle_id}", 1, width)
   lines.append(header)
   
   # Statistiques principales
   main_stats = []
   if 'wallet_scanned' in stats:
       main_stats.append(f"Wallet: {format_wallet_address(stats['wallet_scanned'])}")
   if 'duration' in stats:
       main_stats.append(f"Duration: {format_duration(stats['duration'], compact=True)}")
   if 'discoveries' in stats:
       main_stats.append(f"Discoveries: {stats['discoveries']}")
   if 'transactions' in stats:
       main_stats.append(f"Transactions: {stats['transactions']}")
   
   if main_stats:
       lines.append(f"📊 {' | '.join(main_stats)}")
   
   # Performance
   if 'rpc_requests' in stats and 'efficiency' in stats:
       perf_line = f"⚡ Performance: {stats['rpc_requests']} RPC requests, "
       perf_line += f"{stats['efficiency']:.3f} efficiency"
       lines.append(perf_line)
   
   # Status final
   if 'status' in stats:
       status = format_scan_status(stats['status'], stats)
       lines.append(f"🎯 Status: {status}")
   
   lines.append("=" * width)
   
   return "\n".join(lines)


# =============================================================================
# FORMATAGE POUR L'API ET LE DASHBOARD
# =============================================================================

def format_api_response(data: Any, 
                      success: bool = True,
                      message: str = None,
                      metadata: Dict[str, Any] = None) -> Dict[str, Any]:
   """
   Formate une réponse API standardisée
   
   Args:
       data: Données de la réponse
       success: Indicateur de succès
       message: Message explicatif
       metadata: Métadonnées additionnelles
   
   Returns:
       Réponse API formatée
   """
   response = {
       "success": success,
       "timestamp": int(time.time()),
       "data": data
   }
   
   if message:
       response["message"] = message
   
   if metadata:
       response["metadata"] = metadata
   
   return response


def format_dashboard_stats(raw_stats: Dict[str, Any]) -> Dict[str, Any]:
   """
   Formate les statistiques pour le dashboard
   
   Args:
       raw_stats: Statistiques brutes
   
   Returns:
       Statistiques formatées pour affichage
   """
   formatted = {}
   
   # Formatage des montants
   for key, value in raw_stats.items():
       if 'balance' in key.lower() and isinstance(value, (int, float)):
           formatted[key] = format_sol_amount(value, decimals=4, show_symbol=False)
       elif 'amount' in key.lower() and isinstance(value, (int, float)):
           formatted[key] = format_token_amount(value, decimals=4)
       elif 'price' in key.lower() and isinstance(value, (int, float)):
           formatted[key] = format_price_usd(value)
       elif 'time' in key.lower() and isinstance(value, (int, float)):
           formatted[key] = format_timestamp(value, "relative")
       elif 'duration' in key.lower() and isinstance(value, (int, float)):
           formatted[key] = format_duration(value, compact=True)
       elif 'percentage' in key.lower() and isinstance(value, (int, float)):
           formatted[key] = format_percentage(value)
       else:
           formatted[key] = value
   
   return formatted


def format_token_list_item(token_data: Dict[str, Any]) -> Dict[str, Any]:
   """
   Formate un élément de liste de tokens pour l'affichage
   
   Args:
       token_data: Données brutes du token
   
   Returns:
       Token formaté pour affichage
   """
   formatted = {}
   
   # Informations de base
   formatted['mint'] = token_data.get('mint', 'Unknown')
   formatted['mint_short'] = format_token_mint(formatted['mint'])
   formatted['symbol'] = token_data.get('symbol', 'UNKNOWN')
   formatted['name'] = token_data.get('name', 'Unknown Token')
   
   # Montants
   if 'balance' in token_data:
       formatted['balance'] = format_token_amount(
           token_data['balance'], 
           token_data.get('symbol', ''),
           decimals=4,
           token_decimals=token_data.get('decimals', 9)
       )
   
   if 'price_usd' in token_data:
       formatted['price'] = format_price_usd(token_data['price_usd'])
   
   # Activité
   if 'last_activity' in token_data:
       formatted['last_activity'] = format_time_ago(token_data['last_activity'])
   
   if 'transaction_count' in token_data:
       formatted['transaction_count'] = token_data['transaction_count']
   
   # Statut
   formatted['is_active'] = token_data.get('is_active', True)
   formatted['priority'] = format_priority_level(
       token_data.get('priority', 1.0), 
       format_type="badge"
   )
   
   return formatted


# =============================================================================
# UTILITAIRES DE VALIDATION ET NETTOYAGE
# =============================================================================

def sanitize_for_display(text: str, max_length: int = 100) -> str:
   """
   Nettoie un texte pour l'affichage sécurisé
   
   Args:
       text: Texte à nettoyer
       max_length: Longueur maximum
   
   Returns:
       Texte nettoyé
   """
   if not text or not isinstance(text, str):
       return "N/A"
   
   # Supprimer les caractères de contrôle
   cleaned = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', text)
   
   # Tronquer si nécessaire
   if len(cleaned) > max_length:
       cleaned = cleaned[:max_length-3] + "..."
   
   return cleaned


def format_safe_json(data: Any, indent: int = None) -> str:
   """
   Formate des données en JSON sécurisé pour les logs
   
   Args:
       data: Données à sérialiser
       indent: Indentation JSON
   
   Returns:
       JSON sécurisé ou représentation alternative
   """
   try:
       import json
       return json.dumps(data, indent=indent, default=str, ensure_ascii=False)
   except (TypeError, ValueError) as e:
       return f"<Non-serializable data: {type(data).__name__}>"


# =============================================================================
# FORMATAGE SPÉCIALISÉ POUR DIFFÉRENTS CONTEXTES
# =============================================================================

def format_notification_message(event_type: str, 
                              data: Dict[str, Any],
                              format_type: str = "text") -> str:
   """
   Formate un message de notification
   
   Args:
       event_type: Type d'événement
       data: Données de l'événement
       format_type: Format ("text", "html", "markdown")
   
   Returns:
       Message formaté
   """
   if event_type == "new_large_transaction":
       wallet = format_wallet_address(data.get('wallet_address', ''))
       amount = format_token_amount(
           data.get('token_amount', 0),
           data.get('token_symbol', ''),
           compact=True
       )
       tx_type = format_transaction_type(data.get('transaction_type', ''))
       
       message = f"🔥 Large transaction detected: {tx_type} {amount} on wallet {wallet}"
       
       if format_type == "html":
           message = f"<strong>{message}</strong>"
       elif format_type == "markdown":
           message = f"**{message}**"
   
   elif event_type == "new_token_discovered":
       wallet = format_wallet_address(data.get('wallet_address', ''))
       symbol = data.get('token_symbol', 'UNKNOWN')
       
       message = f"🆕 New token discovered: {symbol} on wallet {wallet}"
       
       if format_type == "html":
           message = f"<em>{message}</em>"
       elif format_type == "markdown":
           message = f"*{message}*"
   
   else:
       message = f"📱 Event: {event_type}"
   
   return message


def format_export_filename(prefix: str, 
                         wallet_address: str = None,
                         date_range: str = None,
                         extension: str = "csv") -> str:
   """
   Génère un nom de fichier d'export standardisé
   
   Args:
       prefix: Préfixe du fichier
       wallet_address: Adresse du wallet (optionnel)
       date_range: Plage de dates (optionnel)
       extension: Extension du fichier
   
   Returns:
       Nom de fichier formaté
   """
   timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
   
   parts = [prefix]
   
   if wallet_address:
       wallet_short = format_wallet_address(wallet_address, length=6)
       parts.append(wallet_short.replace("...", "_"))
   
   if date_range:
       # Nettoyer la plage de dates pour le nom de fichier
       clean_range = re.sub(r'[^\w\-_]', '_', date_range)
       parts.append(clean_range)
   
   parts.append(timestamp)
   
   filename = "_".join(parts) + f".{extension}"
   return filename


# =============================================================================
# FORMATAGE CONDITIONNEL ET ADAPTATIF
# =============================================================================

def format_adaptive_precision(value: Union[float, int], 
                            value_type: str = "auto") -> str:
   """
   Formate une valeur avec une précision adaptative
   
   Args:
       value: Valeur à formater
       value_type: Type de valeur ("currency", "percentage", "ratio", "auto")
   
   Returns:
       Valeur formatée avec précision adaptée
   """
   if value is None:
       return "N/A"
   
   try:
       value = float(value)
   except (ValueError, TypeError):
       return "Invalid"
   
   abs_value = abs(value)
   
   if value_type == "currency":
       if abs_value >= 1000:
           return format_compact_number(value, 2)
       elif abs_value >= 1:
           return f"{value:.2f}"
       elif abs_value >= 0.01:
           return f"{value:.4f}"
       else:
           return f"{value:.8f}"
   
   elif value_type == "percentage":
       if abs_value >= 10:
           return f"{value:.1f}%"
       elif abs_value >= 1:
           return f"{value:.2f}%"
       else:
           return f"{value:.3f}%"
   
   elif value_type == "ratio":
       if abs_value >= 100:
           return f"{value:.0f}"
       elif abs_value >= 10:
           return f"{value:.1f}"
       elif abs_value >= 1:
           return f"{value:.2f}"
       else:
           return f"{value:.4f}"
   
   else:  # auto
       if abs_value >= 1000:
           return format_compact_number(value)
       elif abs_value >= 1:
           return f"{value:.2f}"
       elif abs_value >= 0.001:
           return f"{value:.4f}"
       else:
           return f"{value:.8f}"


def format_contextual_amount(amount: Union[float, int],
                          context: Dict[str, Any]) -> str:
   """
   Formate un montant selon le contexte
   
   Args:
       amount: Montant à formater
       context: Contexte (type, symbole, décimales, etc.)
   
   Returns:
       Montant formaté selon le contexte
   """
   if amount is None:
       return "0"
   
   amount_type = context.get('type', 'generic')
   
   if amount_type == 'sol':
       return format_sol_amount(amount, context.get('decimals', 4))
   elif amount_type == 'token':
       return format_token_amount(
           amount,
           context.get('symbol', ''),
           context.get('display_decimals', 4),
           context.get('token_decimals', 9)
       )
   elif amount_type == 'usd':
       return format_price_usd(amount, context.get('decimals', 2))
   elif amount_type == 'lamports':
       return format_lamports(int(amount))
   else:
       return format_adaptive_precision(amount, 'auto')


# =============================================================================
# CONSTANTES ET HELPERS POUR LE FORMATAGE
# =============================================================================

# Correspondances d'icônes pour différents contextes
CONTEXT_ICONS = {
   'success': '✅',
   'error': '❌',
   'warning': '⚠️',
   'info': 'ℹ️',
   'money': '💰',
   'time': '⏰',
   'wallet': '👛',
   'token': '🪙',
   'transaction': '💸',
   'discovery': '🔍',
   'priority': '🎯',
   'performance': '📊',
   'batch': '📦',
   'system': '⚙️'
}

# Templates de formatage réutilisables
FORMAT_TEMPLATES = {
   'transaction_summary': "{icon} {type} {amount} {symbol} on {wallet_short}",
   'discovery_summary': "🆕 Found {count} new {item_type} on {wallet_short}",
   'priority_change': "{icon} Priority: {old:.2f} → {new:.2f} ({change:+.2f})",
   'performance_metric': "📊 {metric}: {value} ({status})",
   'scan_result': "🔍 Scan {wallet_short}: {discoveries} discoveries, {duration}"
}


def apply_format_template(template_name: str, **kwargs) -> str:
   """
   Applique un template de formatage avec des paramètres
   
   Args:
       template_name: Nom du template
       **kwargs: Paramètres du template
   
   Returns:
       Chaîne formatée selon le template
   """
   template = FORMAT_TEMPLATES.get(template_name, "{data}")
   
   try:
       return template.format(**kwargs)
   except KeyError as e:
       return f"Template error: missing {e}"


def get_context_icon(context: str) -> str:
   """
   Retourne l'icône appropriée pour un contexte
   
   Args:
       context: Nom du contexte
   
   Returns:
       Icône Unicode appropriée
   """
   return CONTEXT_ICONS.get(context.lower(), '📌')


# =============================================================================
# EXPORT DES FONCTIONS PRINCIPALES
# =============================================================================

__all__ = [
   # Formatage des adresses
   'format_wallet_address', 'format_token_mint', 'format_signature', 
   'format_ata_pubkey', 'format_program_id',
   
   # Formatage des montants
   'format_sol_amount', 'format_token_amount', 'format_lamports',
   'format_compact_number', 'format_percentage', 'format_price_usd',
   
   # Formatage du temps
   'format_timestamp', 'format_time_ago', 'format_duration', 'format_eta',
   
   # Formatage des états
   'format_transaction_type', 'format_transaction_status', 
   'format_priority_level', 'format_scan_status',
   
   # Formatage technique
   'format_rpc_method', 'format_batch_info', 'format_error_summary',
   'format_memory_usage',
   
   # Formatage des tableaux
   'format_table_row', 'format_key_value_pairs',
   
   # Formatage des logs
   'format_log_header', 'format_progress_bar', 'format_cycle_summary',
   
   # Formatage API
   'format_api_response', 'format_dashboard_stats', 'format_token_list_item',
   
   # Utilitaires
   'sanitize_for_display', 'format_safe_json', 'format_notification_message',
   'format_export_filename', 'format_adaptive_precision', 'format_contextual_amount',
   
   # Templates et helpers
   'apply_format_template', 'get_context_icon', 'CONTEXT_ICONS', 'FORMAT_TEMPLATES'
]
