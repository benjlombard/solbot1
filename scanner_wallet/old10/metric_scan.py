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
        
        # Métriques générales
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
        
        # Compter les transactions par type
        tx_type_counts = self.transactions_df.groupby(['wallet_address', 'transaction_type']).size().unstack(fill_value=0)
        
        # Ajouter les colonnes de types de transactions s'elles existent
        type_mapping = {
            'TransactionType.BUY': 'buy_count',
            'TransactionType.SELL': 'sell_count', 
            'TransactionType.TRANSFER_IN': 'transfer_in_count',
            'TransactionType.TRANSFER_OUT': 'transfer_out_count'
        }
        
        for enum_type, col_name in type_mapping.items():
            if enum_type in tx_type_counts.columns:
                tx_metrics[col_name] = tx_type_counts[enum_type]
            else:
                tx_metrics[col_name] = 0
        
        # Ajouter d'autres types de transactions détectés
        other_types = [col for col in tx_type_counts.columns 
                      if col not in type_mapping.keys()]
        if other_types:
            tx_metrics['other_transactions'] = tx_type_counts[other_types].sum(axis=1)
        else:
            tx_metrics['other_transactions'] = 0
        
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
        
        # Calculer les taux pour chaque type de transaction
        for tx_type in ['buy', 'sell', 'transfer_in', 'transfer_out']:
            tx_metrics[f'{tx_type}_rate'] = (
                tx_metrics[f'{tx_type}_count'] / tx_metrics['total_transactions']
            ).fillna(0)
        
        # Calculer le ratio buy/sell
        tx_metrics['buy_sell_ratio'] = (
            tx_metrics['buy_count'] / (tx_metrics['sell_count'] + 0.001)  # Éviter division par 0
        ).fillna(0)
        
        # Score d'activité de trading (buy + sell vs transfers)
        tx_metrics['trading_activity_score'] = (
            (tx_metrics['buy_count'] + tx_metrics['sell_count']) / 
            (tx_metrics['total_transactions'] + 0.001)
        ).fillna(0)
        
        return tx_metrics.reset_index()
    
    def get_wallet_tokens_detail(self, wallet_address):
        """Récupère la liste détaillée des tokens pour un wallet"""
        if self.transactions_df is None or len(self.transactions_df) == 0:
            return pd.DataFrame()
        
        wallet_tokens = self.transactions_df[
            (self.transactions_df['wallet_address'] == wallet_address) &
            (self.transactions_df['token_mint'].notna()) &
            (self.transactions_df['token_mint'] != '')
        ].groupby('token_mint').agg({
            'id': 'count',
            'transaction_type': lambda x: list(x.unique()),
            'token_amount': 'sum',
            'amount': 'sum',
            'block_time_dt': ['min', 'max']
        }).round(6)
        
        # Aplatir les colonnes
        wallet_tokens.columns = [
            'tx_count', 'tx_types', 'total_token_amount', 
            'total_sol_amount', 'first_tx', 'last_tx'
        ]
        
        # Ajouter les liens DexScreener et Pump.fun
        wallet_tokens = wallet_tokens.reset_index()
        wallet_tokens['dexscreener_link'] = wallet_tokens['token_mint'].apply(
            lambda x: f"https://dexscreener.com/solana/{x}" if pd.notna(x) else ""
        )
        wallet_tokens['pumpfun_link'] = wallet_tokens['token_mint'].apply(
            lambda x: f"https://pump.fun/{x}" if pd.notna(x) else ""
        )
        
        return wallet_tokens.sort_values('tx_count', ascending=False)
    
    def get_global_tokens_analysis(self):
        """Analyse globale de tous les tokens sur l'ensemble des wallets"""
        if self.transactions_df is None or len(self.transactions_df) == 0:
            return pd.DataFrame()
        
        # Filtrer les transactions avec tokens valides
        token_txs = self.transactions_df[
            (self.transactions_df['token_mint'].notna()) &
            (self.transactions_df['token_mint'] != '') &
            (self.transactions_df['token_mint'] != 'None') &
            (self.transactions_df['token_mint'].str.len() > 10)  # Adresses Solana font ~44 caractères
        ].copy()
        
        if len(token_txs) == 0:
            return pd.DataFrame()
        
        # Agrégation par token_mint uniquement
        token_stats = token_txs.groupby('token_mint').agg({
            'id': 'count',  # Total transactions
            'wallet_address': 'nunique',  # Nombre de wallets uniques
            'token_amount': 'sum',  # Volume total
            'amount': 'sum',  # Volume SOL total
            'block_time': ['min', 'max'],  # Première et dernière transaction
            'created_at': 'min'  # Première découverte
        }).round(6)
        
        # Aplatir les colonnes
        token_stats.columns = [
            'total_transactions', 'unique_wallets', 'total_token_volume',
            'total_sol_volume', 'first_transaction', 'last_transaction', 'first_discovery'
        ]
        
        # Compter les transactions par type
        tx_type_counts = token_txs.groupby(['token_mint', 'transaction_type']).size().unstack(fill_value=0)
        
        # Mapper les types d'enum vers des noms simples
        type_mapping = {
            'TransactionType.BUY': 'buy_count',
            'TransactionType.SELL': 'sell_count',
            'TransactionType.TRANSFER_IN': 'transfer_in_count',
            'TransactionType.TRANSFER_OUT': 'transfer_out_count'
        }
        
        # Ajouter les compteurs par type
        for enum_type, col_name in type_mapping.items():
            if enum_type in tx_type_counts.columns:
                token_stats[col_name] = tx_type_counts[enum_type]
            else:
                token_stats[col_name] = 0
        
        # Reset index pour avoir token_mint comme colonne
        token_stats = token_stats.reset_index()
        
        # Calculer l'âge de la découverte avec gestion des NaN
        now = pd.Timestamp.now()
        
        # S'assurer que first_discovery est valide
        token_stats['first_discovery'] = pd.to_datetime(token_stats['first_discovery'], errors='coerce')
        
        # Calculer les âges
        age_diff = now - token_stats['first_discovery']
        token_stats['discovery_age_days'] = age_diff.dt.days.fillna(0).astype(int)
        token_stats['discovery_age_hours'] = (age_diff.dt.total_seconds() / 3600).fillna(0)
        
        # Formater l'âge de manière lisible
        def format_age(row):
            days = row['discovery_age_days']
            hours = row['discovery_age_hours']
            
            # Gérer les valeurs NaN ou négatives
            if pd.isna(days) or pd.isna(hours) or days < 0 or hours < 0:
                return "N/A"
            
            try:
                days_int = int(days)
                hours_float = float(hours)
                
                if days_int >= 1:
                    return f"{days_int}j"
                elif hours_float >= 1:
                    return f"{int(hours_float)}h"
                else:
                    minutes = int(hours_float * 60) if hours_float >= 0 else 0
                    return f"{minutes}min"
            except (ValueError, TypeError):
                return "N/A"
        
        token_stats['age_formatted'] = token_stats.apply(format_age, axis=1)
        
        # Ajouter les liens
        token_stats['dexscreener_link'] = token_stats['token_mint'].apply(
            lambda x: f"https://dexscreener.com/solana/{x}"
        )
        token_stats['pumpfun_link'] = token_stats['token_mint'].apply(
            lambda x: f"https://pump.fun/{x}"
        )
        
        # Calculer des métriques supplémentaires avec gestion des NaN
        token_stats['buy_sell_ratio'] = (
            token_stats['buy_count'] / (token_stats['sell_count'] + 0.001)
        ).fillna(0).round(2)
        
        token_stats['activity_score'] = (
            token_stats['total_transactions'] * token_stats['unique_wallets']
        ).fillna(0)
        
        return token_stats.sort_values('first_discovery', ascending=False)
    
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
            
            # Debug info
            scan_count = len(analyzer.scan_df) if analyzer.scan_df is not None else 0
            tx_count = len(analyzer.transactions_df) if analyzer.transactions_df is not None else 0
            
            st.info(f"📊 {scan_count} scans et {tx_count} transactions chargées")
            
            # Debug pour les transactions
            if analyzer.transactions_df is not None and len(analyzer.transactions_df) > 0:
                st.sidebar.write("**Debug Transactions:**")
                st.sidebar.write(f"Colonnes: {list(analyzer.transactions_df.columns)}")
                
                # Vérifier les tokens valides
                valid_tokens = analyzer.transactions_df[
                    (analyzer.transactions_df['token_mint'].notna()) &
                    (analyzer.transactions_df['token_mint'] != '') &
                    (analyzer.transactions_df['token_mint'] != 'None')
                ]
                st.sidebar.write(f"Transactions avec tokens valides: {len(valid_tokens)}")
                
                # Vérifier les types de transactions
                tx_types = analyzer.transactions_df['transaction_type'].value_counts()
                st.sidebar.write("Types de transactions:")
                for tx_type, count in tx_types.items():
                    st.sidebar.write(f"  {tx_type}: {count}")
                    
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
    col1, col2, col3, col4, col5, col6 = st.columns(6)
    
    with col1:
        st.metric("Total Wallets", len(combined_metrics))
    with col2:
        st.metric("Total Scans", combined_metrics['total_scans'].sum())
    with col3:
        st.metric("Total Transactions", int(combined_metrics['total_transactions'].sum()))
    with col4:
        st.metric("Total Buy", int(combined_metrics['buy_count'].sum()) if 'buy_count' in combined_metrics.columns else 0)
    with col5:
        st.metric("Total Sell", int(combined_metrics['sell_count'].sum()) if 'sell_count' in combined_metrics.columns else 0)
    with col6:
        st.metric("Tokens Uniques", int(combined_metrics['unique_tokens'].sum()))
    
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
            color='trading_activity_score' if 'trading_activity_score' in combined_metrics.columns else 'inactivity_score',
            hover_data=['wallet_address', 'buy_count', 'sell_count'] if 'buy_count' in combined_metrics.columns else ['wallet_address'],
            title="Détection d'Activité vs Transactions par Scan",
            labels={
                'activity_detection_rate': 'Taux de Détection d\'Activité',
                'transactions_per_scan': 'Transactions / Scan',
                'trading_activity_score': 'Score de Trading'
            }
        )
        st.plotly_chart(fig2, use_container_width=True)
    
    with col2:
        # Graphique 3: Buy vs Sell ratio
        if 'buy_count' in combined_metrics.columns and 'sell_count' in combined_metrics.columns:
            fig3 = px.scatter(
                combined_metrics[combined_metrics['total_transactions'] > 0],
                x='buy_rate',
                y='sell_rate',
                size='total_transactions',
                color='inactivity_score',
                hover_data=['wallet_address', 'buy_count', 'sell_count'],
                title="Taux Buy vs Taux Sell",
                labels={
                    'buy_rate': 'Taux de Buy',
                    'sell_rate': 'Taux de Sell'
                }
            )
        else:
            # Fallback au graphique original
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
                'tokens_discovered_per_scan'
            ]
            
            # Ajouter les colonnes de transactions si elles existent
            if 'buy_count' in wallets_to_eliminate.columns:
                display_cols.extend(['buy_count', 'sell_count', 'transfer_in_count', 'transfer_out_count'])
            
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
    
    # Section détaillée des tokens par wallet
    st.header("🪙 Analyse Détaillée des Tokens par Wallet")
    
    # Sélecteur de wallet
    selected_wallet = st.selectbox(
        "Sélectionnez un wallet pour voir ses tokens:",
        options=combined_metrics['wallet_address'].tolist(),
        index=0 if len(combined_metrics) > 0 else None
    )
    
    if selected_wallet:
        wallet_tokens = analyzer.get_wallet_tokens_detail(selected_wallet)
        
        if len(wallet_tokens) > 0:
            col1, col2 = st.columns([3, 1])
            
            with col1:
                st.subheader(f"Tokens du wallet: {selected_wallet[:8]}...{selected_wallet[-8:]}")
                
                # Créer un DataFrame d'affichage avec liens cliquables
                display_tokens = wallet_tokens.copy()
                
                # Formater les liens en HTML
                display_tokens['DexScreener'] = display_tokens['dexscreener_link'].apply(
                    lambda x: f'<a href="{x}" target="_blank">📊 DexScreener</a>' if x else ""
                )
                display_tokens['PumpFun'] = display_tokens['pumpfun_link'].apply(
                    lambda x: f'<a href="{x}" target="_blank">🚀 Pump.fun</a>' if x else ""
                )
                
                # Formater les types de transactions
                display_tokens['Types TX'] = display_tokens['tx_types'].apply(
                    lambda x: ', '.join([t.replace('TransactionType.', '') for t in x])
                )
                
                # Colonnes à afficher
                cols_to_show = [
                    'token_mint', 'tx_count', 'Types TX', 'total_token_amount', 'DexScreener', 'PumpFun'
                ]
                
                # Afficher le tableau avec les liens HTML
                st.markdown(
                    display_tokens[cols_to_show].to_html(escape=False, index=False),
                    unsafe_allow_html=True
                )
            
            with col2:
                st.subheader("📊 Statistiques")
                st.metric("Tokens Uniques", len(wallet_tokens))
                st.metric("Transactions Totales", wallet_tokens['tx_count'].sum())
                
                # Top 3 tokens les plus tradés
                st.subheader("🔥 Top 3 Tokens")
                top3 = wallet_tokens.head(3)
                for _, token in top3.iterrows():
                    with st.container():
                        st.write(f"**{token['token_mint'][:8]}...{token['token_mint'][-8:]}**")
                        st.write(f"Transactions: {token['tx_count']}")
                        col_a, col_b = st.columns(2)
                        with col_a:
                            st.markdown(
                                f'<a href="{token["dexscreener_link"]}" target="_blank" style="display: inline-block; padding: 0.25rem 0.5rem; background-color: #1f77b4; color: white; text-decoration: none; border-radius: 0.25rem; text-align: center; width: 100%;">📊 DexScreener</a>',
                                unsafe_allow_html=True
                            )
                        with col_b:
                            st.markdown(
                                f'<a href="{token["pumpfun_link"]}" target="_blank" style="display: inline-block; padding: 0.25rem 0.5rem; background-color: #ff7f0e; color: white; text-decoration: none; border-radius: 0.25rem; text-align: center; width: 100%;">🚀 Pump.fun</a>',
                                unsafe_allow_html=True
                            )
                        st.divider()
        else:
            st.info(f"Aucun token trouvé pour le wallet {selected_wallet}")
    
    # Section export des tokens
    st.header("📥 Export des Données")
    
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("📊 Générer rapport complet des tokens"):
            # Générer un rapport de tous les tokens de tous les wallets
            all_tokens_report = []
            
            for wallet in combined_metrics['wallet_address'].tolist()[:10]:  # Limiter aux 10 premiers pour l'exemple
                wallet_tokens = analyzer.get_wallet_tokens_detail(wallet)
                if len(wallet_tokens) > 0:
                    wallet_tokens['wallet_address'] = wallet
                    all_tokens_report.append(wallet_tokens)
            
            if all_tokens_report:
                full_report = pd.concat(all_tokens_report, ignore_index=True)
                
                # Réorganiser les colonnes
                report_cols = [
                    'wallet_address', 'token_mint', 'tx_count', 'tx_types', 
                    'total_token_amount', 'total_sol_amount', 'first_tx', 'last_tx', 
                    'dexscreener_link', 'pumpfun_link'
                ]
                
                csv_report = full_report[report_cols].to_csv(index=False)
                
                st.download_button(
                    label="📥 Télécharger le rapport complet (CSV)",
                    data=csv_report,
                    file_name="wallet_tokens_report.csv",
                    mime="text/csv"
                )
                
                st.success(f"Rapport généré pour {len(full_report)} tokens uniques!")
            else:
                st.warning("Aucun token trouvé pour générer le rapport.")
    
    with col2:
        # Statistiques globales des tokens
        if analyzer.transactions_df is not None and len(analyzer.transactions_df) > 0:
            token_data = analyzer.transactions_df[
                analyzer.transactions_df['token_mint'].notna()
            ]
            
            unique_tokens = token_data['token_mint'].nunique()
            
            # Grouper par token_mint seulement
            most_traded_tokens = token_data.groupby('token_mint').size().sort_values(ascending=False).head(5)
            
            st.subheader("🌟 Tokens les plus tradés")
            for mint, count in most_traded_tokens.items():
                display_name = f"{mint[:8]}...{mint[-8:]}"
                
                col_a, col_b, col_c = st.columns([2, 1, 1])
                with col_a:
                    st.write(f"**{display_name}** ({count} tx)")
                with col_b:
                    if st.button("📊", key=f"dex_{mint[:8]}"):
                        st.markdown(f'<a href="https://dexscreener.com/solana/{mint}" target="_blank">Ouvrir DexScreener</a>', unsafe_allow_html=True)
                with col_c:
                    if st.button("🚀", key=f"pump_{mint[:8]}"):
                        st.markdown(f'<a href="https://pump.fun/{mint}" target="_blank">Ouvrir Pump.fun</a>', unsafe_allow_html=True)
    
    # Nouvelle section : Analyse Globale des Tokens
    st.header("🌍 Analyse Globale des Tokens")
    st.markdown("*Aperçu de tous les tokens découverts par l'ensemble des wallets*")
    
    # Récupérer l'analyse globale des tokens
    global_tokens = analyzer.get_global_tokens_analysis()
    
    if len(global_tokens) > 0:
        # Filtres pour l'analyse globale
        col1, col2, col3 = st.columns(3)
        
        with col1:
            max_tx = global_tokens['total_transactions'].max()
            max_tx_safe = int(max_tx) if pd.notna(max_tx) and max_tx > 0 else 10
            min_transactions = st.slider(
                "Transactions minimum par token", 
                min_value=1, 
                max_value=max_tx_safe,
                value=min(2, max_tx_safe)
            )
        
        with col2:
            max_wallets = global_tokens['unique_wallets'].max()
            max_wallets_safe = int(max_wallets) if pd.notna(max_wallets) and max_wallets > 0 else 5
            min_wallets = st.slider(
                "Wallets minimum par token",
                min_value=1,
                max_value=max_wallets_safe,
                value=1
            )
        
        with col3:
            max_age = global_tokens['discovery_age_days'].max()
            max_age_safe = int(max_age) if pd.notna(max_age) and max_age > 0 else 30
            max_age_days = st.slider(
                "Âge maximum (jours)",
                min_value=1,
                max_value=max_age_safe,
                value=min(30, max_age_safe)
            )
        
        # Filtrer les tokens selon les critères (avec gestion des NaN)
        filtered_tokens = global_tokens[
            (global_tokens['total_transactions'].fillna(0) >= min_transactions) &
            (global_tokens['unique_wallets'].fillna(0) >= min_wallets) &
            (global_tokens['discovery_age_days'].fillna(999) <= max_age_days)
        ]
        
        # Métriques de résumé
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            pct_filtered = (len(filtered_tokens)/len(global_tokens)*100) if len(global_tokens) > 0 else 0
            st.metric(
                "Tokens Filtrés", 
                len(filtered_tokens),
                delta=f"{pct_filtered:.1f}% du total"
            )
        with col2:
            total_tx = filtered_tokens['total_transactions'].sum()
            total_tx_safe = int(total_tx) if pd.notna(total_tx) else 0
            st.metric(
                "Transactions Totales",
                total_tx_safe
            )
        with col3:
            recent_count = len(filtered_tokens[
                (filtered_tokens['discovery_age_days'] < 1) & 
                (~filtered_tokens['discovery_age_days'].isna())
            ]) if len(filtered_tokens) > 0 else 0
            st.metric(
                "Tokens < 24h",
                recent_count
            )
        with col4:
            avg_wallets = filtered_tokens['unique_wallets'].mean()
            avg_wallets_safe = avg_wallets if pd.notna(avg_wallets) else 0
            st.metric(
                "Wallets/Token Moyen",
                f"{avg_wallets_safe:.1f}"
            )
        
        # Options de tri
        col1, col2 = st.columns(2)
        
        with col1:
            sort_by_global = st.selectbox(
                "Trier par:",
                options=[
                    'first_discovery', 'total_transactions', 'unique_wallets', 
                    'buy_count', 'sell_count', 'buy_sell_ratio', 'activity_score'
                ],
                format_func=lambda x: {
                    'first_discovery': 'Date de Découverte',
                    'total_transactions': 'Nombre de Transactions',
                    'unique_wallets': 'Nombre de Wallets',
                    'buy_count': 'Nombre de Buy',
                    'sell_count': 'Nombre de Sell',
                    'buy_sell_ratio': 'Ratio Buy/Sell',
                    'activity_score': 'Score d\'Activité'
                }.get(x, x),
                index=0
            )
        
        with col2:
            ascending_global = st.checkbox("Ordre croissant", value=False, key="global_sort")
        
        # Trier les données
        sorted_tokens = filtered_tokens.sort_values(sort_by_global, ascending=ascending_global)
        
        # Tableau principal des tokens
        st.subheader(f"📊 Tableau des Tokens ({len(sorted_tokens)} tokens)")
        
        # Préparer les données d'affichage
        display_tokens_global = sorted_tokens.copy()
        
        # Formater les liens
        display_tokens_global['DexScreener'] = display_tokens_global['dexscreener_link'].apply(
            lambda x: f'<a href="{x}" target="_blank" style="color: #1f77b4;">📊 DexScreener</a>'
        )
        display_tokens_global['PumpFun'] = display_tokens_global['pumpfun_link'].apply(
            lambda x: f'<a href="{x}" target="_blank" style="color: #ff7f0e;">🚀 Pump.fun</a>'
        )
        
        # Formater l'adresse du token (raccourcie)
        display_tokens_global['Token Address'] = display_tokens_global['token_mint'].apply(
            lambda x: f"{x[:8]}...{x[-8:]}" if len(x) > 16 else x
        )
        
        # Colonnes à afficher dans le tableau
        columns_to_show = [
            'Token Address', 'buy_count', 'sell_count', 'transfer_in_count', 'transfer_out_count',
            'unique_wallets', 'age_formatted', 'buy_sell_ratio', 'DexScreener', 'PumpFun'
        ]
        
        # Renommer les colonnes pour l'affichage
        column_names = {
            'Token Address': 'Adresse Token',
            'buy_count': 'Buy',
            'sell_count': 'Sell', 
            'transfer_in_count': 'Transfer In',
            'transfer_out_count': 'Transfer Out',
            'unique_wallets': 'Wallets',
            'age_formatted': 'Âge',
            'buy_sell_ratio': 'B/S Ratio'
        }
        
        display_df = display_tokens_global[columns_to_show].rename(columns=column_names)
        
        # Afficher le tableau avec pagination
        items_per_page = 20
        total_pages = (len(display_df) + items_per_page - 1) // items_per_page
        
        if total_pages > 1:
            page = st.selectbox(f"Page (1-{total_pages}):", range(1, total_pages + 1)) - 1
            start_idx = page * items_per_page
            end_idx = start_idx + items_per_page
            display_df_page = display_df.iloc[start_idx:end_idx]
        else:
            display_df_page = display_df
        
        # Afficher le tableau HTML
        st.markdown(
            display_df_page.to_html(escape=False, index=False, classes='token-table'),
            unsafe_allow_html=True
        )
        
        # CSS pour améliorer l'apparence du tableau
        st.markdown("""
        <style>
        .token-table {
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
        }
        .token-table th, .token-table td {
            border: 1px solid #ddd;
            padding: 8px;
            text-align: left;
        }
        .token-table th {
            background-color: #f2f2f2;
            font-weight: bold;
        }
        .token-table tr:nth-child(even) {
            background-color: #f9f9f9;
        }
        .token-table tr:hover {
            background-color: #f5f5f5;
        }
        </style>
        """, unsafe_allow_html=True)
        
        # Boutons d'export
        col1, col2 = st.columns(2)
        
        with col1:
            # Export CSV du tableau filtré
            export_cols = [
                'token_mint', 'buy_count', 'sell_count', 'transfer_in_count', 'transfer_out_count', 
                'unique_wallets', 'age_formatted', 'first_discovery', 'dexscreener_link', 'pumpfun_link'
            ]
                
            csv_global = sorted_tokens[export_cols].to_csv(index=False)
            
            st.download_button(
                label="📥 Télécharger tokens filtrés (CSV)",
                data=csv_global,
                file_name=f"global_tokens_analysis_{pd.Timestamp.now().strftime('%Y%m%d_%H%M')}.csv",
                mime="text/csv"
            )
        
        with col2:
            # Export des adresses uniquement (pour import dans d'autres outils)
            addresses_only = '\n'.join(sorted_tokens['token_mint'].tolist())
            
            st.download_button(
                label="📋 Adresses seulement (TXT)",
                data=addresses_only,
                file_name=f"token_addresses_{pd.Timestamp.now().strftime('%Y%m%d_%H%M')}.txt",
                mime="text/plain"
            )
        
        # Insights supplémentaires
        st.subheader("🔍 Insights")
        
        col1, col2 = st.columns(2)
        
        with col1:
            # Top tokens par activité récente (< 24h)
            recent_tokens = filtered_tokens[
                (filtered_tokens['discovery_age_days'] < 1) & 
                (~filtered_tokens['discovery_age_days'].isna())
            ]
            if len(recent_tokens) > 0:
                st.write("**🔥 Tokens découverts récemment (<24h):**")
                for _, token in recent_tokens.head(5).iterrows():
                    # Utiliser l'adresse raccourcie comme nom
                    display_name = f"{token['token_mint'][:8]}...{token['token_mint'][-8:]}"
                    st.write(f"• **{display_name}** - {int(token['buy_count'])} buys, {int(token['unique_wallets'])} wallets")
        
        with col2:
            # Tokens avec fort ratio buy/sell
            hot_tokens = filtered_tokens[
                (filtered_tokens['buy_sell_ratio'] > 2) & 
                (filtered_tokens['buy_count'] >= 3)
            ].head(5)
            
            if len(hot_tokens) > 0:
                st.write("**📈 Tokens avec fort ratio Buy/Sell:**")
                for _, token in hot_tokens.iterrows():
                    # Utiliser l'adresse raccourcie comme nom
                    display_name = f"{token['token_mint'][:8]}...{token['token_mint'][-8:]}"
                    ratio = token['buy_sell_ratio'] if pd.notna(token['buy_sell_ratio']) else 0
                    st.write(f"• **{display_name}** - Ratio: {ratio:.1f}")
    
    else:
        st.info("Aucun token trouvé dans les transactions.")
    
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
        'transactions_per_scan', 'tokens_discovered_per_scan', 'total_transactions'
    ]
    
    # Ajouter les colonnes de types de transactions si elles existent
    if 'buy_count' in sorted_wallets.columns:
        detailed_cols.extend([
            'buy_count', 'sell_count', 'transfer_in_count', 'transfer_out_count',
            'buy_rate', 'sell_rate', 'trading_activity_score'
        ])
    
    detailed_cols.extend(['unique_tokens', 'total_errors', 'last_scan'])
    
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
        display_cols_active = ['wallet_address', 'inactivity_score', 'total_transactions', 'unique_tokens']
        if 'buy_count' in combined_metrics.columns:
            display_cols_active.extend(['buy_count', 'sell_count'])
        
        top_active = combined_metrics.nsmallest(10, 'inactivity_score')[display_cols_active]
        st.dataframe(top_active.round(3))
    
    with col2:
        st.subheader("Top 10 - Wallets les moins actifs")
        display_cols_inactive = ['wallet_address', 'inactivity_score', 'total_transactions', 'unique_tokens']
        if 'buy_count' in combined_metrics.columns:
            display_cols_inactive.extend(['buy_count', 'sell_count'])
        
        top_inactive = combined_metrics.nlargest(10, 'inactivity_score')[display_cols_inactive]
        st.dataframe(top_inactive.round(3))
    
    # Nouvelle section : Analyse des types de transactions
    if 'buy_count' in combined_metrics.columns:
        st.header("💹 Analyse des Types de Transactions")
        
        # Graphiques de distribution des types de transactions
        col1, col2 = st.columns(2)
        
        with col1:
            # Pie chart des types de transactions
            tx_types_total = {
                'Buy': combined_metrics['buy_count'].sum(),
                'Sell': combined_metrics['sell_count'].sum(),
                'Transfer In': combined_metrics['transfer_in_count'].sum(),
                'Transfer Out': combined_metrics['transfer_out_count'].sum()
            }
            
            fig_pie = px.pie(
                values=list(tx_types_total.values()),
                names=list(tx_types_total.keys()),
                title="Distribution Globale des Types de Transactions"
            )
            st.plotly_chart(fig_pie, use_container_width=True)
        
        with col2:
            # Histogramme du ratio buy/sell
            fig_hist = px.histogram(
                combined_metrics[combined_metrics['buy_sell_ratio'] < 10],  # Filtrer les outliers
                x='buy_sell_ratio',
                nbins=20,
                title="Distribution du Ratio Buy/Sell",
                labels={'buy_sell_ratio': 'Ratio Buy/Sell', 'count': 'Nombre de Wallets'}
            )
            st.plotly_chart(fig_hist, use_container_width=True)
        
        # Tableaux des top traders
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("🔥 Top Buyers")
            top_buyers = combined_metrics.nlargest(10, 'buy_count')[
                ['wallet_address', 'buy_count', 'sell_count', 'buy_rate']
            ]
            st.dataframe(top_buyers.round(3))
        
        with col2:
            st.subheader("📉 Top Sellers") 
            top_sellers = combined_metrics.nlargest(10, 'sell_count')[
                ['wallet_address', 'buy_count', 'sell_count', 'sell_rate']
            ]
            st.dataframe(top_sellers.round(3))

if __name__ == "__main__":
    main()