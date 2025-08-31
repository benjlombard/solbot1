#!/usr/bin/env python3
"""
Dashboard Streamlit pour DexScreener Token Tracker
Lance avec: streamlit run streamlit_dashboard.py
"""

import streamlit as st
import sqlite3
import pandas as pd
import json
from datetime import datetime, timedelta
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import time

# Configuration de la page
st.set_page_config(
    page_title="DexScreener Tracker Dashboard",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded"
)

class DashboardData:
    def __init__(self, db_path="dexscreener.db"):
        self.db_path = db_path
    
    def get_connection(self):
        """Retourne une connexion à la base de données"""
        return sqlite3.connect(self.db_path, check_same_thread=False)
    
    def get_all_tokens(self):
        """Récupère tous les tokens"""
        with self.get_connection() as conn:
            query = """
            SELECT * FROM tokens 
            ORDER BY created_at DESC
            """
            return pd.read_sql_query(query, conn)
    
    def get_cycle_stats(self, last_n_cycles=None):
        """Récupère les statistiques par cycle"""
        with self.get_connection() as conn:
            query = """
            SELECT 
                cycle_number,
                endpoint_name,
                items_created,
                items_updated,
                items_processed,
                timestamp
            FROM stats_log 
            """
            if last_n_cycles:
                query += f"""
                WHERE cycle_number > (SELECT MAX(cycle_number) - {last_n_cycles} FROM stats_log)
                """
            query += " ORDER BY cycle_number DESC, timestamp DESC"
            
            return pd.read_sql_query(query, conn)
    
    def get_recent_tokens(self, last_n_cycles=5):
        """Récupère les nouveaux tokens des N derniers cycles"""
        with self.get_connection() as conn:
            # Récupérer les timestamps des derniers cycles
            cycle_query = f"""
            SELECT MIN(timestamp) as start_time
            FROM (
                SELECT DISTINCT cycle_number, timestamp
                FROM stats_log 
                ORDER BY cycle_number DESC 
                LIMIT {last_n_cycles * 4}
            ) recent_cycles
            """
            result = pd.read_sql_query(cycle_query, conn)
            
            if result.empty or result.iloc[0]['start_time'] is None:
                return pd.DataFrame()
            
            start_time = result.iloc[0]['start_time']
            
            # Récupérer les tokens créés depuis ce timestamp (sans JOIN pour éviter les doublons)
            query = """
            SELECT DISTINCT *
            FROM tokens
            WHERE created_at >= ?
            ORDER BY created_at DESC
            """
            return pd.read_sql_query(query, conn, params=[start_time])
    
    def get_summary_stats(self):
        """Récupère les statistiques générales"""
        with self.get_connection() as conn:
            # Stats générales
            general_query = """
            SELECT 
                COUNT(*) as total_tokens,
                COUNT(DISTINCT created_by_endpoint) as total_endpoints,
                MAX(created_at) as last_update,
                COUNT(CASE WHEN created_at > datetime('now', '-1 hour') THEN 1 END) as tokens_last_hour,
                COUNT(CASE WHEN created_at > datetime('now', '-24 hours') THEN 1 END) as tokens_last_24h
            FROM tokens
            """
            general_stats = pd.read_sql_query(general_query, conn).iloc[0]
            
            # Stats par endpoint
            endpoint_query = """
            SELECT 
                created_by_endpoint,
                COUNT(*) as count,
                MAX(created_at) as last_created
            FROM tokens
            GROUP BY created_by_endpoint
            ORDER BY count DESC
            """
            endpoint_stats = pd.read_sql_query(endpoint_query, conn)
            
            return general_stats, endpoint_stats

def format_number(num):
    """Formate les nombres pour l'affichage"""
    if pd.isna(num) or num is None:
        return "N/A"
    if isinstance(num, (int, float)):
        if num >= 1_000_000:
            return f"{num/1_000_000:.1f}M"
        elif num >= 1_000:
            return f"{num/1_000:.1f}K"
        else:
            return f"{num:.2f}"
    return str(num)

def format_price(price):
    """Formate les prix"""
    if pd.isna(price) or price is None:
        return "N/A"
    try:
        price_float = float(price)
        if price_float < 0.000001:
            return f"{price_float:.10f}"
        elif price_float < 0.001:
            return f"{price_float:.8f}"
        else:
            return f"{price_float:.6f}"
    except (ValueError, TypeError):
        return str(price)

def main():
    # Titre principal
    st.title("🚀 DexScreener Token Tracker Dashboard")
    
    # Récupérer les paramètres d'URL pour persister l'auto-refresh
    query_params = st.query_params
    auto_refresh_from_url = query_params.get("autorefresh", "false") == "true"
    
    # Auto-refresh avec persistance via URL
    with st.sidebar:
        st.header("⚙️ Configuration")
        
        # Checkbox avec état persistant via URL
        auto_refresh = st.checkbox(
            "🔄 Auto-refresh (30s)", 
            value=auto_refresh_from_url
        )
        
        # Mettre à jour l'URL si l'état change
        if auto_refresh != auto_refresh_from_url:
            if auto_refresh:
                st.query_params["autorefresh"] = "true"
            else:
                st.query_params.clear()
            st.rerun()
        
        if auto_refresh:
            # Meta refresh avec préservation des paramètres d'URL
            refresh_url = f"?autorefresh=true"
            st.markdown(f"""
            <meta http-equiv="refresh" content="30; url={refresh_url}">
            """, unsafe_allow_html=True)
            st.success("✅ Auto-refresh activé (30s)")
        else:
            st.info("❌ Auto-refresh désactivé")
        
        if st.button("🔄 Refresh Manuel"):
            st.cache_data.clear()
            st.rerun()
        
        # Afficher l'heure actuelle
        st.info(f"🕒 {datetime.now().strftime('%H:%M:%S')}")
    
    st.markdown("---")
    
    # Initialisation des données avec cache court
    @st.cache_data(ttl=30)  # Les données sont rafraîchies toutes les 30s automatiquement
    def load_data():
        dashboard = DashboardData()
        try:
            general_stats, endpoint_stats = dashboard.get_summary_stats()
            cycle_stats = dashboard.get_cycle_stats()
            all_tokens = dashboard.get_all_tokens()
            recent_tokens = dashboard.get_recent_tokens()
            return general_stats, endpoint_stats, cycle_stats, all_tokens, recent_tokens
        except Exception as e:
            st.error(f"Erreur lors du chargement des données: {e}")
            return None, None, None, pd.DataFrame(), pd.DataFrame()
    
    general_stats, endpoint_stats, cycle_stats, all_tokens, recent_tokens = load_data()
    
    if all_tokens.empty:
        st.warning("Aucune donnée trouvée. Vérifiez que le tracker fonctionne et que la base de données existe.")
        return
    
    # === INDICATEURS PRINCIPAUX ===
    st.header("📊 Vue d'ensemble")
    
    col1, col2, col3, col4, col5 = st.columns(5)
    
    with col1:
        st.metric(
            label="Total Tokens",
            value=general_stats['total_tokens'],
            delta=f"+{general_stats['tokens_last_24h']} (24h)"
        )
    
    with col2:
        st.metric(
            label="Dernière heure",
            value=general_stats['tokens_last_hour']
        )
    
    with col3:
        st.metric(
            label="Endpoints actifs",
            value=general_stats['total_endpoints']
        )
    
    with col4:
        if not cycle_stats.empty:
            last_cycle = cycle_stats.iloc[0]['cycle_number'] if not cycle_stats.empty else 0
            st.metric(
                label="Dernier cycle",
                value=f"#{last_cycle}"
            )
        else:
            st.metric(label="Dernier cycle", value="N/A")
    
    with col5:
        last_update = general_stats['last_update']
        if last_update:
            try:
                last_update_dt = datetime.fromisoformat(last_update.replace('Z', '+00:00'))
                time_diff = datetime.now() - last_update_dt
                if time_diff.total_seconds() < 3600:
                    delta_text = f"{int(time_diff.total_seconds() / 60)}min ago"
                else:
                    delta_text = f"{int(time_diff.total_seconds() / 3600)}h ago"
                st.metric(
                    label="Dernière MAJ",
                    value=delta_text
                )
            except:
                st.metric(label="Dernière MAJ", value="N/A")
        else:
            st.metric(label="Dernière MAJ", value="N/A")
    
    # === STATISTIQUES PAR CYCLES ===
    st.header("📈 Statistiques par cycles")
    
    # Onglets pour différentes périodes
    tab1, tab2, tab3, tab4 = st.tabs(["Dernier cycle", "5 derniers cycles", "30 derniers cycles", "Tous les cycles"])
    
    def show_cycle_stats(cycles_data, title):
        if cycles_data.empty:
            st.info("Aucune donnée disponible")
            return
        
        # Agrégation par cycle
        cycle_summary = cycles_data.groupby('cycle_number').agg({
            'items_created': 'sum',
            'items_updated': 'sum',
            'items_processed': 'sum',
            'timestamp': 'max'
        }).reset_index()
        cycle_summary = cycle_summary.sort_values('cycle_number', ascending=False)
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader(f"Résumé {title}")
            for _, row in cycle_summary.head(10).iterrows():
                st.write(f"**Cycle #{int(row['cycle_number'])}**: "
                        f"{int(row['items_created'])} créés, "
                        f"{int(row['items_updated'])} MAJ, "
                        f"{int(row['items_processed'])} traités")
        
        with col2:
            # Graphique
            if len(cycle_summary) > 1:
                fig = make_subplots(specs=[[{"secondary_y": True}]])
                
                fig.add_trace(
                    go.Bar(
                        x=cycle_summary['cycle_number'],
                        y=cycle_summary['items_created'],
                        name="Créés",
                        marker_color='green'
                    ),
                    secondary_y=False
                )
                
                fig.add_trace(
                    go.Bar(
                        x=cycle_summary['cycle_number'],
                        y=cycle_summary['items_updated'],
                        name="Mis à jour",
                        marker_color='orange'
                    ),
                    secondary_y=False
                )
                
                fig.update_xaxes(title_text="Numéro de cycle")
                fig.update_yaxes(title_text="Nombre de tokens", secondary_y=False)
                fig.update_layout(
                    title=f"Évolution {title}",
                    height=400
                )
                
                st.plotly_chart(fig, use_container_width=True)
    
    with tab1:
        last_cycle_data = cycle_stats.head(4) if not cycle_stats.empty else pd.DataFrame()
        show_cycle_stats(last_cycle_data, "du dernier cycle")
    
    with tab2:
        cycle_5_data = DashboardData().get_cycle_stats(5)
        show_cycle_stats(cycle_5_data, "des 5 derniers cycles")
    
    with tab3:
        cycle_30_data = DashboardData().get_cycle_stats(30)
        show_cycle_stats(cycle_30_data, "des 30 derniers cycles")
    
    with tab4:
        show_cycle_stats(cycle_stats, "de tous les cycles")
    
    # === NOUVEAUX TOKENS DES 5 DERNIERS CYCLES ===
    st.header("🆕 Nouveaux tokens (5 derniers cycles)")
    
    if not recent_tokens.empty:
        # Préparer les données pour l'affichage
        recent_display = recent_tokens[['token_address', 'base_token_symbol', 'base_token_name', 
                                      'price_usd', 'volume_h24', 'market_cap', 'liquidity_usd',
                                      'created_by_endpoint', 'created_at']].copy()
        
        # Formater les colonnes
        recent_display['price_usd'] = recent_display['price_usd'].apply(format_price)
        recent_display['volume_h24'] = recent_display['volume_h24'].apply(format_number)
        recent_display['market_cap'] = recent_display['market_cap'].apply(format_number)
        recent_display['liquidity_usd'] = recent_display['liquidity_usd'].apply(format_number)
        
        # Renommer les colonnes
        recent_display.columns = ['Adresse Token', 'Symbole', 'Nom', 'Prix USD', 
                                 'Volume 24h', 'Market Cap', 'Liquidité', 'Endpoint', 'Créé le']
        
        st.dataframe(
            recent_display,
            use_container_width=True,
            hide_index=True
        )
        
        # Statistiques des nouveaux tokens
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.metric("Nouveaux tokens", len(recent_tokens))
        
        with col2:
            endpoints_count = recent_tokens['created_by_endpoint'].value_counts()
            top_endpoint = endpoints_count.index[0] if len(endpoints_count) > 0 else "N/A"
            st.metric("Top endpoint", f"{top_endpoint} ({endpoints_count.iloc[0] if len(endpoints_count) > 0 else 0})")
        
        with col3:
            # Moyenne du volume 24h des nouveaux tokens
            avg_volume = recent_tokens['volume_h24'].dropna().mean() if not recent_tokens.empty else 0
            st.metric("Volume moy. 24h", format_number(avg_volume))
    
    else:
        st.info("Aucun nouveau token trouvé dans les 5 derniers cycles")
    
    # === TABLEAU COMPLET DES TOKENS ===
    st.header("📋 Tous les tokens")
    
    # Filtres
    with st.expander("🔍 Filtres"):
        col1, col2, col3 = st.columns(3)
        
        with col1:
            endpoint_filter = st.selectbox(
                "Filtrer par endpoint:",
                ["Tous"] + list(all_tokens['created_by_endpoint'].unique())
            )
        
        with col2:
            min_volume = st.number_input(
                "Volume min. 24h:",
                min_value=0.0,
                value=0.0,
                step=1000.0
            )
        
        with col3:
            show_columns = st.multiselect(
                "Colonnes à afficher:",
                options=all_tokens.columns.tolist(),
                default=['token_address', 'base_token_symbol', 'base_token_name', 'price_usd', 
                        'volume_h24', 'market_cap', 'liquidity_usd', 'created_by_endpoint', 'created_at']
            )
    
    # Appliquer les filtres
    filtered_tokens = all_tokens.copy()
    
    if endpoint_filter != "Tous":
        filtered_tokens = filtered_tokens[filtered_tokens['created_by_endpoint'] == endpoint_filter]
    
    if min_volume > 0:
        filtered_tokens = filtered_tokens[
            (filtered_tokens['volume_h24'].fillna(0) >= min_volume)
        ]
    
    # Affichage du tableau filtré
    if show_columns and not filtered_tokens.empty:
        display_df = filtered_tokens[show_columns].copy()
        
        # Formater les colonnes numériques
        numeric_columns = ['price_usd', 'volume_h24', 'market_cap', 'liquidity_usd', 'fdv']
        for col in numeric_columns:
            if col in display_df.columns:
                if col == 'price_usd':
                    display_df[col] = display_df[col].apply(format_price)
                else:
                    display_df[col] = display_df[col].apply(format_number)
        
        st.dataframe(
            display_df,
            use_container_width=True,
            hide_index=True
        )
        
        st.info(f"Affichage de {len(display_df)} tokens sur {len(all_tokens)} total")
    
    else:
        st.warning("Aucune donnée à afficher avec les filtres sélectionnés")
    
    # === GRAPHIQUES ADDITIONNELS ===
    st.header("📊 Analyses")
    
    col1, col2 = st.columns(2)
    
    with col1:
        # Distribution par endpoint
        if not endpoint_stats.empty:
            fig_pie = px.pie(
                endpoint_stats,
                values='count',
                names='created_by_endpoint',
                title="Distribution des tokens par endpoint"
            )
            st.plotly_chart(fig_pie, use_container_width=True)
    
    with col2:
        # Évolution temporelle
        if not all_tokens.empty:
            # Créer des bins temporels
            all_tokens['created_date'] = pd.to_datetime(all_tokens['created_at']).dt.date
            daily_counts = all_tokens.groupby('created_date').size().reset_index()
            daily_counts.columns = ['Date', 'Nouveaux tokens']
            
            if len(daily_counts) > 1:
                fig_timeline = px.line(
                    daily_counts,
                    x='Date',
                    y='Nouveaux tokens',
                    title="Évolution quotidienne des créations"
                )
                st.plotly_chart(fig_timeline, use_container_width=True)
    
    # === SECTION DEBUG ===
    with st.expander("🛠️ Informations de debug"):
        st.write("**Statistiques générales:**")
        st.json(general_stats.to_dict())
        
        st.write("**Dernières entrées stats_log:**")
        if not cycle_stats.empty:
            st.dataframe(cycle_stats.head(10))
        
        st.write("**Structure de la base:**")
        st.write(f"- Tokens: {len(all_tokens)} lignes")
        st.write(f"- Stats cycles: {len(cycle_stats)} lignes")
        st.write(f"- Colonnes tokens: {len(all_tokens.columns)}")
        if 'last_refresh_time' in st.session_state:
            st.write(f"- Dernière MAJ: {datetime.fromtimestamp(st.session_state.last_refresh_time).strftime('%H:%M:%S')}")
    
    # Boutons de contrôle
    col1, col2, col3 = st.columns([1, 1, 2])
    
    with col1:
        if st.button("🔄 Actualiser maintenant"):
            st.session_state.last_update = time.time()
            st.cache_data.clear()
            st.rerun()
    
    with col2:
        auto_refresh = st.checkbox("🔄 Auto-refresh 30s", value=True)
        if not auto_refresh:
            st.session_state.last_update = time.time()  # Reset timer
    
    with col3:
        st.write(f"⏰ Dernière MAJ: {datetime.fromtimestamp(st.session_state.last_update).strftime('%H:%M:%S')}")
    
    # Auto-refresh logic si activé
    if auto_refresh:
        current_time = time.time()
        if current_time - st.session_state.last_update >= 30:
            st.session_state.last_update = current_time
            st.cache_data.clear()
            st.rerun()

if __name__ == "__main__":
    main()