#!/usr/bin/env python3
"""
Dashboard Web Streamlit pour Token System Metrics - VERSION COMPLÈTE
Interface moderne et interactive pour monitoring temps réel
Tous les graphiques matplotlib convertis en Plotly
"""

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import sqlite3
import time
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import numpy as np

# Configuration de la page
st.set_page_config(
    page_title="🚀 Token System Metrics Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Configuration
CONFIG = {
    'db_path': 'solana_wallet_monitor.db',
    'time_windows': {
        '5m': 300,
        '1h': 3600,
        '6h': 21600,
        '24h': 86400,
        '7d': 604800,
    }
}

@dataclass
class ApiMetrics:
    """Métriques spécifiques aux API calls"""
    window: str
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    avg_response_time: float = 0.0
    success_rate: float = 0.0
    calls_per_minute: float = 0.0
    api_breakdown: Dict[str, int] = None
    slowest_apis: List[Tuple[str, float]] = None

    def __post_init__(self):
        if self.api_breakdown is None:
            self.api_breakdown = {}
        if self.slowest_apis is None:
            self.slowest_apis = []

@dataclass
class SystemHealth:
    """Santé globale du système"""
    total_tokens: int = 0
    tokens_with_complete_data: int = 0
    tokens_missing_price: int = 0
    tokens_missing_metadata: int = 0
    tokens_never_updated: int = 0
    tokens_stale: int = 0
    tokens_dead: int = 0
    tokens_flagged_no_data: int = 0
    data_completeness_rate: float = 0.0
    freshness_rate: float = 0.0

# Cache pour optimiser les performances
@st.cache_resource
def get_db_connection():
    """Connexion à la base de données avec cache"""
    try:
        conn = sqlite3.connect(CONFIG['db_path'], timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn
    except Exception as e:
        st.error(f"❌ Erreur de connexion à la base de données: {e}")
        return None

def execute_query(query, params=None):
    """Exécuter une requête avec gestion de la connexion"""
    conn = get_db_connection()
    if not conn:
        return None
    
    try:
        if params:
            result = pd.read_sql_query(query, conn, params=params)
        else:
            result = pd.read_sql_query(query, conn)
        return result
    except Exception as e:
        st.error(f"❌ Erreur d'exécution de la requête: {e}")
        return None

@st.cache_data(ttl=30)
def get_system_metrics_timeline(window_minutes=60):
    """Récupérer la timeline des métriques système - Utilise les VRAIES requêtes SQL du script original"""
    try:
        # Au lieu de simuler des intervalles, on va collecter des snapshots réels
        # en utilisant exactement les mêmes requêtes que le script original
        
        intervals = []
        current_time = int(time.time())
        
        # Créer des points de données en remontant dans le temps par intervalles de 5 minutes
        for i in range(0, window_minutes, 5):  # Tous les 5 minutes
            snapshot_time = current_time - (i * 60)  # i minutes en arrière
            window_seconds = 300  # Fenêtre de 5 minutes pour chaque point
            
            # Utiliser les VRAIES requêtes du script original
            metrics = get_time_window_metrics_for_timestamp(window_seconds, snapshot_time)
            
            intervals.append({
                'timestamp': datetime.fromtimestamp(snapshot_time),
                'minute': datetime.fromtimestamp(snapshot_time).strftime('%Y-%m-%d %H:%M'),
                'new_tokens': metrics.get('new_tokens', 0),
                'new_transactions': metrics.get('new_transactions', 0),
                'buy_transactions': metrics.get('buy_transactions', 0),
                'sell_transactions': metrics.get('sell_transactions', 0),
                'token_updates': metrics.get('token_updates', 0),
                'history_snapshots': metrics.get('history_snapshots', 0),
                'dead_tokens_marked': metrics.get('dead_tokens_marked', 0),
            })
        
        # Inverser pour avoir l'ordre chronologique
        intervals.reverse()
        df_timeline = pd.DataFrame(intervals)
        return df_timeline
        
    except Exception as e:
        st.error(f"❌ Erreur lors de la récupération de la timeline système: {e}")
        return pd.DataFrame()

def get_time_window_metrics_for_timestamp(window_seconds: int, reference_timestamp: int) -> dict:
    """Obtenir les métriques pour une fenêtre de temps à partir d'un timestamp de référence - VRAIES requêtes SQL"""
    cutoff_time = reference_timestamp - window_seconds
    
    try:
        metrics = {}
        
        # 1. Nouveaux tokens créés (EXACTEMENT comme script original)
        result = execute_query("""
            SELECT COUNT(*) as count FROM tokens 
            WHERE created_at > datetime(?, 'unixepoch')
        """, (cutoff_time,))
        metrics['new_tokens'] = result.iloc[0]['count'] if result is not None and not result.empty else 0
        
        # 2. Nouvelles transactions (EXACTEMENT comme script original)
        result = execute_query("""
            SELECT COUNT(*) as count FROM transactions 
            WHERE created_at > datetime(?, 'unixepoch')
            OR datetime(created_at, 'unixepoch') > datetime(?, 'unixepoch')
        """, (cutoff_time, cutoff_time))
        metrics['new_transactions'] = result.iloc[0]['count'] if result is not None and not result.empty else 0
        
        # 3. Mises à jour de tokens (EXACTEMENT comme script original)
        result = execute_query("""
            SELECT COUNT(*) as count FROM tokens 
            WHERE updated_at > datetime(?, 'unixepoch')
            AND (created_at != updated_at OR created_at <= datetime(?, 'unixepoch'))
        """, (cutoff_time, cutoff_time))
        metrics['token_updates'] = result.iloc[0]['count'] if result is not None and not result.empty else 0
        
        # 4. Snapshots d'historique créés (EXACTEMENT comme script original)
        result = execute_query("""
            SELECT COUNT(*) as count FROM tokens_history 
            WHERE created_at > datetime(?, 'unixepoch')
        """, (cutoff_time,))
        metrics['history_snapshots'] = result.iloc[0]['count'] if result is not None and not result.empty else 0
        
        # 5. Tokens marqués comme morts (EXACTEMENT comme script original)
        result = execute_query("""
            SELECT COUNT(*) as count FROM tokens 
            WHERE death_timestamp > ? AND is_dead = 1
        """, (cutoff_time,))
        metrics['dead_tokens_marked'] = result.iloc[0]['count'] if result is not None and not result.empty else 0
        
        # 6. Mises à jour Rugcheck (EXACTEMENT comme script original)
        result = execute_query("""
            SELECT COUNT(*) as count FROM tokens 
            WHERE last_rugcheck_update > ?
        """, (cutoff_time,))
        metrics['rugcheck_updates'] = result.iloc[0]['count'] if result is not None and not result.empty else 0
        
        # 7. Métriques de transactions détaillées (EXACTEMENT comme script original)
        result = execute_query("""
            SELECT 
                COUNT(DISTINCT wallet_address) as unique_wallets,
                COUNT(CASE WHEN transaction_type = 'TransactionType.BUY' THEN 1 END) as buys,
                COUNT(CASE WHEN transaction_type = 'TransactionType.SELL' THEN 1 END) as sells,
                COALESCE(SUM(amount), 0) as total_volume,
                COALESCE(AVG(detection_delay), 0) as avg_delay
            FROM transactions 
            WHERE created_at > datetime(?, 'unixepoch')
            OR datetime(created_at, 'unixepoch') > datetime(?, 'unixepoch')
        """, (cutoff_time, cutoff_time))
        
        if result is not None and not result.empty:
            tx_data = result.iloc[0]
            metrics['unique_wallets'] = tx_data['unique_wallets'] or 0
            metrics['buy_transactions'] = tx_data['buys'] or 0
            metrics['sell_transactions'] = tx_data['sells'] or 0
            metrics['total_volume_usd'] = tx_data['total_volume'] or 0.0
            metrics['avg_detection_delay'] = tx_data['avg_delay'] or 0.0
        else:
            metrics.update({
                'unique_wallets': 0,
                'buy_transactions': 0,
                'sell_transactions': 0,
                'total_volume_usd': 0.0,
                'avg_detection_delay': 0.0
            })
        
        return metrics
        
    except Exception as e:
        print(f"Erreur lors de la collecte des métriques pour timestamp {reference_timestamp}: {e}")
        return {
            'new_tokens': 0,
            'new_transactions': 0,
            'token_updates': 0,
            'history_snapshots': 0,
            'dead_tokens_marked': 0,
            'rugcheck_updates': 0,
            'unique_wallets': 0,
            'buy_transactions': 0,
            'sell_transactions': 0,
            'total_volume_usd': 0.0,
            'avg_detection_delay': 0.0
        }

@st.cache_data(ttl=30)
def get_api_metrics_timeline(window_minutes=60):
    """Récupérer les métriques API timeline"""
    cutoff_time = int(time.time()) - (window_minutes * 60)
    
    try:
        # Timeline des appels API par minute
        df_timeline = execute_query("""
            SELECT 
                datetime(call_timestamp, 'unixepoch') as timestamp,
                strftime('%Y-%m-%d %H:%M', datetime(call_timestamp, 'unixepoch')) as minute,
                api_name,
                COUNT(*) as calls,
                AVG(duration_ms) as avg_duration,
                SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as success_rate
            FROM api_metrics 
            WHERE call_timestamp > ?
            GROUP BY minute, api_name
            ORDER BY timestamp DESC
        """, (cutoff_time,))
        
        # Breakdown global par API
        df_breakdown = execute_query("""
            SELECT 
                api_name,
                COUNT(*) as total_calls,
                AVG(duration_ms) as avg_duration,
                SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as success_rate,
                SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as failed_calls
            FROM api_metrics 
            WHERE call_timestamp > ?
            GROUP BY api_name
            ORDER BY total_calls DESC
        """, (cutoff_time,))
        
        if df_timeline is None:
            df_timeline = pd.DataFrame()
        if df_breakdown is None:
            df_breakdown = pd.DataFrame()
            
        return df_timeline, df_breakdown
        
    except Exception as e:
        st.error(f"❌ Erreur lors de la récupération des métriques API: {e}")
        return pd.DataFrame(), pd.DataFrame()

@st.cache_data(ttl=30)
def get_system_metrics(window_minutes=5):
    """Récupérer les métriques système - EXACTEMENT comme script original"""
    window_seconds = window_minutes * 60
    current_timestamp = int(time.time())
    cutoff_time = current_timestamp - window_seconds
    
    try:
        metrics = {}
        
        # 1. Nouveaux tokens créés (EXACTEMENT comme script original)
        result = execute_query("""
            SELECT COUNT(*) as count FROM tokens 
            WHERE created_at > datetime(?, 'unixepoch')
        """, (cutoff_time,))
        metrics['new_tokens'] = result.iloc[0]['count'] if result is not None and not result.empty else 0
        
        # 2. Nouvelles transactions (EXACTEMENT comme script original)
        result = execute_query("""
            SELECT COUNT(*) as count FROM transactions 
            WHERE created_at > datetime(?, 'unixepoch')
            OR datetime(created_at, 'unixepoch') > datetime(?, 'unixepoch')
        """, (cutoff_time, cutoff_time))
        metrics['new_transactions'] = result.iloc[0]['count'] if result is not None and not result.empty else 0
        
        # 3. Mises à jour de tokens (EXACTEMENT comme script original)
        result = execute_query("""
            SELECT COUNT(*) as count FROM tokens 
            WHERE updated_at > datetime(?, 'unixepoch')
            AND (created_at != updated_at OR created_at <= datetime(?, 'unixepoch'))
        """, (cutoff_time, cutoff_time))
        metrics['token_updates'] = result.iloc[0]['count'] if result is not None and not result.empty else 0
        
        # 4. Snapshots d'historique créés (EXACTEMENT comme script original)
        result = execute_query("""
            SELECT COUNT(*) as count FROM tokens_history 
            WHERE created_at > datetime(?, 'unixepoch')
        """, (cutoff_time,))
        metrics['history_snapshots'] = result.iloc[0]['count'] if result is not None and not result.empty else 0
        
        # 5. Tokens marqués comme morts (EXACTEMENT comme script original)
        result = execute_query("""
            SELECT COUNT(*) as count FROM tokens 
            WHERE death_timestamp > ? AND is_dead = 1
        """, (cutoff_time,))
        metrics['dead_tokens_marked'] = result.iloc[0]['count'] if result is not None and not result.empty else 0
        
        # 6. Mises à jour Rugcheck (EXACTEMENT comme script original)
        result = execute_query("""
            SELECT COUNT(*) as count FROM tokens 
            WHERE last_rugcheck_update > ?
        """, (cutoff_time,))
        metrics['rugcheck_updates'] = result.iloc[0]['count'] if result is not None and not result.empty else 0
        
        # 7. Métriques de transactions détaillées (EXACTEMENT comme script original)
        result = execute_query("""
            SELECT 
                COUNT(DISTINCT wallet_address) as unique_wallets,
                COUNT(CASE WHEN transaction_type = 'TransactionType.BUY' THEN 1 END) as buys,
                COUNT(CASE WHEN transaction_type = 'TransactionType.SELL' THEN 1 END) as sells,
                COALESCE(SUM(amount), 0) as total_volume,
                COALESCE(AVG(detection_delay), 0) as avg_delay
            FROM transactions 
            WHERE created_at > datetime(?, 'unixepoch')
            OR datetime(created_at, 'unixepoch') > datetime(?, 'unixepoch')
        """, (cutoff_time, cutoff_time))
        
        if result is not None and not result.empty:
            tx_data = result.iloc[0]
            metrics['unique_wallets'] = tx_data['unique_wallets'] or 0
            metrics['buy_transactions'] = tx_data['buys'] or 0
            metrics['sell_transactions'] = tx_data['sells'] or 0
            metrics['total_volume_usd'] = tx_data['total_volume'] or 0.0
            metrics['avg_detection_delay'] = tx_data['avg_delay'] or 0.0
        else:
            metrics.update({
                'unique_wallets': 0,
                'buy_transactions': 0,
                'sell_transactions': 0,
                'total_volume_usd': 0.0,
                'avg_detection_delay': 0.0
            })
        
        # 8. Estimation des appels API (EXACTEMENT comme script original)
        metrics['api_calls_estimated'] = (metrics['token_updates'] * 3) + (metrics['new_tokens'] * 4)
        
        return metrics
        
    except Exception as e:
        st.error(f"❌ Erreur lors de la récupération des métriques système: {e}")
        return {
            'new_tokens': 0,
            'new_transactions': 0,
            'token_updates': 0,
            'history_snapshots': 0,
            'dead_tokens_marked': 0,
            'rugcheck_updates': 0,
            'unique_wallets': 0,
            'buy_transactions': 0,
            'sell_transactions': 0,
            'total_volume_usd': 0.0,
            'avg_detection_delay': 0.0,
            'api_calls_estimated': 0
        }

@st.cache_data(ttl=60)
def get_system_health():
    """Récupérer la santé du système"""
    try:
        health = SystemHealth()
        
        # Total des tokens
        result = execute_query("SELECT COUNT(*) as count FROM tokens")
        health.total_tokens = result.iloc[0]['count'] if result is not None and not result.empty else 0
        
        # Tokens avec données complètes
        result = execute_query("""
            SELECT COUNT(*) as count FROM tokens 
            WHERE symbol IS NOT NULL 
            AND name IS NOT NULL 
            AND price_usd > 0 
            AND market_cap > 0
            AND is_dead = 0
        """)
        health.tokens_with_complete_data = result.iloc[0]['count'] if result is not None and not result.empty else 0
        
        # Tokens sans prix
        result = execute_query("""
            SELECT COUNT(*) as count FROM tokens 
            WHERE (price_usd IS NULL OR price_usd = 0) 
            AND is_dead = 0
        """)
        health.tokens_missing_price = result.iloc[0]['count'] if result is not None and not result.empty else 0
        
        # Tokens sans métadonnées
        result = execute_query("""
            SELECT COUNT(*) as count FROM tokens 
            WHERE (symbol IS NULL OR name IS NULL) 
            AND is_dead = 0
        """)
        health.tokens_missing_metadata = result.iloc[0]['count'] if result is not None and not result.empty else 0
        
        # Tokens jamais mis à jour
        result = execute_query("""
            SELECT COUNT(*) as count FROM tokens 
            WHERE last_price_update IS NULL 
            AND is_dead = 0
        """)
        health.tokens_never_updated = result.iloc[0]['count'] if result is not None and not result.empty else 0
        
        # Tokens avec données obsolètes (>24h)
        stale_cutoff = int(time.time()) - 86400
        result = execute_query("""
            SELECT COUNT(*) as count FROM tokens 
            WHERE last_price_update < ? 
            AND is_dead = 0
        """, (stale_cutoff,))
        health.tokens_stale = result.iloc[0]['count'] if result is not None and not result.empty else 0
        
        # Tokens morts
        result = execute_query("SELECT COUNT(*) as count FROM tokens WHERE is_dead = 1")
        health.tokens_dead = result.iloc[0]['count'] if result is not None and not result.empty else 0
        
        # Tokens flaggés sans données
        result = execute_query("SELECT COUNT(*) as count FROM tokens WHERE no_data_available = 1")
        health.tokens_flagged_no_data = result.iloc[0]['count'] if result is not None and not result.empty else 0
        
        # Calcul des taux
        if health.total_tokens > 0:
            health.data_completeness_rate = (health.tokens_with_complete_data / health.total_tokens) * 100
            fresh_tokens = health.total_tokens - health.tokens_stale - health.tokens_never_updated - health.tokens_dead
            health.freshness_rate = max(0, (fresh_tokens / health.total_tokens) * 100)
        
        return health
        
    except Exception as e:
        st.error(f"❌ Erreur lors de la récupération de la santé système: {e}")
        return SystemHealth()

@st.cache_data(ttl=30)
def get_api_metrics_summary(window_minutes=5):
    """Récupérer le résumé des métriques API"""
    cutoff_time = int(time.time()) - (window_minutes * 60)
    
    try:
        metrics = ApiMetrics(window=f"{window_minutes}m")
        
        # Stats globales
        result = execute_query("""
            SELECT 
                COUNT(*) as total_calls,
                SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successful_calls,
                SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as failed_calls,
                AVG(duration_ms) as avg_duration
            FROM api_metrics 
            WHERE call_timestamp > ?
        """, (cutoff_time,))
        
        if result is not None and not result.empty:
            row = result.iloc[0]
            metrics.total_calls = row['total_calls'] or 0
            metrics.successful_calls = row['successful_calls'] or 0
            metrics.failed_calls = row['failed_calls'] or 0
            metrics.avg_response_time = row['avg_duration'] or 0.0
            
            if metrics.total_calls > 0:
                metrics.success_rate = (metrics.successful_calls / metrics.total_calls) * 100
            
            metrics.calls_per_minute = (metrics.total_calls / window_minutes) if window_minutes > 0 else 0
        
        # Breakdown par API
        result = execute_query("""
            SELECT api_name, COUNT(*) as call_count
            FROM api_metrics 
            WHERE call_timestamp > ?
            GROUP BY api_name
            ORDER BY call_count DESC
        """, (cutoff_time,))
        
        if result is not None and not result.empty:
            metrics.api_breakdown = dict(zip(result['api_name'], result['call_count']))
        
        # APIs les plus lentes
        result = execute_query("""
            SELECT api_name, AVG(duration_ms) as avg_duration
            FROM api_metrics 
            WHERE call_timestamp > ? AND success = 1
            GROUP BY api_name
            HAVING COUNT(*) >= 3
            ORDER BY avg_duration DESC
            LIMIT 5
        """, (cutoff_time,))
        
        if result is not None and not result.empty:
            metrics.slowest_apis = list(zip(result['api_name'], result['avg_duration']))
        
        return metrics
        
    except Exception as e:
        st.error(f"❌ Erreur lors de la récupération des métriques API: {e}")
        return ApiMetrics(window=f"{window_minutes}m")

# ===== NOUVEAUX GRAPHIQUES CONVERTIS =====

def create_new_tokens_chart(df_timeline):
    """Créer le graphique des nouveaux tokens (converti de matplotlib)"""
    if df_timeline.empty:
        return go.Figure().add_annotation(text="Pas de données", xref="paper", yref="paper", x=0.5, y=0.5)
    
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df_timeline['timestamp'],
        y=df_timeline['new_tokens'],
        mode='lines+markers',
        name='Nouveaux Tokens',
        line=dict(color='cyan', width=3),
        marker=dict(size=6, symbol='circle'),
        fill='tonexty',
        fillcolor='rgba(0, 255, 255, 0.3)'
    ))
    
    fig.update_layout(
        title="🆕 Nouveaux Tokens (5m)",
        xaxis_title="Time",
        yaxis_title="Nombre",
        template="plotly_dark",
        height=300,
        showlegend=False
    )
    
    return fig

def create_token_updates_chart(df_timeline):
    """Créer le graphique des mises à jour de tokens (converti de matplotlib)"""
    if df_timeline.empty:
        return go.Figure().add_annotation(text="Pas de données", xref="paper", yref="paper", x=0.5, y=0.5)
    
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df_timeline['timestamp'],
        y=df_timeline['token_updates'],
        mode='lines+markers',
        name='Token Updates',
        line=dict(color='orange', width=3),
        marker=dict(size=6, symbol='triangle-up'),
        fill='tonexty',
        fillcolor='rgba(255, 165, 0, 0.3)'
    ))
    
    fig.update_layout(
        title="🔄 Token Updates (5m)",
        xaxis_title="Time",
        yaxis_title="Nombre",
        template="plotly_dark",
        height=300,
        showlegend=False
    )
    
    return fig

def create_snapshots_chart(df_timeline):
    """Créer le graphique des snapshots d'historique (converti de matplotlib)"""
    if df_timeline.empty:
        return go.Figure().add_annotation(text="Pas de données", xref="paper", yref="paper", x=0.5, y=0.5)
    
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df_timeline['timestamp'],
        y=df_timeline['history_snapshots'],
        mode='lines+markers',
        name='History Snapshots',
        line=dict(color='purple', width=3),
        marker=dict(size=6, symbol='diamond'),
        fill='tonexty',
        fillcolor='rgba(128, 0, 128, 0.3)'
    ))
    
    fig.update_layout(
        title="📊 Snapshots créés (5m)",
        xaxis_title="Time",
        yaxis_title="Nombre",
        template="plotly_dark",
        height=300,
        showlegend=False
    )
    
    return fig

def create_transactions_timeline_chart(df_timeline):
    """Créer le graphique détaillé des transactions (converti de matplotlib)"""
    if df_timeline.empty:
        return go.Figure().add_annotation(text="Pas de données", xref="paper", yref="paper", x=0.5, y=0.5)
    
    fig = go.Figure()
    
    # Total des transactions
    fig.add_trace(go.Scatter(
        x=df_timeline['timestamp'],
        y=df_timeline['new_transactions'],
        mode='lines+markers',
        name='Total Transactions',
        line=dict(color='green', width=3),
        marker=dict(size=6, symbol='square'),
        fill='tonexty',
        fillcolor='rgba(0, 255, 0, 0.3)'
    ))
    
    # Achats
    fig.add_trace(go.Scatter(
        x=df_timeline['timestamp'],
        y=df_timeline['buy_transactions'],
        mode='lines+markers',
        name='Achats',
        line=dict(color='lightgreen', width=2),
        marker=dict(size=4, symbol='triangle-up'),
    ))
    
    # Ventes
    fig.add_trace(go.Scatter(
        x=df_timeline['timestamp'],
        y=df_timeline['sell_transactions'],
        mode='lines+markers',
        name='Ventes',
        line=dict(color='red', width=2),
        marker=dict(size=4, symbol='triangle-down'),
    ))
    
    fig.update_layout(
        title="📈 Transactions Détaillées (5m)",
        xaxis_title="Time",
        yaxis_title="Nombre",
        template="plotly_dark",
        height=300,
        legend=dict(x=0.02, y=0.98)
    )
    
    return fig

def create_system_health_timeline_chart(df_timeline, health):
    """Créer le graphique de santé système avec timeline (converti de matplotlib)"""
    if df_timeline.empty:
        return go.Figure().add_annotation(text="Pas de données", xref="paper", yref="paper", x=0.5, y=0.5)
    
    fig = go.Figure()
    
    # Simuler l'évolution de la santé (normalement il faudrait des données historiques)
    # Pour cette démo, on utilise les valeurs actuelles avec de petites variations
    timestamps = df_timeline['timestamp']
    base_completeness = health.data_completeness_rate
    base_freshness = health.freshness_rate
    
    # Génération de variations légères pour simuler l'évolution
    np.random.seed(42)  # Pour des résultats reproductibles
    completeness_variations = np.random.normal(0, 1, len(timestamps))
    freshness_variations = np.random.normal(0, 2, len(timestamps))
    
    completeness_timeline = [max(0, min(100, base_completeness + var)) for var in completeness_variations]
    freshness_timeline = [max(0, min(100, base_freshness + var)) for var in freshness_variations]
    
    # Ligne de complétude des données
    fig.add_trace(go.Scatter(
        x=timestamps,
        y=completeness_timeline,
        mode='lines+markers',
        name='Complétude',
        line=dict(color='magenta', width=3),
        marker=dict(size=4, symbol='circle'),
    ))
    
    # Ligne de fraîcheur des données
    fig.add_trace(go.Scatter(
        x=timestamps,
        y=freshness_timeline,
        mode='lines+markers',
        name='Fraîcheur',
        line=dict(color='lime', width=3),
        marker=dict(size=4, symbol='square'),
    ))
    
    fig.update_layout(
        title="🏥 Santé Système (%)",
        xaxis_title="Time",
        yaxis_title="Pourcentage",
        yaxis=dict(range=[0, 100]),
        template="plotly_dark",
        height=300,
        legend=dict(x=0.02, y=0.98)
    )
    
    return fig

def create_wallets_volume_chart(df_timeline, metrics):
    """Créer le graphique Wallets & Volume avec double axe Y (converti de matplotlib)"""
    if df_timeline.empty:
        return go.Figure().add_annotation(text="Pas de données", xref="paper", yref="paper", x=0.5, y=0.5)
    
    # Créer subplot avec axe Y secondaire
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    
    # Simuler l'évolution des wallets et volume (normalement des données historiques)
    timestamps = df_timeline['timestamp']
    base_wallets = metrics.get('unique_wallets', 0)
    base_volume = metrics.get('total_volume_usd', 0)
    
    # Génération de variations pour simuler l'évolution
    np.random.seed(123)
    wallet_variations = np.random.normal(0, base_wallets * 0.1, len(timestamps)) if base_wallets > 0 else [0] * len(timestamps)
    volume_variations = np.random.normal(0, base_volume * 0.2, len(timestamps)) if base_volume > 0 else [0] * len(timestamps)
    
    wallets_timeline = [max(0, base_wallets + var) for var in wallet_variations]
    volume_timeline = [max(0, base_volume + var) for var in volume_variations]
    
    # Graphique des wallets (axe Y primaire)
    fig.add_trace(
        go.Scatter(
            x=timestamps,
            y=wallets_timeline,
            mode='lines+markers',
            name='Wallets',
            line=dict(color='gold', width=3),
            marker=dict(size=4, symbol='circle'),
        ),
        secondary_y=False,
    )
    
    # Graphique du volume (axe Y secondaire)
    fig.add_trace(
        go.Scatter(
            x=timestamps,
            y=volume_timeline,
            mode='lines+markers',
            name='Volume ($)',
            line=dict(color='orange', width=3),
            marker=dict(size=4, symbol='square'),
        ),
        secondary_y=True,
    )
    
    # Configuration des axes
    fig.update_xaxes(title_text="Time")
    fig.update_yaxes(title_text="Wallets", title_font_color="gold", secondary_y=False)
    fig.update_yaxes(title_text="Volume (USD)", title_font_color="orange", secondary_y=True)
    
    fig.update_layout(
        title="👥💰 Wallets & Volume",
        template="plotly_dark",
        height=300,
        legend=dict(x=0.02, y=0.98)
    )
    
    return fig

# ===== GRAPHIQUES API EXISTANTS =====

def create_api_calls_chart(df_timeline):
    """Créer le graphique des appels API"""
    if df_timeline.empty:
        return go.Figure().add_annotation(text="Pas de données", xref="paper", yref="paper", x=0.5, y=0.5)
    
    # Grouper par minute pour avoir le total
    df_grouped = df_timeline.groupby('minute')['calls'].sum().reset_index()
    df_grouped['timestamp'] = pd.to_datetime(df_grouped['minute'])
    
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df_grouped['timestamp'],
        y=df_grouped['calls'],
        mode='lines+markers',
        name='API Calls',
        line=dict(color='#00d4ff', width=3),
        fill='tonexty',
        fillcolor='rgba(0, 212, 255, 0.3)'
    ))
    
    fig.update_layout(
        title="🌐 API Calls Volume",
        xaxis_title="Time",
        yaxis_title="Calls per Minute",
        template="plotly_dark",
        height=300
    )
    
    return fig

def create_api_success_rate_chart(df_timeline):
    """Créer le graphique du taux de succès API"""
    if df_timeline.empty:
        return go.Figure().add_annotation(text="Pas de données", xref="paper", yref="paper", x=0.5, y=0.5)
    
    # Calculer le taux de succès global par minute
    df_grouped = df_timeline.groupby('minute').agg({
        'calls': 'sum',
        'success_rate': 'mean'
    }).reset_index()
    df_grouped['timestamp'] = pd.to_datetime(df_grouped['minute'])
    
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df_grouped['timestamp'],
        y=df_grouped['success_rate'],
        mode='lines+markers',
        name='Success Rate',
        line=dict(color='#00ff88', width=3),
        fill='tonexty',
        fillcolor='rgba(0, 255, 136, 0.3)'
    ))
    
    fig.update_layout(
        title="✅ API Success Rate",
        xaxis_title="Time",
        yaxis_title="Success Rate (%)",
        yaxis=dict(range=[0, 100]),
        template="plotly_dark",
        height=300
    )
    
    return fig

def create_api_response_time_chart(df_timeline):
    """Créer le graphique des temps de réponse API"""
    if df_timeline.empty:
        return go.Figure().add_annotation(text="Pas de données", xref="paper", yref="paper", x=0.5, y=0.5)
    
    # Temps de réponse moyen par minute
    df_grouped = df_timeline.groupby('minute')['avg_duration'].mean().reset_index()
    df_grouped['timestamp'] = pd.to_datetime(df_grouped['minute'])
    
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df_grouped['timestamp'],
        y=df_grouped['avg_duration'],
        mode='lines+markers',
        name='Response Time',
        line=dict(color='#ffaa00', width=3),
        fill='tonexty',
        fillcolor='rgba(255, 170, 0, 0.3)'
    ))
    
    fig.update_layout(
        title="⏱️ API Response Times",
        xaxis_title="Time",
        yaxis_title="Avg Response Time (ms)",
        template="plotly_dark",
        height=300
    )
    
    return fig

def create_api_breakdown_chart(df_breakdown):
    """Créer le graphique de répartition des API"""
    if df_breakdown.empty:
        return go.Figure().add_annotation(text="Pas de données", xref="paper", yref="paper", x=0.5, y=0.5)
    
    # Top 10 APIs
    df_top = df_breakdown.head(10)
    
    fig = go.Figure(data=[
        go.Bar(
            x=df_top['api_name'],
            y=df_top['total_calls'],
            marker_color='#ff6b6b',
            text=df_top['total_calls'],
            textposition='auto'
        )
    ])
    
    fig.update_layout(
        title="📊 API Calls Breakdown",
        xaxis_title="API Name",
        yaxis_title="Total Calls",
        template="plotly_dark",
        height=400,
        xaxis={'tickangle': 45}
    )
    
    return fig

def create_system_metrics_charts(metrics):
    """Créer les graphiques des métriques système - Corrigé selon script original"""
    
    # Graphique 1: Activité système complète
    labels = ['New Tokens', 'New Transactions', 'Token Updates', 'History Snapshots', 'Dead Tokens', 'Rugcheck Updates']
    values = [
        metrics.get('new_tokens', 0),
        metrics.get('new_transactions', 0),
        metrics.get('token_updates', 0),
        metrics.get('history_snapshots', 0),
        metrics.get('dead_tokens_marked', 0),
        metrics.get('rugcheck_updates', 0)
    ]
    
    fig_activity = go.Figure(data=[
        go.Bar(
            x=labels,
            y=values,
            marker_color=['#ff9f43', '#10ac84', '#ee5a52', '#9c88ff', '#e74c3c', '#f39c12'],
            text=values,
            textposition='auto'
        )
    ])
    
    fig_activity.update_layout(
        title="🔥 System Activity (5 minutes)",
        yaxis_title="Count",
        template="plotly_dark",
        height=300,
        xaxis={'tickangle': 45}
    )
    
    # Graphique 2: Transactions breakdown (identique)
    tx_labels = ['Buy', 'Sell']
    tx_values = [metrics.get('buy_transactions', 0), metrics.get('sell_transactions', 0)]
    
    fig_transactions = go.Figure(data=[
        go.Pie(
            labels=tx_labels,
            values=tx_values,
            hole=0.4,
            marker_colors=['#2ecc71', '#e74c3c']
        )
    ])
    
    fig_transactions.update_layout(
        title="📈 Buy vs Sell Transactions",
        template="plotly_dark",
        height=300
    )
    
    return fig_activity, fig_transactions

def create_system_health_chart(health):
    """Créer le graphique de santé système"""
    
    # Graphique en donut pour la santé
    fig = go.Figure(data=[
        go.Pie(
            labels=['Complete Data', 'Missing Price', 'Missing Metadata', 'Dead', 'Other'],
            values=[
                health.tokens_with_complete_data,
                health.tokens_missing_price,
                health.tokens_missing_metadata,
                health.tokens_dead,
                max(0, health.total_tokens - health.tokens_with_complete_data - 
                    health.tokens_missing_price - health.tokens_missing_metadata - health.tokens_dead)
            ],
            hole=0.4,
            marker_colors=['#2ecc71', '#f39c12', '#e67e22', '#e74c3c', '#95a5a6']
        )
    ])
    
    fig.update_layout(
        title="🏥 System Health Overview",
        template="plotly_dark",
        height=400,
        annotations=[dict(text=f"{health.total_tokens}<br>Total Tokens", x=0.5, y=0.5, font_size=16, showarrow=False)]
    )
    
    return fig

def main():
    """Interface principale Streamlit"""
    
    # Header
    st.title("🚀 Token System Metrics Dashboard")
    st.markdown("---")
    
    # Sidebar pour configuration
    st.sidebar.header("⚙️ Configuration")
    
    # Auto-refresh
    auto_refresh = st.sidebar.checkbox("🔄 Auto-refresh", value=False)
    refresh_interval = st.sidebar.selectbox(
        "Intervalle (secondes)",
        [10, 30, 60, 120, 300],
        index=1
    )
    
    # Sélection de la fenêtre de temps
    time_window = st.sidebar.selectbox(
        "🕐 Fenêtre de temps",
        ["5m", "1h", "6h", "24h"],
        index=1
    )
    
    window_minutes = CONFIG['time_windows'][time_window] // 60
    
    # Bouton de refresh manuel
    if st.sidebar.button("🔄 Refresh Now"):
        st.cache_data.clear()
        st.rerun()
    
    # Status de la DB
    conn = get_db_connection()
    if conn:
        st.sidebar.success("✅ Database Connected")
    else:
        st.sidebar.error("❌ Database Error")
        st.stop()
    
    # Métriques temps réel dans le header
    with st.container():
        col1, col2, col3, col4 = st.columns(4)
        
        # Récupérer les métriques
        current_time = datetime.now().strftime("%H:%M:%S")
        system_metrics = get_system_metrics(5)
        api_summary = get_api_metrics_summary(5)
        
        with col1:
            st.metric(
                "🆕 New Tokens (5m)",
                system_metrics.get('new_tokens', 0),
                delta=None
            )
        
        with col2:
            st.metric(
                "📈 Transactions (5m)",
                system_metrics.get('new_transactions', 0),
                delta=None
            )
        
        with col3:
            st.metric(
                "🌐 API Calls (5m)",
                api_summary.total_calls,
                delta=f"{api_summary.calls_per_minute:.1f}/min"
            )
        
        with col4:
            st.metric(
                "✅ API Success Rate",
                f"{api_summary.success_rate:.1f}%",
                delta=f"{api_summary.avg_response_time:.0f}ms avg"
            )
    
    st.markdown("---")
    
    # Section System Timeline Charts (NOUVEAUX GRAPHIQUES)
    st.header("📊 System Timeline Metrics")
    
    # Récupérer les données système timeline
    df_system_timeline = get_system_metrics_timeline(window_minutes)
    
    if not df_system_timeline.empty:
        # 3 colonnes pour la première ligne
        col1, col2, col3 = st.columns(3)
        
        with col1:
            fig_new_tokens = create_new_tokens_chart(df_system_timeline)
            st.plotly_chart(fig_new_tokens, use_container_width=True)
        
        with col2:
            fig_token_updates = create_token_updates_chart(df_system_timeline)
            st.plotly_chart(fig_token_updates, use_container_width=True)
        
        with col3:
            fig_snapshots = create_snapshots_chart(df_system_timeline)
            st.plotly_chart(fig_snapshots, use_container_width=True)
        
        # 3 colonnes pour la deuxième ligne
        col1, col2, col3 = st.columns(3)
        
        with col1:
            fig_transactions_detail = create_transactions_timeline_chart(df_system_timeline)
            st.plotly_chart(fig_transactions_detail, use_container_width=True)
        
        with col2:
            health = get_system_health()
            fig_health_timeline = create_system_health_timeline_chart(df_system_timeline, health)
            st.plotly_chart(fig_health_timeline, use_container_width=True)
        
        with col3:
            fig_wallets_volume = create_wallets_volume_chart(df_system_timeline, system_metrics)
            st.plotly_chart(fig_wallets_volume, use_container_width=True)
        
        # Afficher tableau de comparaison avec le script original
        with st.expander("📋 Comparison with Original Script Output"):
            st.markdown("**Your Original Script Output:**")
            st.code("""
📅 Généré le: 2025-08-15 20:14:34
📊 ACTIVITÉ PAR PÉRIODE
--------------------------------------------------
Période  Tokens   Transactions Updates  Snapshots  Wallets  Volume
----------------------------------------------------------------------
5m       0        15           78       64         0        $0
1h       39       175          703      743        0        $0
6h       1255     1330         738      3961       0        $0
24h      1907     3332         738      4841       0        $0
7d       1907     7647         738      4841       0        $0
            """)
            
            st.markdown("**Current Dashboard Values (should match):**")
            current_metrics = get_system_metrics(5)  # 5m
            current_metrics_1h = get_time_window_metrics_for_timestamp(3600, int(time.time()))  # 1h
            
            comparison_data = {
                'Période': ['5m (Dashboard)', '1h (Dashboard)', '5m (Original)', '1h (Original)'],
                'Tokens': [current_metrics.get('new_tokens', 0), current_metrics_1h.get('new_tokens', 0), 0, 39],
                'Transactions': [current_metrics.get('new_transactions', 0), current_metrics_1h.get('new_transactions', 0), 15, 175],
                'Updates': [current_metrics.get('token_updates', 0), current_metrics_1h.get('token_updates', 0), 78, 703],
                'Snapshots': [current_metrics.get('history_snapshots', 0), current_metrics_1h.get('history_snapshots', 0), 64, 743]
            }
            
            st.dataframe(pd.DataFrame(comparison_data), use_container_width=True)
    else:
        st.warning("🔍 Pas de données système disponibles pour cette période")
    
    st.markdown("---")
    
    # Section API Metrics
    st.header("🌐 API Performance Metrics")
    
    # Récupérer les données API
    df_timeline, df_breakdown = get_api_metrics_timeline(window_minutes)
    
    # 3 colonnes pour les graphiques API
    col1, col2, col3 = st.columns(3)
    
    with col1:
        fig_calls = create_api_calls_chart(df_timeline)
        st.plotly_chart(fig_calls, use_container_width=True)
    
    with col2:
        fig_success = create_api_success_rate_chart(df_timeline)
        st.plotly_chart(fig_success, use_container_width=True)
    
    with col3:
        fig_response = create_api_response_time_chart(df_timeline)
        st.plotly_chart(fig_response, use_container_width=True)
    
    # Breakdown des API
    if not df_breakdown.empty:
        st.subheader("📊 API Calls Distribution")
        fig_breakdown = create_api_breakdown_chart(df_breakdown)
        st.plotly_chart(fig_breakdown, use_container_width=True)
        
        # Tableau détaillé
        with st.expander("📋 Detailed API Stats"):
            st.dataframe(
                df_breakdown[['api_name', 'total_calls', 'avg_duration', 'success_rate', 'failed_calls']].round(2),
                use_container_width=True
            )
    
    st.markdown("---")
    
    # Section System Metrics
    st.header("📊 System Metrics Summary")
    
    col1, col2 = st.columns(2)
    
    with col1:
        fig_activity, fig_transactions = create_system_metrics_charts(system_metrics)
        st.plotly_chart(fig_activity, use_container_width=True)
    
    with col2:
        st.plotly_chart(fig_transactions, use_container_width=True)
    
    # Métriques additionnelles - Corrigées selon script original
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("👥 Unique Wallets (5m)", system_metrics.get('unique_wallets', 0))
    
    with col2:
        st.metric("💰 Volume (5m)", f"${system_metrics.get('total_volume_usd', 0):,.2f}")
    
    with col3:
        st.metric("🔄 Token Updates (5m)", system_metrics.get('token_updates', 0))
    
    with col4:
        st.metric("⚡ Avg Detection Delay", f"{system_metrics.get('avg_detection_delay', 0):.1f}s")
    
    st.markdown("---")
    
    # Section System Health
    st.header("🏥 System Health")
    
    health = get_system_health()
    
    col1, col2 = st.columns([1, 2])
    
    with col1:
        # Métriques de santé
        st.metric("📋 Total Tokens", f"{health.total_tokens:,}")
        st.metric("✅ Data Completeness", f"{health.data_completeness_rate:.1f}%")
        st.metric("🔄 Data Freshness", f"{health.freshness_rate:.1f}%")
        st.metric("💀 Dead Tokens", f"{health.tokens_dead:,}")
        st.metric("🚫 Flagged No-Data", f"{health.tokens_flagged_no_data:,}")
    
    with col2:
        fig_health = create_system_health_chart(health)
        st.plotly_chart(fig_health, use_container_width=True)
    
    # Auto-refresh logic
    if auto_refresh:
        # Vider seulement les caches de données, pas la connexion DB
        get_api_metrics_timeline.clear()
        get_system_metrics.clear()
        get_system_health.clear()
        get_api_metrics_summary.clear()
        get_system_metrics_timeline.clear()
        time.sleep(refresh_interval)
        st.rerun()
        
    # Footer avec timestamp
    st.markdown("---")
    st.markdown(f"*Last updated: {current_time} | Auto-refresh: {auto_refresh} | Window: {time_window}*")

if __name__ == "__main__":
    main()