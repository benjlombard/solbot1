import streamlit as st
import sqlite3
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import numpy as np
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

# Configuration de la page
st.set_page_config(
    page_title="Token Investment Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# CSS personnalisé
st.markdown("""
<style>
    .metric-card {
        background-color: #f0f2f6;
        padding: 1rem;
        border-radius: 0.5rem;
        border-left: 4px solid #1f77b4;
    }
    .risk-low { border-left-color: #2ecc71; }
    .risk-medium { border-left-color: #f39c12; }
    .risk-high { border-left-color: #e74c3c; }
</style>
""", unsafe_allow_html=True)

@st.cache_data
def load_data(db_path):
    """Charge les données depuis la base SQLite"""
    try:
        conn = sqlite3.connect(db_path)
        query = """
        SELECT * FROM tokens_history 
        ORDER BY snapshot_timestamp DESC, token_address
        """
        df = pd.read_sql_query(query, conn)
        conn.close()
        
        # Conversion des timestamps
        df['datetime'] = pd.to_datetime(df['snapshot_timestamp'], unit='s')
        df['date'] = df['datetime'].dt.date
        
        return df
    except Exception as e:
        st.error(f"Erreur lors du chargement des données : {e}")
        return pd.DataFrame()

def get_token_list(df):
    """Récupère la liste unique des tokens avec leurs métadonnées"""
    latest_data = df.groupby('token_address').first().reset_index()
    token_info = []
    
    for _, row in latest_data.iterrows():
        symbol = row['symbol'] if pd.notna(row['symbol']) else 'N/A'
        name = row['name'] if pd.notna(row['name']) else 'Unknown'
        display_name = f"{symbol} - {name} ({row['token_address'][:8]}...)"
        token_info.append((display_name, row['token_address']))
    
    return sorted(token_info)

def create_price_chart(df_token):
    """Crée le graphique d'évolution des prix"""
    fig = make_subplots(
        rows=2, cols=1,
        subplot_titles=('Prix USD', 'Volume 24h'),
        vertical_spacing=0.1,
        row_heights=[0.7, 0.3]
    )
    
    # Prix
    fig.add_trace(
        go.Scatter(
            x=df_token['datetime'],
            y=df_token['price_usd'],
            mode='lines+markers',
            name='Prix USD',
            line=dict(color='#1f77b4', width=2),
            hovertemplate='<b>Prix:</b> $%{y:.8f}<br><b>Date:</b> %{x}<extra></extra>'
        ),
        row=1, col=1
    )
    
    # Volume
    fig.add_trace(
        go.Bar(
            x=df_token['datetime'],
            y=df_token['volume_24h'],
            name='Volume 24h',
            marker_color='rgba(255, 152, 0, 0.7)',
            hovertemplate='<b>Volume:</b> $%{y:,.0f}<br><b>Date:</b> %{x}<extra></extra>'
        ),
        row=2, col=1
    )
    
    fig.update_layout(
        height=500,
        title_text="Évolution Prix & Volume",
        showlegend=True,
        hovermode='x unified'
    )
    
    return fig

def create_market_metrics_chart(df_token):
    """Crée les graphiques des métriques de marché"""
    fig = make_subplots(
        rows=2, cols=2,
        subplot_titles=('Market Cap', 'Liquidité USD', 'Nombre de Holders', 'Ratio Liquidité/MC'),
        vertical_spacing=0.1,
        horizontal_spacing=0.1
    )
    
    # Market Cap
    fig.add_trace(
        go.Scatter(x=df_token['datetime'], y=df_token['market_cap'], 
                  mode='lines', name='Market Cap', line=dict(color='#2ecc71')),
        row=1, col=1
    )
    
    # Liquidité
    fig.add_trace(
        go.Scatter(x=df_token['datetime'], y=df_token['liquidity_usd'], 
                  mode='lines', name='Liquidité', line=dict(color='#3498db')),
        row=1, col=2
    )
    
    # Holders
    fig.add_trace(
        go.Scatter(x=df_token['datetime'], y=df_token['holder_count'], 
                  mode='lines+markers', name='Holders', line=dict(color='#9b59b6')),
        row=2, col=1
    )
    
    # Ratio Liquidité/MC
    fig.add_trace(
        go.Scatter(x=df_token['datetime'], y=df_token['liquidity_mc_ratio'], 
                  mode='lines', name='Liq/MC Ratio', line=dict(color='#e67e22')),
        row=2, col=2
    )
    
    fig.update_layout(height=500, title_text="Métriques de Marché", showlegend=False)
    return fig

def create_risk_scores_chart(df_token):
    """Crée le graphique des scores de risque"""
    fig = go.Figure()
    
    fig.add_trace(go.Scatter(
        x=df_token['datetime'], 
        y=df_token['viability_score'],
        mode='lines+markers',
        name='Viabilité',
        line=dict(color='#2ecc71', width=2)
    ))
    
    fig.add_trace(go.Scatter(
        x=df_token['datetime'], 
        y=df_token['risk_score'],
        mode='lines+markers',
        name='Risque',
        line=dict(color='#e74c3c', width=2)
    ))
    
    fig.add_trace(go.Scatter(
        x=df_token['datetime'], 
        y=df_token['momentum_score'],
        mode='lines+markers',
        name='Momentum',
        line=dict(color='#f39c12', width=2)
    ))
    
    fig.update_layout(
        title="Évolution des Scores",
        yaxis_title="Score",
        height=400,
        hovermode='x unified'
    )
    
    return fig

def create_volume_analysis(df_token):
    """Analyse des volumes sur différentes périodes"""
    fig = make_subplots(
        rows=1, cols=2,
        subplot_titles=('Volumes Multi-Périodes', 'Variations de Prix'),
        horizontal_spacing=0.1
    )
    
    # Volumes
    periods = ['volume_5m', 'volume_1h', 'volume_6h', 'volume_24h']
    colors = ['#ff6b6b', '#4ecdc4', '#45b7d1', '#96ceb4']
    
    for i, period in enumerate(periods):
        fig.add_trace(
            go.Scatter(
                x=df_token['datetime'], 
                y=df_token[period],
                mode='lines',
                name=period.replace('volume_', ''),
                line=dict(color=colors[i])
            ),
            row=1, col=1
        )
    
    # Variations de prix
    price_changes = ['price_change_5m', 'price_change_1h', 'price_change_6h', 'price_change_24h']
    for i, change in enumerate(price_changes):
        fig.add_trace(
            go.Scatter(
                x=df_token['datetime'], 
                y=df_token[change],
                mode='lines',
                name=change.replace('price_change_', '') + ' %',
                line=dict(color=colors[i])
            ),
            row=1, col=2
        )
    
    fig.update_layout(height=400, title_text="Analyse Volumes & Variations")
    return fig

def display_token_metrics(df_token):
    """Affiche les métriques clés du token"""
    latest = df_token.iloc[0]  # Données les plus récentes
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric(
            "Prix USD", 
            f"${latest['price_usd']:.8f}",
            f"{latest['price_change_24h']:.2f}%" if latest['price_change_24h'] != 0 else None
        )
        
    with col2:
        st.metric(
            "Market Cap", 
            f"${latest['market_cap']:,.0f}",
            f"{latest['market_cap_delta']:,.0f}" if latest['market_cap_delta'] != 0 else None
        )
        
    with col3:
        st.metric(
            "Volume 24h", 
            f"${latest['volume_24h']:,.0f}",
            f"{latest['volume_24h_delta']:,.0f}" if latest['volume_24h_delta'] != 0 else None
        )
        
    with col4:
        st.metric(
            "Holders", 
            f"{latest['holder_count']:,}",
            f"{latest['holder_count_delta']}" if latest['holder_count_delta'] != 0 else None
        )

def create_holder_analysis(df_token):
    """Analyse de la distribution des holders"""
    fig = make_subplots(
        rows=2, cols=1,
        subplot_titles=('Évolution des Holders', 'Concentration Top Holders'),
        vertical_spacing=0.15
    )
    
    # Évolution holders
    fig.add_trace(
        go.Scatter(
            x=df_token['datetime'], 
            y=df_token['holder_count'],
            mode='lines+markers',
            name='Total Holders',
            line=dict(color='#3498db')
        ),
        row=1, col=1
    )
    
    # Concentration
    fig.add_trace(
        go.Scatter(
            x=df_token['datetime'], 
            y=df_token['top_holder_percentage'],
            mode='lines',
            name='Top Holder %',
            line=dict(color='#e74c3c')
        ),
        row=2, col=1
    )
    
    fig.add_trace(
        go.Scatter(
            x=df_token['datetime'], 
            y=df_token['top_10_holders_percentage'],
            mode='lines',
            name='Top 10 Holders %',
            line=dict(color='#f39c12')
        ),
        row=2, col=1
    )
    
    fig.update_layout(height=500, title_text="Analyse des Holders")
    return fig

def create_opportunity_dashboard(df):
    """Dashboard des opportunités d'investissement"""
    st.header("🎯 Opportunités d'Investissement")
    
    # Données les plus récentes
    latest_timestamp = df['snapshot_timestamp'].max()
    latest_data = df[df['snapshot_timestamp'] == latest_timestamp].copy()
    
    # Filtres pour les opportunités
    col1, col2 = st.columns(2)
    
    with col1:
        min_market_cap = st.number_input("Market Cap min ($)", value=10000, step=10000)
        max_risk_score = st.slider("Score de risque max", 0, 100, 40)
        
    with col2:
        min_viability = st.slider("Score de viabilité min", 0, 100, 60)
        min_holders = st.number_input("Nombre de holders min", value=50, step=10)
    
    # Application des filtres
    filtered_data = latest_data[
        (latest_data['market_cap'] >= min_market_cap) &
        (latest_data['risk_score'] <= max_risk_score) &
        (latest_data['viability_score'] >= min_viability) &
        (latest_data['holder_count'] >= min_holders) &
        (latest_data['is_rugged'] == 0)
    ].copy()
    
    st.write(f"**{len(filtered_data)} tokens correspondent aux critères**")
    
    if len(filtered_data) > 0:
        # Graphique de dispersion
        fig = px.scatter(
            filtered_data,
            x='risk_score',
            y='viability_score',
            size='market_cap',
            color='momentum_score',
            hover_name='symbol',
            hover_data={
                'price_change_24h': ':.2f',
                'volume_24h': ':,.0f',
                'holder_count': ':,',
                'liquidity_mc_ratio': ':.3f'
            },
            title="Risk vs Viability (Taille = Market Cap, Couleur = Momentum)",
            labels={
                'risk_score': 'Score de Risque',
                'viability_score': 'Score de Viabilité'
            }
        )
        
        st.plotly_chart(fig, use_container_width=True)
        
        # Top 10 opportunités
        st.subheader("🏆 Top 10 Opportunités")
        
        # Score composite
        filtered_data['opportunity_score'] = (
            filtered_data['viability_score'] * 0.3 +
            (100 - filtered_data['risk_score']) * 0.3 +
            filtered_data['momentum_score'] * 0.2 +
            filtered_data['price_change_24h'] * 0.2
        )
        
        top_opportunities = filtered_data.nlargest(10, 'opportunity_score')[
            ['symbol', 'name', 'price_usd', 'market_cap', 'price_change_24h', 
             'viability_score', 'risk_score', 'momentum_score', 'holder_count', 'opportunity_score']
        ]
        
        st.dataframe(
            top_opportunities.style.format({
                'price_usd': '${:.8f}',
                'market_cap': '${:,.0f}',
                'price_change_24h': '{:.2f}%',
                'viability_score': '{:.1f}',
                'risk_score': '{:.1f}',
                'momentum_score': '{:.1f}',
                'opportunity_score': '{:.2f}'
            }),
            use_container_width=True
        )

def main():
    st.title("📊 Token Investment Dashboard")
    st.markdown("*Analyse complète des tokens pour optimiser vos décisions d'investissement*")
    
    # Sidebar pour la configuration
    st.sidebar.header("⚙️ Configuration")
    
    # Chemin vers la base de données
    db_path = st.sidebar.text_input(
        "Chemin vers la base SQLite", 
        value="solana_wallet_monitor.db",
        help="Chemin vers votre fichier de base de données SQLite"
    )
    
    # Chargement des données
    if st.sidebar.button("🔄 Charger les données") or 'df' not in st.session_state:
        with st.spinner("Chargement des données..."):
            df = load_data(db_path)
            if not df.empty:
                st.session_state.df = df
                st.success(f"✅ {len(df)} enregistrements chargés")
            else:
                st.error("❌ Impossible de charger les données")
                return
    
    if 'df' not in st.session_state:
        st.warning("⚠️ Veuillez d'abord charger les données")
        return
    
    df = st.session_state.df
    
    # Navigation
    tab1, tab2, tab3 = st.tabs(["🔍 Analyse Token", "🎯 Opportunités", "📊 Vue Globale"])
    
    with tab1:
        st.header("🔍 Analyse Détaillée d'un Token")
        
        # Options de sélection du token
        col_search1, col_search2 = st.columns([2, 1])
        
        with col_search1:
            search_method = st.radio(
                "Méthode de recherche",
                ["📝 Saisir l'adresse", "📋 Liste déroulante"],
                horizontal=True
            )
        
        with col_search2:
            if st.button("🔄 Actualiser la liste"):
                st.rerun()
        
        token_address = None
        
        if search_method == "📝 Saisir l'adresse":
            # Saisie directe de l'adresse
            token_address = st.text_input(
                "Adresse du token",
                placeholder="Ex: AZBRbNNgmMQScrZZD3w5y2gooue6um9P3RwKneJHGL1",
                help="Collez l'adresse complète du token à analyser"
            ).strip()
            
            # Vérification que le token existe
            if token_address:
                if token_address not in df['token_address'].values:
                    st.error(f"❌ Token non trouvé: {token_address}")
                    # Suggestions de tokens similaires
                    similar_tokens = df[df['token_address'].str.contains(token_address[:8], case=False, na=False)]['token_address'].unique()[:3]
                    if len(similar_tokens) > 0:
                        st.info("💡 Tokens similaires trouvés:")
                        for similar in similar_tokens:
                            token_info = df[df['token_address'] == similar].iloc[0]
                            symbol = token_info['symbol'] if pd.notna(token_info['symbol']) else 'N/A'
                            st.write(f"• `{similar}` ({symbol})")
                    token_address = None
                else:
                    # Afficher les infos du token trouvé
                    token_info = df[df['token_address'] == token_address].iloc[0]
                    symbol = token_info['symbol'] if pd.notna(token_info['symbol']) else 'N/A'
                    name = token_info['name'] if pd.notna(token_info['name']) else 'Unknown'
                    st.success(f"✅ Token trouvé: **{symbol}** - {name}")
        
        else:
            # Liste déroulante (ancienne méthode)
            token_list = get_token_list(df)
            if token_list:
                selected_token_info = st.selectbox(
                    "Sélectionnez un token",
                    token_list,
                    format_func=lambda x: x[0]
                )
                token_address = selected_token_info[1]
        
        # Analyse du token si une adresse valide est sélectionnée
        if token_address:
            df_token = df[df['token_address'] == token_address].sort_values('datetime', ascending=False)
            
            if not df_token.empty:
                # Métriques principales
                display_token_metrics(df_token)
                
                # Graphiques
                col1, col2 = st.columns(2)
                
                with col1:
                    st.plotly_chart(create_price_chart(df_token), use_container_width=True)
                    
                with col2:
                    st.plotly_chart(create_risk_scores_chart(df_token), use_container_width=True)
                
                st.plotly_chart(create_market_metrics_chart(df_token), use_container_width=True)
                
                col3, col4 = st.columns(2)
                
                with col3:
                    st.plotly_chart(create_volume_analysis(df_token), use_container_width=True)
                    
                with col4:
                    st.plotly_chart(create_holder_analysis(df_token), use_container_width=True)
                
                # Données brutes
                with st.expander("📋 Données Historiques"):
                    st.dataframe(df_token.drop(['id', 'previous_snapshot_id'], axis=1), use_container_width=True)
        
        elif search_method == "📋 Liste déroulante":
            st.warning("Aucun token trouvé dans les données")
        else:
            st.info("👆 Saisissez une adresse de token pour commencer l'analyse")
    
    with tab2:
        create_opportunity_dashboard(df)
    
    with tab3:
        st.header("📊 Vue d'Ensemble du Marché")
        
        # Statistiques globales
        latest_data = df[df['snapshot_timestamp'] == df['snapshot_timestamp'].max()]
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Tokens Analysés", len(latest_data))
            
        with col2:
            avg_risk = latest_data['risk_score'].mean()
            st.metric("Risque Moyen", f"{avg_risk:.1f}")
            
        with col3:
            avg_viability = latest_data['viability_score'].mean()
            st.metric("Viabilité Moyenne", f"{avg_viability:.1f}")
            
        with col4:
            total_market_cap = latest_data['market_cap'].sum()
            st.metric("Market Cap Total", f"${total_market_cap:,.0f}")
        
        # Distribution des scores
        col5, col6 = st.columns(2)
        
        with col5:
            fig_risk = px.histogram(
                latest_data, 
                x='risk_score', 
                nbins=20, 
                title="Distribution des Scores de Risque",
                labels={'risk_score': 'Score de Risque', 'count': 'Nombre de Tokens'}
            )
            st.plotly_chart(fig_risk, use_container_width=True)
        
        with col6:
            fig_viability = px.histogram(
                latest_data, 
                x='viability_score', 
                nbins=20, 
                title="Distribution des Scores de Viabilité",
                labels={'viability_score': 'Score de Viabilité', 'count': 'Nombre de Tokens'}
            )
            st.plotly_chart(fig_viability, use_container_width=True)

if __name__ == "__main__":
    main()