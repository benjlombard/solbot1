import streamlit as st
import requests
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import time
import numpy as np
# Ajouter après les imports existants
import sys
import os

print(f"🔍 Python path: {sys.path}")
print(f"🔍 Current dir: {os.getcwd()}")
print(f"🔍 Script dir: {os.path.dirname(__file__)}")
print(f"🔍 Files in streamlit dir: {os.listdir(os.path.dirname(__file__))}")
# Ajouter le chemin pour importer la page d'analyse des tokens
sys.path.append(os.path.dirname(__file__))


# Configuration de la page
st.set_page_config(
    page_title="PumpFun Early Adopters Tracker - Polling",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded"
)

try:
    from token_analysis import main as token_analysis_main
except ImportError:
    token_analysis_main = None

# Par ceci :
try:
    import token_analysis
    token_analysis_main = token_analysis.main
    print("✅ Module token_analysis importé avec succès")
except ImportError as e:
    print(f"❌ ImportError: {e}")
    token_analysis_main = None
except SyntaxError as e:
    print(f"❌ SyntaxError dans token_analysis.py: {e}")
    token_analysis_main = None
except Exception as e:
    print(f"❌ Autre erreur: {e}")
    token_analysis_main = None

# Configuration de l'API
API_BASE_URL = "http://localhost:8010/api"  # Changé de 8000 à 8010

# Cache des données pour éviter les appels répétés
@st.cache_data(ttl=30)  # Cache pendant 30 secondes
def fetch_dashboard_data():
    """Récupère les données du dashboard depuis l'API"""
    try:
        response = requests.get(f"{API_BASE_URL}/dashboard-data", timeout=10)
        if response.status_code == 200:
            return response.json()
        else:
            st.error(f"Erreur API: {response.status_code}")
            return None
    except requests.exceptions.RequestException as e:
        st.error(f"Erreur de connexion à l'API: {e}")
        return None

@st.cache_data(ttl=60)  # Cache pendant 1 minute
def fetch_health_status():
    """Récupère le statut de santé du système"""
    try:
        response = requests.get(f"{API_BASE_URL}/health", timeout=5)
        if response.status_code == 200:
            return response.json()
        else:
            return {"status": "error", "error": f"HTTP {response.status_code}"}
    except:
        return {"status": "error", "error": "Connexion impossible"}

@st.cache_data(ttl=30)
def fetch_polling_stats():
    """Récupère les statistiques détaillées du polling"""
    try:
        response = requests.get(f"{API_BASE_URL}/polling-stats", timeout=5)
        if response.status_code == 200:
            return response.json()
        else:
            return None
    except:
        return None

@st.cache_data(ttl=30)
def fetch_updated_tokens_stats():
    """Récupère les statistiques des tokens mis à jour récemment"""
    try:
        response = requests.get(f"{API_BASE_URL}/updated-tokens-stats", timeout=5)
        if response.status_code == 200:
            return response.json()
        else:
            return None
    except:
        return None

def format_wallet_address(address):
    """Formate une adresse de wallet pour l'affichage"""
    if len(address) > 16:
        return f"{address[:8]}...{address[-8:]}"
    return address

def format_number(num, decimals=2):
    """Formate un nombre pour l'affichage"""
    if num is None:
        return "N/A"
    if num >= 1_000_000:
        return f"{num/1_000_000:.{decimals}f}M"
    elif num >= 1_000:
        return f"{num/1_000:.{decimals}f}K"
    else:
        return f"{num:.{decimals}f}"

def format_percentage(pct):
    """Formate un pourcentage"""
    if pct is None:
        return "N/A"
    return f"{pct*100:.1f}%"

def format_roi(roi):
    """Formate un ROI"""
    if roi is None or roi == 0:
        return "N/A"
    return f"{roi:.1f}x"

def get_confidence_color(score):
    """Retourne la couleur selon le score de confiance"""
    if score >= 0.9:
        return "🟢"
    elif score >= 0.8:
        return "🟡"
    elif score >= 0.7:
        return "🟠"
    else:
        return "🔴"

def get_status_color(status):
    """Retourne la couleur selon le statut"""
    if status == "healthy":
        return "🟢"
    elif status == "warning":
        return "🟡"
    else:
        return "🔴"

def format_duration(seconds):
    """Formate une durée en secondes"""
    if seconds < 60:
        return f"{seconds:.0f}s"
    elif seconds < 3600:
        return f"{seconds/60:.0f}m"
    else:
        return f"{seconds/3600:.1f}h"

def main():
    """Interface principale du dashboard"""
    
    # Gestion des pages
    query_params = st.query_params
    if "page" in query_params and query_params["page"] == "token_details":
        from token_details import main as token_details_main
        token_details_main()
        return

    # Titre principal
    st.title("🚀 PumpFun Early Adopters Tracker")
    st.markdown("*Système de tracking avec polling intelligent - Version optimisée*")
    
    # Sidebar pour les contrôles
    with st.sidebar:
        st.header("⚙️ Contrôles")
        
        # Bouton de rafraîchissement
        if st.button("🔄 Actualiser", use_container_width=True, key="sidebar_refresh"):
            st.cache_data.clear()
            st.rerun()
        
        # Force poll pour debug
        if st.button("⚡ Force Poll Now", use_container_width=True, key="system_force_poll"):
            try:
                response = requests.post(f"{API_BASE_URL}/force-poll", timeout=10)
                if response.status_code == 200:
                    result = response.json()
                    if result['status'] == 'success':
                        st.success("✅ Polling forcé avec succès")
                    else:
                        st.error(f"❌ Erreur: {result.get('message', 'Unknown error')}")
                else:
                    st.error(f"❌ Erreur HTTP: {response.status_code}")
            except Exception as e:
                st.error(f"❌ Erreur: {e}")
        
        st.divider()
        
        # Statut du système
        st.header("📊 Statut Système")
        health = fetch_health_status()
        
        status_text = f"{get_status_color(health['status'])} {health['status'].upper()}"
        st.markdown(f"**Statut:** {status_text}")
        
        # Métriques de base
        if 'database' in health:
            db_info = health['database']
            st.metric("Tokens trackés", db_info.get('total_tokens', 0))
            st.metric("Early Adopters", db_info.get('total_early_adopters', 0))
        
        st.divider()
        
        # Statistiques de polling
        st.header("🔄 Polling Status")
        polling_stats = fetch_polling_stats()
        
        if polling_stats:
            poll_data = polling_stats.get('polling_stats', {})
            health_data = polling_stats.get('health_check', {})
            
            # Statut du polling
            polling_status = "🟢 Actif" if poll_data.get('is_running') else "🔴 Arrêté"
            st.markdown(f"**Polling:** {polling_status}")
            
            # Intervalle actuel
            interval = poll_data.get('current_polling_interval', 0)
            st.metric("Intervalle", f"{interval}s")
            
            # Activité récente
            avg_activity = poll_data.get('recent_activity_avg', 0)
            st.metric("Activité moy.", f"{avg_activity:.1f} tx/poll")
            
            # Utilisation des crédits
            credits_used = poll_data.get('credits_used_today', 0)
            max_credits = poll_data.get('max_daily_credits', 2000)
            credit_pct = (credits_used / max_credits) * 100 if max_credits > 0 else 0
            
            st.metric("Crédits", f"{credits_used}/{max_credits}")
            
            # Barre de progression pour les crédits
            progress_color = "normal"
            if credit_pct > 90:
                progress_color = "red"
            elif credit_pct > 70:
                progress_color = "orange"
            
            st.progress(credit_pct / 100)
            
            if credit_pct > 90:
                st.error(f"⚠️ Crédits critiques: {credit_pct:.1f}%")
            elif credit_pct > 70:
                st.warning(f"⚠️ Crédits élevés: {credit_pct:.1f}%")
        
        # Auto-refresh
        auto_refresh = st.checkbox("🔄 Auto-refresh (30s)")
        if auto_refresh:
            time.sleep(30)
            st.rerun()
    
    # Récupération des données principales
    data = fetch_dashboard_data()
    
    if not data:
        st.error("❌ Impossible de récupérer les données du dashboard")
        st.stop()
    
    # Métriques principales
    col1, col2, col3, col4 = st.columns(4)
    
    stats = data.get('stats', {})
    
    with col1:
        st.metric(
            "🎯 Tokens Trackés",
            stats.get('total_tokens_tracked', 0),
            delta=None
        )
    
    with col2:
        st.metric(
            "👥 Early Adopters",
            stats.get('total_early_adopters', 0),
            delta=None
        )
    
    with col3:
        st.metric(
            "📈 Achats 24h",
            stats.get('recent_purchases_24h', 0),
            delta=None
        )
    
    with col4:
        opportunities_count = len(data.get('copy_trading_opportunities', []))
        st.metric(
            "🎯 Opportunités",
            opportunities_count,
            delta=None
        )
    
    st.divider()

    st.subheader("Tokens mis à jour récemment")
    updated_tokens_stats = fetch_updated_tokens_stats()
    if updated_tokens_stats:
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("🔥 5 dernières min", updated_tokens_stats.get('5m', 0))
        with col2:
            st.metric("⚡ 30 dernières min", updated_tokens_stats.get('30m', 0))
        with col3:
            st.metric("🟡 Dernière heure", updated_tokens_stats.get('1h', 0))
        with col4:
            st.metric("🔵 6 dernières heures", updated_tokens_stats.get('6h', 0))

    st.divider()
    
    # Section de monitoring du polling
    polling_stats = fetch_polling_stats()
    if polling_stats:
        with st.expander("📊 Monitoring Polling Détaillé", expanded=False):
            col1, col2, col3 = st.columns(3)
            
            poll_data = polling_stats.get('polling_stats', {})
            health_data = polling_stats.get('health_check', {})
            
            with col1:
                st.subheader("🔄 Statistiques Polling")
                daily_stats = poll_data.get('daily_stats', {})
                
                st.write(f"**Transactions traitées:** {daily_stats.get('transactions_processed', 0)}")
                st.write(f"**Cycles de polling:** {daily_stats.get('polling_cycles', 0)}")
                st.write(f"**Cache signatures:** {poll_data.get('cache_size', 0)}")
                
                # Calculs de performance
                tx_per_min = poll_data.get('transactions_per_minute', 0)
                st.write(f"**TX/min:** {tx_per_min:.1f}")
            
            with col2:
                st.subheader("⚡ Performance")
                
                # Intervalle adaptatif
                current_interval = poll_data.get('current_polling_interval', 120)
                st.write(f"**Intervalle actuel:** {current_interval}s")
                
                # Activité récente
                recent_activity = poll_data.get('recent_activity_avg', 0)
                st.write(f"**Activité récente:** {recent_activity:.1f} tx/poll")
                
                # Dernière activité
                last_activity = poll_data.get('last_activity_time', '')
                if last_activity:
                    last_time = datetime.fromisoformat(last_activity.replace('Z', '+00:00'))
                    time_diff = datetime.now() - last_time.replace(tzinfo=None)
                    st.write(f"**Dernière activité:** {format_duration(time_diff.total_seconds())} ago")
            
            with col3:
                st.subheader("🩺 Santé Système")
                
                issues = health_data.get('issues', [])
                if not issues:
                    st.success("✅ Aucun problème détecté")
                else:
                    for issue in issues:
                        st.warning(f"⚠️ {issue}")
                
                # Graphique d'utilisation des crédits
                credit_pct = health_data.get('credit_usage_percent', 0)
                
                fig_credits = go.Figure(go.Indicator(
                    mode = "gauge+number+delta",
                    value = credit_pct,
                    domain = {'x': [0, 1], 'y': [0, 1]},
                    title = {'text': "Utilisation Crédits (%)"},
                    delta = {'reference': 80},
                    gauge = {
                        'axis': {'range': [None, 100]},
                        'bar': {'color': "darkblue"},
                        'steps': [
                            {'range': [0, 70], 'color': "lightgray"},
                            {'range': [70, 90], 'color': "yellow"},
                            {'range': [90, 100], 'color': "red"}
                        ],
                        'threshold': {
                            'line': {'color': "red", 'width': 4},
                            'thickness': 0.75,
                            'value': 90
                        }
                    }
                ))
                fig_credits.update_layout(height=200)
                st.plotly_chart(fig_credits, use_container_width=True)
    
    # Onglets pour organiser le contenu
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["📊 Vue d'ensemble", "🏆 Top Performers", "🆕 Nouveaux Tokens", "🎯 Signaux Trading", "🔍 Analyse Tokens", "🔧 Système"])
    
    with tab1:
        st.header("📊 Vue d'ensemble du système")
        
        col1, col2 = st.columns(2)
        
        with col1:
            # Graphique des top performers
            top_performers = data.get('top_performers', [])
            if top_performers:
                df_performers = pd.DataFrame(top_performers)
                
                fig_confidence = px.bar(
                    df_performers.head(10),
                    x='confidence_score',
                    y=[format_wallet_address(addr) for addr in df_performers.head(10)['wallet_address']],
                    orientation='h',
                    title="🏆 Top 10 Early Adopters par Score de Confiance",
                    labels={'confidence_score': 'Score de Confiance', 'y': 'Wallet'},
                    color='confidence_score',
                    color_continuous_scale='Viridis'
                )
                fig_confidence.update_layout(height=400)
                st.plotly_chart(fig_confidence, use_container_width=True)
        
        with col2:
            # Graphique des success rates
            if top_performers:
                fig_success = px.scatter(
                    df_performers.head(10),
                    x='success_rate',
                    y='avg_roi',
                    size='total_picks',
                    color='confidence_score',
                    title="📈 Success Rate vs ROI Moyen",
                    labels={
                        'success_rate': 'Taux de Succès',
                        'avg_roi': 'ROI Moyen',
                        'total_picks': 'Nombre de Picks'
                    },
                    hover_data=['wallet_address']
                )
                fig_success.update_layout(height=400)
                st.plotly_chart(fig_success, use_container_width=True)
        
        # Timeline des tokens récents
        st.subheader("⏰ Timeline des Nouveaux Tokens (24h)")
        recent_tokens = data.get('recent_tokens', [])
        
        if recent_tokens:
            df_tokens = pd.DataFrame(recent_tokens)
            df_tokens['created_at'] = pd.to_datetime(df_tokens['created_at'])
            df_tokens['early_adopter_signal'] = df_tokens['early_adopter_buyers'].apply(len)
            
            fig_timeline = px.scatter(
                df_tokens,
                x='created_at',
                y='early_adopter_signal',
                size='early_purchases_count',
                color='early_adopter_signal',
                title="🆕 Nouveaux Tokens avec Signaux Early Adopters",
                labels={
                    'created_at': 'Heure de Création',
                    'early_adopter_signal': 'Nombre Early Adopters',
                    'early_purchases_count': 'Total Achats Précoces'
                },
                hover_data=['name', 'symbol', 'creator']
            )
            fig_timeline.update_layout(height=400)
            st.plotly_chart(fig_timeline, use_container_width=True)
        else:
            st.info("Aucun nouveau token détecté dans les dernières 24h")
    
    with tab2:
        st.header("🏆 Top Performers - Early Adopters")
        
        top_performers = data.get('top_performers', [])
        
        if not top_performers:
            st.info("Aucun early adopter détecté pour le moment")
        else:
            # Tableau des top performers
            performers_data = []
            for performer in top_performers[:20]:
                performers_data.append({
                    "Wallet": format_wallet_address(performer['wallet_address']),
                    "Score": f"{get_confidence_color(performer['confidence_score'])} {performer['confidence_score']:.3f}",
                    "Success Rate": f"{performer['success_rate']*100:.1f}%",
                    "Total Picks": int(performer['total_picks']),
                    "Picks Réussis": int(performer['successful_picks']),
                    "ROI Moyen": f"{performer['avg_roi']:.1f}x" if performer['avg_roi'] else "N/A",
                    "Timing Moy. (h)": f"{performer['avg_entry_timing']:.1f}",
                    "Niveau": performer['confidence_level'],
                    "Dernière Activité": performer['last_activity'][:10]
                })
            
            df_display = pd.DataFrame(performers_data)
            st.dataframe(df_display, use_container_width=True, height=600)
            
            # Détails d'un wallet sélectionné
            st.subheader("🔍 Analyse Détaillée")
            
            wallet_options = [p['wallet_address'] for p in top_performers[:10]]
            selected_wallet = st.selectbox(
                "Sélectionner un wallet pour analyse détaillée:",
                options=wallet_options,
                format_func=format_wallet_address
            )
            
            if selected_wallet:
                try:
                    response = requests.get(f"{API_BASE_URL}/wallet/{selected_wallet}")
                    if response.status_code == 200:
                        wallet_data = response.json()
                        
                        col1, col2 = st.columns(2)
                        
                        with col1:
                            profile = wallet_data.get('early_adopter_profile')
                            if profile:
                                st.write("**Profil Early Adopter:**")
                                st.write(f"• Score de confiance: {profile['confidence_score']:.3f}")
                                st.write(f"• Taux de succès: {format_percentage(profile['success_rate'])}")
                                st.write(f"• Total picks: {profile['total_picks']}")
                                st.write(f"• ROI moyen: {format_roi(profile['avg_roi'])}")
                        
                        with col2:
                            purchases = wallet_data.get('recent_purchases', [])
                            if purchases:
                                st.write("**Achats Récents (30j):**")
                                for purchase in purchases[:5]:
                                    st.write(f"• {purchase['token_symbol'] or 'UNK'} - {purchase['minutes_after_creation']}min après création")
                    
                except Exception as e:
                    st.error(f"Erreur lors de la récupération des détails: {e}")
    
    with tab3:
        st.header("🆕 Nouveaux Tokens avec Early Adopter Signals")
        
        recent_tokens = data.get('recent_tokens', [])
        
        if not recent_tokens:
            st.info("Aucun nouveau token détecté dans les dernières 24h")
        else:
            # Filtres
            col1, col2 = st.columns(2)
            with col1:
                min_early_adopters = st.slider("Minimum Early Adopters", 0, 10, 1)
            with col2:
                show_all = st.checkbox("Afficher tous les tokens")
            
            # Filtrage des données
            filtered_tokens = []
            for token in recent_tokens:
                early_adopter_count = len(token.get('early_adopter_buyers', []))
                if show_all or early_adopter_count >= min_early_adopters:
                    filtered_tokens.append(token)
            
            # Affichage des tokens
            for token in filtered_tokens[:20]:
                early_adopters = token.get('early_adopter_buyers', [])
                early_adopter_count = len(early_adopters)
                
                # Couleur selon le signal
                if early_adopter_count >= 3:
                    signal_color = "🟢"
                    signal_text = "SIGNAL FORT"
                elif early_adopter_count >= 1:
                    signal_color = "🟡"
                    signal_text = "SIGNAL MOYEN"
                else:
                    signal_color = "⚪"
                    signal_text = "PAS DE SIGNAL"
                
                with st.expander(f"{signal_color} {token.get('symbol', 'UNK')} - {token.get('name', 'Unknown')} - {signal_text}"):
                    col1, col2, col3 = st.columns(3)
                    
                    with col1:
                        st.write(f"**Adresse:** `{token['address']}`")
                        st.write(f"**Créateur:** `{format_wallet_address(token['creator'])}`")
                        st.write(f"**Créé:** {token['created_at'][:19]}")
                    
                    with col2:
                        st.write(f"**Early Adopters:** {early_adopter_count}")
                        st.write(f"**Total Achats:** {token.get('early_purchases_count', 0)}")
                        if token.get('market_cap_discovery'):
                            st.write(f"**Market Cap:** ${format_number(token['market_cap_discovery'])}")
                    
                    with col3:
                        if early_adopters:
                            st.write("**Early Adopters Actifs:**")
                            for adopter in early_adopters[:3]:
                                st.write(f"• `{format_wallet_address(adopter)}`")
                        
                        # Liens utiles
                        st.write("**Liens:**")
                        st.write(f"[Pump.fun](https://pump.fun/{token['address']})")
                        st.write(f"[Solscan](https://solscan.io/token/{token['address']})")
    
    with tab4:
        st.header("🎯 Signaux de Copy Trading")
        
        opportunities = data.get('copy_trading_opportunities', [])
        
        if not opportunities:
            st.info("Aucune opportunité de copy trading détectée actuellement")
        else:
            st.success(f"🎯 {len(opportunities)} opportunités détectées!")
            
            for opp in opportunities:
                confidence_level = opp.get('confidence_level', 'INCONNUE')
                
                # Couleur selon le niveau de confiance
                if confidence_level == "TRÈS ÉLEVÉE":
                    alert_color = "🟢"
                elif confidence_level == "ÉLEVÉE":
                    alert_color = "🟡"
                else:
                    alert_color = "🟠"
                
                with st.container():
                    st.markdown(f"""
                    <div style="border: 2px solid #4CAF50; border-radius: 10px; padding: 15px; margin: 10px 0; background-color: #f8f9fa;">
                        <h4>{alert_color} SIGNAL {confidence_level}</h4>
                        <p><strong>Token:</strong> {opp.get('token_symbol', 'UNK')} - {opp.get('token_name', 'Unknown')}</p>
                        <p><strong>Early Adopter:</strong> <code>{format_wallet_address(opp['early_adopter'])}</code></p>
                        <p><strong>Confiance Adopter:</strong> {opp['adopter_confidence']:.3f} (Success Rate: {format_percentage(opp['adopter_success_rate'])})</p>
                        <p><strong>Timing:</strong> {opp['minutes_after_creation']} minutes après création</p>
                        <p><strong>Montant:</strong> {opp['sol_amount']:.3f} SOL</p>
                        <p><strong>Timestamp:</strong> {opp['purchase_timestamp']}</p>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    # Boutons d'action
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.link_button("🚀 Pump.fun", f"https://pump.fun/{opp['token_address']}")
                    with col2:
                        st.link_button("🔍 Solscan", f"https://solscan.io/token/{opp['token_address']}")
                    with col3:
                        st.link_button("👤 Wallet", f"https://solscan.io/account/{opp['early_adopter']}")
    
    with tab5:
        st.header("🔍 Analyse Avancée des Tokens")
        
        if token_analysis_main:
            # Afficher la page d'analyse des tokens
            try:
                token_analysis_main()
            except Exception as e:
                st.error(f"Erreur lors du chargement de l'analyse des tokens: {e}")
                st.info("Veuillez créer le fichier 'token_analysis.py' avec la fonction main()")
        else:
            st.warning("Module d'analyse des tokens non disponible")
            st.info("Créez le fichier 'token_analysis.py' dans le même dossier avec le code de la page d'analyse")
            
            # Interface de base en attendant
            st.subheader("🚧 Fonctionnalité en développement")
            
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Tokens à analyser", "En attente")
            with col2:
                st.metric("Score moyen", "N/A")
            with col3:
                st.metric("Recommandations", "0")
            
            st.info("""
            Cette page contiendra :
            - 📊 Analyse complète des tokens avec scoring
            - 🎯 Matrice risque vs opportunité
            - 🔍 Filtres avancés (liquidité, holders, etc.)
            - 📈 Données bonding curve en temps réel
            - ⚡ Recommandations d'achat automatiques
            """)

    with tab6:
        st.header("🔧 Système & Monitoring")
        
        # Statistiques détaillées du polling
        if polling_stats:
            poll_data = polling_stats.get('polling_stats', {})
            health_data = polling_stats.get('health_check', {})
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.subheader("📈 Statistiques de Performance")
                
                daily_stats = poll_data.get('daily_stats', {})
                
                # Tableau des métriques avec types de données corrects
                metrics_data = {
                    "Métrique": [
                        "Transactions Traitées",
                        "Cycles de Polling",
                        "Crédits Utilisés",
                        "Cache Signatures",
                        "Intervalle Actuel (sec)",
                        "Activité Récente (tx/poll)"
                    ],
                    "Valeur": [
                        int(daily_stats.get('transactions_processed', 0)),
                        int(daily_stats.get('polling_cycles', 0)),
                        int(poll_data.get('credits_used_today', 0)),
                        int(poll_data.get('cache_size', 0)),
                        int(poll_data.get('current_polling_interval', 0)),
                        round(float(poll_data.get('recent_activity_avg', 0)), 1)
                    ]
                }
                
                df_metrics = pd.DataFrame(metrics_data)
                st.dataframe(df_metrics, hide_index=True, use_container_width=True)
            
            with col2:
                st.subheader("🩺 État de Santé")
                
                # Status général
                overall_status = health_data.get('status', 'unknown')
                st.markdown(f"**Statut Global:** {get_status_color(overall_status)} {overall_status.upper()}")
                
                # Issues détaillées
                issues = health_data.get('issues', [])
                if issues:
                    st.write("**Problèmes détectés:**")
                    for issue in issues:
                        st.warning(f"⚠️ {issue}")
                else:
                    st.success("✅ Aucun problème détecté")
                
                # Métriques de santé
                st.write("**Métriques de Santé:**")
                st.write(f"• Utilisation crédits: {health_data.get('credit_usage_percent', 0):.1f}%")
                st.write(f"• Temps depuis dernière activité: {health_data.get('time_since_last_activity_minutes', 0):.1f}min")
                st.write(f"• Intervalle polling: {health_data.get('polling_interval', 0)}s")
        
        # Actions système
        st.subheader("🛠️ Actions Système")
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            if st.button("🔄 Force Update Scores", use_container_width=True, key="system_update_scores"):
                try:
                    response = requests.post(f"{API_BASE_URL}/update-scores")
                    if response.status_code == 200:
                        st.success("✅ Mise à jour des scores déclenchée")
                    else:
                        st.error("❌ Erreur lors de la mise à jour")
                except Exception as e:
                    st.error(f"❌ Erreur: {e}")
        
        with col2:
            if st.button("⚡ Force Poll Now", use_container_width=True):
                try:
                    response = requests.post(f"{API_BASE_URL}/force-poll")
                    if response.status_code == 200:
                        result = response.json()
                        if result['status'] == 'success':
                            st.success("✅ Polling forcé avec succès")
                        else:
                            st.error(f"❌ {result.get('message', 'Erreur inconnue')}")
                    else:
                        st.error(f"❌ Erreur HTTP: {response.status_code}")
                except Exception as e:
                    st.error(f"❌ Erreur: {e}")
        
        with col3:
            if st.button("🗑️ Clear Cache", use_container_width=True, key="system_clear_cache"):
                st.cache_data.clear()
                st.success("✅ Cache vidé")
    
    # Footer avec informations système
    st.divider()
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.caption(f"🕒 Dernière mise à jour: {data.get('last_updated', 'N/A')[:19]}")
    
    with col2:
        st.caption("🔗 API Status: ✅ Connecté (Polling Mode)")
    
    with col3:
        # Indicateur de mode
        st.caption("🚀 Mode: Polling Intelligent")

if __name__ == "__main__":
    main()