import streamlit as st
import requests
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import time

# Configuration de la page
st.set_page_config(
    page_title="Transactions Pump.fun - Détails",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Configuration de l'API
API_BASE_URL = "http://localhost:8010/api"

@st.cache_data(ttl=30)
def fetch_detailed_transactions():
    """Récupère les transactions détaillées avec toutes les informations"""
    try:
        # Utiliser le nouvel endpoint dédié
        response = requests.get(f"{API_BASE_URL}/recent-purchases-detailed?hours_back=24&limit=100", timeout=10)
        if response.status_code == 200:
            data = response.json()
            return data.get('purchases', [])
        else:
            st.error(f"Erreur API: {response.status_code}")
            return []
    except Exception as e:
        st.error(f"Erreur de connexion: {e}")
        return []

@st.cache_data(ttl=60)
def fetch_recent_purchases_detailed():
    """Récupère toutes les transactions récentes avec détails complets"""
    try:
        # Cette fonction nécessiterait un endpoint API dédié
        # Pour l'instant, on simule avec les données disponibles
        
        # Récupérer les tokens récents
        response = requests.get(f"{API_BASE_URL}/recent-tokens?hours_back=24&limit=50", timeout=10)
        if response.status_code == 200:
            data = response.json()
            tokens = data.get('tokens', [])
            
            detailed_purchases = []
            
            for token in tokens:
                # Pour chaque token, récupérer les achats
                for buyer in token.get('early_adopter_buyers', []):
                    try:
                        wallet_response = requests.get(f"{API_BASE_URL}/wallet/{buyer}", timeout=5)
                        if wallet_response.status_code == 200:
                            wallet_data = wallet_response.json()
                            
                            for purchase in wallet_data.get('recent_purchases', []):
                                if purchase['token_address'] == token['address']:
                                    detailed_purchases.append({
                                        **purchase,
                                        'token_name': token.get('name'),
                                        'token_symbol': token.get('symbol'),
                                        'token_creator': token['creator'],
                                        'token_created_at': token['created_at'],
                                        'early_adopter_profile': wallet_data.get('early_adopter_profile')
                                    })
                    except:
                        continue
            
            return detailed_purchases
        return []
    except:
        return []

def format_wallet_address(address):
    """Formate une adresse de wallet"""
    if not address:
        return "N/A"
    return f"{address[:8]}...{address[-8:]}"

def format_timestamp(timestamp_str):
    """Formate un timestamp"""
    try:
        dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except:
        return timestamp_str

def format_sol_amount(amount):
    """Formate un montant SOL"""
    if amount is None:
        return "N/A"
    return f"{amount:.4f} SOL"

def format_minutes_ago(minutes):
    """Formate le temps écoulé"""
    if minutes < 60:
        return f"{minutes}min"
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours}h{mins:02d}min"

def main():
    st.title("📋 Transactions Pump.fun - Analyse Détaillée")
    st.markdown("*Analyse complète des achats de tokens pump.fun détectés*")
    
    # Sidebar pour les contrôles
    with st.sidebar:
        st.header("⚙️ Filtres")
        
        # Filtre par période
        time_filter = st.selectbox(
            "Période",
            ["Dernière heure", "Dernières 6h", "Dernières 24h", "Dernière semaine"],
            index=2
        )
        
        # Filtre par montant minimum
        min_sol = st.slider("Montant SOL minimum", 0.0, 1.0, 0.01, 0.001)
        
        # Filtre par timing
        max_minutes = st.slider("Max minutes après création", 0, 360, 60)
        
        # Filtre early adopters uniquement
        only_early_adopters = st.checkbox("Early adopters uniquement", value=True)
        
        # Bouton de rafraîchissement
        if st.button("🔄 Actualiser", use_container_width=True):
            st.cache_data.clear()
            st.rerun()
    
    # Récupération des données
    with st.spinner("Chargement des transactions..."):
        transactions = fetch_detailed_transactions()
    
    if not transactions:
        st.warning("Aucune transaction détaillée trouvée")
        st.stop()
    
    # Conversion en DataFrame
    df = pd.DataFrame(transactions)
    
    # Application des filtres
    if min_sol > 0:
        df = df[df['sol_amount'] >= min_sol]
    
    if max_minutes < 360:
        df = df[df['minutes_after_creation'] <= max_minutes]
    
    if only_early_adopters:
        df = df[df['early_adopter_profile'].notna()]
    
    # Métriques principales
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Transactions trouvées", len(df))
    
    with col2:
        avg_timing = df['minutes_after_creation'].mean() if len(df) > 0 else 0
        st.metric("Timing moyen", f"{avg_timing:.1f}min")
    
    with col3:
        avg_sol = df['sol_amount'].mean() if len(df) > 0 else 0
        st.metric("Montant SOL moyen", f"{avg_sol:.4f}")
    
    with col4:
        unique_tokens = df['token_address'].nunique() if len(df) > 0 else 0
        st.metric("Tokens uniques", unique_tokens)
    
    # Tabs pour organiser les vues
    tab1, tab2, tab3, tab4 = st.tabs(["🔍 Détails", "📊 Analyse", "👥 Early Adopters", "📈 Timeline"])
    
    with tab1:
        st.header("🔍 Détails des Transactions")
        
        if len(df) > 0:
            # Tableau détaillé
            display_df = df.copy()
            
            # Formater les colonnes pour l'affichage
            display_df['Signature'] = display_df['signature'].apply(lambda x: f"{x[:12]}...")
            display_df['Date/Heure'] = display_df['timestamp'].apply(format_timestamp)
            display_df['Acheteur'] = display_df['buyer_address'].apply(format_wallet_address)
            display_df['Token'] = display_df.apply(lambda row: f"{row['token_symbol']} ({format_wallet_address(row['token_address'])})", axis=1)
            display_df['Créateur'] = display_df['token_creator'].apply(format_wallet_address)
            display_df['Montant SOL'] = display_df['sol_amount'].apply(format_sol_amount)
            display_df['Timing'] = display_df['minutes_after_creation'].apply(format_minutes_ago)
            display_df['Score EA'] = display_df['early_adopter_profile'].apply(
                lambda x: f"{x['confidence_score']:.3f}" if x else "N/A"
            )
            
            # Colonnes à afficher
            display_columns = [
                'Date/Heure', 'Acheteur', 'Token', 'Créateur', 
                'Montant SOL', 'Timing', 'Score EA', 'Signature'
            ]
            
            st.dataframe(
                display_df[display_columns],
                use_container_width=True,
                height=600
            )
            
            # Détails d'une transaction sélectionnée
            st.subheader("🔍 Détails de Transaction")
            
            selected_idx = st.selectbox(
                "Sélectionner une transaction",
                range(len(df)),
                format_func=lambda i: f"{df.iloc[i]['token_symbol']} - {format_wallet_address(df.iloc[i]['buyer_address'])} - {format_timestamp(df.iloc[i]['timestamp'])}"
            )
            
            if selected_idx is not None:
                tx = df.iloc[selected_idx]
                
                col1, col2 = st.columns(2)
                
                with col1:
                    st.write("**Informations Transaction:**")
                    st.write(f"• **Signature:** `{tx['signature']}`")
                    st.write(f"• **Date:** {format_timestamp(tx['timestamp'])}")
                    st.write(f"• **Montant SOL:** {format_sol_amount(tx['sol_amount'])}")
                    st.write(f"• **Timing:** {format_minutes_ago(tx['minutes_after_creation'])}")
                    
                    st.write("**Informations Token:**")
                    st.write(f"• **Adresse:** `{tx['token_address']}`")
                    st.write(f"• **Nom:** {tx['token_name'] or 'Non disponible'}")
                    st.write(f"• **Symbole:** {tx['token_symbol']}")
                    st.write(f"• **Créateur:** `{tx['token_creator']}`")
                    st.write(f"• **Créé le:** {format_timestamp(tx['token_created_at'])}")
                
                with col2:
                    st.write("**Informations Acheteur:**")
                    st.write(f"• **Adresse:** `{tx['buyer_address']}`")
                    
                    if tx['early_adopter_profile']:
                        profile = tx['early_adopter_profile']
                        st.write(f"• **Score confiance:** {profile['confidence_score']:.3f}")
                        st.write(f"• **Taux succès:** {profile['success_rate']*100:.1f}%")
                        st.write(f"• **Total picks:** {profile['total_picks']}")
                        st.write(f"• **ROI moyen:** {profile['avg_roi']:.1f}x")
                    else:
                        st.write("• **Profil:** Non qualifié comme early adopter")
                    
                    # Liens utiles
                    st.write("**Liens:**")
                    st.write(f"[Solscan Transaction](https://solscan.io/tx/{tx['signature']})")
                    st.write(f"[Solscan Token](https://solscan.io/token/{tx['token_address']})")
                    st.write(f"[Solscan Wallet](https://solscan.io/account/{tx['buyer_address']})")
                    st.write(f"[Pump.fun](https://pump.fun/{tx['token_address']})")
        
        else:
            st.info("Aucune transaction correspondant aux filtres")
    
    with tab2:
        st.header("📊 Analyse des Transactions")
        
        if len(df) > 0:
            col1, col2 = st.columns(2)
            
            with col1:
                # Distribution des timings
                fig_timing = px.histogram(
                    df, 
                    x='minutes_after_creation',
                    nbins=20,
                    title="Distribution des Timings d'Achat",
                    labels={'minutes_after_creation': 'Minutes après création', 'count': 'Nombre de transactions'}
                )
                st.plotly_chart(fig_timing, use_container_width=True)
                
                # Top tokens
                token_counts = df['token_symbol'].value_counts().head(10)
                fig_tokens = px.bar(
                    x=token_counts.values,
                    y=token_counts.index,
                    orientation='h',
                    title="Top 10 Tokens par Nombre d'Achats"
                )
                st.plotly_chart(fig_tokens, use_container_width=True)
            
            with col2:
                # Distribution des montants SOL
                fig_amounts = px.histogram(
                    df,
                    x='sol_amount',
                    nbins=20,
                    title="Distribution des Montants SOL",
                    labels={'sol_amount': 'Montant SOL', 'count': 'Nombre de transactions'}
                )
                st.plotly_chart(fig_amounts, use_container_width=True)
                
                # Relation timing vs montant
                fig_scatter = px.scatter(
                    df,
                    x='minutes_after_creation',
                    y='sol_amount',
                    color='token_symbol',
                    title="Timing vs Montant SOL",
                    labels={
                        'minutes_after_creation': 'Minutes après création',
                        'sol_amount': 'Montant SOL'
                    }
                )
                st.plotly_chart(fig_scatter, use_container_width=True)
    
    with tab3:
        st.header("👥 Profils Early Adopters")
        
        # Filtrer les early adopters
        ea_df = df[df['early_adopter_profile'].notna()].copy()
        
        if len(ea_df) > 0:
            # Extraire les scores de confiance
            ea_df['confidence_score'] = ea_df['early_adopter_profile'].apply(lambda x: x['confidence_score'])
            ea_df['success_rate'] = ea_df['early_adopter_profile'].apply(lambda x: x['success_rate'])
            ea_df['total_picks'] = ea_df['early_adopter_profile'].apply(lambda x: x['total_picks'])
            
            # Top early adopters
            top_adopters = ea_df.groupby('buyer_address').agg({
                'confidence_score': 'first',
                'success_rate': 'first',
                'total_picks': 'first',
                'sol_amount': 'sum',
                'token_address': 'count'
            }).sort_values('confidence_score', ascending=False).head(10)
            
            st.subheader("🏆 Top Early Adopters")
            
            adopters_display = []
            for idx, (wallet, data) in enumerate(top_adopters.iterrows(), 1):
                adopters_display.append({
                    'Rang': idx,
                    'Wallet': format_wallet_address(wallet),
                    'Score': f"{data['confidence_score']:.3f}",
                    'Succès': f"{data['success_rate']*100:.1f}%",
                    'Total Picks': data['total_picks'],
                    'SOL Total': f"{data['sol_amount']:.4f}",
                    'Achats Récents': data['token_address']
                })
            
            st.dataframe(pd.DataFrame(adopters_display), use_container_width=True)
            
            # Graphique scores vs performance
            col1, col2 = st.columns(2)
            
            with col1:
                fig_scores = px.scatter(
                    ea_df,
                    x='confidence_score',
                    y='success_rate',
                    size='total_picks',
                    title="Score de Confiance vs Taux de Succès"
                )
                st.plotly_chart(fig_scores, use_container_width=True)
            
            with col2:
                fig_activity = px.histogram(
                    ea_df,
                    x='confidence_score',
                    nbins=15,
                    title="Distribution des Scores de Confiance"
                )
                st.plotly_chart(fig_activity, use_container_width=True)
        
        else:
            st.info("Aucun early adopter trouvé dans les transactions filtrées")
    
    with tab4:
        st.header("📈 Timeline des Transactions")
        
        if len(df) > 0:
            # Convertir les timestamps pour le graphique
            df_timeline = df.copy()
            df_timeline['datetime'] = pd.to_datetime(df_timeline['timestamp'])
            df_timeline = df_timeline.sort_values('datetime')
            
            # Timeline des achats
            fig_timeline = px.scatter(
                df_timeline,
                x='datetime',
                y='sol_amount',
                color='token_symbol',
                size='minutes_after_creation',
                title="Timeline des Achats Pump.fun",
                labels={
                    'datetime': 'Date/Heure',
                    'sol_amount': 'Montant SOL',
                    'minutes_after_creation': 'Minutes après création'
                }
            )
            st.plotly_chart(fig_timeline, use_container_width=True)
            
            # Activité par heure
            df_timeline['hour'] = df_timeline['datetime'].dt.hour
            hourly_activity = df_timeline.groupby('hour').size()
            
            fig_hourly = px.bar(
                x=hourly_activity.index,
                y=hourly_activity.values,
                title="Activité par Heure de la Journée",
                labels={'x': 'Heure', 'y': 'Nombre de transactions'}
            )
            st.plotly_chart(fig_hourly, use_container_width=True)
        
        else:
            st.info("Aucune donnée pour la timeline")

if __name__ == "__main__":
    main()