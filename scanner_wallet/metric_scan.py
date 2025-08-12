import sqlite3
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import streamlit as st
from datetime import datetime, timedelta
import numpy as np

# Configuration de la page Streamlit
st.set_page_config(
    page_title="Analyseur de Wallets",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="expanded"
)

class WalletAnalyzer:
    def __init__(self, db_path):
        self.db_path = db_path
        self.scan_df = None
        self.transactions_df = None
        
    def load_data(self):
        """Charge les données depuis la base SQLite"""
        try:
            conn = sqlite3.connect(self.db_path)
            
            # Charger les données de scan
            self.scan_df = pd.read_sql_query("SELECT * FROM scan_history", conn)
            
            # Charger les transactions
            self.transactions_df = pd.read_sql_query("SELECT * FROM transactions", conn)
            
            conn.close()
            
            # Conversion des timestamps pour scan_history
            self.scan_df['completed_at_dt'] = pd.to_datetime(self.scan_df['completed_at'], unit='s')
            self.scan_df['created_at_dt'] = pd.to_datetime(self.scan_df['created_at'])
            
            # Conversion des timestamps pour transactions
            if len(self.transactions_df) > 0:
                self.transactions_df['block_time_dt'] = pd.to_datetime(self.transactions_df['block_time'], unit='s')
                self.transactions_df['created_at_dt'] = pd.to_datetime(self.transactions_df['created_at'])
            
            return True
        except Exception as e:
            st.error(f"Erreur lors du chargement des données: {e}")
            return False
    
    def calculate_transaction_metrics(self):
        """Calcule les métriques de transactions par wallet"""
        if self.transactions_df is None or len(self.transactions_df) == 0:
            return pd.DataFrame()
            
        tx_metrics = self.transactions_df.groupby('wallet_address').agg({
            'id': 'count',  # Nombre total de transactions
            'amount': 'sum',  # Volume total SOL
            'token_amount': 'sum',  # Volume total tokens
            'fee': 'sum',  # Frais totaux
            'token_mint': 'nunique',  # Nombre de tokens uniques
            'is_token_transaction': 'sum',  # Transactions tokens
            'is_large_token_amount': 'sum',  # Grosses transactions
            'block_time_dt': ['min', 'max'],  # Première et dernière transaction
            'price_per_token': 'mean',  # Prix moyen
            'detection_delay': 'mean'  # Délai de détection moyen
        }).round(6)
        
        # Aplatir les colonnes multi-index
        tx_metrics.columns = [
            'total_transactions', 'total_sol_volume', 'total_token_volume',
            'total_fees', 'unique_tokens', 'token_transactions', 'large_transactions',
            'first_transaction', 'last_transaction', 'avg_token_price', 'avg_detection_delay'
        ]
        
        # Calculer des métriques dérivées
        tx_metrics['days_with_transactions'] = (
            tx_metrics['last_transaction'] - tx_metrics['first_transaction']
        ).dt.days + 1
        
        tx_metrics['transactions_per_day'] = (
            tx_metrics['total_transactions'] / tx_metrics['days_with_transactions']
        ).fillna(0)
        
        tx_metrics['token_transaction_rate'] = (
            tx_metrics['token_transactions'] / tx_metrics['total_transactions']
        ).fillna(0)
        
        tx_metrics['large_transaction_rate'] = (
            tx_metrics['large_transactions'] / tx_metrics['total_transactions']
        ).fillna(0)
        
        tx_metrics['avg_sol_per_transaction'] = (
            tx_metrics['total_sol_volume'] / tx_metrics['total_transactions']
        ).fillna(0)
        
        return tx_metrics.reset_index()
    
    def calculate_scan_metrics(self):
        """Calcule les métriques de scan par wallet"""
        if self.scan_df is None:
            return pd.DataFrame()
            
        scan_metrics = self.scan_df.groupby('wallet_address').agg({
            'id': 'count',  # Nombre total de scans
            'activity_detected': 'sum',  # Total activités détectées
            'scan_duration': 'mean',  # Durée moyenne des scans
            'efficiency_score': 'mean',  # Score d'efficacité moyen
            'priority_score_after': 'last',  # Dernier score de priorité
            'errors_count': 'sum',  # Total erreurs
            'completed_at_dt': ['min', 'max'],  # Premier et dernier scan
            'rpc_requests_count': 'sum'  # Total requêtes RPC
        }).round(3)
        
        # Aplatir les colonnes multi-index
        scan_metrics.columns = [
            'total_scans', 'total_activity_detected', 'avg_scan_duration',
            'avg_efficiency_score', 'last_priority_score', 'total_errors',
            'first_scan', 'last_scan', 'total_rpc_requests'
        ]
        
        # Calculer des métriques dérivées
        scan_metrics['days_scanned'] = (
            scan_metrics['last_scan'] - scan_metrics['first_scan']
        ).dt.days + 1
        
        scan_metrics['scans_per_day'] = (
            scan_metrics['total_scans'] / scan_metrics['days_scanned']
        )
        
        scan_metrics['activity_detection_rate'] = (
            scan_metrics['total_activity_detected'] / scan_metrics['total_scans']
        )
        
        scan_metrics['error_rate'] = (
            scan_metrics['total_errors'] / scan_metrics['total_scans']
        )
        
        scan_metrics['rpc_per_scan'] = (
            scan_metrics['total_rpc_requests'] / scan_metrics['total_scans']
        )
        
        return scan_metrics.reset_index()
    
    def calculate_combined_metrics(self):
        """Combine les métriques de scan et de transactions"""
        scan_metrics = self.calculate_scan_metrics()
        tx_metrics = self.calculate_transaction_metrics()
        
        if len(scan_metrics) == 0:
            return pd.DataFrame()
        
        # Joindre les métriques
        if len(tx_metrics) > 0:
            combined = scan_metrics.merge(tx_metrics, on='wallet_address', how='left')
            
            # Remplacer les NaN par 0 pour les wallets sans transactions
            tx_cols = [col for col in tx_metrics.columns if col != 'wallet_address']
            combined[tx_cols] = combined[tx_cols].fillna(0)
            
            # Calculer les ratios scan/transaction
            combined['transactions_per_scan'] = (
                combined['total_transactions'] / combined['total_scans']
            )
            
            combined['tokens_discovered_per_scan'] = (
                combined['unique_tokens'] / combined['total_scans']
            )
            
        else:
            combined = scan_metrics.copy()
            # Ajouter des colonnes de transactions avec des valeurs 0
            combined['total_transactions'] = 0
            combined['unique_tokens'] = 0
            combined['transactions_per_scan'] = 0
            combined['tokens_discovered_per_scan'] = 0
            combined['token_transaction_rate'] = 0
            combined['total_sol_volume'] = 0
        
        # Calculer le score d'inactivité composite
        combined['inactivity_score'] = self.calculate_inactivity_score(combined)
        
        return combined
    
    def calculate_inactivity_score(self, df):
        """Calcule un score d'inactivité composite (0 = très actif, 1 = très inactif)"""
        if len(df) == 0:
            return pd.Series()
        
        # Normaliser les métriques (0-1, où 1 = mauvais pour l'inactivité)
        scores = pd.DataFrame()
        
        # 1. Faible taux de détection d'activité (25%)
        scores['low_activity_detection'] = 1 - df['activity_detection_rate']
        
        # 2. Peu de transactions par scan (25%)
        max_tx_per_scan = df['transactions_per_scan'].max() if df['transactions_per_scan'].max() > 0 else 1
        scores['low_transactions'] = 1 - (df['transactions_per_scan'] / max_tx_per_scan)
        
        # 3. Peu de nouveaux tokens découverts (20%)
        max_tokens_per_scan = df['tokens_discovered_per_scan'].max() if df['tokens_discovered_per_scan'].max() > 0 else 1
        scores['low_token_discovery'] = 1 - (df['tokens_discovered_per_scan'] / max_tokens_per_scan)
        
        # 4. Faible efficacité de scan (15%)
        scores['low_efficiency'] = 1 - df['avg_efficiency_score']
        
        # 5. Taux d'erreur élevé (15%)
        scores['high_errors'] = df['error_rate']
        
        # Calculer le score composite avec pondération
        weights = {
            'low_activity_detection': 0.25,
            'low_transactions': 0.25,
            'low_token_discovery': 0.20,
            'low_efficiency': 0.15,
            'high_errors': 0.15
        }
        
        inactivity_score = sum(scores[col] * weight for col, weight in weights.items())
        
        return inactivity_score.fillna(1.0)  # Les wallets sans données sont considérés comme inactifs

def main():
    st.title("💰 Analyseur de Wallets - Dashboard d'Inactivité")
    st.markdown("---")
    
    # Sidebar pour la configuration
    st.sidebar.header("Configuration")
    db_path = st.sidebar.text_input(
        "Chemin vers la base de données SQLite", 
        value="solana_wallet_monitor.db",
        help="Chemin vers votre fichier de base de données"
    )
    
    # Initialisation de l'analyseur
    analyzer = WalletAnalyzer(db_path)
    
    if st.sidebar.button("🔄 Charger les données"):
        if analyzer.load_data():
            st.success("✅ Données chargées avec succès!")
            st.info(f"📊 {len(analyzer.scan_df)} scans et {len(analyzer.transactions_df) if analyzer.transactions_df is not None else 0} transactions chargées")
        else:
            st.stop()
    
    # Vérifier si les données sont chargées
    if analyzer.scan_df is None:
        st.warning("⚠️ Veuillez charger les données en cliquant sur le bouton dans la sidebar.")
        st.stop()
    
    # Calcul des métriques combinées
    combined_metrics = analyzer.calculate_combined_metrics()
    
    if len(combined_metrics) == 0:
        st.error("❌ Aucune donnée trouvée dans les tables.")
        st.stop()
    
    # Métriques globales
    st.header("📊 Vue d'ensemble")
    col1, col2, col3, col4, col5 = st.columns(5)
    
    with col1:
        st.metric("Total Wallets", len(combined_metrics))
    with col2:
        st.metric("Total Scans", combined_metrics['total_scans'].sum())
    with col3:
        st.metric("Total Transactions", int(combined_metrics['total_transactions'].sum()))
    with col4:
        st.metric("Activité Détectée Moyenne", f"{combined_metrics['activity_detection_rate'].mean():.2%}")
    with col5:
        st.metric("Tokens Uniques Total", int(combined_metrics['unique_tokens'].sum()))
    
    # Filtres
    st.header("🔧 Filtres")
    col1, col2, col3 = st.columns(3)
    
    with col1:
        min_scans = st.slider(
            "Nombre minimum de scans", 
            min_value=1, 
            max_value=int(combined_metrics['total_scans'].max()),
            value=5
        )
    
    with col2:
        max_inactivity_score = st.slider(
            "Score d'inactivité maximum (pour élimination)",
            min_value=0.0,
            max_value=1.0,
            value=0.7,
            step=0.05
        )
    
    with col3:
        min_days_scanned = st.slider(
            "Minimum jours de scan",
            min_value=1,
            max_value=int(combined_metrics['days_scanned'].max()),
            value=7
        )
    
    # Wallets à éliminer
    wallets_to_eliminate = combined_metrics[
        (combined_metrics['total_scans'] >= min_scans) &
        (combined_metrics['days_scanned'] >= min_days_scanned) &
        (combined_metrics['inactivity_score'] > max_inactivity_score)
    ].sort_values('inactivity_score', ascending=False)
    
    # Graphiques
    st.header("📈 Analyses Visuelles")
    
    # Graphique 1: Distribution du score d'inactivité
    fig1 = px.histogram(
        combined_metrics,
        x='inactivity_score',
        nbins=30,
        title="Distribution des Scores d'Inactivité",
        labels={'inactivity_score': 'Score d\'Inactivité', 'count': 'Nombre de Wallets'}
    )
    fig1.add_vline(x=max_inactivity_score, line_dash="dash", line_color="red", 
                   annotation_text="Seuil d'élimination")
    st.plotly_chart(fig1, use_container_width=True)
    
    # Graphiques en colonnes
    col1, col2 = st.columns(2)
    
    with col1:
        # Graphique 2: Transactions vs Détection d'activité
        fig2 = px.scatter(
            combined_metrics,
            x='activity_detection_rate',
            y='transactions_per_scan',
            size='total_scans',
            color='inactivity_score',
            hover_data=['wallet_address'],
            title="Détection d'Activité vs Transactions par Scan",
            labels={
                'activity_detection_rate': 'Taux de Détection d\'Activité',
                'transactions_per_scan': 'Transactions / Scan'
            }
        )
        st.plotly_chart(fig2, use_container_width=True)
    
    with col2:
        # Graphique 3: Efficacité vs Découverte de tokens
        fig3 = px.scatter(
            combined_metrics,
            x='avg_efficiency_score',
            y='tokens_discovered_per_scan',
            size='total_scans',
            color='inactivity_score',
            hover_data=['wallet_address'],
            title="Efficacité vs Découverte de Tokens",
            labels={
                'avg_efficiency_score': 'Score d\'Efficacité Moyen',
                'tokens_discovered_per_scan': 'Tokens Découverts / Scan'
            }
        )
        st.plotly_chart(fig3, use_container_width=True)
    
    # Graphique 4: Évolution temporelle des scans et transactions
    if analyzer.transactions_df is not None and len(analyzer.transactions_df) > 0:
        # Données quotidiennes pour les scans
        daily_scans = analyzer.scan_df.groupby(
            analyzer.scan_df['completed_at_dt'].dt.date
        )['activity_detected'].sum().reset_index()
        daily_scans.columns = ['date', 'activity_detected']
        
        # Données quotidiennes pour les transactions
        daily_tx = analyzer.transactions_df.groupby(
            analyzer.transactions_df['block_time_dt'].dt.date
        ).agg({
            'id': 'count',
            'token_mint': 'nunique'
        }).reset_index()
        daily_tx.columns = ['date', 'transactions', 'unique_tokens']
        
        fig4 = make_subplots(
            rows=2, cols=1,
            subplot_titles=('Activité Détectée par Jour (Scans)', 'Transactions et Tokens par Jour'),
            shared_xaxes=True
        )
        
        fig4.add_trace(
            go.Scatter(
                x=daily_scans['date'],
                y=daily_scans['activity_detected'],
                mode='lines+markers',
                name='Activité Détectée',
                line=dict(color='blue')
            ),
            row=1, col=1
        )
        
        fig4.add_trace(
            go.Scatter(
                x=daily_tx['date'],
                y=daily_tx['transactions'],
                mode='lines+markers',
                name='Transactions',
                line=dict(color='green')
            ),
            row=2, col=1
        )
        
        fig4.add_trace(
            go.Scatter(
                x=daily_tx['date'],
                y=daily_tx['unique_tokens'],
                mode='lines+markers',
                name='Tokens Uniques',
                yaxis='y4',
                line=dict(color='orange')
            ),
            row=2, col=1
        )
        
        fig4.update_layout(height=500, title_text="Évolution Temporelle de l'Activité")
        st.plotly_chart(fig4, use_container_width=True)
    
    # Section des recommandations
    st.header("🎯 Recommandations d'Élimination")
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.subheader(f"Wallets à Éliminer ({len(wallets_to_eliminate)} wallets)")
        if len(wallets_to_eliminate) > 0:
            display_cols = [
                'wallet_address', 'inactivity_score', 'total_scans', 
                'activity_detection_rate', 'transactions_per_scan', 
                'tokens_discovered_per_scan', 'avg_efficiency_score'
            ]
            st.dataframe(
                wallets_to_eliminate[display_cols].round(3),
                use_container_width=True
            )
            
            # Bouton de téléchargement
            csv = wallets_to_eliminate['wallet_address'].to_csv(index=False)
            st.download_button(
                label="📥 Télécharger la liste des wallets à éliminer",
                data=csv,
                file_name="wallets_to_eliminate.csv",
                mime="text/csv"
            )
        else:
            st.info("Aucun wallet à éliminer selon les critères actuels.")
    
    with col2:
        st.subheader("📊 Statistiques d'Impact")
        if len(wallets_to_eliminate) > 0:
            st.metric(
                "Wallets à éliminer", 
                len(wallets_to_eliminate),
                delta=f"{len(wallets_to_eliminate)/len(combined_metrics)*100:.1f}% du total"
            )
            st.metric(
                "Score d'inactivité moyen",
                f"{wallets_to_eliminate['inactivity_score'].mean():.3f}"
            )
            st.metric(
                "Scans économisés",
                int(wallets_to_eliminate['total_scans'].sum())
            )
            st.metric(
                "Requêtes RPC économisées",
                int(wallets_to_eliminate['total_rpc_requests'].sum())
            )
    
    # Section détaillée
    st.header("📋 Analyse Détaillée par Wallet")
    
    # Tableau complet avec options de tri
    st.subheader("Tous les Wallets")
    sort_by = st.selectbox(
        "Trier par:",
        options=[
            'inactivity_score', 'total_scans', 'activity_detection_rate',
            'transactions_per_scan', 'tokens_discovered_per_scan', 'avg_efficiency_score',
            'total_transactions', 'unique_tokens', 'last_scan'
        ],
        format_func=lambda x: {
            'inactivity_score': 'Score d\'Inactivité',
            'total_scans': 'Nombre de Scans',
            'activity_detection_rate': 'Taux de Détection',
            'transactions_per_scan': 'Transactions/Scan',
            'tokens_discovered_per_scan': 'Tokens/Scan',
            'avg_efficiency_score': 'Score d\'Efficacité',
            'total_transactions': 'Total Transactions',
            'unique_tokens': 'Tokens Uniques',
            'last_scan': 'Dernier Scan'
        }.get(x, x)
    )
    
    ascending = st.checkbox("Ordre croissant", value=False)
    
    sorted_wallets = combined_metrics.sort_values(sort_by, ascending=ascending)
    
    # Colonnes à afficher
    detailed_cols = [
        'wallet_address', 'inactivity_score', 'total_scans', 'activity_detection_rate',
        'transactions_per_scan', 'tokens_discovered_per_scan', 'avg_efficiency_score',
        'total_transactions', 'unique_tokens', 'total_errors', 'last_scan'
    ]
    
    st.dataframe(
        sorted_wallets[detailed_cols].round(4),
        use_container_width=True,
        height=400
    )
    
    # Section d'analyse comparative
    st.header("🔍 Analyse Comparative")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Top 10 - Wallets les plus actifs")
        top_active = combined_metrics.nsmallest(10, 'inactivity_score')[
            ['wallet_address', 'inactivity_score', 'total_transactions', 'unique_tokens']
        ]
        st.dataframe(top_active.round(3))
    
    with col2:
        st.subheader("Top 10 - Wallets les moins actifs")
        top_inactive = combined_metrics.nlargest(10, 'inactivity_score')[
            ['wallet_address', 'inactivity_score', 'total_transactions', 'unique_tokens']
        ]
        st.dataframe(top_inactive.round(3))

if __name__ == "__main__":
    main()