import sqlite3
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
import time
import numpy as np
from typing import Dict, List, Optional
from dataclasses import dataclass
import sys
import os
from pathlib import Path

# Ajouter la racine du projet au path pour accéder aux modules de config
project_root = Path(__file__).parent.parent.parent.absolute()  # Remonter de 2 niveaux depuis pages/
sys.path.insert(0, str(project_root))

# Import du système de configuration
try:
    from core.config import get_config
    
    # Charger la configuration
    config = get_config()
    DEFAULT_DB_PATH = config.database.get_full_path()
    
except ImportError:
    # Fallback si le système de config n'est pas disponible
    DEFAULT_DB_PATH = os.getenv('REALTIME_MONITORING_DB_PATH', 'database/data/solana_wallet.db')
    st.warning("⚠️ Système de configuration non disponible, utilisation du fallback")
except Exception as e:
    DEFAULT_DB_PATH = 'database/data/solana_wallet.db'
    st.error(f"❌ Erreur chargement config: {e}")

# Configuration globale
CONFIG = {
    'db_path': DEFAULT_DB_PATH,
    'time_windows': {
        '5m': 300,
        '1h': 3600,
        '6h': 21600,
        '24h': 86400,
        '7d': 604800
    }
}

# Configuration Streamlit
st.set_page_config(
    page_title="📊 Monitoring Temps Réel",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# CSS pour améliorer l'apparence
st.markdown("""
<style>
.metric-row {
    display: flex;
    justify-content: space-between;
    margin: 1rem 0;
}

.metric-card {
    background-color: #f0f2f6;
    padding: 1rem;
    border-radius: 0.5rem;
    border-left: 4px solid #ff4b4b;
    margin: 0.5rem;
    flex: 1;
}

.positive {
    color: #00ff00;
    font-weight: bold;
}

.negative {
    color: #ff0000;
    font-weight: bold;
}

.neutral {
    color: #888888;
}

.status-healthy {
    color: #00ff00;
}

.status-warning {
    color: #ffa500;
}

.status-critical {
    color: #ff0000;
}
</style>
""", unsafe_allow_html=True)

@dataclass
class SystemHealth:
    """Structure pour les métriques de santé système"""
    total_tokens: int = 0
    tokens_with_complete_data: int = 0
    tokens_missing_price: int = 0
    tokens_missing_metadata: int = 0
    tokens_never_updated: int = 0
    tokens_stale: int = 0
    tokens_dead: int = 0
    tokens_flagged_no_data: int = 0
    tokens_rugged: int = 0
    tokens_recently_updated: int = 0
    tokens_outdated: int = 0
    tokens_unknown_symbol: int = 0
    tokens_no_data_available: int = 0
    data_completeness_rate: float = 0.0
    freshness_rate: float = 0.0

@st.cache_resource
def get_db_connection():
    """Connexion à la base de données avec st.connection (thread-safe)"""
    try:
        db_path = CONFIG.get('db_path', DEFAULT_DB_PATH)
        # Utiliser st.connection pour SQLite
        conn = st.connection(
            "metrics_db",
            type="sql", 
            url=f"sqlite:///{db_path}",
            autocommit=True
        )
        return conn
    except Exception as e:
        st.error(f"❌ Erreur connexion DB avec st.connection: {e}")
        return None

@st.cache_data(ttl=60)
def get_system_metrics(window_minutes):
    """Récupère les métriques système - Version corrigée"""
    conn = get_db_connection()
    if not conn:
        return {}
    
    try:
        cutoff_timestamp = int(time.time()) - (window_minutes * 60)
        
        # Nouveaux tokens
        df_new_tokens = conn.query(
            "SELECT COUNT(*) as count FROM tokens WHERE created_at > datetime(:cutoff, 'unixepoch')",
            params={"cutoff": cutoff_timestamp}
        )
        new_tokens = int(df_new_tokens['count'].iloc[0]) if not df_new_tokens.empty else 0
        
        # Nouvelles transactions
        df_new_transactions = conn.query("""
            SELECT COUNT(*) as count FROM transactions 
            WHERE created_at > datetime(:cutoff, 'unixepoch')
            OR datetime(created_at, 'unixepoch') > datetime(:cutoff, 'unixepoch')
        """, params={"cutoff": cutoff_timestamp})
        new_transactions = int(df_new_transactions['count'].iloc[0]) if not df_new_transactions.empty else 0
        
        # Token updates
        df_token_updates = conn.query("""
            SELECT COUNT(*) as count FROM tokens 
            WHERE updated_at > datetime(:cutoff, 'unixepoch')
            AND (created_at != updated_at OR created_at <= datetime(:cutoff, 'unixepoch'))
        """, params={"cutoff": cutoff_timestamp})
        token_updates = int(df_token_updates['count'].iloc[0]) if not df_token_updates.empty else 0
        
        # History snapshots
        df_snapshots = conn.query("""
            SELECT COUNT(*) as count FROM tokens_history 
            WHERE created_at > datetime(:cutoff, 'unixepoch')
        """, params={"cutoff": cutoff_timestamp})
        history_snapshots = int(df_snapshots['count'].iloc[0]) if not df_snapshots.empty else 0
        
        # Métriques de transactions détaillées
        df_tx_metrics = conn.query("""
            SELECT 
                COUNT(DISTINCT wallet_address) as unique_wallets,
                COUNT(CASE WHEN transaction_type = 'TransactionType.BUY' THEN 1 END) as buys,
                COUNT(CASE WHEN transaction_type = 'TransactionType.SELL' THEN 1 END) as sells,
                COALESCE(SUM(amount), 0) as total_volume,
                COALESCE(AVG(detection_delay), 0) as avg_delay
            FROM transactions 
            WHERE created_at > datetime(:cutoff, 'unixepoch')
            OR datetime(created_at, 'unixepoch') > datetime(:cutoff, 'unixepoch')
        """, params={"cutoff": cutoff_timestamp})
        
        if not df_tx_metrics.empty:
            tx_row = df_tx_metrics.iloc[0]
            unique_wallets = int(tx_row['unique_wallets'] or 0)
            buy_transactions = int(tx_row['buys'] or 0)
            sell_transactions = int(tx_row['sells'] or 0)
            total_volume_usd = float(tx_row['total_volume'] or 0.0)
            avg_detection_delay = float(tx_row['avg_delay'] or 0.0)
        else:
            unique_wallets = buy_transactions = sell_transactions = 0
            total_volume_usd = avg_detection_delay = 0.0
        
        return {
            'new_tokens': new_tokens,
            'new_transactions': new_transactions,
            'token_updates': token_updates,
            'history_snapshots': history_snapshots,
            'unique_wallets': unique_wallets,
            'buy_transactions': buy_transactions,
            'sell_transactions': sell_transactions,
            'total_volume_usd': total_volume_usd,
            'avg_detection_delay': avg_detection_delay
        }
        
    except Exception as e:
        st.error(f"❌ Erreur get_system_metrics: {e}")
        return {}

@st.cache_data(ttl=300)
def get_system_health():
    """Récupère la santé globale du système - Version corrigée"""
    conn = get_db_connection()
    if not conn:
        return None
    
    try:
        # Total tokens
        df_total = conn.query("SELECT COUNT(*) as count FROM tokens")
        total_tokens = int(df_total['count'].iloc[0]) if not df_total.empty else 0
        
        # Tokens avec données complètes
        df_complete = conn.query("""
            SELECT COUNT(*) as count FROM tokens 
            WHERE symbol IS NOT NULL 
            AND name IS NOT NULL 
            AND price_usd > 0 
            AND market_cap > 0
            AND is_dead = 0
        """)
        tokens_with_complete_data = int(df_complete['count'].iloc[0]) if not df_complete.empty else 0
        
        # Tokens morts
        df_dead = conn.query("SELECT COUNT(*) as count FROM tokens WHERE is_dead = 1")
        tokens_dead = int(df_dead['count'].iloc[0]) if not df_dead.empty else 0
        
        # Tokens flaggés sans données
        df_flagged = conn.query("SELECT COUNT(*) as count FROM tokens WHERE no_data_available = 1")
        tokens_flagged_no_data = int(df_flagged['count'].iloc[0]) if not df_flagged.empty else 0
        
        # Tokens ruggés
        df_rugged = conn.query("SELECT COUNT(*) as count FROM tokens WHERE is_rugged = 1")
        tokens_rugged = int(df_rugged['count'].iloc[0]) if not df_rugged.empty else 0
        
        # Tokens récemment mis à jour (5 minutes)
        df_recent = conn.query("""
            SELECT COUNT(*) as count FROM tokens 
            WHERE updated_at > datetime('now', '-5 minutes')
            AND no_data_available != 1 
            AND (symbol NOT LIKE 'UNK%' OR symbol IS NULL)
            AND (is_rugged = 0)
        """)
        tokens_recently_updated = int(df_recent['count'].iloc[0]) if not df_recent.empty else 0
        
        # Tokens obsolètes (>5 minutes)
        df_outdated = conn.query("""
            SELECT COUNT(*) as count FROM tokens 
            WHERE updated_at < datetime('now', '-5 minutes')
            AND no_data_available != 1 
            AND (symbol NOT LIKE 'UNK%' OR symbol IS NULL)
            AND (is_rugged = 0)
        """)
        tokens_outdated = int(df_outdated['count'].iloc[0]) if not df_outdated.empty else 0
        
        # Calculs des taux
        data_completeness_rate = (tokens_with_complete_data / total_tokens * 100) if total_tokens > 0 else 0
        
        # Fraîcheur basée sur les tokens non morts/non flaggés
        fresh_tokens = total_tokens - tokens_dead - tokens_flagged_no_data
        freshness_rate = max(0, (fresh_tokens / total_tokens * 100)) if total_tokens > 0 else 0
        
        return {
            'total_tokens': total_tokens,
            'tokens_with_complete_data': tokens_with_complete_data,
            'data_completeness_rate': float(data_completeness_rate),
            'freshness_rate': float(freshness_rate),
            'tokens_dead': tokens_dead,
            'tokens_flagged_no_data': tokens_flagged_no_data,
            'tokens_rugged': tokens_rugged,
            'tokens_recently_updated': tokens_recently_updated,
            'tokens_outdated': tokens_outdated,
            'tokens_no_data_available': tokens_flagged_no_data
        }
        
    except Exception as e:
        st.error(f"❌ Erreur get_system_health: {e}")
        return None

@st.cache_data(ttl=60)
def get_api_metrics_summary(window_minutes):
    """Récupère le résumé des métriques API - Version corrigée"""
    conn = get_db_connection()
    if not conn:
        return {
            'total_calls': 0,
            'success_rate': 0.0,
            'avg_response_time': 0.0,
            'calls_per_minute': 0.0
        }
    
    try:
        cutoff_timestamp = int(time.time()) - (window_minutes * 60)
        
        # Requête corrigée avec paramètres nommés
        df_api = conn.query("""
            SELECT 
                COUNT(*) as total_calls,
                AVG(duration_ms) as avg_duration,
                SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as success_rate
            FROM api_metrics 
            WHERE call_timestamp > :cutoff_timestamp
        """, params={"cutoff_timestamp": cutoff_timestamp})
        
        if not df_api.empty:
            row = df_api.iloc[0]
            total_calls = int(row['total_calls'] or 0)
            avg_response_time = float(row['avg_duration'] or 0.0)
            success_rate = float(row['success_rate'] or 0.0)
            calls_per_minute = float(total_calls / window_minutes) if window_minutes > 0 else 0.0
        else:
            total_calls = 0
            avg_response_time = 0.0
            success_rate = 0.0
            calls_per_minute = 0.0
        
        return {
            'total_calls': total_calls,
            'success_rate': success_rate,
            'avg_response_time': avg_response_time,
            'calls_per_minute': calls_per_minute
        }
        
    except Exception as e:
        st.error(f"❌ Erreur get_api_metrics_summary: {e}")
        return {
            'total_calls': 0,
            'success_rate': 0.0,
            'avg_response_time': 0.0,
            'calls_per_minute': 0.0
        }

@st.cache_data(ttl=120)
def get_system_metrics_timeline(window_minutes):
    """Récupère les métriques système timeline"""
    conn = get_db_connection()
    if not conn:
        return pd.DataFrame()
    
    try:
        cutoff_timestamp = int(time.time()) - (window_minutes * 60)
        
        # Créer des intervalles de temps
        interval_seconds = max(60, window_minutes * 60 // 20)  # 20 points maximum
        
        df_timeline = conn.query("""
            WITH time_series AS (
                SELECT 
                    ? + (value * ?) as timestamp_bucket
                FROM (
                    SELECT 0 as value UNION SELECT 1 UNION SELECT 2 UNION SELECT 3 UNION SELECT 4 UNION
                    SELECT 5 UNION SELECT 6 UNION SELECT 7 UNION SELECT 8 UNION SELECT 9 UNION
                    SELECT 10 UNION SELECT 11 UNION SELECT 12 UNION SELECT 13 UNION SELECT 14 UNION
                    SELECT 15 UNION SELECT 16 UNION SELECT 17 UNION SELECT 18 UNION SELECT 19
                )
                WHERE ? + (value * ?) <= ?
            ),
            token_counts AS (
                SELECT 
                    (strftime('%s', created_at) / ?) * ? as bucket,
                    COUNT(*) as new_tokens
                FROM tokens 
                WHERE created_at > datetime(?, 'unixepoch')
                GROUP BY bucket
            ),
            transaction_counts AS (
                SELECT 
                    (strftime('%s', created_at) / ?) * ? as bucket,
                    COUNT(*) as new_transactions
                FROM transactions 
                WHERE created_at > datetime(?, 'unixepoch')
                OR datetime(created_at, 'unixepoch') > datetime(?, 'unixepoch')
                GROUP BY bucket
            )
            SELECT 
                ts.timestamp_bucket as timestamp,
                COALESCE(tc.new_tokens, 0) as new_tokens,
                COALESCE(txc.new_transactions, 0) as new_transactions
            FROM time_series ts
            LEFT JOIN token_counts tc ON ts.timestamp_bucket = tc.bucket
            LEFT JOIN transaction_counts txc ON ts.timestamp_bucket = txc.bucket
            ORDER BY ts.timestamp_bucket
        """, params=[
            cutoff_timestamp, interval_seconds, cutoff_timestamp, interval_seconds, int(time.time()),
            interval_seconds, interval_seconds, cutoff_timestamp,
            interval_seconds, interval_seconds, cutoff_timestamp, cutoff_timestamp
        ])
        
        # Ajouter la colonne datetime
        if not df_timeline.empty:
            df_timeline['datetime'] = pd.to_datetime(df_timeline['timestamp'], unit='s')
        
        return df_timeline
        
    except Exception as e:
        st.error(f"❌ Erreur get_system_metrics_timeline: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=120)
def get_api_metrics_timeline(window_minutes):
    """Récupère les métriques API timeline"""
    conn = get_db_connection()
    if not conn:
        return pd.DataFrame(), pd.DataFrame()
    
    try:
        cutoff_timestamp = int(time.time()) - (window_minutes * 60)
        
        # Timeline des appels API
        df_timeline = conn.query("""
            SELECT 
                datetime(call_timestamp, 'unixepoch') as datetime,
                COUNT(*) as total_calls,
                AVG(duration_ms) as avg_duration,
                SUM(CASE WHEN success THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as success_rate
            FROM api_metrics 
            WHERE call_timestamp > ?
            GROUP BY datetime(call_timestamp, 'unixepoch', 'start of hour')
            ORDER BY datetime
        """, params=[cutoff_timestamp])
        
        # Breakdown par API
        df_breakdown = conn.query("""
            SELECT 
                api_name,
                COUNT(*) as total_calls,
                AVG(duration_ms) as avg_duration,
                SUM(CASE WHEN success THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as success_rate,
                SUM(CASE WHEN NOT success THEN 1 ELSE 0 END) as failed_calls
            FROM api_metrics 
            WHERE call_timestamp > ?
            GROUP BY api_name
            ORDER BY total_calls DESC
        """, params=[cutoff_timestamp])
        
        return df_timeline, df_breakdown
        
    except Exception as e:
        st.error(f"❌ Erreur get_api_metrics_timeline: {e}")
        return pd.DataFrame(), pd.DataFrame()

def get_time_window_metrics_for_timestamp(window_seconds, timestamp):
    """Récupère les métriques pour une fenêtre de temps spécifique"""
    conn = get_db_connection()
    if not conn:
        return {}
    
    try:
        cutoff_timestamp = timestamp - window_seconds
        
        # Nouveaux tokens
        df_tokens = conn.query(
            "SELECT COUNT(*) as count FROM tokens WHERE created_at > datetime(?, 'unixepoch')",
            params=[cutoff_timestamp]
        )
        new_tokens = df_tokens['count'].iloc[0] if not df_tokens.empty else 0
        
        # Nouvelles transactions
        df_transactions = conn.query("""
            SELECT COUNT(*) as count FROM transactions 
            WHERE created_at > datetime(?, 'unixepoch')
            OR datetime(created_at, 'unixepoch') > datetime(?, 'unixepoch')
        """, params=[cutoff_timestamp, cutoff_timestamp])
        new_transactions = df_transactions['count'].iloc[0] if not df_transactions.empty else 0
        
        # Token updates
        df_updates = conn.query("""
            SELECT COUNT(*) as count FROM tokens 
            WHERE updated_at > datetime(?, 'unixepoch')
            AND (created_at != updated_at OR created_at <= datetime(?, 'unixepoch'))
        """, params=[cutoff_timestamp, cutoff_timestamp])
        token_updates = df_updates['count'].iloc[0] if not df_updates.empty else 0
        
        # History snapshots
        df_snapshots = conn.query("""
            SELECT COUNT(*) as count FROM tokens_history 
            WHERE created_at > datetime(?, 'unixepoch')
        """, params=[cutoff_timestamp])
        history_snapshots = df_snapshots['count'].iloc[0] if not df_snapshots.empty else 0
        
        return {
            'new_tokens': new_tokens,
            'new_transactions': new_transactions,
            'token_updates': token_updates,
            'history_snapshots': history_snapshots
        }
        
    except Exception as e:
        st.error(f"❌ Erreur get_time_window_metrics_for_timestamp: {e}")
        return {}

# Fonctions de création des graphiques
def create_new_tokens_chart(df):
    """Crée le graphique des nouveaux tokens"""
    if df.empty:
        fig = go.Figure()
        fig.add_annotation(text="Pas de données", xref="paper", yref="paper", x=0.5, y=0.5)
        fig.update_layout(title="🆕 Nouveaux Tokens")
        return fig
    
    fig = px.bar(df, x='datetime', y='new_tokens', 
                 title='🆕 Nouveaux Tokens',
                 color='new_tokens',
                 color_continuous_scale='Viridis')
    fig.update_layout(height=300, showlegend=False)
    return fig

def create_token_updates_chart(df):
    """Crée le graphique des mises à jour de tokens"""
    if df.empty:
        fig = go.Figure()
        fig.add_annotation(text="Pas de données", xref="paper", yref="paper", x=0.5, y=0.5)
        fig.update_layout(title="🔄 Token Updates")
        return fig
    
    # Calculer les updates comme approximation
    df_updates = df.copy()
    df_updates['token_updates'] = df_updates['new_tokens'] * 2  # Approximation
    
    fig = px.line(df_updates, x='datetime', y='token_updates', 
                  title='🔄 Token Updates',
                  markers=True)
    fig.update_traces(line_color='orange')
    fig.update_layout(height=300)
    return fig

def create_snapshots_chart(df):
    """Crée le graphique des snapshots"""
    if df.empty:
        fig = go.Figure()
        fig.add_annotation(text="Pas de données", xref="paper", yref="paper", x=0.5, y=0.5)
        fig.update_layout(title="📊 History Snapshots")
        return fig
    
    # Approximation des snapshots
    df_snapshots = df.copy()
    df_snapshots['snapshots'] = df_snapshots['new_tokens'] * 3
    
    fig = px.area(df_snapshots, x='datetime', y='snapshots', 
                  title='📊 History Snapshots')
    fig.update_traces(fill='tonexty', fillcolor='rgba(0,100,80,0.3)')
    fig.update_layout(height=300)
    return fig

def create_transactions_timeline_chart(df):
    """Crée le graphique timeline des transactions"""
    if df.empty:
        fig = go.Figure()
        fig.add_annotation(text="Pas de données", xref="paper", yref="paper", x=0.5, y=0.5)
        fig.update_layout(title="📈 Transactions")
        return fig
    
    fig = px.line(df, x='datetime', y='new_transactions', 
                  title='📈 Transactions Timeline',
                  markers=True)
    fig.update_traces(line_color='green')
    fig.update_layout(height=300)
    return fig

def create_system_health_timeline_chart(df, health):
    """Crée le graphique de santé système"""
    if not health:
        fig = go.Figure()
        fig.add_annotation(text="Pas de données de santé", xref="paper", yref="paper", x=0.5, y=0.5)
        fig.update_layout(title="🏥 System Health")
        return fig
    
    # Créer un graphique en donut pour la santé
    labels = ['Healthy', 'Dead', 'No Data', 'Outdated']
    values = [
        health.tokens_with_complete_data,
        health.tokens_dead,
        health.tokens_flagged_no_data,
        health.tokens_outdated
    ]
    
    fig = go.Figure(data=[go.Pie(labels=labels, values=values, hole=.3)])
    fig.update_layout(title="🏥 System Health Distribution", height=300)
    return fig

def create_wallets_volume_chart(df, metrics):
    """Crée le graphique wallets/volume"""
    if df.empty:
        fig = go.Figure()
        fig.add_annotation(text="Pas de données", xref="paper", yref="paper", x=0.5, y=0.5)
        fig.update_layout(title="👥 Wallets & Volume")
        return fig
    
    # Créer un graphique simple avec les métriques actuelles
    fig = go.Figure()
    
    # Ajouter une barre pour les wallets uniques
    fig.add_trace(go.Bar(
        x=['Wallets', 'Volume (SOL)'],
        y=[metrics.get('unique_wallets', 0), metrics.get('total_volume_usd', 0) / 100],  # Scale down volume
        name='Current Metrics'
    ))
    
    fig.update_layout(title="👥 Current Wallets & Volume", height=300)
    return fig

def create_api_calls_chart(df):
    """Crée le graphique des appels API"""
    if df.empty:
        fig = go.Figure()
        fig.add_annotation(text="Pas de données API", xref="paper", yref="paper", x=0.5, y=0.5)
        fig.update_layout(title="🌐 API Calls")
        return fig
    
    fig = px.bar(df, x='datetime', y='total_calls', 
                 title='🌐 API Calls Timeline')
    fig.update_layout(height=300)
    return fig

def create_api_success_rate_chart(df):
    """Crée le graphique du taux de succès API"""
    if df.empty:
        fig = go.Figure()
        fig.add_annotation(text="Pas de données", xref="paper", yref="paper", x=0.5, y=0.5)
        fig.update_layout(title="✅ API Success Rate")
        return fig
    
    fig = px.line(df, x='datetime', y='success_rate', 
                  title='✅ API Success Rate (%)',
                  markers=True)
    fig.update_traces(line_color='green')
    fig.update_layout(height=300, yaxis_range=[0, 100])
    return fig

def create_api_response_time_chart(df):
    """Crée le graphique du temps de réponse API"""
    if df.empty:
        fig = go.Figure()
        fig.add_annotation(text="Pas de données", xref="paper", yref="paper", x=0.5, y=0.5)
        fig.update_layout(title="⏱️ API Response Time")
        return fig
    
    fig = px.line(df, x='datetime', y='avg_duration', 
                  title='⏱️ API Response Time (ms)',
                  markers=True)
    fig.update_traces(line_color='orange')
    fig.update_layout(height=300)
    return fig

def create_api_breakdown_chart(df):
    """Crée le graphique de breakdown des API"""
    if df.empty:
        fig = go.Figure()
        fig.add_annotation(text="Pas de données", xref="paper", yref="paper", x=0.5, y=0.5)
        fig.update_layout(title="📊 API Breakdown")
        return fig
    
    fig = px.pie(df, values='total_calls', names='api_name', 
                 title='📊 API Calls Distribution')
    fig.update_layout(height=400)
    return fig

def create_system_metrics_charts(metrics):
    """Crée les graphiques des métriques système"""
    # Graphique d'activité
    categories = ['New Tokens', 'Transactions', 'Updates', 'Snapshots']
    values = [
        metrics.get('new_tokens', 0),
        metrics.get('new_transactions', 0),
        metrics.get('token_updates', 0),
        metrics.get('history_snapshots', 0)
    ]
    
    fig_activity = go.Figure(data=[go.Bar(x=categories, y=values)])
    fig_activity.update_layout(title="📊 System Activity (5m)", height=300)
    
    # Graphique des transactions
    tx_types = ['Buys', 'Sells']
    tx_values = [
        metrics.get('buy_transactions', 0),
        metrics.get('sell_transactions', 0)
    ]
    
    fig_transactions = go.Figure(data=[go.Bar(x=tx_types, y=tx_values, 
                                             marker_color=['green', 'red'])])
    fig_transactions.update_layout(title="💹 Buy/Sell Transactions", height=300)
    
    return fig_activity, fig_transactions

def create_system_health_chart(health):
    """Crée le graphique de santé système"""
    if not health:
        fig = go.Figure()
        fig.add_annotation(text="Pas de données de santé", xref="paper", yref="paper", x=0.5, y=0.5)
        return fig
    
    categories = [
        'Complete Data', 'Dead Tokens', 'No Data Available', 
        'Recently Updated', 'Outdated', 'Rugged'
    ]
    values = [
        health.tokens_with_complete_data,
        health.tokens_dead,
        health.tokens_no_data_available,
        health.tokens_recently_updated,
        health.tokens_outdated,
        health.tokens_rugged
    ]

    colors = ['green', 'red', 'orange', 'blue', 'purple', 'yellow']
    
    fig = go.Figure(data=[go.Pie(labels=categories, values=values, 
                                 marker_colors=colors, hole=.3)])
    fig.update_layout(title="🏥 System Health Overview", height=400)
    return fig

def main():
    """Interface principale Streamlit"""
    
    # Header
    st.title("🚀 Token System Metrics Dashboard")

    if 'config' in globals():
        st.success(f"✅ Configuration chargée - DB: {config.database.name}")
        with st.expander("ℹ️ Configuration Details", expanded=False):
            col1, col2, col3 = st.columns(3)
            with col1:
                st.info(f"📊 DB Path: `{config.database.get_full_path()}`")
            with col2:
                st.info(f"⏰ Timeout: {config.database.timeout}s")
            with col3:
                st.info(f"📁 Base Dir: `{config.database.base_dir}/{config.database.data_subdir}`")
    else:
        st.warning(f"⚠️ Configuration fallback: `{DEFAULT_DB_PATH}`")

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
    try:
        conn = get_db_connection()
        if conn:
            # Test simple de la connexion
            test_df = conn.query("SELECT 1 as test")
            if not test_df.empty and test_df['test'].iloc[0] == 1:
                st.sidebar.success("✅ Database Connected")
                
                # Afficher des infos supplémentaires sur la DB
                if 'config' in globals():
                    st.sidebar.info(f"📊 Using: {config.database.name}")
                    st.sidebar.info(f"📁 Location: {config.database.base_dir}")
                else:
                    st.sidebar.info(f"📊 Using: {os.path.basename(DEFAULT_DB_PATH)}")
            else:
                st.sidebar.error("❌ Database Test Failed")
                st.stop()
        else:
            st.sidebar.error("❌ Database Connection Failed")
            st.stop()
    except Exception as e:
        st.sidebar.error(f"❌ Database Error: {e}")
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
                api_summary.get('total_calls', 0),
                delta=f"{api_summary.get('calls_per_minute', 0):.1f}/min"
            )
        
        with col4:
            st.metric(
                "✅ API Success Rate",
                f"{api_summary.get('success_rate', 0):.1f}%",
                delta=f"{api_summary.get('avg_response_time', 0):.0f}ms avg"
            )
    
    st.markdown("---")
    
    # Section System Timeline Charts
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
    
    # Métriques additionnelles
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