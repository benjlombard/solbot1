import streamlit as st
import requests
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import numpy as np


def get_safe(data, key, default):
    """Récupère une valeur d'un dictionnaire de manière sûre, en retournant une valeur par défaut
    si la clé est absente ou si la valeur est None."""
    val = data.get(key)
    return default if val is None else val


# Configuration API
API_BASE_URL = "http://localhost:8010/api"

@st.cache_data(ttl=60)
def fetch_token_analysis_data():
    """Récupère les données d'analyse des tokens"""
    try:
        response = requests.get(f"{API_BASE_URL}/tokens-analysis", timeout=10)
        if response.status_code == 200:
            return response.json()
        return []
    except:
        return []

@st.cache_data(ttl=300)
def fetch_token_details(token_address):
    """Récupère les détails complets d'un token"""
    try:
        response = requests.get(f"{API_BASE_URL}/token/{token_address}/details", timeout=10)
        if response.status_code == 200:
            return response.json()
        return None
    except:
        return None

def calculate_risk_score(token_data):
    """Calcule un score de risque (0-100, plus bas = moins risqué)"""
    risk_factors = {
        'liquidity_low': 30 if get_safe(token_data, 'liquidity_sol', 0) < 10 else 0,
        'holder_concentration': min(50, get_safe(token_data, 'top_5_holders_percentage', 0)),
        'no_early_adopters': 20 if len(get_safe(token_data, 'early_adopter_buyers', [])) == 0 else 0,
        'recent_creation': 15 if get_safe(token_data, 'age_hours', 0) < 1 else 0,
        'low_volume': 25 if get_safe(token_data, 'volume_24h_sol', 0) < 1 else 0,
        'creator_history': 10 if get_safe(token_data, 'creator_previous_tokens', 0) > 5 else 0
    }
    
    total_risk = sum(risk_factors.values())
    return min(100, total_risk)

def calculate_opportunity_score(token_data):
    """Calcule un score d'opportunité (0-100, plus haut = meilleure opportunité)"""
    opportunity_factors = {
        'early_adopter_signal': min(40, len(get_safe(token_data, 'early_adopter_buyers', [])) * 10),
        'good_timing': 20 if get_safe(token_data, 'age_hours', 24) < 6 else 10,
        'rising_volume': 15 if get_safe(token_data, 'volume_trend', 0) > 0 else 0,
        'good_liquidity': 15 if get_safe(token_data, 'liquidity_sol', 0) > 20 else 5,
        'holder_growth': 10 if get_safe(token_data, 'holder_growth_24h', 0) > 0 else 0
    }
    
    total_opportunity = sum(opportunity_factors.values())
    return min(100, total_opportunity)

def format_large_number(num):
    """Formate les gros nombres"""
    if num >= 1_000_000:
        return f"{num/1_000_000:.1f}M"
    elif num >= 1_000:
        return f"{num/1_000:.1f}K"
    return f"{num:.2f}"

def get_recommendation(risk_score, opportunity_score, token_data):
    """Génère une recommandation d'investissement"""
    ea_count = len(get_safe(token_data, 'early_adopter_buyers', []))
    age_hours = get_safe(token_data, 'age_hours', 24)
    
    if opportunity_score >= 70 and risk_score <= 30 and ea_count >= 3:
        return "🟢 ACHAT FORT", "Excellente opportunité avec signal EA fort"
    elif opportunity_score >= 50 and risk_score <= 50 and ea_count >= 1:
        return "🟡 ACHAT MODÉRÉ", "Opportunité intéressante, surveiller de près"
    elif opportunity_score >= 30 and risk_score <= 70:
        return "🟠 SURVEILLANCE", "Potentiel mais risques présents"
    else:
        return "🔴 ÉVITER", "Risques trop élevés ou opportunité faible"

def main():
    st.title("🔍 Analyse Avancée des Tokens Pump.fun")
    st.markdown("*Aide à la décision d'investissement avec scoring avancé*")
    
    # Sidebar pour les filtres
    with st.sidebar:
        st.header("🎛️ Filtres et Paramètres")
        
        # Filtres temporels
        age_filter = st.selectbox(
            "Âge du token",
            ["Toutes", "< 1h", "< 6h", "< 24h", "< 7j"],
            index=2
        )
        
        # Filtres de qualité
        min_liquidity = st.slider("Liquidité minimum (SOL)", 0, 100, 0)
        min_holders = st.slider("Holders minimum", 0, 1000, 0)
        min_ea_signal = st.slider("Signal EA minimum", 0, 10, 0)
        
        # Filtres de performance
        min_volume_24h = st.slider("Volume 24h min (SOL)", 0.0, 50.0, 0.0)
        max_risk_score = st.slider("Score risque max", 0, 100, 100)
        min_opportunity_score = st.slider("Score opportunité min", 0, 100, 0)
        
        # Options d'affichage
        show_only_recommendations = st.checkbox("Montrer seulement les recommandations d'achat", False)
        sort_by = st.selectbox(
            "Trier par",
            ["Score Opportunité", "Score Risque", "Signal EA", "Volume 24h", "Âge"],
            index=0
        )
        
        if st.button("🔄 Actualiser", use_container_width=True, key="token_analysis_refresh"):
            st.cache_data.clear()
            st.rerun()
    
    # Récupération des données
    with st.spinner("Analyse des tokens en cours..."):
        tokens_data = fetch_token_analysis_data()

    if not tokens_data:
        st.warning("⚠️ Aucune donnée disponible via l'API. Affichage des données de démonstration.")
        # Utiliser des données de démonstration
        tokens_data = [
            {
                'address': 'demo1',
                'symbol': 'DEMO1',
                'name': 'Demo Token 1',
                'age_hours': 2,
                'liquidity_sol': 25,
                'holders_count': 150,
                'early_adopter_buyers': ['addr1', 'addr2', 'addr3'],
                'volume_24h_sol': 10,
                'price_usd': 0.000045,
                'market_cap_usd': 45000,
                'bonding_curve_progress': 67.8,
                'top_5_holders_percentage': 35
            },
            {
                'address': 'demo2',
                'symbol': 'DEMO2', 
                'name': 'Demo Token 2',
                'age_hours': 8,
                'liquidity_sol': 15,
                'holders_count': 80,
                'early_adopter_buyers': ['addr4', 'addr5'],
                'volume_24h_sol': 5,
                'price_usd': 0.000032,
                'market_cap_usd': 32000,
                'bonding_curve_progress': 45.2,
                'top_5_holders_percentage': 50
            }
        ]
    
    
    # Calcul des scores et filtrage
    analyzed_tokens = []
    for token in tokens_data:
        # Calcul des scores
        risk_score = calculate_risk_score(token)
        opportunity_score = calculate_opportunity_score(token)
        recommendation, reason = get_recommendation(risk_score, opportunity_score, token)
        
        # Application des filtres
        ea_count = len(get_safe(token, 'early_adopter_buyers', []))
        age_hours = get_safe(token, 'age_hours', 24)
        
        # Filtres temporels
        if age_filter != "Toutes":
            if age_filter == "< 1h" and age_hours >= 1:
                continue
            elif age_filter == "< 6h" and age_hours >= 6:
                continue
            elif age_filter == "< 24h" and age_hours >= 24:
                continue
            elif age_filter == "< 7j" and age_hours >= 168:
                continue
        
        # Autres filtres
        if (get_safe(token, 'liquidity_sol', 0) < min_liquidity or
            get_safe(token, 'holders_count', 0) < min_holders or
            ea_count < min_ea_signal or
            get_safe(token, 'volume_24h_sol', 0) < min_volume_24h or
            risk_score > max_risk_score or
            opportunity_score < min_opportunity_score):
            continue
        
        # Filtre recommandations
        if show_only_recommendations and not recommendation.startswith("🟢"):
            if not (recommendation.startswith("🟡") and opportunity_score >= 60):
                continue
        
        token_analyzed = {
            **token,
            'risk_score': risk_score,
            'opportunity_score': opportunity_score,
            'recommendation': recommendation,
            'reason': reason,
            'ea_count': ea_count
        }
        analyzed_tokens.append(token_analyzed)
    
    # Tri
    sort_key_map = {
        "Score Opportunité": 'opportunity_score',
        "Score Risque": 'risk_score',
        "Signal EA": 'ea_count',
        "Volume 24h": 'volume_24h_sol',
        "Âge": 'age_hours'
    }
    
    if sort_by in sort_key_map:
        reverse = sort_by not in ["Score Risque", "Âge"]
        sort_key = sort_key_map[sort_by]
        analyzed_tokens.sort(key=lambda x: get_safe(x, sort_key, 0), reverse=reverse)
    
    # Métriques globales
    col1, col2, col3, col4, col5 = st.columns(5)
    
    total_tokens = len(analyzed_tokens)
    strong_buy = len([t for t in analyzed_tokens if t['recommendation'].startswith("🟢")])
    moderate_buy = len([t for t in analyzed_tokens if t['recommendation'].startswith("🟡")])
    avg_opportunity = np.mean([t['opportunity_score'] for t in analyzed_tokens]) if analyzed_tokens else 0
    avg_risk = np.mean([t['risk_score'] for t in analyzed_tokens]) if analyzed_tokens else 0
    
    with col1:
        st.metric("Tokens Analysés", total_tokens)
    with col2:
        st.metric("🟢 Achat Fort", strong_buy)
    with col3:
        st.metric("🟡 Achat Modéré", moderate_buy)
    with col4:
        st.metric("Score Opportunité Moy.", f"{avg_opportunity:.1f}")
    with col5:
        st.metric("Score Risque Moy.", f"{avg_risk:.1f}")
    
    # Onglets
    tab1, tab2, tab3, tab4 = st.tabs(["📊 Vue d'ensemble", "🎯 Tokens à Surveiller", "⚡ Analyses Rapides", "🔬 Analyse Détaillée"])
    
    with tab1:
        st.header("📊 Vue d'ensemble du Marché")
        
        if analyzed_tokens:
            for token in analyzed_tokens:
                if token.get('ea_count') is None:
                    token['ea_count'] = 0
                if token.get('opportunity_score') is None:
                    token['opportunity_score'] = 0
                if token.get('risk_score') is None:
                    token['risk_score'] = 0
                if token.get('volume_24h_sol') is None:
                    token['volume_24h_sol'] = 0
                if token.get('age_hours') is None:
                    token['age_hours'] = 0
            # Graphiques de distribution
            col1, col2 = st.columns(2)
            
            with col1:
                # Distribution des scores d'opportunité
                scores_df = pd.DataFrame(analyzed_tokens)
                fig_opp = px.histogram(
                    scores_df,
                    x='opportunity_score',
                    nbins=20,
                    title="Distribution des Scores d'Opportunité",
                    color_discrete_sequence=['#2E8B57']
                )
                st.plotly_chart(fig_opp, use_container_width=True)
                
                # Distribution des signaux EA
                max_ea_count = scores_df['ea_count'].max()
                # Cast to int to avoid numpy.int64 type error in plotly
                nbins_ea = int(max(1, max_ea_count if max_ea_count is not None else 1))

                fig_ea = px.histogram(
                    scores_df,
                    x='ea_count',
                    nbins=nbins_ea,
                    title="Distribution des Signaux Early Adopters",
                    color_discrete_sequence=['#FF6B6B']
                )
                st.plotly_chart(fig_ea, use_container_width=True)
            
            with col2:
                # Relation Risque vs Opportunité
                fig_risk_opp = px.scatter(
                    scores_df,
                    x='risk_score',
                    y='opportunity_score',
                    color='recommendation',
                    size='volume_24h_sol',
                    hover_data=['symbol', 'ea_count', 'age_hours'],
                    title="Matrice Risque vs Opportunité",
                    labels={
                        'risk_score': 'Score de Risque',
                        'opportunity_score': 'Score d\'Opportunité'
                    }
                )
                st.plotly_chart(fig_risk_opp, use_container_width=True)
                
                # Répartition des recommandations
                recommendations = scores_df['recommendation'].str.split(' ').str[0].value_counts()
                fig_rec = px.pie(
                    values=recommendations.values,
                    names=recommendations.index,
                    title="Répartition des Recommandations"
                )
                st.plotly_chart(fig_rec, use_container_width=True)
    
    with tab2:
        st.header("🎯 Tokens à Surveiller de Près")
        
        if analyzed_tokens:
            # Convertir en DataFrame pour une manipulation facile
            df = pd.DataFrame(analyzed_tokens)

            # Définir toutes les colonnes possibles
            ALL_COLUMNS = [
                "Lien", "Symbole", "Nom", "Âge (h)", "Market Cap ($)", "Holders", "Volume (SOL)", 
                "Risque", "Opportunité", "Recommandation", "Twitter", "Website", "Telegram", 
                "Metadata", "Total Supply", "Description", "Créateur", "NSFW", "Vérifié",
                "Bonding Curve", "KOTH Timestamp", "Assoc. Bonding Curve", "Raydium Pool",
                "Virtual SOL", "Virtual Tokens", "Hidden", "Show Name", "Last Trade",
                "Market Cap (Native)", "Market ID", "Inverted", "Real SOL", "Real Tokens",
                "Ban Expiry", "Last Reply", "Reply Count", "Banned", "Live", "Initialized",
                "Video", "Updated At", "Pump Swap Pool", "ATH Market Cap", "ATH Timestamp",
                "Banner", "Hide Banner", "Livestream Score"
            ]
            
            # Par défaut, afficher toutes les colonnes comme demandé par l'utilisateur
            DEFAULT_COLUMNS = ALL_COLUMNS.copy()

            # Widget de sélection de colonnes dans la sidebar
            with st.sidebar:
                st.header("📊 Colonnes du Tableau")
                selected_columns = st.multiselect(
                    "Choisir les colonnes à afficher",
                    options=ALL_COLUMNS,
                    default=DEFAULT_COLUMNS
                )

            # Préparer les données pour le tableau
            table_data = []
            for _, token in df.iterrows():
                row_data = {
                    "Lien": f"https://pump.fun/{get_safe(token, 'address', '')}",
                    "Symbole": get_safe(token, 'symbol', 'UNK'),
                    "Nom": get_safe(token, 'name', 'N/A'),
                    "Âge (h)": get_safe(token, 'age_hours', 0),
                    "Market Cap ($)": get_safe(token, 'usd_market_cap', 0),
                    "Holders": get_safe(token, 'holders_count', 0),
                    "Volume (SOL)": get_safe(token, 'volume_24h_sol', 0),
                    "Risque": get_safe(token, 'risk_score', 0),
                    "Opportunité": get_safe(token, 'opportunity_score', 0),
                    "Recommandation": get_safe(token, 'recommendation', ''),
                    "Twitter": get_safe(token, 'twitter', ''),
                    "Website": get_safe(token, 'website', ''),
                    "Telegram": get_safe(token, 'telegram', ''),
                    "Metadata": get_safe(token, 'metadata_uri', ''),
                    "Total Supply": get_safe(token, 'total_supply', 0),
                    "Description": get_safe(token, 'description', ''),
                    "Créateur": get_safe(token, 'creator', ''),
                    "NSFW": get_safe(token, 'nsfw', False),
                    "Vérifié": get_safe(token, 'is_verified', False),
                    "Bonding Curve": get_safe(token, 'bonding_curve', ''),
                    "KOTH Timestamp": get_safe(token, 'king_of_the_hill_timestamp', None),
                    "Assoc. Bonding Curve": get_safe(token, 'associated_bonding_curve', ''),
                    "Raydium Pool": get_safe(token, 'raydium_pool', ''),
                    "Virtual SOL": get_safe(token, 'virtual_sol_reserves', 0),
                    "Virtual Tokens": get_safe(token, 'virtual_token_reserves', 0),
                    "Hidden": get_safe(token, 'hidden', False),
                    "Show Name": get_safe(token, 'show_name', False),
                    "Last Trade": get_safe(token, 'last_trade_timestamp', None),
                    "Market Cap (Native)": get_safe(token, 'market_cap', 0),
                    "Market ID": get_safe(token, 'market_id', ''),
                    "Inverted": get_safe(token, 'inverted', False),
                    "Real SOL": get_safe(token, 'real_sol_reserves', 0),
                    "Real Tokens": get_safe(token, 'real_token_reserves', 0),
                    "Ban Expiry": get_safe(token, 'livestream_ban_expiry', None),
                    "Last Reply": get_safe(token, 'last_reply', None),
                    "Reply Count": get_safe(token, 'reply_count', 0),
                    "Banned": get_safe(token, 'is_banned', False),
                    "Live": get_safe(token, 'is_currently_live', False),
                    "Initialized": get_safe(token, 'initialized', False),
                    "Video": get_safe(token, 'video_uri', ''),
                    "Updated At": get_safe(token, 'updated_at', None),
                    "Pump Swap Pool": get_safe(token, 'pump_swap_pool', ''),
                    "ATH Market Cap": get_safe(token, 'ath_market_cap', 0),
                    "ATH Timestamp": get_safe(token, 'ath_market_cap_timestamp', None),
                    "Banner": get_safe(token, 'banner_uri', ''),
                    "Hide Banner": get_safe(token, 'hide_banner', False),
                    "Livestream Score": get_safe(token, 'livestream_downrank_score', 0)
                }
                table_data.append(row_data)
            
            display_df = pd.DataFrame(table_data)
            
            # Filtrer le DataFrame pour n'afficher que les colonnes sélectionnées
            if selected_columns:
                existing_selected_columns = [col for col in selected_columns if col in display_df.columns]
                display_df = display_df[existing_selected_columns]

            # Afficher le tableau interactif
            st.dataframe(
                display_df,
                column_config={
                    "Lien": st.column_config.LinkColumn("Pump.fun", display_text="🚀"),
                    "Twitter": st.column_config.LinkColumn("Twitter"),
                    "Website": st.column_config.LinkColumn("Website"),
                    "Telegram": st.column_config.LinkColumn("Telegram"),
                    "Metadata": st.column_config.LinkColumn("Metadata"),
                    "Banner": st.column_config.LinkColumn("Banner"),
                    "Video": st.column_config.LinkColumn("Video"),
                    "Market Cap ($)": st.column_config.NumberColumn(format="$ %.2f"),
                    "Market Cap (Native)": st.column_config.NumberColumn(format="%.2f"),
                    "ATH Market Cap": st.column_config.NumberColumn(format="$ %.2f"),
                    "Volume (SOL)": st.column_config.NumberColumn(format="%.2f SOL"),
                    "Âge (h)": st.column_config.NumberColumn(format="%.1f h"),
                    "Total Supply": st.column_config.NumberColumn(),
                    "Virtual SOL": st.column_config.NumberColumn(),
                    "Virtual Tokens": st.column_config.NumberColumn(),
                    "Real SOL": st.column_config.NumberColumn(),
                    "Real Tokens": st.column_config.NumberColumn(),
                    "Risque": st.column_config.ProgressColumn("Risque", min_value=0, max_value=100),
                    "Opportunité": st.column_config.ProgressColumn("Opportunité", min_value=0, max_value=100),
                    "NSFW": st.column_config.CheckboxColumn("NSFW"),
                    "Vérifié": st.column_config.CheckboxColumn("Vérifié"),
                    "Hidden": st.column_config.CheckboxColumn("Hidden"),
                    "Show Name": st.column_config.CheckboxColumn("Show Name"),
                    "Inverted": st.column_config.CheckboxColumn("Inverted"),
                    "Banned": st.column_config.CheckboxColumn("Banned"),
                    "Live": st.column_config.CheckboxColumn("Live"),
                    "Initialized": st.column_config.CheckboxColumn("Initialized"),
                    "Hide Banner": st.column_config.CheckboxColumn("Hide Banner"),
                    "KOTH Timestamp": st.column_config.DatetimeColumn("KOTH"),
                    "Last Trade": st.column_config.DatetimeColumn("Last Trade"),
                    "Ban Expiry": st.column_config.DatetimeColumn("Ban Expiry"),
                    "Last Reply": st.column_config.DatetimeColumn("Last Reply"),
                    "Updated At": st.column_config.DatetimeColumn("Updated At"),
                    "ATH Timestamp": st.column_config.DatetimeColumn("ATH"),
                },
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info("Aucun token ne correspond aux filtres actuels.")
    
    with tab3:
        st.header("⚡ Analyses et Actions Rapides")
        
        # Actions rapides
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.subheader("🔥 Top Opportunités")
            top_opportunities = sorted(analyzed_tokens, key=lambda x: x['opportunity_score'], reverse=True)[:10]
            
            for token in top_opportunities:
                st.write(f"**{get_safe(token, 'symbol', 'UNK')}** - {token['opportunity_score']}/100")
                st.write(f"[🚀 Pump.fun](https://pump.fun/{token['address']}) | EA: {token['ea_count']}")
                st.write("---")
        
        with col2:
            st.subheader("⚠️ Risques les Plus Faibles")
            low_risk = sorted(analyzed_tokens, key=lambda x: x['risk_score'])[:10]
            
            for token in low_risk:
                st.write(f"**{get_safe(token, 'symbol', 'UNK')}** - Risque: {token['risk_score']}/100")
                st.write(f"[🚀 Pump.fun](https://pump.fun/{token['address']}) | Opp: {token['opportunity_score']}/100")
                st.write("---")
        
        with col3:
            st.subheader("🎯 Signaux EA Forts")
            strong_ea = sorted(analyzed_tokens, key=lambda x: x['ea_count'], reverse=True)[:10]
            
            for token in strong_ea:
                st.write(f"**{get_safe(token, 'symbol', 'UNK')}** - {token['ea_count']} EA")
                st.write(f"[🚀 Pump.fun](https://pump.fun/{token['address']}) | Opp: {token['opportunity_score']}/100")
                st.write("---")
        
        # Export et copie
        st.subheader("📋 Export et Copie")
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            if st.button("📋 Copier Adresses Opportunités", use_container_width=True, key="copy_addresses"):
                top_addresses = [t['address'] for t in top_opportunities]
                st.text_area("Top Opportunités:", value='\n'.join(top_addresses), height=150)
        
        with col2:
            if st.button("📋 Copier Liens Pump.fun", use_container_width=True, key="copy_links"):
                top_links = [f"https://pump.fun/{t['address']}" for t in top_opportunities]
                st.text_area("Liens Pump.fun:", value='\n'.join(top_links), height=150)
        
        with col3:
            if st.button("📊 Exporter Analyse CSV", use_container_width=True, key="export_csv"):
                export_data = []
                for token in analyzed_tokens:
                    export_data.append({
                        'Adresse': token['address'],
                        'Symbole': get_safe(token, 'symbol', 'UNK'),
                        'Nom': get_safe(token, 'name', 'N/A'),
                        'Score_Opportunité': token['opportunity_score'],
                        'Score_Risque': token['risk_score'],
                        'Recommandation': token['recommendation'],
                        'Early_Adopters': token['ea_count'],
                        'Liquidité_SOL': get_safe(token, 'liquidity_sol', 0),
                        'Volume_24h_SOL': get_safe(token, 'volume_24h_sol', 0),
                        'Holders': get_safe(token, 'holders_count', 0),
                        'Âge_Heures': get_safe(token, 'age_hours', 0),
                        'Market_Cap_USD': get_safe(token, 'market_cap_usd', 0),
                        'Pump_fun_Link': f"https://pump.fun/{token['address']}"
                    })
                
                csv = pd.DataFrame(export_data).to_csv(index=False)
                st.download_button(
                    label="⬇️ Télécharger Analyse CSV",
                    data=csv,
                    file_name=f"token_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                    mime="text/csv",
                    use_container_width=True
                )
    
    with tab4:
        st.header("🔬 Analyse Détaillée d'un Token")
        
        if analyzed_tokens:
            # Sélecteur de token
            token_options = []
            for token in analyzed_tokens[:50]:
                label = f"{get_safe(token, 'symbol', 'UNK')} - Opp: {token['opportunity_score']}/100 - EA: {token['ea_count']}"
                token_options.append((label, token['address']))
            
            selected_token_label = st.selectbox(
                "Sélectionner un token pour analyse approfondie:",
                options=[opt[0] for opt in token_options],
                index=0
            )
            
            # Trouver le token correspondant
            selected_address = None
            for label, address in token_options:
                if label == selected_token_label:
                    selected_address = address
                    break
            
            if selected_address:
                # Récupérer les détails complets
                with st.spinner("Chargement des détails..."):
                    detailed_token = fetch_token_details(selected_address)
                
                if detailed_token:
                    # Affichage détaillé
                    col1, col2, col3 = st.columns(3)
                    
                    with col1:
                        st.subheader("📊 Métriques Avancées")
                        # Afficher toutes les métriques disponibles
                        st.json(detailed_token)
                    
                    with col2:
                        st.subheader("📈 Graphiques")
                        # Graphiques temporels si disponibles
                        if 'price_history' in detailed_token:
                            price_df = pd.DataFrame(detailed_token['price_history'])
                            fig_price = px.line(price_df, x='timestamp', y='price', title="Évolution du Prix")
                            st.plotly_chart(fig_price, use_container_width=True)
                    
                    with col3:
                        st.subheader("🎯 Recommandation Finale")
                        # Logique de recommandation avancée
                        token_data = next(t for t in analyzed_tokens if t['address'] == selected_address)
                        
                        st.metric("Score Opportunité", f"{token_data['opportunity_score']}/100")
                        st.metric("Score Risque", f"{token_data['risk_score']}/100")
                        
                        st.markdown(f"### {token_data['recommendation']}")
                        st.write(token_data['reason'])
                        
                        # Facteurs de décision
                        st.write("**Facteurs positifs:**")
                        if token_data['ea_count'] > 0:
                            st.write(f"✅ {token_data['ea_count']} Early Adopters détectés")
                        if get_safe(token_data, 'volume_24h_sol', 0) > 5:
                            st.write("✅ Volume élevé")
                        if get_safe(token_data, 'age_hours', 24) < 6:
                            st.write("✅ Token très récent")
                        
                        st.write("**Facteurs de risque:**")
                        if get_safe(token_data, 'liquidity_sol', 0) < 10:
                            st.write("⚠️ Liquidité faible")
                        if get_safe(token_data, 'top_5_holders_percentage', 0) > 50:
                            st.write("⚠️ Concentration élevée des holders")
                else:
                    st.error("Impossible de charger les détails du token")

if __name__ == "__main__":
    main()