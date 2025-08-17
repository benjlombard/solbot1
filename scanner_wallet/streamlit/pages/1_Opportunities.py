import sqlite3
import pandas as pd
import streamlit as st
from datetime import datetime, timedelta
import plotly.express as px
import plotly.graph_objects as go
from typing import Dict, List, Optional, Tuple
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
    
    # Afficher un indicateur de succès
    st.success(f"✅ Configuration chargée - DB: {config.database.name}")
    
except ImportError:
    # Fallback si le système de config n'est pas disponible
    DEFAULT_DB_PATH = os.getenv('TRADING_OPPORTUNITIES_DB_PATH', 'database/data/solana_wallet.db')
    st.warning("⚠️ Système de configuration non disponible, utilisation du fallback")
except Exception as e:
    DEFAULT_DB_PATH = 'database/data/solana_wallet.db'
    st.error(f"❌ Erreur chargement config: {e}")

# Configuration de la page
st.set_page_config(
    page_title="🔍 Opportunités de Trading",
    page_icon="🎯",
    layout="wide",
)

# Styles CSS personnalisés
st.markdown("""
<style>
.metric-card {
    background-color: #f0f2f6;
    padding: 1rem;
    border-radius: 0.5rem;
    border-left: 4px solid #ff4b4b;
}

.filter-section {
    background-color: #fafafa;
    padding: 1rem;
    border-radius: 0.5rem;
    margin-bottom: 1rem;
}

.positive-change {
    color: #00ff00;
    font-weight: bold;
}

.negative-change {
    color: #ff0000;
    font-weight: bold;
}

.neutral-change {
    color: #888888;
}
</style>
""", unsafe_allow_html=True)

@dataclass
class FilterConfig:
    """Configuration d'un filtre"""
    name: str
    column: str
    operator: str
    value: float
    enabled: bool
    data_type: str  # 'float', 'int', 'string'
    min_val: Optional[float] = None
    max_val: Optional[float] = None
    step: Optional[float] = None

class TokenScanner:
    """Classe principale pour le scanner de tokens"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = None
        
        # Configuration des filtres disponibles
        self.available_filters = {
            "momentum_score": FilterConfig(
                name="🚀 Momentum Score",
                column="momentum_score",
                operator=">",
                value=70.0,
                enabled=False,
                data_type="float",
                min_val=-100.0,
                max_val=100.0,
                step=1.0
            ),
            "risk_score": FilterConfig(
                name="⚠️ Risk Score",
                column="risk_score", 
                operator="<",
                value=30.0,
                enabled=False,
                data_type="float",
                min_val=0.0,
                max_val=100.0,
                step=1.0
            ),
            "rug_risk_score": FilterConfig(
                name="🚨 Rug Risk Score",
                column="rug_risk_score",
                operator="<", 
                value=20.0,
                enabled=False,
                data_type="float",
                min_val=0.0,
                max_val=100.0,
                step=1.0
            ),
            "price_change_24h": FilterConfig(
                name="📈 Price Change 24h (%)",
                column="price_change_24h",
                operator=">",
                value=10.0,
                enabled=True,
                data_type="float",
                min_val=-100.0,
                max_val=1000.0,
                step=1.0
            ),
            "volume_24h": FilterConfig(
                name="💰 Volume 24h",
                column="volume_24h",
                operator=">",
                value=10000.0,
                enabled=True,
                data_type="float",
                min_val=0.0,
                max_val=10000000.0,
                step=1000.0
            ),
            "liquidity_mc_ratio": FilterConfig(
                name="🌊 Liquidity/MC Ratio",
                column="liquidity_mc_ratio",
                operator=">",
                value=0.1,
                enabled=False,
                data_type="float",
                min_val=0.0,
                max_val=1.0,
                step=0.01
            ),
            "market_cap": FilterConfig(
                name="💎 Market Cap",
                column="market_cap",
                operator=">",
                value=100000.0,
                enabled=False,
                data_type="float",
                min_val=0.0,
                max_val=100000000.0,
                step=10000.0
            ),
            "holder_count": FilterConfig(
                name="👥 Holder Count",
                column="holder_count",
                operator=">",
                value=100.0,
                enabled=False,
                data_type="int",
                min_val=0.0,
                max_val=10000.0,
                step=10.0
            )
        }
        
        # Presets de configuration
        self.presets = {
            "🚀 Pump Detector": {
                "momentum_score": (True, ">", 70.0),
                "price_change_24h": (True, ">", 20.0),
                "volume_24h": (True, ">", 50000.0)
            },
            "💎 Safe Gems": {
                "risk_score": (True, "<", 20.0),
                "rug_risk_score": (True, "<", 15.0),
                "liquidity_mc_ratio": (True, ">", 0.1),
                "momentum_score": (True, ">", 30.0)
            },
            "⚡ Volume Surge": {
                "volume_24h": (True, ">", 100000.0),
                "price_change_24h": (True, ">", 5.0),
                "momentum_score": (True, ">", 20.0)
            },
            "🔍 Custom": {}  # Configuration libre
        }
    
    def connect(self) -> bool:
        """Connexion à la base de données"""
        try:
            self.conn = sqlite3.connect(self.db_path)
            self.conn.row_factory = sqlite3.Row
            return True
        except Exception as e:
            st.error(f"❌ Erreur de connexion à la base de données: {e}")
            return False
    
    def build_dynamic_query(self, filters: Dict[str, FilterConfig], limit: int = 20) -> Tuple[str, List]:
        """Construit la requête SQL dynamiquement"""
        
        base_query = """
        SELECT 
            token_address,
            symbol,
            name,
            price_usd,
            market_cap,
            price_change_24h,
            volume_24h,
            momentum_score,
            risk_score,
            rug_risk_score,
            holder_count,
            liquidity_mc_ratio,
            snapshot_timestamp
        FROM tokens_history 
        WHERE snapshot_timestamp = (SELECT MAX(snapshot_timestamp) FROM tokens_history)
        """
        
        # Construire les conditions WHERE
        conditions = []
        params = []
        
        for filter_key, filter_config in filters.items():
            if filter_config.enabled:
                condition = f"AND {filter_config.column} {filter_config.operator} ?"
                conditions.append(condition)
                params.append(filter_config.value)
        
        # Assembler la requête
        where_clause = " ".join(conditions)
        order_clause = "ORDER BY momentum_score DESC, price_change_24h DESC"
        limit_clause = f"LIMIT {limit}"
        
        final_query = f"{base_query} {where_clause} {order_clause} {limit_clause}"
        
        return final_query, params
    
    def execute_query(self, filters: Dict[str, FilterConfig], limit: int = 20) -> pd.DataFrame:
        """Exécute la requête avec les filtres actifs"""
        if not self.conn:
            return pd.DataFrame()
        
        try:
            query, params = self.build_dynamic_query(filters, limit)
            df = pd.read_sql_query(query, self.conn, params=params)
            return df
        except Exception as e:
            st.error(f"❌ Erreur lors de l'exécution de la requête: {e}")
            return pd.DataFrame()
    
    def get_latest_snapshot_info(self) -> Dict:
        """Récupère les informations du dernier snapshot"""
        if not self.conn:
            return {}
        
        try:
            query = """
            SELECT 
                MAX(snapshot_timestamp) as latest_timestamp,
                COUNT(DISTINCT token_address) as total_tokens
            FROM tokens_history 
            WHERE snapshot_timestamp = (SELECT MAX(snapshot_timestamp) FROM tokens_history)
            """
            
            result = self.conn.execute(query).fetchone()
            
            if result:
                latest_time = datetime.fromtimestamp(result['latest_timestamp'])
                return {
                    'timestamp': latest_time,
                    'total_tokens': result['total_tokens'],
                    'age_minutes': (datetime.now() - latest_time).total_seconds() / 60
                }
        except Exception as e:
            st.error(f"❌ Erreur lors de la récupération des infos snapshot: {e}")
        
        return {}

def format_number(value, decimal_places=2):
    """Formate les nombres pour l'affichage"""
    if pd.isna(value) or value is None:
        return "N/A"
    
    try:
        num = float(value)
        if abs(num) >= 1000000000:
            return f"{num/1000000000:.{decimal_places}f}B"
        elif abs(num) >= 1000000:
            return f"{num/1000000:.{decimal_places}f}M"
        elif abs(num) >= 1000:
            return f"{num/1000:.{decimal_places}f}K"
        else:
            return f"{num:.{decimal_places}f}"
    except:
        return "N/A"

def format_percentage(value, decimal_places=1):
    """Formate les pourcentages"""
    if pd.isna(value) or value is None:
        return "N/A"
    
    try:
        return f"{float(value):.{decimal_places}f}%"
    except:
        return "N/A"

def get_change_color_class(value):
    """Retourne la classe CSS pour colorer les changements"""
    if pd.isna(value) or value is None:
        return "neutral-change"
    
    try:
        val = float(value)
        if val > 0:
            return "positive-change"
        elif val < 0:
            return "negative-change"
        else:
            return "neutral-change"
    except:
        return "neutral-change"

def display_filter_section(scanner: TokenScanner):
    """Affiche la section de configuration des filtres"""
    
    st.sidebar.header("🔧 Configuration des Filtres")
    
    # Sélection de preset
    st.sidebar.subheader("📋 Presets")
    selected_preset = st.sidebar.selectbox(
        "Choisir un preset:",
        options=list(scanner.presets.keys()),
        index=3  # "🔍 Custom" par défaut
    )
    
    # Appliquer le preset
    if selected_preset != "🔍 Custom" and st.sidebar.button(f"Appliquer {selected_preset}"):
        preset_config = scanner.presets[selected_preset]
        
        # Désactiver tous les filtres d'abord
        for filter_key in scanner.available_filters:
            scanner.available_filters[filter_key].enabled = False
        
        # Appliquer la configuration du preset
        for filter_key, (enabled, operator, value) in preset_config.items():
            if filter_key in scanner.available_filters:
                scanner.available_filters[filter_key].enabled = enabled
                scanner.available_filters[filter_key].operator = operator
                scanner.available_filters[filter_key].value = value
        
        st.sidebar.success(f"✅ Preset {selected_preset} appliqué!")
        st.rerun()
    
    st.sidebar.markdown("---")
    
    # Configuration des filtres individuels
    st.sidebar.subheader("⚙️ Filtres Individuels")
    
    # Organiser les filtres par catégorie
    categories = {
        "📈 Performance": ["momentum_score", "price_change_24h"],
        "🛡️ Sécurité": ["risk_score", "rug_risk_score"],
        "💰 Marché": ["volume_24h", "market_cap", "liquidity_mc_ratio"],
        "👥 Adoption": ["holder_count"]
    }
    
    for category_name, filter_keys in categories.items():
        with st.sidebar.expander(category_name, expanded=True):
            for filter_key in filter_keys:
                if filter_key in scanner.available_filters:
                    filter_config = scanner.available_filters[filter_key]
                    
                    # Checkbox pour activer/désactiver
                    col1, col2 = st.columns([3, 1])
                    
                    with col1:
                        filter_config.enabled = st.checkbox(
                            filter_config.name,
                            value=filter_config.enabled,
                            key=f"enable_{filter_key}"
                        )
                    
                    if filter_config.enabled:
                        with col2:
                            # Sélecteur d'opérateur
                            operators = [">", ">=", "<", "<=", "="]
                            filter_config.operator = st.selectbox(
                                "Op",
                                options=operators,
                                index=operators.index(filter_config.operator),
                                key=f"op_{filter_key}",
                                label_visibility="collapsed"
                            )
                        
                        # Slider pour la valeur
                        if filter_config.data_type == "float":
                            filter_config.value = st.slider(
                                f"Valeur pour {filter_config.name}",
                                min_value=filter_config.min_val,
                                max_value=filter_config.max_val,
                                value=filter_config.value,
                                step=filter_config.step,
                                key=f"val_{filter_key}",
                                label_visibility="collapsed"
                            )
                        elif filter_config.data_type == "int":
                            filter_config.value = st.slider(
                                f"Valeur pour {filter_config.name}",
                                min_value=int(filter_config.min_val),
                                max_value=int(filter_config.max_val),
                                value=int(filter_config.value),
                                step=int(filter_config.step),
                                key=f"val_{filter_key}",
                                label_visibility="collapsed"
                            )
    
    st.sidebar.markdown("---")
    
    # Paramètres généraux
    st.sidebar.subheader("⚙️ Paramètres")
    limit = st.sidebar.slider("Nombre max de résultats", 5, 100, 20, 5)
    
    auto_refresh = st.sidebar.checkbox("🔄 Auto-refresh (30s)", value=False)
    if auto_refresh:
        st.sidebar.info("⏰ Refresh automatique activé")
        # Auto-refresh toutes les 30 secondes
        import time
        time.sleep(30)
        st.rerun()
    
    return limit

def display_results_table(df: pd.DataFrame):
    """Affiche le tableau des résultats"""
    
    if df.empty:
        st.warning("⚠️ Aucun token ne correspond aux critères sélectionnés")
        return
    
    st.subheader(f"🎯 Tokens Détectés ({len(df)} résultats)")
    
    # Préparer les données pour l'affichage
    display_df = df.copy()
    
    # Formater les colonnes
    display_df['Token'] = display_df['token_address'].apply(lambda x: f"{x[:8]}...{x[-6:]}")
    display_df['Symbol'] = display_df['symbol'].fillna('N/A')
    display_df['Name'] = display_df['name'].apply(lambda x: x[:30] + '...' if pd.notna(x) and len(x) > 30 else (x if pd.notna(x) else 'N/A'))
    display_df['Price'] = display_df['price_usd'].apply(lambda x: f"${float(x):.6f}" if pd.notna(x) else "N/A")
    display_df['Market Cap'] = display_df['market_cap'].apply(format_number)
    display_df['Price 24h'] = display_df['price_change_24h'].apply(format_percentage)
    display_df['Volume 24h'] = display_df['volume_24h'].apply(format_number)
    display_df['Momentum'] = display_df['momentum_score'].apply(lambda x: f"{float(x):.1f}" if pd.notna(x) else "N/A")
    display_df['Risk'] = display_df['risk_score'].apply(lambda x: f"{float(x):.1f}" if pd.notna(x) else "N/A")
    display_df['Rug Risk'] = display_df['rug_risk_score'].apply(lambda x: f"{float(x):.1f}" if pd.notna(x) else "N/A")
    display_df['Holders'] = display_df['holder_count'].apply(lambda x: f"{int(x):,}" if pd.notna(x) else "N/A")
    display_df['Liq/MC'] = display_df['liquidity_mc_ratio'].apply(lambda x: f"{float(x):.3f}" if pd.notna(x) else "N/A")
    
    # Créer les liens
    display_df['🔗 DexScreener'] = display_df['token_address'].apply(
        lambda x: f"https://dexscreener.com/solana/{x}"
    )
    display_df['🔗 Pump.fun'] = display_df['token_address'].apply(
        lambda x: f"https://pump.fun/{x}"
    )
    
    # Colonnes à afficher
    display_columns = [
        'Token', 'Symbol', 'Name', 'Price', 'Market Cap', 'Price 24h', 
        'Volume 24h', 'Momentum', 'Risk', 'Rug Risk', 'Holders', 'Liq/MC',
        '🔗 DexScreener', '🔗 Pump.fun'
    ]
    
    # Configuration des colonnes
    column_config = {
        'Token': st.column_config.TextColumn('Token', width="small"),
        'Symbol': st.column_config.TextColumn('Symbol', width="small"),
        'Name': st.column_config.TextColumn('Name', width="medium"),
        'Price': st.column_config.TextColumn('Price', width="small"),
        'Market Cap': st.column_config.TextColumn('MC', width="small"),
        'Price 24h': st.column_config.TextColumn('Price 24h', width="small"),
        'Volume 24h': st.column_config.TextColumn('Vol 24h', width="small"),
        'Momentum': st.column_config.TextColumn('Mom.', width="small"),
        'Risk': st.column_config.TextColumn('Risk', width="small"),
        'Rug Risk': st.column_config.TextColumn('Rug', width="small"),
        'Holders': st.column_config.TextColumn('Holders', width="small"),
        'Liq/MC': st.column_config.TextColumn('Liq/MC', width="small"),
        '🔗 DexScreener': st.column_config.LinkColumn('📊 Dex', width="small"),
        '🔗 Pump.fun': st.column_config.LinkColumn('🚀 Pump', width="small")
    }
    
    # Afficher le tableau
    selected_rows = st.dataframe(
        display_df[display_columns],
        use_container_width=True,
        height=400,
        column_config=column_config,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row"
    )
    
    # Actions sur sélection
    if selected_rows.selection.rows:
        selected_idx = selected_rows.selection.rows[0]
        selected_token = df.iloc[selected_idx]
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("🎯 Token Sélectionné", f"{selected_token['token_address'][:8]}...")
        
        with col2:
            if pd.notna(selected_token['momentum_score']):
                st.metric("🚀 Momentum", f"{selected_token['momentum_score']:.1f}")
            
        with col3:
            if pd.notna(selected_token['price_change_24h']):
                delta_color = "normal" if selected_token['price_change_24h'] > 0 else "inverse"
                st.metric("📈 Change 24h", f"{selected_token['price_change_24h']:.1f}%")
        
        with col4:
            if st.button("📋 Copier l'adresse", key="copy_address"):
                st.code(selected_token['token_address'])

def display_summary_metrics(df: pd.DataFrame, snapshot_info: Dict):
    """Affiche les métriques de résumé"""
    
    col1, col2, col3, col4, col5 = st.columns(5)
    
    with col1:
        st.metric(
            "📊 Tokens Trouvés",
            len(df),
            delta=f"sur {snapshot_info.get('total_tokens', 'N/A')} total"
        )
    
    with col2:
        if not df.empty and 'momentum_score' in df.columns:
            avg_momentum = df['momentum_score'].mean()
            st.metric(
                "🚀 Momentum Moyen",
                f"{avg_momentum:.1f}" if pd.notna(avg_momentum) else "N/A"
            )
        else:
            st.metric("🚀 Momentum Moyen", "N/A")
    
    with col3:
        if not df.empty and 'price_change_24h' in df.columns:
            avg_change = df['price_change_24h'].mean()
            st.metric(
                "📈 Change Moy. 24h",
                f"{avg_change:.1f}%" if pd.notna(avg_change) else "N/A"
            )
        else:
            st.metric("📈 Change Moy. 24h", "N/A")
    
    with col4:
        if not df.empty and 'volume_24h' in df.columns:
            total_volume = df['volume_24h'].sum()
            st.metric(
                "💰 Volume Total",
                format_number(total_volume) if pd.notna(total_volume) else "N/A"
            )
        else:
            st.metric("💰 Volume Total", "N/A")
    
    with col5:
        if snapshot_info.get('timestamp'):
            age_min = snapshot_info.get('age_minutes', 0)
            if age_min < 60:
                age_text = f"{age_min:.0f}min"
            else:
                age_text = f"{age_min/60:.1f}h"
            
            st.metric(
                "⏰ Dernière MAJ",
                snapshot_info['timestamp'].strftime('%H:%M:%S'),
                delta=f"il y a {age_text}"
            )
        else:
            st.metric("⏰ Dernière MAJ", "N/A")

def display_charts(df: pd.DataFrame):
    """Affiche les graphiques d'analyse"""
    
    if df.empty:
        return
    
    st.subheader("📊 Analyse Graphique")
    
    col1, col2 = st.columns(2)
    
    with col1:
        # Graphique Momentum vs Price Change
        if 'momentum_score' in df.columns and 'price_change_24h' in df.columns:
            fig_scatter = px.scatter(
                df,
                x='momentum_score',
                y='price_change_24h',
                size='volume_24h',
                color='risk_score',
                hover_data=['symbol', 'market_cap'],
                title="Momentum vs Price Change 24h",
                labels={
                    'momentum_score': 'Momentum Score',
                    'price_change_24h': 'Price Change 24h (%)',
                    'risk_score': 'Risk Score'
                }
            )
            fig_scatter.update_layout(height=400)
            st.plotly_chart(fig_scatter, use_container_width=True)
    
    with col2:
        # Distribution des Risk Scores
        if 'risk_score' in df.columns:
            fig_hist = px.histogram(
                df,
                x='risk_score',
                nbins=20,
                title="Distribution des Risk Scores",
                labels={'risk_score': 'Risk Score', 'count': 'Nombre de Tokens'}
            )
            fig_hist.update_layout(height=400)
            st.plotly_chart(fig_hist, use_container_width=True)

def main():
    """Fonction principale"""
    
    st.title("🎯 Opportunités de Trading")
    st.markdown("Utilisez les filtres pour découvrir des tokens prometteurs basé sur les dernières données historiques.")
    
    # Configuration de la base de données
    db_path = DEFAULT_DB_PATH
    
    if 'config' in globals():
        with st.expander("ℹ️ Informations de Configuration", expanded=False):
            st.info(f"📊 Base de données: `{db_path}`")
            st.info(f"📁 Répertoire DB: `{config.database.base_dir}/{config.database.data_subdir}`")
            st.info(f"⏰ Timeout DB: {config.database.timeout}s")

    # Initialiser le scanner
    scanner = TokenScanner(db_path)
    
    if not scanner.connect():
        st.stop()
    
    # Récupérer les infos du snapshot
    snapshot_info = scanner.get_latest_snapshot_info()
    
    # Afficher la sidebar de configuration
    limit = display_filter_section(scanner)
    
    # Bouton de refresh manuel
    col1, col2, col3 = st.columns([1, 1, 2])
    
    with col1:
        if st.button("🔄 Actualiser", type="primary"):
            st.rerun()
    
    with col2:
        if st.button("🔍 Scanner"):
            st.rerun()
    
    with col3:
        if snapshot_info:
            st.info(f"📊 Dernier snapshot: {snapshot_info['timestamp'].strftime('%Y-%m-%d %H:%M:%S')} ({snapshot_info['total_tokens']} tokens)")
    

    
    # Exécuter la requête
    with st.spinner("🔄 Recherche des tokens..."):
        results_df = scanner.execute_query(scanner.available_filters, limit)
    
    # Afficher les résultats
    if not results_df.empty:
        # Métriques de résumé
        display_summary_metrics(results_df, snapshot_info)
        
        st.markdown("---")
        
        # Tableau des résultats
        display_results_table(results_df)
        
        st.markdown("---")
        
        # Graphiques
        display_charts(results_df)
        
        st.markdown("---")
        
        # Section requête SQL (repliable et en bas)
        with st.expander("🔍 Afficher la requête SQL générée", expanded=False):
            # Générer la requête pour l'affichage
            query, params = scanner.build_dynamic_query(scanner.available_filters, limit)
            
            # Remplacer les ? par les valeurs pour un affichage plus lisible
            display_query = query
            for i, param in enumerate(params):
                display_query = display_query.replace('?', str(param), 1)
            
            # Affichage compact avec height réduite
            st.code(display_query, language="sql")
            
            # Informations supplémentaires en colonnes
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.metric("📊 Filtres actifs", len([f for f in scanner.available_filters.values() if f.enabled]))
            
            with col2:
                st.metric("📝 Paramètres", len(params))
            
            with col3:
                if st.button("📋 Copier", key="copy_sql"):
                    st.success("✅ Requête copiée dans le presse-papier !")
                    # On affiche la requête dans un format facilement sélectionnable
                    st.text_area(
                        "Sélectionnez et copiez:",
                        value=display_query,
                        height=100,
                        key="copy_area"
                    )
        
        st.markdown("---")
        
        st.markdown("---")
        
        # Export
        st.subheader("📥 Export")
        
        # Préparer les données d'export
        export_df = results_df.copy()
        csv_data = export_df.to_csv(index=False)
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.download_button(
                label="📄 Télécharger CSV",
                data=csv_data,
                file_name=f"token_scan_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv"
            )
        
        with col2:
            # Informations sur la requête
            st.info(f"💾 Requête exécutée avec {len([f for f in scanner.available_filters.values() if f.enabled])} filtres actifs")
    
    else:
        st.warning("⚠️ Aucun résultat trouvé avec les filtres actuels")
        st.info("💡 Essayez de relaxer certains critères ou de désactiver des filtres")

if __name__ == "__main__":
    main()
