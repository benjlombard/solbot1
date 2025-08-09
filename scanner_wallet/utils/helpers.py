
#!/usr/bin/env python3
"""
Fonctions utilitaires générales pour le Solana Wallet Monitor
Fonctions pures sans état pour faciliter les opérations communes
"""

import time
import hashlib
import secrets
import re
import json
import math
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Union, Tuple, Callable
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
import base58
import uuid


# =============================================================================
# UTILITAIRES TEMPORELS
# =============================================================================

def get_current_timestamp() -> int:
    """
    Retourne le timestamp Unix actuel
    
    Returns:
        Timestamp Unix en secondes
    """
    return int(time.time())


def get_current_timestamp_ms() -> int:
    """
    Retourne le timestamp Unix actuel en millisecondes
    
    Returns:
        Timestamp Unix en millisecondes
    """
    return int(time.time() * 1000)


def calculate_time_since(timestamp: Union[int, float]) -> int:
    """
    Calcule le temps écoulé depuis un timestamp
    
    Args:
        timestamp: Timestamp de référence
    
    Returns:
        Secondes écoulées depuis le timestamp
    """
    if timestamp is None or timestamp <= 0:
        return 999999  # Valeur arbitraire pour "très ancien"
    
    try:
        current = time.time()
        return max(0, int(current - float(timestamp)))
    except (ValueError, TypeError):
        return 999999


def calculate_time_until(timestamp: Union[int, float]) -> int:
    """
    Calcule le temps restant jusqu'à un timestamp futur
    
    Args:
        timestamp: Timestamp futur
    
    Returns:
        Secondes restantes (0 si dans le passé)
    """
    if timestamp is None or timestamp <= 0:
        return 0
    
    try:
        current = time.time()
        return max(0, int(float(timestamp) - current))
    except (ValueError, TypeError):
        return 0


def is_timestamp_recent(timestamp: Union[int, float], threshold_seconds: int = 3600) -> bool:
    """
    Vérifie si un timestamp est récent
    
    Args:
        timestamp: Timestamp à vérifier
        threshold_seconds: Seuil en secondes (défaut: 1h)
    
    Returns:
        True si le timestamp est récent
    """
    if timestamp is None or timestamp <= 0:
        return False
    
    time_since = calculate_time_since(timestamp)
    return time_since <= threshold_seconds


def get_time_bucket(timestamp: Union[int, float], bucket_size_minutes: int = 15) -> int:
    """
    Groupe un timestamp dans un bucket temporel
    
    Args:
        timestamp: Timestamp à grouper
        bucket_size_minutes: Taille du bucket en minutes
    
    Returns:
        Timestamp du début du bucket
    """
    if timestamp is None or timestamp <= 0:
        return 0
    
    try:
        bucket_size_seconds = bucket_size_minutes * 60
        return int(timestamp // bucket_size_seconds) * bucket_size_seconds
    except (ValueError, TypeError):
        return 0


def sleep_with_jitter(base_seconds: float, jitter_factor: float = 0.1) -> None:
    """
    Sleep avec jitter aléatoire pour éviter la synchronisation
    
    Args:
        base_seconds: Durée de base en secondes
        jitter_factor: Facteur de jitter (0.1 = ±10%)
    """
    if base_seconds <= 0:
        return
    
    jitter = base_seconds * jitter_factor * (2 * secrets.SystemRandom().random() - 1)
    sleep_time = max(0.1, base_seconds + jitter)
    time.sleep(sleep_time)


# =============================================================================
# UTILITAIRES MATHÉMATIQUES
# =============================================================================

def safe_divide(numerator: Union[float, int], 
                denominator: Union[float, int], 
                default: Union[float, int] = 0) -> float:
    """
    Division sécurisée avec gestion de la division par zéro
    
    Args:
        numerator: Numérateur
        denominator: Dénominateur
        default: Valeur par défaut si division par zéro
    
    Returns:
        Résultat de la division ou valeur par défaut
    """
    try:
        num = float(numerator) if numerator is not None else 0.0
        den = float(denominator) if denominator is not None else 0.0
        
        if den == 0:
            return float(default)
        
        return num / den
    except (ValueError, TypeError, ZeroDivisionError):
        return float(default)


def safe_percentage(part: Union[float, int], 
                   total: Union[float, int], 
                   default: float = 0.0) -> float:
    """
    Calcul sécurisé d'un pourcentage
    
    Args:
        part: Partie
        total: Total
        default: Valeur par défaut
    
    Returns:
        Pourcentage (0-100)
    """
    if total is None or total == 0:
        return default
    
    try:
        return (float(part or 0) / float(total)) * 100.0
    except (ValueError, TypeError, ZeroDivisionError):
        return default


def round_to_precision(value: Union[float, int], precision: int = 2) -> float:
    """
    Arrondit une valeur à une précision donnée
    
    Args:
        value: Valeur à arrondir
        precision: Nombre de décimales
    
    Returns:
        Valeur arrondie
    """
    if value is None:
        return 0.0
    
    try:
        decimal_value = Decimal(str(value))
        rounded = decimal_value.quantize(
            Decimal('0.' + '0' * precision), 
            rounding=ROUND_HALF_UP
        )
        return float(rounded)
    except (ValueError, TypeError, InvalidOperation):
        return 0.0


def clamp(value: Union[float, int], 
          min_val: Union[float, int], 
          max_val: Union[float, int]) -> Union[float, int]:
    """
    Limite une valeur entre min et max
    
    Args:
        value: Valeur à limiter
        min_val: Valeur minimum
        max_val: Valeur maximum
    
    Returns:
        Valeur limitée
    """
    try:
        return max(min_val, min(max_val, value))
    except (TypeError, ValueError):
        return min_val


def calculate_moving_average(values: List[Union[float, int]], 
                           window_size: int = 5) -> float:
    """
    Calcule une moyenne mobile
    
    Args:
        values: Liste des valeurs
        window_size: Taille de la fenêtre
    
    Returns:
        Moyenne mobile
    """
    if not values or window_size <= 0:
        return 0.0
    
    try:
        # Prendre les dernières valeurs
        recent_values = values[-window_size:]
        valid_values = [float(v) for v in recent_values if v is not None]
        
        if not valid_values:
            return 0.0
        
        return sum(valid_values) / len(valid_values)
    except (ValueError, TypeError):
        return 0.0


def calculate_percentile(values: List[Union[float, int]], 
                        percentile: float) -> float:
    """
    Calcule un percentile d'une liste de valeurs
    
    Args:
        values: Liste des valeurs
        percentile: Percentile à calculer (0-100)
    
    Returns:
        Valeur du percentile
    """
    if not values or not 0 <= percentile <= 100:
        return 0.0
    
    try:
        valid_values = sorted([float(v) for v in values if v is not None])
        if not valid_values:
            return 0.0
        
        if percentile == 0:
            return valid_values[0]
        if percentile == 100:
            return valid_values[-1]
        
        index = (percentile / 100) * (len(valid_values) - 1)
        lower = int(math.floor(index))
        upper = int(math.ceil(index))
        
        if lower == upper:
            return valid_values[lower]
        
        # Interpolation linéaire
        weight = index - lower
        return valid_values[lower] * (1 - weight) + valid_values[upper] * weight
        
    except (ValueError, TypeError, IndexError):
        return 0.0


# =============================================================================
# UTILITAIRES SOLANA
# =============================================================================

def parse_solana_amount(raw_amount: Union[str, int, float], 
                       decimals: int = 9) -> float:
    """
    Parse un montant Solana avec gestion des décimales
    
    Args:
        raw_amount: Montant brut
        decimals: Nombre de décimales du token
    
    Returns:
        Montant parsé en float
    """
    if raw_amount is None:
        return 0.0
    
    try:
        if isinstance(raw_amount, str):
            # Supprimer les espaces et virgules
            cleaned = raw_amount.replace(',', '').replace(' ', '')
            amount = float(cleaned)
        else:
            amount = float(raw_amount)
        
        # Si le montant semble être en unités brutes (très grand), le convertir
        if decimals > 0 and amount > (10 ** (decimals - 2)):
            return amount / (10 ** decimals)
        
        return amount
    except (ValueError, TypeError):
        return 0.0


def lamports_to_sol(lamports: int) -> float:
    """
    Convertit des lamports en SOL
    
    Args:
        lamports: Montant en lamports
    
    Returns:
        Montant en SOL
    """
    if lamports is None:
        return 0.0
    
    try:
        return float(lamports) / 1_000_000_000
    except (ValueError, TypeError):
        return 0.0


def sol_to_lamports(sol: Union[float, int]) -> int:
    """
    Convertit des SOL en lamports
    
    Args:
        sol: Montant en SOL
    
    Returns:
        Montant en lamports
    """
    if sol is None:
        return 0
    
    try:
        return int(float(sol) * 1_000_000_000)
    except (ValueError, TypeError):
        return 0


def is_native_sol_mint(mint_address: str) -> bool:
    """
    Vérifie si une adresse de mint correspond au SOL natif
    
    Args:
        mint_address: Adresse du mint
    
    Returns:
        True si c'est le mint du SOL natif (wrapped SOL)
    """
    if not mint_address:
        return False
    
    return mint_address == "So11111111111111111111111111111111111111112"


def get_token_program_id(mint_address: str) -> str:
    """
    Retourne le Program ID approprié selon le type de token
    
    Args:
        mint_address: Adresse du mint
    
    Returns:
        Program ID (Token Program ou Token-2022)
    """
    # Pour l'instant, retourner toujours le Token Program standard
    # À l'avenir, on pourrait détecter Token-2022 selon le mint
    return "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"


# =============================================================================
# UTILITAIRES DE GÉNÉRATION D'IDENTIFIANTS
# =============================================================================

def generate_cycle_id(prefix: str = "cycle") -> str:
    """
    Génère un identifiant unique de cycle
    
    Args:
        prefix: Préfixe de l'identifiant
    
    Returns:
        Identifiant unique (ex: "cycle_123_1642687200")
    """
    timestamp = get_current_timestamp()
    random_part = secrets.randbelow(10000)
    return f"{prefix}_{random_part}_{timestamp}"


def generate_scan_id(wallet_address: str) -> str:
    """
    Génère un identifiant de scan pour un wallet
    
    Args:
        wallet_address: Adresse du wallet
    
    Returns:
        Identifiant de scan unique
    """
    timestamp = get_current_timestamp()
    wallet_short = wallet_address[:8] if wallet_address else "unknown"
    return f"scan_{wallet_short}_{timestamp}"


def generate_short_hash(data: str, length: int = 8) -> str:
    """
    Génère un hash court pour identifier des données
    
    Args:
        data: Données à hasher
        length: Longueur du hash (défaut: 8)
    
    Returns:
        Hash court en hexadécimal
    """
    if not data:
        return "00000000"[:length]
    
    try:
        hash_object = hashlib.sha256(data.encode('utf-8'))
        return hash_object.hexdigest()[:length]
    except Exception:
        return secrets.token_hex(length // 2)


def generate_uuid() -> str:
    """
    Génère un UUID4 standard
    
    Returns:
        UUID4 sous forme de string
    """
    return str(uuid.uuid4())


# =============================================================================
# UTILITAIRES DE COLLECTIONS ET STRUCTURES
# =============================================================================

def safe_get(dictionary: Dict[str, Any], 
             key: str, 
             default: Any = None,
             key_path: str = None) -> Any:
    """
    Récupération sécurisée dans un dictionnaire avec support des chemins
    
    Args:
        dictionary: Dictionnaire source
        key: Clé à récupérer
        default: Valeur par défaut
        key_path: Chemin de clés séparées par '.' (ex: "data.result.value")
    
    Returns:
        Valeur trouvée ou valeur par défaut
    """
    if not isinstance(dictionary, dict):
        return default
    
    try:
        if key_path:
            # Navigation par chemin
            current = dictionary
            for path_key in key_path.split('.'):
                if isinstance(current, dict) and path_key in current:
                    current = current[path_key]
                else:
                    return default
            return current
        else:
            # Récupération simple
            return dictionary.get(key, default)
    except (KeyError, TypeError, AttributeError):
        return default


def merge_dictionaries(*dicts: Dict[str, Any], deep: bool = False) -> Dict[str, Any]:
    """
    Fusionne plusieurs dictionnaires
    
    Args:
        *dicts: Dictionnaires à fusionner
        deep: Fusion profonde (récursive)
    
    Returns:
        Dictionnaire fusionné
    """
    if not dicts:
        return {}
    
    result = {}
    
    for d in dicts:
        if not isinstance(d, dict):
            continue
        
        for key, value in d.items():
            if deep and key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = merge_dictionaries(result[key], value, deep=True)
            else:
                result[key] = value
    
    return result


def flatten_dict(nested_dict: Dict[str, Any], 
                separator: str = '.', 
                prefix: str = '') -> Dict[str, Any]:
    """
    Aplatit un dictionnaire imbriqué
    
    Args:
        nested_dict: Dictionnaire imbriqué
        separator: Séparateur pour les clés
        prefix: Préfixe pour les clés
    
    Returns:
        Dictionnaire aplati
    """
    if not isinstance(nested_dict, dict):
        return {}
    
    result = {}
    
    for key, value in nested_dict.items():
        new_key = f"{prefix}{separator}{key}" if prefix else key
        
        if isinstance(value, dict):
            result.update(flatten_dict(value, separator, new_key))
        else:
            result[new_key] = value
    
    return result


def chunk_list(lst: List[Any], chunk_size: int) -> List[List[Any]]:
    """
    Divise une liste en chunks de taille donnée
    
    Args:
        lst: Liste à diviser
        chunk_size: Taille des chunks
    
    Returns:
        Liste de chunks
    """
    if not lst or chunk_size <= 0:
        return []
    
    return [lst[i:i + chunk_size] for i in range(0, len(lst), chunk_size)]


def deduplicate_list(lst: List[Any], key_func: Callable = None) -> List[Any]:
    """
    Supprime les doublons d'une liste
    
    Args:
        lst: Liste avec doublons
        key_func: Fonction pour extraire la clé de comparaison
    
    Returns:
        Liste sans doublons (ordre préservé)
    """
    if not lst:
        return []
    
    seen = set()
    result = []
    
    for item in lst:
        key = key_func(item) if key_func else item
        
        if key not in seen:
            seen.add(key)
            result.append(item)
    
    return result


def rotate_list(lst: List[Any], positions: int) -> List[Any]:
    """
    Fait une rotation d'une liste
    
    Args:
        lst: Liste à faire tourner
        positions: Nombre de positions (positif = droite, négatif = gauche)
    
    Returns:
        Liste avec rotation appliquée
    """
    if not lst or positions == 0:
        return lst.copy()
    
    n = len(lst)
    positions = positions % n  # Normaliser les positions
    
    return lst[positions:] + lst[:positions]


# =============================================================================
# UTILITAIRES DE VALIDATION ET NETTOYAGE
# =============================================================================

def clean_string(text: str, 
                max_length: int = None, 
                allowed_chars: str = None) -> str:
    """
    Nettoie une chaîne de caractères
    
    Args:
        text: Texte à nettoyer
        max_length: Longueur maximum
        allowed_chars: Regex des caractères autorisés
    
    Returns:
        Texte nettoyé
    """
    if not text or not isinstance(text, str):
        return ""
    
    # Supprimer les caractères de contrôle
    cleaned = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', text)
    
    # Appliquer le filtre de caractères si fourni
    if allowed_chars:
        cleaned = re.sub(f'[^{allowed_chars}]', '', cleaned)
    
    # Nettoyer les espaces multiples
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    
    # Tronquer si nécessaire
    if max_length and len(cleaned) > max_length:
        cleaned = cleaned[:max_length].strip()
    
    return cleaned


def validate_numeric_string(text: str, 
                          numeric_type: str = "float") -> bool:
    """
    Valide qu'une chaîne représente un nombre
    
    Args:
        text: Texte à valider
        numeric_type: Type numérique ("int", "float", "positive", "percentage")
    
    Returns:
        True si valide
    """
    if not text or not isinstance(text, str):
        return False
    
    try:
        if numeric_type == "int":
            int(text)
            return True
        elif numeric_type == "float":
            float(text)
            return True
        elif numeric_type == "positive":
            value = float(text)
            return value >= 0
        elif numeric_type == "percentage":
            value = float(text)
            return 0 <= value <= 100
        else:
            return False
    except (ValueError, TypeError):
        return False


def sanitize_filename(filename: str) -> str:
    """
    Sanitise un nom de fichier pour qu'il soit valide sur tous les OS
    
    Args:
        filename: Nom de fichier à sanitiser
    
    Returns:
        Nom de fichier sécurisé
    """
    if not filename:
        return "unknown_file"
    
    # Caractères interdits sur Windows/Linux/Mac
    forbidden_chars = '<>:"/\\|?*'
    
    # Remplacer les caractères interdits par des underscores
    sanitized = filename
    for char in forbidden_chars:
        sanitized = sanitized.replace(char, '_')
    
    # Supprimer les caractères de contrôle
    sanitized = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', sanitized)
    
    # Limiter la longueur (255 caractères max sur la plupart des systèmes)
    if len(sanitized) > 200:
        name, ext = sanitized.rsplit('.', 1) if '.' in sanitized else (sanitized, '')
        sanitized = name[:190] + ('.' + ext if ext else '')
    
    # Éviter les noms réservés Windows
    reserved_names = {'CON', 'PRN', 'AUX', 'NUL', 'COM1', 'COM2', 'COM3', 'COM4', 
                     'COM5', 'COM6', 'COM7', 'COM8', 'COM9', 'LPT1', 'LPT2', 
                     'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9'}
    
    base_name = sanitized.split('.')[0].upper()
    if base_name in reserved_names:
        sanitized = f"file_{sanitized}"
    
    return sanitized or "unknown_file"


# =============================================================================
# UTILITAIRES DE PERFORMANCE ET MONITORING
# =============================================================================

def measure_execution_time(func: Callable) -> Callable:
    """
    Décorateur pour mesurer le temps d'exécution d'une fonction
    
    Args:
        func: Fonction à mesurer
    
    Returns:
        Fonction décorée qui retourne (résultat, durée_en_secondes)
    """
    def wrapper(*args, **kwargs):
        start_time = time.time()
        try:
            result = func(*args, **kwargs)
            duration = time.time() - start_time
            return result, duration
        except Exception as e:
            duration = time.time() - start_time
            raise e
    
    wrapper.__name__ = func.__name__
    wrapper.__doc__ = func.__doc__
    return wrapper


class ExecutionTimer:
    """Context manager pour mesurer le temps d'exécution"""
    
    def __init__(self, name: str = "operation"):
        self.name = name
        self.start_time = None
        self.duration = None
    
    def __enter__(self):
        self.start_time = time.time()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.duration = time.time() - self.start_time
    
    def get_duration(self) -> float:
        """Retourne la durée mesurée en secondes"""
        return self.duration or 0.0
    
    def get_duration_ms(self) -> float:
        """Retourne la durée mesurée en millisecondes"""
        return (self.duration or 0.0) * 1000


def calculate_rate_per_second(count: int, duration_seconds: float) -> float:
    """
    Calcule un taux par seconde
    
    Args:
        count: Nombre d'opérations
        duration_seconds: Durée en secondes
    
    Returns:
        Taux par seconde
    """
    return safe_divide(count, duration_seconds, 0.0)


def calculate_efficiency_score(successes: int, 
                             total_attempts: int, 
                             time_taken: float,
                             optimal_time: float = None) -> float:
    """
    Calcule un score d'efficacité
    
    Args:
        successes: Nombre de réussites
        total_attempts: Nombre total de tentatives
        time_taken: Temps pris
        optimal_time: Temps optimal (optionnel)
    
    Returns:
        Score d'efficacité (0-1)
    """
    if total_attempts == 0:
        return 0.0
    
    success_rate = successes / total_attempts
    
    if optimal_time and time_taken > 0:
        time_efficiency = min(1.0, optimal_time / time_taken)
        return (success_rate + time_efficiency) / 2
    
    return success_rate


# =============================================================================
# UTILITAIRES DE RETRY ET RESILIENCE
# =============================================================================

def exponential_backoff(attempt: int, 
                       base_delay: float = 1.0, 
                       max_delay: float = 60.0,
                       jitter: bool = True) -> float:
    """
    Calcule un délai d'attente avec backoff exponentiel
    
    Args:
        attempt: Numéro de la tentative (commence à 0)
        base_delay: Délai de base en secondes
        max_delay: Délai maximum
        jitter: Ajouter du jitter aléatoire
    
    Returns:
        Délai d'attente en secondes
    """
    delay = min(base_delay * (2 ** attempt), max_delay)
    
    if jitter:
        # Ajouter ±25% de jitter
        jitter_amount = delay * 0.25 * (2 * secrets.SystemRandom().random() - 1)
        delay = max(0.1, delay + jitter_amount)
    
    return delay


def should_retry(exception: Exception, 
                attempt: int, 
                max_attempts: int,
                retryable_exceptions: Tuple = None) -> bool:
    """
    Détermine si une opération doit être retentée
    
    Args:
        exception: Exception levée
        attempt: Numéro de tentative actuelle
        max_attempts: Nombre maximum de tentatives
        retryable_exceptions: Types d'exceptions à retenter
    
    Returns:
        True si l'opération doit être retentée
    """
    if attempt >= max_attempts:
        return False
    
    if retryable_exceptions:
        return isinstance(exception, retryable_exceptions)
    
    # Exceptions généralement retentables
    retryable_types = (
        ConnectionError,
        TimeoutError,
        # Ajouter d'autres types selon les besoins
    )
    
    return isinstance(exception, retryable_types)


# =============================================================================
# UTILITAIRES JSON ET SÉRIALISATION
# =============================================================================

def safe_json_loads(json_string: str, default: Any = None) -> Any:
    """
    Parse JSON avec gestion d'erreur gracieuse
    
    Args:
        json_string: Chaîne JSON à parser
        default: Valeur par défaut si parsing échoue
    
    Returns:
        Objet Python ou valeur par défaut
    """
    if not json_string:
        return default
    
    try:
        return json.loads(json_string)
    except (json.JSONDecodeError, TypeError, ValueError):
        return default


def safe_json_dumps(obj: Any, default: Any = "N/A", **kwargs) -> str:
    """
    Sérialise en JSON avec gestion d'erreur gracieuse
    
    Args:
        obj: Objet à sérialiser
        default: Valeur par défaut si sérialisation échoue
        **kwargs: Arguments pour json.dumps
    
    Returns:
        Chaîne JSON ou valeur par défaut
    """
    try:
        return json.dumps(obj, default=str, ensure_ascii=False, **kwargs)
    except (TypeError, ValueError):
        return str(default)


# =============================================================================
# UTILITAIRES DE FICHIERS
# =============================================================================

_QUERIES_DIR = None

def load_query(query_name: str) -> Optional[str]:
    """
    Charge une requête SQL depuis le répertoire des requêtes.

    Args:
        query_name: Le nom du fichier de requête (ex: 'get_top_tokens.sql').

    Returns:
        Le contenu de la requête sous forme de chaîne, ou None si non trouvée.
    """
    global _QUERIES_DIR
    if _QUERIES_DIR is None:
        # Construit le chemin vers le dossier 'queries' relatif à ce fichier
        current_dir = os.path.dirname(os.path.abspath(__file__))
        # Remonte d'un niveau (de utils à scanner_wallet) puis va dans api/queries
        _QUERIES_DIR = os.path.join(current_dir, '..', 'api', 'queries')

    query_file_path = os.path.join(_QUERIES_DIR, query_name)

    try:
        with open(query_file_path, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        # Utiliser logger si disponible, sinon print
        try:
            from core.logger import get_logger
            logger = get_logger(__name__)
            logger.error(f"Fichier de requête non trouvé: {query_file_path}")
        except (ImportError, NameError):
            print(f"ERROR: Query file not found: {query_file_path}")
        return None
    except Exception as e:
        try:
            from core.logger import get_logger
            logger = get_logger(__name__)
            logger.error(f"Erreur lors de la lecture du fichier de requête {query_name}: {e}")
        except (ImportError, NameError):
            print(f"ERROR: Could not read query file {query_name}: {e}")
        return None

# =============================================================================
# EXPORT DES FONCTIONS PRINCIPALES
# =============================================================================

__all__ = [
    # Temporel
    'get_current_timestamp', 'get_current_timestamp_ms', 'calculate_time_since',
    'calculate_time_until', 'is_timestamp_recent', 'get_time_bucket', 'sleep_with_jitter',
    
    # Mathématiques
    'safe_divide', 'safe_percentage', 'round_to_precision', 'clamp',
    'calculate_moving_average', 'calculate_percentile',
    
    # Solana
    'parse_solana_amount', 'lamports_to_sol', 'sol_to_lamports',
    'is_native_sol_mint',
    'get_token_program_id',
    
    # Identifiants
    'generate_cycle_id', 'generate_scan_id', 'generate_short_hash', 'generate_uuid',
   
    # Collections
    'safe_get', 'merge_dictionaries', 'flatten_dict', 'chunk_list',
    'deduplicate_list', 'rotate_list',
   
    # Validation et nettoyage
    'clean_string', 'validate_numeric_string', 'sanitize_filename',
   
    # Performance
    'measure_execution_time', 'ExecutionTimer', 'calculate_rate_per_second',
    'calculate_efficiency_score',
   
    # Retry et résilience
    'exponential_backoff', 'should_retry',
   
    # JSON
   'safe_json_loads', 'safe_json_dumps',

   # Fichiers
   'load_query'
]


# =============================================================================
# CLASSES UTILITAIRES AVANCÉES
# =============================================================================

class RateLimiter:
   """Limiteur de taux simple basé sur une fenêtre glissante"""
   
   def __init__(self, max_requests: int, window_seconds: int = 60):
       self.max_requests = max_requests
       self.window_seconds = window_seconds
       self.requests = []
   
   def can_proceed(self) -> bool:
       """Vérifie si une nouvelle requête peut être effectuée"""
       now = time.time()
       
       # Nettoyer les anciennes requêtes
       self.requests = [req_time for req_time in self.requests 
                       if now - req_time < self.window_seconds]
       
       return len(self.requests) < self.max_requests
   
   def record_request(self) -> None:
       """Enregistre une nouvelle requête"""
       self.requests.append(time.time())
   
   def wait_time(self) -> float:
       """Calcule le temps d'attente avant la prochaine requête autorisée"""
       if self.can_proceed():
           return 0.0
       
       if not self.requests:
           return 0.0
       
       oldest_request = min(self.requests)
       return max(0.0, self.window_seconds - (time.time() - oldest_request))
   
   def get_current_rate(self) -> float:
       """Retourne le taux actuel de requêtes par seconde"""
       now = time.time()
       recent_requests = [req for req in self.requests 
                         if now - req < self.window_seconds]
       
       if not recent_requests:
           return 0.0
       
       time_span = now - min(recent_requests)
       if time_span == 0:
           return float('inf')
       
       return len(recent_requests) / time_span


class CircularBuffer:
   """Buffer circulaire pour stocker les dernières N valeurs"""
   
   def __init__(self, size: int):
       self.size = max(1, size)
       self.buffer = []
       self.index = 0
       self.is_full = False
   
   def append(self, item: Any) -> None:
       """Ajoute un élément au buffer"""
       if len(self.buffer) < self.size:
           self.buffer.append(item)
       else:
           self.buffer[self.index] = item
           self.is_full = True
       
       self.index = (self.index + 1) % self.size
   
   def get_all(self) -> List[Any]:
       """Retourne tous les éléments dans l'ordre chronologique"""
       if not self.is_full:
           return self.buffer.copy()
       
       return self.buffer[self.index:] + self.buffer[:self.index]
   
   def get_last(self, n: int = 1) -> List[Any]:
       """Retourne les n derniers éléments"""
       all_items = self.get_all()
       return all_items[-n:] if n <= len(all_items) else all_items
   
   def average(self) -> float:
       """Calcule la moyenne des valeurs numériques"""
       try:
           numeric_values = [float(x) for x in self.buffer if x is not None]
           return sum(numeric_values) / len(numeric_values) if numeric_values else 0.0
       except (ValueError, TypeError):
           return 0.0
   
   def is_empty(self) -> bool:
       """Vérifie si le buffer est vide"""
       return len(self.buffer) == 0
   
   def clear(self) -> None:
       """Vide le buffer"""
       self.buffer.clear()
       self.index = 0
       self.is_full = False


class SimpleCache:
   """Cache simple avec TTL et taille maximum"""
   
   def __init__(self, max_size: int = 1000, default_ttl: int = 3600):
       self.max_size = max_size
       self.default_ttl = default_ttl
       self.cache = {}
       self.access_times = {}
   
   def get(self, key: str, default: Any = None) -> Any:
       """Récupère une valeur du cache"""
       if key not in self.cache:
           return default
       
       value, expiry = self.cache[key]
       
       if time.time() > expiry:
           self.delete(key)
           return default
       
       self.access_times[key] = time.time()
       return value
   
   def set(self, key: str, value: Any, ttl: int = None) -> None:
       """Stocke une valeur dans le cache"""
       if ttl is None:
           ttl = self.default_ttl
       
       expiry = time.time() + ttl
       
       # Nettoyer si nécessaire
       if len(self.cache) >= self.max_size:
           self._evict_expired()
           if len(self.cache) >= self.max_size:
               self._evict_lru()
       
       self.cache[key] = (value, expiry)
       self.access_times[key] = time.time()
   
   def delete(self, key: str) -> bool:
       """Supprime une clé du cache"""
       if key in self.cache:
           del self.cache[key]
           self.access_times.pop(key, None)
           return True
       return False
   
   def clear(self) -> None:
       """Vide complètement le cache"""
       self.cache.clear()
       self.access_times.clear()
   
   def _evict_expired(self) -> None:
       """Supprime les entrées expirées"""
       now = time.time()
       expired_keys = [key for key, (_, expiry) in self.cache.items() if now > expiry]
       for key in expired_keys:
           self.delete(key)
   
   def _evict_lru(self) -> None:
       """Supprime l'entrée la moins récemment utilisée"""
       if not self.access_times:
           return
       
       lru_key = min(self.access_times.keys(), key=lambda k: self.access_times[k])
       self.delete(lru_key)
   
   def size(self) -> int:
       """Retourne le nombre d'entrées dans le cache"""
       return len(self.cache)
   
   def hit_rate(self) -> Dict[str, int]:
       """Retourne des statistiques basiques du cache"""
       return {
           'size': len(self.cache),
           'max_size': self.max_size,
           'utilization': len(self.cache) / self.max_size * 100
       }


class AdaptiveCounter:
   """Compteur adaptatif avec fenêtre glissante et seuils"""
   
   def __init__(self, window_size: int = 100):
       self.window_size = window_size
       self.values = CircularBuffer(window_size)
       self.total_count = 0
   
   def increment(self, value: Union[int, float] = 1) -> None:
       """Incrémente le compteur"""
       self.values.append(float(value))
       self.total_count += 1
   
   def get_average(self) -> float:
       """Retourne la moyenne sur la fenêtre"""
       return self.values.average()
   
   def get_total(self) -> int:
       """Retourne le total depuis la création"""
       return self.total_count
   
   def get_rate_per_second(self, window_seconds: int = 60) -> float:
       """Calcule le taux par seconde sur une fenêtre de temps"""
       recent_values = self.values.get_last(min(window_seconds, self.window_size))
       return len(recent_values) / window_seconds if recent_values else 0.0
   
   def reset(self) -> None:
       """Remet le compteur à zéro"""
       self.values.clear()
       self.total_count = 0


class ConfigValidator:
   """Validateur de configuration avec règles personnalisables"""
   
   def __init__(self):
       self.rules = {}
       self.errors = []
       self.warnings = []
   
   def add_rule(self, key: str, validator: Callable, required: bool = True, warning_only: bool = False):
       """
       Ajoute une règle de validation
       
       Args:
           key: Clé de configuration à valider
           validator: Fonction de validation (retourne bool)
           required: Si la clé est obligatoire
           warning_only: Si les erreurs sont des warnings
       """
       self.rules[key] = {
           'validator': validator,
           'required': required,
           'warning_only': warning_only
       }
   
   def validate(self, config: Dict[str, Any]) -> Tuple[List[str], List[str]]:
       """
       Valide une configuration
       
       Args:
           config: Configuration à valider
       
       Returns:
           Tuple (erreurs, warnings)
       """
       self.errors = []
       self.warnings = []
       
       for key, rule in self.rules.items():
           if key not in config:
               if rule['required']:
                   message = f"Missing required configuration: {key}"
                   if rule['warning_only']:
                       self.warnings.append(message)
                   else:
                       self.errors.append(message)
               continue
           
           try:
               is_valid = rule['validator'](config[key])
               if not is_valid:
                   message = f"Invalid configuration for {key}: {config[key]}"
                   if rule['warning_only']:
                       self.warnings.append(message)
                   else:
                       self.errors.append(message)
           except Exception as e:
               message = f"Validation error for {key}: {e}"
               self.errors.append(message)
       
       return self.errors.copy(), self.warnings.copy()


# =============================================================================
# FONCTIONS UTILITAIRES AVANCÉES
# =============================================================================

def retry_with_backoff(func: Callable, 
                     *args,
                     max_attempts: int = 3,
                     base_delay: float = 1.0,
                     max_delay: float = 60.0,
                     retryable_exceptions: Tuple = None,
                     **kwargs) -> Any:
   """
   Exécute une fonction avec retry et backoff exponentiel
   
   Args:
       func: Fonction à exécuter
       *args: Arguments positionnels pour la fonction
       max_attempts: Nombre maximum de tentatives
       base_delay: Délai de base entre tentatives
       max_delay: Délai maximum
       retryable_exceptions: Types d'exceptions à retenter
       **kwargs: Arguments nommés pour la fonction
   
   Returns:
       Résultat de la fonction
   
   Raises:
       Dernière exception si toutes les tentatives échouent
   """
   last_exception = None
   
   for attempt in range(max_attempts):
       try:
           return func(*args, **kwargs)
       except Exception as e:
           last_exception = e
           
           if not should_retry(e, attempt, max_attempts, retryable_exceptions):
               raise e
           
           if attempt < max_attempts - 1:  # Pas de délai après la dernière tentative
               delay = exponential_backoff(attempt, base_delay, max_delay)
               time.sleep(delay)
   
   raise last_exception


def batch_process(items: List[Any], 
                processor: Callable,
                batch_size: int = 100,
                delay_between_batches: float = 0.0,
                progress_callback: Callable = None) -> List[Any]:
   """
   Traite une liste d'éléments par batches
   
   Args:
       items: Éléments à traiter
       processor: Fonction de traitement (prend une liste d'items)
       batch_size: Taille des batches
       delay_between_batches: Délai entre batches (secondes)
       progress_callback: Callback de progression (batch_index, total_batches)
   
   Returns:
       Liste des résultats de tous les batches
   """
   if not items or batch_size <= 0:
       return []
   
   results = []
   batches = chunk_list(items, batch_size)
   total_batches = len(batches)
   
   for i, batch in enumerate(batches):
       if progress_callback:
           progress_callback(i, total_batches)
       
       try:
           batch_result = processor(batch)
           if isinstance(batch_result, list):
               results.extend(batch_result)
           else:
               results.append(batch_result)
       except Exception as e:
           # Continuer avec les autres batches même en cas d'erreur
           results.append(f"Batch {i} error: {e}")
       
       if delay_between_batches > 0 and i < total_batches - 1:
           time.sleep(delay_between_batches)
   
   return results


def deep_merge_configs(base_config: Dict[str, Any], 
                     override_config: Dict[str, Any]) -> Dict[str, Any]:
   """
   Fusion profonde de configurations avec priorité à l'override
   
   Args:
       base_config: Configuration de base
       override_config: Configuration à surcharger
   
   Returns:
       Configuration fusionnée
   """
   if not isinstance(base_config, dict):
       return override_config.copy() if isinstance(override_config, dict) else {}
   
   if not isinstance(override_config, dict):
       return base_config.copy()
   
   result = base_config.copy()
   
   for key, value in override_config.items():
       if (key in result and 
           isinstance(result[key], dict) and 
           isinstance(value, dict)):
           result[key] = deep_merge_configs(result[key], value)
       else:
           result[key] = value
   
   return result


def create_hash_signature(*args, algorithm: str = "sha256") -> str:
   """
   Crée une signature hash à partir de plusieurs arguments
   
   Args:
       *args: Arguments à hasher
       algorithm: Algorithme de hash ("md5", "sha1", "sha256", "sha512")
   
   Returns:
       Hash hexadécimal
   """
   try:
       hasher = hashlib.new(algorithm)
       
       for arg in args:
           if arg is not None:
               hasher.update(str(arg).encode('utf-8'))
       
       return hasher.hexdigest()
   except Exception:
       # Fallback vers SHA256 si l'algorithme n'est pas supporté
       hasher = hashlib.sha256()
       for arg in args:
           if arg is not None:
               hasher.update(str(arg).encode('utf-8'))
       return hasher.hexdigest()


def parse_duration_string(duration_str: str) -> int:
   """
   Parse une chaîne de durée en secondes
   
   Args:
       duration_str: Durée sous forme de chaîne (ex: "1h30m", "45s", "2d")
   
   Returns:
       Durée en secondes
   """
   if not duration_str or not isinstance(duration_str, str):
       return 0
   
   # Patterns pour différentes unités
   patterns = {
       r'(\d+)d': 86400,  # jours
       r'(\d+)h': 3600,   # heures
       r'(\d+)m': 60,     # minutes
       r'(\d+)s': 1       # secondes
   }
   
   total_seconds = 0
   duration_str = duration_str.lower().strip()
   
   for pattern, multiplier in patterns.items():
       matches = re.findall(pattern, duration_str)
       for match in matches:
           total_seconds += int(match) * multiplier
   
   # Si aucun pattern n'est trouvé, essayer de parser comme un nombre simple
   if total_seconds == 0:
       try:
           total_seconds = int(float(duration_str))
       except (ValueError, TypeError):
           pass
   
   return max(0, total_seconds)


def interpolate_value(value1: float, value2: float, factor: float) -> float:
   """
   Interpole entre deux valeurs
   
   Args:
       value1: Première valeur
       value2: Deuxième valeur
       factor: Facteur d'interpolation (0.0 = value1, 1.0 = value2)
   
   Returns:
       Valeur interpolée
   """
   try:
       factor = clamp(factor, 0.0, 1.0)
       return value1 + (value2 - value1) * factor
   except (TypeError, ValueError):
       return value1


# Mise à jour de __all__ avec les nouvelles classes et fonctions
__all__ = [
   # Temporel
   'get_current_timestamp', 'get_current_timestamp_ms', 'calculate_time_since',
   'calculate_time_until', 'is_timestamp_recent', 'get_time_bucket', 'sleep_with_jitter',
   
   # Mathématiques
   'safe_divide', 'safe_percentage', 'round_to_precision', 'clamp',
   'calculate_moving_average', 'calculate_percentile',
   
   # Solana
   'parse_solana_amount', 'lamports_to_sol', 'sol_to_lamports',
   'validate_wallet_address', 'validate_signature', 'is_native_sol_mint',
   'get_token_program_id',
   
   # Identifiants
   'generate_cycle_id', 'generate_scan_id', 'generate_short_hash', 'generate_uuid',
   
   # Collections
   'safe_get', 'merge_dictionaries', 'flatten_dict', 'chunk_list',
   'deduplicate_list', 'rotate_list',
   
   # Validation et nettoyage
   'clean_string', 'validate_numeric_string', 'sanitize_filename',
   
   # Performance
   'measure_execution_time', 'ExecutionTimer', 'calculate_rate_per_second',
   'calculate_efficiency_score',
   
   # Retry et résilience
   'exponential_backoff', 'should_retry', 'retry_with_backoff',
   
   # JSON
   'safe_json_loads', 'safe_json_dumps',
   
   # Classes utilitaires
   'RateLimiter', 'CircularBuffer', 'SimpleCache', 'AdaptiveCounter', 'ConfigValidator',
   
   # Fonctions avancées
   'batch_process', 'deep_merge_configs', 'create_hash_signature',
   'parse_duration_string', 'interpolate_value'
]
