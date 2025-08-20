import streamlit as st
import requests
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import time
import streamlit.components.v1 as components

# Configuration de la page
st.set_page_config(
    page_title="Transactions Pump.fun - Détails",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Configuration de l'API
API_BASE_URL = "http://localhost:8010/api"

# Prix SOL en USD
SOL_PRICE_USD = 180.0

# CSS et JavaScript pour les fonctionnalités de copie et liens
def inject_custom_css_and_js():
    st.markdown("""
    <style>
    .address-cell {
        display: flex;
        align-items: center;
        gap: 5px;
        font-family: monospace;
        font-size: 12px;
        flex-wrap: nowrap;
    }
    .copy-btn {
        background: #ff6b6b;
        border: none;
        color: white;
        padding: 2px 4px;
        border-radius: 3px;
        font-size: 10px;
        cursor: pointer;
        flex-shrink: 0;
    }
    .copy-btn:hover {
        background: #ff5252;
    }
    .link-btn {
        background: #4CAF50;
        border: none;
        color: white;
        padding: 2px 4px;
        border-radius: 3px;
        font-size: 10px;
        cursor: pointer;
        text-decoration: none;
        flex-shrink: 0;
    }
    .link-btn:hover {
        background: #45a049;
    }
    .token-cell {
        display: flex;
        flex-direction: column;
        gap: 3px;
    }
    .toast {
        position: fixed;
        top: 20px;
        right: 20px;
        background: #4CAF50;
        color: white;
        padding: 10px 15px;
        border-radius: 5px;
        z-index: 1000;
        animation: slideIn 0.3s ease-in-out;
    }
    @keyframes slideIn {
        from { transform: translateX(100%); }
        to { transform: translateX(0); }
    }
    </style>
    
    <script>
    function copyToClipboard(text, type = '') {
        navigator.clipboard.writeText(text).then(function() {
            showToast(`${type} copié!`);
        }).catch(function(err) {
            console.error('Erreur de copie:', err);
        });
    }
    
    function showToast(message) {
        // Supprimer les toasts existants
        const existingToasts = document.querySelectorAll('.toast');
        existingToasts.forEach(toast => toast.remove());
        
        // Créer nouveau toast
        const toast = document.createElement('div');
        toast.className = 'toast';
        toast.textContent = message;
        document.body.appendChild(toast);
        
        // Supprimer après 2 secondes
        setTimeout(() => {
            toast.remove();
        }, 2000);
    }
    </script>
    """, unsafe_allow_html=True)

@st.cache_data(ttl=30)
def fetch_detailed_transactions(hours_back=24, limit=100, min_sol=0.0, max_minutes=1440, early_adopters_only=False):
    """Récupère les transactions détaillées"""
    try:
        params = {
            'hours_back': hours_back,
            'limit': limit,
            'min_sol_amount': min_sol,
            'max_minutes_after': max_minutes,
            'early_adopters_only': early_adopters_only
        }
        
        response = requests.get(f"{API_BASE_URL}/transactions-detailed", params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            return data.get('transactions', [])
        else:
            st.error(f"Erreur API: {response.status_code}")
            return []
    except Exception as e:
        st.error(f"Erreur de connexion: {e}")
        return []

@st.cache_data(ttl=300)
def fetch_sol_price():
    """Récupère le prix SOL en USD"""
    try:
        response = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd", timeout=5)
        if response.status_code == 200:
            data = response.json()
            return data.get('solana', {}).get('usd', SOL_PRICE_USD)
    except:
        pass
    return SOL_PRICE_USD

def format_wallet_address(address):
    """Formate une adresse de wallet"""
    if not address:
        return "N/A"
    return f"{address[:8]}...{address[-8:]}"

def format_timestamp(timestamp_str):
    """Formate un timestamp"""
    try:
        dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        return dt.strftime("%m-%d %H:%M")
    except:
        return timestamp_str

def format_sol_amount(amount):
    """Formate un montant SOL"""
    if amount is None:
        return "0.0000"
    return f"{amount:.4f}"

def format_usd_amount(sol_amount, sol_price):
    """Calcule et formate le montant en USD"""
    if sol_amount is None:
        return "$0.00"
    usd_amount = sol_amount * sol_price
    return f"${usd_amount:.2f}"

def format_minutes_ago(minutes):
    """Formate le temps écoulé"""
    if minutes < 60:
        return f"{minutes}min"
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours}h{mins:02d}"

def create_token_cell_with_links(token_address, token_symbol, token_name=""):
    """Crée une cellule token avec symbole et liens alignés"""
    if not token_address:
        return "N/A"
    
    formatted_addr = format_wallet_address(token_address)
    symbol = token_symbol or "UNK"
    
    return f'''
    <div class="token-cell">
        <div class="address-cell">
            <span>{formatted_addr}</span>
            <button class="copy-btn" onclick="copyToClipboard('{token_address}', 'Token')">📋</button>
            <a href="https://pump.fun/{token_address}" target="_blank" class="link-btn">🚀</a>
            <a href="https://solscan.io/token/{token_address}" target="_blank" class="link-btn">🔍</a>
        </div>
    </div>
    '''

def create_wallet_cell_with_links(address, wallet_type="buyer"):
    """Crée une cellule wallet avec liens alignés"""
    if not address:
        return "N/A"
    
    formatted = format_wallet_address(address)
    label = "Buyer" if wallet_type == "buyer" else "Creator"
    
    return f'''
    <div class="address-cell">
        <span>{formatted}</span>
        <button class="copy-btn" onclick="copyToClipboard('{address}', '{label}')">📋</button>
        <a href="https://solscan.io/account/{address}" target="_blank" class="link-btn">🔍</a>
    </div>
    '''

def create_signature_cell_with_links(signature):
    """Crée une cellule signature avec liens alignés"""
    if not signature:
        return "N/A"
    
    formatted = f"{signature[:12]}..."
    
    return f'''
    <div class="address-cell">
        <span>{formatted}</span>
        <button class="copy-btn" onclick="copyToClipboard('{signature}', 'Signature')">📋</button>
        <a href="https://solscan.io/tx/{signature}" target="_blank" class="link-btn">🔍</a>
    </div>
    '''

def apply_dataframe_filters(df, min_timing, max_timing, min_sol_filter, max_sol_filter):
    """Applique les filtres au DataFrame"""
    filtered_df = df.copy()
    
    filtered_df = filtered_df[
        (filtered_df['minutes_after_creation'] >= min_timing) & 
        (filtered_df['minutes_after_creation'] <= max_timing)
    ]
    
    filtered_df = filtered_df[
        (filtered_df['sol_amount'] >= min_sol_filter) & 
        (filtered_df['sol_amount'] <= max_sol_filter)
    ]
    
    return filtered_df

def create_enhanced_dataframe(df, sol_price):
    """Crée un DataFrame avec cellules enrichies"""
    enhanced_df = pd.DataFrame()
    
    # Colonnes de base
    enhanced_df['Date/Heure'] = df['timestamp'].apply(format_timestamp)
    
    # Colonnes avec HTML pour liens et copie
    enhanced_df['Acheteur'] = df.apply(lambda row: create_wallet_cell_with_links(row['buyer_address'], "buyer"), axis=1)
    enhanced_df['Token'] = df.apply(lambda row: create_token_cell_with_links(
        row['token_address'], 
        row.get('token_symbol', 'UNK'),
        row.get('token_name', '')
    ), axis=1)
    enhanced_df['Créateur'] = df.apply(lambda row: create_wallet_cell_with_links(row['token_creator'], "creator"), axis=1)
    
    # Colonnes monétaires
    enhanced_df['SOL'] = df['sol_amount'].apply(format_sol_amount)
    enhanced_df['USD'] = df['sol_amount'].apply(lambda x: format_usd_amount(x, sol_price))
    
    # Autres colonnes
    enhanced_df['Timing'] = df['minutes_after_creation'].apply(format_minutes_ago)
    enhanced_df['Score EA'] = df['early_adopter_profile'].apply(
        lambda x: f"{x['confidence_score']:.3f}" if x else "N/A"
    )
    enhanced_df['Signature'] = df['signature'].apply(create_signature_cell_with_links)
    
    return enhanced_df

def main():
    st.title("📋 Transactions Pump.fun - Tableau Interactif")
    st.markdown("*Tableau avec liens et copie intégrés directement dans les cellules*")
    
    # Injecter CSS et JavaScript
    inject_custom_css_and_js()
    
    # Récupérer le prix SOL
    sol_price = fetch_sol_price()
    st.info(f"💰 Prix SOL actuel: ${sol_price:.2f} USD")
    
    # Sidebar pour les contrôles globaux
    with st.sidebar:
        st.header("⚙️ Filtres Globaux")
        
        time_options = {
            "Dernière heure": 1,
            "Dernières 6h": 6,
            "Dernières 24h": 24,
            "Dernière semaine": 168
        }
        time_filter = st.selectbox("Période", list(time_options.keys()), index=2)
        hours_back = time_options[time_filter]
        
        min_sol = st.slider("SOL minimum global", 0.0, 1.0, 0.0, 0.001)
        max_minutes = st.slider("Minutes max global", 0, 1440, 1440)
        only_early_adopters = st.checkbox("Early adopters uniquement", value=False)
        limit = st.slider("Limite résultats", 10, 200, 100)
        
        if st.button("🔄 Actualiser", use_container_width=True):
            st.cache_data.clear()
            st.rerun()
    
    # Récupération des données
    with st.spinner("Chargement des transactions..."):
        transactions = fetch_detailed_transactions(
            hours_back=hours_back,
            limit=limit,
            min_sol=min_sol,
            max_minutes=max_minutes,
            early_adopters_only=only_early_adopters
        )
    
    if not transactions:
        st.warning("⚠️ Aucune transaction trouvée")
        st.stop()
    
    df = pd.DataFrame(transactions)
    
    # Filtres du tableau
    st.header("🔍 Filtres du Tableau")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        min_timing = st.number_input("Timing min (min)", min_value=0, value=0)
    with col2:
        max_timing = st.number_input("Timing max (min)", min_value=0, value=int(df['minutes_after_creation'].max()) if len(df) > 0 else 1440)
    with col3:
        min_sol_filter = st.number_input("SOL min", min_value=0.0, value=0.0, step=0.001, format="%.4f")
    with col4:
        max_sol_filter = st.number_input("SOL max", min_value=0.0, value=float(df['sol_amount'].max()) if len(df) > 0 else 1.0, step=0.001, format="%.4f")
    
    # Appliquer les filtres
    filtered_df = apply_dataframe_filters(df, min_timing, max_timing, min_sol_filter, max_sol_filter)
    
    # Métriques
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Transactions", f"{len(filtered_df)}/{len(df)}")
    with col2:
        avg_timing = filtered_df['minutes_after_creation'].mean() if len(filtered_df) > 0 else 0
        st.metric("Timing moyen", f"{avg_timing:.1f}min")
    with col3:
        avg_sol = filtered_df['sol_amount'].mean() if len(filtered_df) > 0 else 0
        st.metric("SOL moyen", f"{avg_sol:.4f}")
    with col4:
        total_usd = (filtered_df['sol_amount'].sum() * sol_price) if len(filtered_df) > 0 else 0
        st.metric("Total USD", f"${total_usd:.2f}")
    
    # Tabs
    tab1, tab2, tab3, tab4 = st.tabs(["🔍 Tableau Interactif", "📊 Analyse", "👥 Analyse Acheteurs", "⚡ Actions"])
    
    with tab1:
        st.header("🔍 Tableau avec Liens et Copie Intégrés")
        
        if len(filtered_df) == 0:
            st.warning("Aucune transaction ne correspond aux filtres")
        else:
            # Créer le tableau enrichi
            enhanced_df = create_enhanced_dataframe(filtered_df, sol_price)
            
            # Afficher avec st.markdown pour supporter le HTML
            st.markdown("### 📋 Cliquez sur 📋 pour copier, sur 🚀🔍 pour ouvrir les liens")
            
            # Utilisation d'un composant HTML personnalisé pour un meilleur rendu
            table_html = """
            <div style="max-height: 600px; overflow-y: auto; border: 1px solid #ddd;">
                <table style="width: 100%; border-collapse: collapse; font-size: 12px;">
                    <thead style="position: sticky; top: 0; background: #f0f2f6; z-index: 10;">
                        <tr>
                            <th style="border: 1px solid #ddd; padding: 8px; text-align: left;">Date/Heure</th>
                            <th style="border: 1px solid #ddd; padding: 8px; text-align: left;">Acheteur</th>
                            <th style="border: 1px solid #ddd; padding: 8px; text-align: left;">Token</th>
                            <th style="border: 1px solid #ddd; padding: 8px; text-align: left;">Créateur</th>
                            <th style="border: 1px solid #ddd; padding: 8px; text-align: left;">SOL</th>
                            <th style="border: 1px solid #ddd; padding: 8px; text-align: left;">USD</th>
                            <th style="border: 1px solid #ddd; padding: 8px; text-align: left;">Timing</th>
                            <th style="border: 1px solid #ddd; padding: 8px; text-align: left;">Score EA</th>
                            <th style="border: 1px solid #ddd; padding: 8px; text-align: left;">Signature</th>
                        </tr>
                    </thead>
                    <tbody>
            """
            
            for idx, row in enhanced_df.iterrows():
                table_html += f"""
                <tr style="border-bottom: 1px solid #eee;">
                    <td style="border: 1px solid #ddd; padding: 8px; vertical-align: top;">{row['Date/Heure']}</td>
                    <td style="border: 1px solid #ddd; padding: 8px; vertical-align: top;">{row['Acheteur']}</td>
                    <td style="border: 1px solid #ddd; padding: 8px; vertical-align: top;">{row['Token']}</td>
                    <td style="border: 1px solid #ddd; padding: 8px; vertical-align: top;">{row['Créateur']}</td>
                    <td style="border: 1px solid #ddd; padding: 8px; vertical-align: top;">{row['SOL']}</td>
                    <td style="border: 1px solid #ddd; padding: 8px; vertical-align: top;">{row['USD']}</td>
                    <td style="border: 1px solid #ddd; padding: 8px; vertical-align: top;">{row['Timing']}</td>
                    <td style="border: 1px solid #ddd; padding: 8px; vertical-align: top;">{row['Score EA']}</td>
                    <td style="border: 1px solid #ddd; padding: 8px; vertical-align: top;">{row['Signature']}</td>
                </tr>
                """
            
            table_html += """
                    </tbody>
                </table>
            </div>
            """
            
            # Afficher le tableau HTML
            components.html(table_html, height=650, scrolling=True)
            
            # Instructions
            st.markdown("""
            **💡 Comment utiliser le tableau :**
            - **📋** : Cliquez pour copier l'adresse complète dans le presse-papiers
            - **🚀** : Ouvre la page Pump.fun du token
            - **🔍** : Ouvre la page Solscan (token, wallet ou transaction)
            """)
            
            # Section de détails de transaction
            st.subheader("🔍 Détails de Transaction")
            
            if len(filtered_df) > 0:
                # Sélecteur de transaction
                transaction_options = []
                for i, (idx, row) in enumerate(filtered_df.iterrows()):
                    label = f"{row.get('token_symbol', 'UNK')} - {format_wallet_address(row['buyer_address'])} - {format_timestamp(row['timestamp'])}"
                    transaction_options.append((label, idx))
                
                selected_label = st.selectbox(
                    "Sélectionner une transaction pour voir les détails:",
                    options=[opt[0] for opt in transaction_options],
                    index=0
                )
                
                # Trouver l'index correspondant
                selected_idx = None
                for label, idx in transaction_options:
                    if label == selected_label:
                        selected_idx = idx
                        break
                
                if selected_idx is not None:
                    selected_row = filtered_df.loc[selected_idx]
                    
                    # Afficher les informations de la transaction
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        st.write("**Informations Transaction:**")
                        st.write(f"• **Signature:** `{selected_row['signature']}`")
                        st.write(f"• **Date:** {format_timestamp(selected_row['timestamp'])}")
                        st.write(f"• **Montant SOL:** {format_sol_amount(selected_row['sol_amount'])} SOL")
                        st.write(f"• **Montant USD:** {format_usd_amount(selected_row['sol_amount'], sol_price)}")
                        st.write(f"• **Timing:** {format_minutes_ago(selected_row['minutes_after_creation'])}")
                        
                        st.write("**Informations Token:**")
                        st.write(f"• **Adresse:** `{selected_row['token_address']}`")
                        st.write(f"• **Nom:** {selected_row.get('token_name') or 'Non disponible'}")
                        st.write(f"• **Symbole:** {selected_row.get('token_symbol', 'UNK')}")
                        st.write(f"• **Créateur:** `{selected_row['token_creator']}`")
                        st.write(f"• **Créé le:** {format_timestamp(selected_row['token_created_at'])}")
                    
                    with col2:
                        st.write("**Informations Acheteur:**")
                        st.write(f"• **Adresse:** `{selected_row['buyer_address']}`")
                        
                        if selected_row['early_adopter_profile']:
                            profile = selected_row['early_adopter_profile']
                            st.write(f"• **Score confiance:** {profile['confidence_score']:.3f}")
                            st.write(f"• **Taux succès:** {profile['success_rate']*100:.1f}%")
                            st.write(f"• **Total picks:** {profile['total_picks']}")
                            st.write(f"• **ROI moyen:** {profile['avg_roi']:.1f}x")
                        else:
                            st.write("• **Profil:** Non qualifié comme early adopter")
                        
                        # Liens utiles
                        st.write("**Liens directs:**")
                        st.write(f"[🚀 Pump.fun](https://pump.fun/{selected_row['token_address']})")
                        st.write(f"[🔍 Token Solscan](https://solscan.io/token/{selected_row['token_address']})")
                        st.write(f"[👤 Acheteur Solscan](https://solscan.io/account/{selected_row['buyer_address']})")
                        st.write(f"[👨‍💻 Créateur Solscan](https://solscan.io/account/{selected_row['token_creator']})")
                        st.write(f"[📄 Transaction Solscan](https://solscan.io/tx/{selected_row['signature']})")
                        
                        # Boutons de copie
                        st.write("**Copier les adresses:**")
                        
                        col_a, col_b = st.columns(2)
                        with col_a:
                            if st.button("📋 Token", key="copy_token", use_container_width=True):
                                st.code(selected_row['token_address'])
                            if st.button("📋 Créateur", key="copy_creator", use_container_width=True):
                                st.code(selected_row['token_creator'])
                        
                        with col_b:
                            if st.button("📋 Acheteur", key="copy_buyer", use_container_width=True):
                                st.code(selected_row['buyer_address'])
                            if st.button("📋 Signature", key="copy_sig", use_container_width=True):
                                st.code(selected_row['signature'])
    
    with tab3:
        st.header("👥 Analyse Détaillée des Acheteurs")
        
        if len(filtered_df) > 0:
            # Analyse groupée par acheteur
            buyer_analysis = filtered_df.groupby('buyer_address').agg({
                'sol_amount': ['sum', 'mean', 'count'],
                'token_address': 'nunique',
                'minutes_after_creation': ['mean', 'min'],
                'timestamp': ['min', 'max'],
                'early_adopter_profile': 'first'
            }).round(4)
            
            # Aplatir les colonnes multi-niveau
            buyer_analysis.columns = [
                'total_sol_invested', 'avg_sol_per_trade', 'total_trades',
                'unique_tokens', 'avg_timing_minutes', 'best_timing_minutes',
                'first_trade', 'last_trade', 'ea_profile'
            ]
            
            # Calculer des métriques supplémentaires
            buyer_analysis['total_usd_invested'] = buyer_analysis['total_sol_invested'] * sol_price
            buyer_analysis['avg_usd_per_trade'] = buyer_analysis['avg_sol_per_trade'] * sol_price
            buyer_analysis['trading_period_days'] = (
                pd.to_datetime(buyer_analysis['last_trade']) - 
                pd.to_datetime(buyer_analysis['first_trade'])
            ).dt.days + 1
            buyer_analysis['trades_per_day'] = buyer_analysis['total_trades'] / buyer_analysis['trading_period_days']
            
            # Extraire les données early adopter
            buyer_analysis['is_early_adopter'] = buyer_analysis['ea_profile'].notna()
            buyer_analysis['ea_confidence_score'] = buyer_analysis['ea_profile'].apply(
                lambda x: x['confidence_score'] if x else 0
            )
            buyer_analysis['ea_success_rate'] = buyer_analysis['ea_profile'].apply(
                lambda x: x['success_rate'] if x else 0
            )
            buyer_analysis['ea_total_picks'] = buyer_analysis['ea_profile'].apply(
                lambda x: x['total_picks'] if x else 0
            )
            
            # Calculer le score de diversification (plus de tokens uniques = mieux)
            buyer_analysis['diversification_score'] = (
                buyer_analysis['unique_tokens'] / buyer_analysis['total_trades']
            ).round(3)
            
            # Calculer un score de timing global (plus petit = mieux)
            buyer_analysis['timing_score'] = (
                1 / (buyer_analysis['avg_timing_minutes'] + 1)
            ).round(4)
            
            # Trier par montant total investi
            buyer_analysis = buyer_analysis.sort_values('total_sol_invested', ascending=False)
            
            # Métriques globales des acheteurs
            st.subheader("📊 Métriques Globales des Acheteurs")
            
            col1, col2, col3, col4, col5 = st.columns(5)
            
            with col1:
                total_buyers = len(buyer_analysis)
                st.metric("Total Acheteurs", total_buyers)
            
            with col2:
                ea_buyers = buyer_analysis['is_early_adopter'].sum()
                ea_percentage = (ea_buyers / total_buyers * 100) if total_buyers > 0 else 0
                st.metric("Early Adopters", f"{ea_buyers} ({ea_percentage:.1f}%)")
            
            with col3:
                total_volume_sol = buyer_analysis['total_sol_invested'].sum()
                st.metric("Volume Total", f"{total_volume_sol:.2f} SOL")
            
            with col4:
                total_volume_usd = buyer_analysis['total_usd_invested'].sum()
                st.metric("Volume USD", f"${total_volume_usd:,.2f}")
            
            with col5:
                avg_investment = buyer_analysis['total_sol_invested'].mean()
                st.metric("Investissement Moyen", f"{avg_investment:.4f} SOL")
            
            # Filtres pour le tableau des acheteurs
            st.subheader("🔍 Filtres Acheteurs")
            
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                min_sol_invested = st.number_input(
                    "SOL investi min", 
                    min_value=0.0, 
                    value=0.0, 
                    step=0.01,
                    format="%.4f"
                )
            
            with col2:
                min_trades = st.number_input(
                    "Trades minimum", 
                    min_value=1, 
                    value=1
                )
            
            with col3:
                only_ea_filter = st.checkbox("Early Adopters uniquement")
            
            with col4:
                sort_by = st.selectbox(
                    "Trier par",
                    ["total_sol_invested", "total_trades", "ea_confidence_score", "avg_timing_minutes", "diversification_score"],
                    format_func=lambda x: {
                        "total_sol_invested": "SOL Investi",
                        "total_trades": "Nombre de Trades",
                        "ea_confidence_score": "Score EA",
                        "avg_timing_minutes": "Timing Moyen",
                        "diversification_score": "Diversification"
                    }.get(x, x)
                )
            
            # Appliquer les filtres
            filtered_buyers = buyer_analysis[
                (buyer_analysis['total_sol_invested'] >= min_sol_invested) &
                (buyer_analysis['total_trades'] >= min_trades)
            ]
            
            if only_ea_filter:
                filtered_buyers = filtered_buyers[filtered_buyers['is_early_adopter']]
            
            # Trier selon le choix
            filtered_buyers = filtered_buyers.sort_values(sort_by, ascending=False)
            
            st.subheader(f"🏆 Top Acheteurs ({len(filtered_buyers)} résultats)")
            
            # Créer le tableau d'affichage
            display_buyers = []
            for wallet, data in filtered_buyers.head(50).iterrows():
                
                # Déterminer le type d'acheteur
                if data['is_early_adopter']:
                    if data['ea_confidence_score'] >= 0.9:
                        buyer_type = "🟢 EA Elite"
                    elif data['ea_confidence_score'] >= 0.8:
                        buyer_type = "🟡 EA Confirmé"
                    else:
                        buyer_type = "🟠 EA Débutant"
                else:
                    if data['total_trades'] >= 10:
                        buyer_type = "🔵 Trader Actif"
                    elif data['total_trades'] >= 5:
                        buyer_type = "⚪ Trader Moyen"
                    else:
                        buyer_type = "⚫ Trader Occasionnel"
                
                display_buyers.append({
                    'Rang': len(display_buyers) + 1,
                    'Wallet': format_wallet_address(wallet),
                    'Type': buyer_type,
                    'SOL Investi': f"{data['total_sol_invested']:.4f}",
                    'USD Investi': f"${data['total_usd_invested']:,.2f}",
                    'Nb Trades': int(data['total_trades']),
                    'Tokens Uniques': int(data['unique_tokens']),
                    'SOL/Trade': f"{data['avg_sol_per_trade']:.4f}",
                    'Timing Moy': f"{data['avg_timing_minutes']:.0f}min",
                    'Meilleur Timing': f"{data['best_timing_minutes']:.0f}min",
                    'Diversification': f"{data['diversification_score']:.2f}",
                    'Score EA': f"{data['ea_confidence_score']:.3f}" if data['is_early_adopter'] else "N/A",
                    'Taux Succès EA': f"{data['ea_success_rate']*100:.1f}%" if data['is_early_adopter'] else "N/A",
                    'Période (jours)': int(data['trading_period_days']),
                    'Trades/Jour': f"{data['trades_per_day']:.2f}",
                    'Première Trade': data['first_trade'][:10],
                    'Dernière Trade': data['last_trade'][:10]
                })
            
            # Afficher le tableau
            buyers_df = pd.DataFrame(display_buyers)
            st.dataframe(buyers_df, use_container_width=True, height=600)
            
            # Section de détails d'un acheteur
            st.subheader("🔍 Analyse Détaillée d'un Acheteur")
            
            if len(filtered_buyers) > 0:
                # Sélecteur d'acheteur
                buyer_options = []
                for wallet, data in filtered_buyers.head(20).iterrows():
                    label = f"{format_wallet_address(wallet)} - {data['total_sol_invested']:.4f} SOL - {int(data['total_trades'])} trades"
                    buyer_options.append((label, wallet))
                
                selected_buyer_label = st.selectbox(
                    "Sélectionner un acheteur pour analyse détaillée:",
                    options=[opt[0] for opt in buyer_options],
                    index=0
                )
                
                # Trouver le wallet correspondant
                selected_wallet = None
                for label, wallet in buyer_options:
                    if label == selected_buyer_label:
                        selected_wallet = wallet
                        break
                
                if selected_wallet:
                    buyer_data = filtered_buyers.loc[selected_wallet]
                    buyer_transactions = filtered_df[filtered_df['buyer_address'] == selected_wallet]
                    
                    col1, col2, col3 = st.columns(3)
                    
                    with col1:
                        st.write("**📊 Statistiques Globales:**")
                        st.write(f"• **Wallet:** `{selected_wallet}`")
                        st.write(f"• **SOL Total:** {buyer_data['total_sol_invested']:.4f} SOL")
                        st.write(f"• **USD Total:** ${buyer_data['total_usd_invested']:,.2f}")
                        st.write(f"• **Nombre de trades:** {int(buyer_data['total_trades'])}")
                        st.write(f"• **Tokens uniques:** {int(buyer_data['unique_tokens'])}")
                        st.write(f"• **Période active:** {int(buyer_data['trading_period_days'])} jours")
                        
                        # Liens
                        st.write("**🔗 Liens:**")
                        st.write(f"[👤 Solscan](https://solscan.io/account/{selected_wallet})")
                        
                        if st.button("📋 Copier adresse", key="copy_selected_wallet"):
                            st.code(selected_wallet)
                    
                    with col2:
                        st.write("**⚡ Performance Trading:**")
                        st.write(f"• **SOL moyen/trade:** {buyer_data['avg_sol_per_trade']:.4f}")
                        st.write(f"• **Timing moyen:** {buyer_data['avg_timing_minutes']:.0f} minutes")
                        st.write(f"• **Meilleur timing:** {buyer_data['best_timing_minutes']:.0f} minutes")
                        st.write(f"• **Score diversification:** {buyer_data['diversification_score']:.2f}")
                        st.write(f"• **Trades/jour:** {buyer_data['trades_per_day']:.2f}")
                        
                        # Calcul de cohérence temporelle
                        timing_std = buyer_transactions['minutes_after_creation'].std()
                        st.write(f"• **Cohérence timing:** {timing_std:.1f} (écart-type)")
                    
                    with col3:
                        st.write("**🏆 Profil Early Adopter:**")
                        if buyer_data['is_early_adopter']:
                            st.write(f"• **Score confiance:** {buyer_data['ea_confidence_score']:.3f}")
                            st.write(f"• **Taux succès:** {buyer_data['ea_success_rate']*100:.1f}%")
                            st.write(f"• **Total picks EA:** {int(buyer_data['ea_total_picks'])}")
                            
                            profile = buyer_data['ea_profile']
                            if profile:
                                st.write(f"• **ROI moyen:** {profile['avg_roi']:.1f}x")
                                st.write(f"• **Picks réussis:** {profile['successful_picks']}")
                        else:
                            st.write("• **Statut:** Non qualifié Early Adopter")
                            st.write("• **Raison:** Critères non remplis")
                            if buyer_data['total_trades'] < 5:
                                st.write("  - Moins de 5 trades")
                            if buyer_data['avg_timing_minutes'] > 360:
                                st.write("  - Timing trop tardif")
                    
                    # Historique des trades de cet acheteur
                    st.write("**📈 Historique des Trades:**")
                    
                    buyer_trades_display = []
                    for _, trade in buyer_transactions.iterrows():
                        buyer_trades_display.append({
                            'Date': format_timestamp(trade['timestamp']),
                            'Token Adresse': trade['token_address'],
                            'Symbole': trade.get('token_symbol', 'UNK'),
                            'SOL': f"{trade['sol_amount']:.4f}",
                            'USD': f"${trade['sol_amount'] * sol_price:.2f}",
                            'Timing': f"{trade['minutes_after_creation']}min",
                            'Pump.fun': f"https://pump.fun/{trade['token_address']}"
                        })
                    
                    if buyer_trades_display:
                        trades_df = pd.DataFrame(buyer_trades_display)
                        
                        # Configuration des colonnes avec liens cliquables
                        st.dataframe(
                            trades_df, 
                            use_container_width=True, 
                            height=300,
                            column_config={
                                "Token Adresse": st.column_config.TextColumn(
                                    "Token Adresse",
                                    help="Adresse complète du token",
                                    width="large"
                                ),
                                "Pump.fun": st.column_config.LinkColumn(
                                    "Pump.fun",
                                    help="Lien vers la page Pump.fun du token",
                                    display_text="🚀 Ouvrir",
                                    width="small"
                                ),
                                "Date": st.column_config.TextColumn("Date", width="medium"),
                                "Symbole": st.column_config.TextColumn("Symbole", width="small"),
                                "SOL": st.column_config.TextColumn("SOL", width="small"),
                                "USD": st.column_config.TextColumn("USD", width="small"),
                                "Timing": st.column_config.TextColumn("Timing", width="small")
                            }
                        )
                        
                        # Bouton pour copier toutes les adresses de tokens de cet acheteur
                        st.write("**📋 Actions pour cet acheteur:**")
                        col_a, col_b = st.columns(2)
                        
                        with col_a:
                            if st.button("📋 Copier toutes les adresses tokens", key="copy_buyer_tokens"):
                                token_addresses = buyer_transactions['token_address'].unique().tolist()
                                st.text_area(
                                    f"Adresses des {len(token_addresses)} tokens achetés:",
                                    value='\n'.join(token_addresses),
                                    height=150,
                                    key="buyer_tokens_textarea"
                                )
                        
                        with col_b:
                            if st.button("🚀 Liens Pump.fun", key="show_pumpfun_links"):
                                st.write("**Liens Pump.fun pour tous les tokens :**")
                                for addr in buyer_transactions['token_address'].unique():
                                    symbol = buyer_transactions[buyer_transactions['token_address'] == addr]['token_symbol'].iloc[0] or 'UNK'
                                    st.write(f"• [{symbol}](https://pump.fun/{addr}) - `{format_wallet_address(addr)}`")
            
            # Graphiques d'analyse
            st.subheader("📈 Graphiques d'Analyse")
            
            col1, col2 = st.columns(2)
            
            with col1:
                # Distribution des montants investis
                fig_investment = px.histogram(
                    filtered_buyers.reset_index(),
                    x='total_sol_invested',
                    nbins=20,
                    title="Distribution des Montants Investis (SOL)",
                    labels={'total_sol_invested': 'SOL Total Investi', 'count': 'Nombre d\'acheteurs'}
                )
                st.plotly_chart(fig_investment, use_container_width=True)
                
                # Relation timing vs investissement
                fig_timing_invest = px.scatter(
                    filtered_buyers.reset_index(),
                    x='avg_timing_minutes',
                    y='total_sol_invested',
                    color='is_early_adopter',
                    size='total_trades',
                    title="Timing vs Investissement",
                    labels={
                        'avg_timing_minutes': 'Timing Moyen (minutes)',
                        'total_sol_invested': 'SOL Total Investi'
                    }
                )
                st.plotly_chart(fig_timing_invest, use_container_width=True)
            
            with col2:
                # Early Adopters vs Regular Traders
                buyer_types = filtered_buyers['is_early_adopter'].value_counts()
                fig_types = px.pie(
                    values=buyer_types.values,
                    names=['Traders Réguliers' if not x else 'Early Adopters' for x in buyer_types.index],
                    title="Répartition Early Adopters vs Traders Réguliers"
                )
                st.plotly_chart(fig_types, use_container_width=True)
                
                # Score de diversification vs performance
                if filtered_buyers['is_early_adopter'].any():
                    ea_data = filtered_buyers[filtered_buyers['is_early_adopter']]
                    fig_diversif = px.scatter(
                        ea_data.reset_index(),
                        x='diversification_score',
                        y='ea_confidence_score',
                        size='total_trades',
                        title="Diversification vs Score EA",
                        labels={
                            'diversification_score': 'Score de Diversification',
                            'ea_confidence_score': 'Score de Confiance EA'
                        }
                    )
                    st.plotly_chart(fig_diversif, use_container_width=True)
        
        else:
            st.info("Aucune donnée d'acheteur à analyser avec les filtres actuels")
    
    with tab4:
        st.header("📊 Analyse des Transactions")
        
        if len(filtered_df) > 0:
            col1, col2 = st.columns(2)
            
            with col1:
                # Distribution des timings
                fig_timing = px.histogram(
                    filtered_df, 
                    x='minutes_after_creation',
                    nbins=20,
                    title="Distribution des Timings d'Achat"
                )
                st.plotly_chart(fig_timing, use_container_width=True)
            
            with col2:
                # Distribution des montants
                filtered_df['usd_amount'] = filtered_df['sol_amount'] * sol_price
                fig_amounts = px.histogram(
                    filtered_df,
                    x='usd_amount',
                    nbins=20,
                    title="Distribution des Montants USD"
                )
                st.plotly_chart(fig_amounts, use_container_width=True)
    
    with tab3:
        st.header("⚡ Actions Rapides")
        
        if len(filtered_df) > 0:
            col1, col2, col3 = st.columns(3)
            
            with col1:
                if st.button("📋 Copier tous les tokens", use_container_width=True):
                    token_addresses = filtered_df['token_address'].unique().tolist()
                    st.text_area("Adresses des tokens:", value='\n'.join(token_addresses), height=200)
            
            with col2:
                if st.button("📋 Copier tous les acheteurs", use_container_width=True):
                    buyer_addresses = filtered_df['buyer_address'].unique().tolist()
                    st.text_area("Adresses des acheteurs:", value='\n'.join(buyer_addresses), height=200)
            
            with col3:
                if st.button("📊 Exporter CSV", use_container_width=True):
                    csv = filtered_df.to_csv(index=False)
                    st.download_button(
                        label="⬇️ Télécharger CSV",
                        data=csv,
                        file_name=f"pumpfun_transactions_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                        mime="text/csv",
                        use_container_width=True
                    )

if __name__ == "__main__":
    main()