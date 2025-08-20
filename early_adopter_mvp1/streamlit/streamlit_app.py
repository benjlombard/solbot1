import streamlit as st
import requests
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import time
import numpy as np

# Configuration de la page
st.set_page_config(
    page_title="PumpFun Early Adopters Tracker",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Configuration de l'API
API_BASE_URL = "http://localhost:8000/api"

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

def main():
    """Interface principale du dashboard"""
    
    # Titre principal
    st.title("🚀 PumpFun Early Adopters Tracker")
    st.markdown("*Système de tracking des early adopters pump.fun en temps réel*")
    
    # Sidebar pour les contrôles
    with st.sidebar:
        st.header("⚙️ Contrôles")
        
        # Bouton de rafraîchissement
        if st.button("🔄 Actualiser", use_container_width=True):
            st.cache_data.clear()
            st.rerun()
        
        # Statut du système
        st.header("📊 Statut Système")
        health = fetch_health_status()
        
        if health['status'] == 'healthy':
            st.success("✅ Système opérationnel")
        elif health['status'] == 'warning':
            st.warning("⚠️ Système en alerte")
        else:
            st.error("❌ Système en erreur")
        
        # Affichage des métriques de santé
        if 'database' in health:
            st.metric("Tokens trackés", health['database'].get('total_tokens', 0))
            st.metric("Early Adopters", health['database'].get('total_early_adopters', 0))
        
        if 'webhook_handler' in health:
            webhook_stats = health['webhook_handler']
            st.metric("Crédits utilisés", f"{webhook_stats.get('credits_used_today', 0)}/{webhook_stats.get('max_daily_credits', 2500)}")
            
            credit_pct = webhook_stats.get('credit_usage_percent', 0)
            if credit_pct > 90:
                st.error(f"⚠️ Utilisation crédits: {credit_pct:.1f}%")
            elif credit_pct > 70:
                st.warning(f"⚠️ Utilisation crédits: {credit_pct:.1f}%")
            else:
                st.info(f"📊 Utilisation crédits: {credit_pct:.1f}%")
        
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
    
    # Onglets pour organiser le contenu
    tab1, tab2, tab3, tab4 = st.tabs(["📊 Vue d'ensemble", "🏆 Top Performers", "🆕 Nouveaux Tokens", "🎯 Signaux Trading"])
    
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
                    labels={'confidence_score': 'Score de Confiance', 'y': 'Wallet'}
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
                    "Success Rate": format_percentage(performer['success_rate']),
                    "Total Picks": performer['total_picks'],
                    "Picks Réussis": performer['successful_picks'],
                    "ROI Moyen": format_roi(performer['avg_roi']),
                    "Timing Moy.": f"{performer['avg_entry_timing']:.1f}h",
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
    
    # Footer avec informations système
    st.divider()
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.caption(f"🕒 Dernière mise à jour: {data.get('last_updated', 'N/A')[:19]}")
    
    with col2:
        st.caption("🔗 API Status: ✅ Connecté")
    
    with col3:
        if st.button("🔄 Forcer Mise à Jour Scores"):
            try:
                response = requests.post(f"{API_BASE_URL}/update-scores")
                if response.status_code == 200:
                    st.success("✅ Mise à jour des scores déclenchée")
                else:
                    st.error("❌ Erreur lors de la mise à jour")
            except Exception as e:
                st.error(f"❌ Erreur: {e}")

if __name__ == "__main__":
    main()