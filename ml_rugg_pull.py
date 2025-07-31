import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, roc_auc_score
from sklearn.preprocessing import StandardScaler
import sqlite3

class RugPullPredictor:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.model = None
        self.scaler = StandardScaler()
        self.feature_names = []
        
    def extract_features(self, address: str = None, df: pd.DataFrame = None) -> pd.DataFrame:
        """
        Extrait les features pour la prédiction de rug pull
        """
        if df is None:
            conn = sqlite3.connect(self.db_path)
            if address:
                query = "SELECT * FROM tokens_hist WHERE address = ? ORDER BY snapshot_timestamp"
                df = pd.read_sql_query(query, conn, params=(address,))
            else:
                query = "SELECT * FROM tokens_hist ORDER BY address, snapshot_timestamp"
                df = pd.read_sql_query(query, conn)
            conn.close()
        
        features_list = []
        
        for addr in df['address'].unique():
            token_data = df[df['address'] == addr].sort_values('snapshot_timestamp')
            
            if len(token_data) < 1:
                continue
                
            latest = token_data.iloc[-1]
            
            # Features de base
            features = {
                'address': addr,
                
                # === FEATURES DE RISQUE ÉLEVÉ ===
                # Distribution et concentration
                'holders_count': latest.get('holders', 0) or 0,
                'holders_very_low': 1 if (latest.get('holders', 0) or 0) <= 5 else 0,
                'holders_low': 1 if (latest.get('holders', 0) or 0) <= 20 else 0,
                
                # Market cap et liquidité
                'market_cap': latest.get('market_cap', 0) or 0,
                'market_cap_very_low': 1 if (latest.get('market_cap', 0) or 0) < 1000 else 0,
                'liquidity_usd': latest.get('liquidity_usd', 0) or 0,
                'has_liquidity_data': 1 if (latest.get('liquidity_usd', 0) or 0) > 0 else 0,
                
                # Âge du token
                'age_hours': latest.get('age_hours', 0) or 0,
                'age_very_new': 1 if (latest.get('age_hours', 0) or 0) < 24 else 0,
                'age_new': 1 if (latest.get('age_hours', 0) or 0) < 168 else 0,  # 1 semaine
                
                # === FEATURES D'ACTIVITÉ ===
                # Volume et transactions
                'volume_24h': latest.get('volume_24h', 0) or 0,
                'volume_zero': 1 if (latest.get('volume_24h', 0) or 0) == 0 else 0,
                'dexscreener_txns_24h': latest.get('dexscreener_txns_24h', 0) or 0,
                'txns_zero': 1 if (latest.get('dexscreener_txns_24h', 0) or 0) == 0 else 0,
                
                # Ratio achats/ventes
                'buys_24h': latest.get('dexscreener_buys_24h', 0) or 0,
                'sells_24h': latest.get('dexscreener_sells_24h', 0) or 0,
                'only_sells': 1 if ((latest.get('dexscreener_sells_24h', 0) or 0) > 0 and 
                                   (latest.get('dexscreener_buys_24h', 0) or 0) == 0) else 0,
                
                # === FEATURES DE PRIX ===
                'price_usd': latest.get('price_usdc', 0) or latest.get('dexscreener_price_usd', 0) or 0,
                'price_change_24h': latest.get('price_change_24h', 0) or 0,
                'price_massive_drop': 1 if (latest.get('price_change_24h', 0) or 0) <= -80 else 0,
                'price_big_drop': 1 if (latest.get('price_change_24h', 0) or 0) <= -50 else 0,
                
                # === FEATURES ÉVOLUTIVES (si historique disponible) ===
                'snapshots_count': len(token_data),
                'data_continuity': len(token_data) / max(1, (latest.get('age_hours', 1) or 1) / 24),  # snapshots par jour
            }
            
            # Features évolutives si on a plusieurs points de données
            if len(token_data) >= 2:
                first = token_data.iloc[0]
                
                # Évolution des holders
                first_holders = first.get('holders', 0) or 0
                latest_holders = latest.get('holders', 0) or 0
                if first_holders > 0:
                    features['holders_evolution'] = (latest_holders - first_holders) / first_holders
                    features['holders_declining'] = 1 if features['holders_evolution'] < -0.2 else 0
                else:
                    features['holders_evolution'] = 0
                    features['holders_declining'] = 0
                
                # Évolution du prix
                first_price = first.get('price_usdc', 0) or first.get('dexscreener_price_usd', 0) or 0
                latest_price = latest.get('price_usdc', 0) or latest.get('dexscreener_price_usd', 0) or 0
                if first_price > 0:
                    features['total_price_evolution'] = (latest_price - first_price) / first_price
                    features['price_severe_decline'] = 1 if features['total_price_evolution'] <= -0.9 else 0
                else:
                    features['total_price_evolution'] = 0
                    features['price_severe_decline'] = 0
                
                # Évolution du volume
                first_volume = first.get('volume_24h', 0) or 0
                latest_volume = latest.get('volume_24h', 0) or 0
                if first_volume > 0:
                    features['volume_evolution'] = (latest_volume - first_volume) / first_volume
                    features['volume_died'] = 1 if features['volume_evolution'] <= -0.8 else 0
                else:
                    features['volume_evolution'] = 0
                    features['volume_died'] = 0
            else:
                # Valeurs par défaut si pas assez de données
                features.update({
                    'holders_evolution': 0,
                    'holders_declining': 0,
                    'total_price_evolution': 0,
                    'price_severe_decline': 0,
                    'volume_evolution': 0,
                    'volume_died': 0
                })
            
            # === SCORE DE RISQUE COMPOSITE ===
            risk_factors = [
                features['holders_very_low'],
                features['market_cap_very_low'],
                features['volume_zero'],
                features['txns_zero'],
                features['only_sells'],
                features['price_massive_drop'],
                features['holders_declining'],
                features['price_severe_decline'],
                features['volume_died']
            ]
            features['risk_score'] = sum(risk_factors)
            features['high_risk'] = 1 if features['risk_score'] >= 4 else 0
            
            features_list.append(features)
        
        return pd.DataFrame(features_list)
    
    def prepare_training_data_from_sql_classification(self) -> tuple:
        """
        Utilise les classifications SQL existantes comme labels d'entraînement
        SUSPECT + TRÈS SUSPECT = rug pulls (1)
        ATTENTION + OK = pas rug pulls (0)
        """
        conn = sqlite3.connect(self.db_path)
        
        # Requête qui reprend votre logique SQL de classification
        query = """
        WITH latest_token_data AS (
            SELECT 
                address, symbol, name, price_usdc, market_cap, dexscreener_price_usd, 
                dexscreener_market_cap, price_change_24h, dexscreener_price_change_h24, 
                dexscreener_price_change_6h, dexscreener_price_change_1h, volume_24h, 
                dexscreener_volume_24h, dexscreener_txns_24h, dexscreener_buys_24h, 
                dexscreener_sells_24h, age_hours, holders, rug_score, quality_score
            FROM tokens_hist
            WHERE snapshot_timestamp = (
                SELECT MAX(snapshot_timestamp) 
                FROM tokens_hist t2 
                WHERE t2.address = tokens_hist.address
            )
        ),
        rug_indicators AS (
            SELECT *,
                CASE WHEN price_change_24h <= -80 OR dexscreener_price_change_h24 <= -80 THEN 1 ELSE 0 END as massive_price_drop,
                CASE WHEN (volume_24h IS NULL OR volume_24h = 0) AND (dexscreener_volume_24h IS NULL OR dexscreener_volume_24h = 0) THEN 1 ELSE 0 END as zero_volume,
                CASE WHEN (dexscreener_txns_24h IS NULL OR dexscreener_txns_24h = 0) THEN 1 ELSE 0 END as zero_transactions,
                CASE WHEN holders IS NOT NULL AND holders <= 10 THEN 1 ELSE 0 END as very_few_holders,
                CASE WHEN age_hours > 24 AND (market_cap < 1000 OR dexscreener_market_cap < 1000) THEN 1 ELSE 0 END as dead_low_mcap,
                CASE WHEN dexscreener_sells_24h > 0 AND dexscreener_buys_24h = 0 THEN 1 ELSE 0 END as only_sells_no_buys
            FROM latest_token_data
        ),
        classified_tokens AS (
            SELECT 
                address, symbol, name, price_usdc, market_cap, dexscreener_price_usd, 
                dexscreener_market_cap, price_change_24h, volume_24h, dexscreener_volume_24h, 
                dexscreener_txns_24h, dexscreener_buys_24h, dexscreener_sells_24h, 
                age_hours, holders,
                (massive_price_drop + zero_volume + zero_transactions + very_few_holders + dead_low_mcap + only_sells_no_buys) as rug_indicators_count,
                CASE 
                    WHEN (massive_price_drop + zero_volume + zero_transactions + very_few_holders + dead_low_mcap + only_sells_no_buys) >= 4 THEN 'TRÈS SUSPECT'
                    WHEN (massive_price_drop + zero_volume + zero_transactions + very_few_holders + dead_low_mcap + only_sells_no_buys) >= 3 THEN 'SUSPECT'
                    WHEN (massive_price_drop + zero_volume + zero_transactions + very_few_holders + dead_low_mcap + only_sells_no_buys) >= 2 THEN 'ATTENTION'
                    ELSE 'OK'
                END as rug_classification
            FROM rug_indicators
        )
        SELECT * FROM classified_tokens
        """
        
        df = pd.read_sql_query(query, conn)
        conn.close()
        
        # Création des labels binaires
        # SUSPECT + TRÈS SUSPECT = 1 (rug pull)
        # ATTENTION + OK = 0 (pas rug pull)
        df['is_rug_pull'] = (
            (df['rug_classification'] == 'SUSPECT') | 
            (df['rug_classification'] == 'TRÈS SUSPECT')
        ).astype(int)
        
        # Statistiques
        positive_count = df['is_rug_pull'].sum()
        total_count = len(df)
        
        print(f"=== LABELS D'ENTRAÎNEMENT ===")
        print(f"Total tokens: {total_count}")
        print(f"Rug pulls (SUSPECT + TRÈS SUSPECT): {positive_count} ({positive_count/total_count*100:.1f}%)")
        print(f"Sains (ATTENTION + OK): {total_count - positive_count} ({(total_count-positive_count)/total_count*100:.1f}%)")
        
        # Détail par catégorie
        print(f"\nDétail:")
        for cat in ['TRÈS SUSPECT', 'SUSPECT', 'ATTENTION', 'OK']:
            count = (df['rug_classification'] == cat).sum()
            print(f"  {cat}: {count} tokens ({count/total_count*100:.1f}%)")
        
        # Préparation des features
        feature_cols = [
            'price_usdc', 'market_cap', 'dexscreener_price_usd', 'dexscreener_market_cap',
            'price_change_24h', 'volume_24h', 'dexscreener_volume_24h', 'dexscreener_txns_24h',
            'dexscreener_buys_24h', 'dexscreener_sells_24h', 'age_hours', 'holders', 'rug_indicators_count'
        ]
        
        # Gestion des valeurs manquantes
        for col in feature_cols:
            if col in df.columns:
                df[col] = df[col].fillna(0)
        
        # Ajout de features calculées
        df['volume_ratio'] = np.where(df['dexscreener_volume_24h'] > 0, 
                                    df['volume_24h'] / df['dexscreener_volume_24h'], 0)
        df['buy_sell_ratio'] = np.where(df['dexscreener_sells_24h'] > 0, 
                                      df['dexscreener_buys_24h'] / df['dexscreener_sells_24h'], 
                                      np.where(df['dexscreener_buys_24h'] > 0, 10, 0))  # 10 si que des achats
        df['market_cap_age_ratio'] = np.where(df['age_hours'] > 0, 
                                            df['market_cap'] / df['age_hours'], 0)
        df['holders_per_mcap'] = np.where(df['market_cap'] > 0, 
                                        df['holders'] / df['market_cap'] * 1000, 0)  # holders per 1000$ mcap
        
        # Features finales
        feature_cols_extended = feature_cols + ['volume_ratio', 'buy_sell_ratio', 'market_cap_age_ratio', 'holders_per_mcap']
        
        X = df[feature_cols_extended]
        y = df['is_rug_pull']
        
        self.feature_names = feature_cols_extended
        
        return X, y, df
    
    def predict_rug_probability_from_sql(self, address: str) -> dict:
        """
        Version adaptée pour les données SQL
        """
        if self.model is None:
            raise ValueError("Le modèle n'est pas encore entraîné!")
        
        conn = sqlite3.connect(self.db_path)
        
        # Récupération des données du token avec la même logique SQL
        query = """
        WITH latest_token_data AS (
            SELECT 
                address, symbol, name, price_usdc, market_cap, dexscreener_price_usd, 
                dexscreener_market_cap, price_change_24h, volume_24h, dexscreener_volume_24h, 
                dexscreener_txns_24h, dexscreener_buys_24h, dexscreener_sells_24h, 
                age_hours, holders
            FROM tokens_hist
            WHERE address = ? AND snapshot_timestamp = (
                SELECT MAX(snapshot_timestamp) 
                FROM tokens_hist t2 
                WHERE t2.address = tokens_hist.address
            )
        ),
        rug_indicators AS (
            SELECT *,
                CASE WHEN price_change_24h <= -80 THEN 1 ELSE 0 END as massive_price_drop,
                CASE WHEN (volume_24h IS NULL OR volume_24h = 0) AND (dexscreener_volume_24h IS NULL OR dexscreener_volume_24h = 0) THEN 1 ELSE 0 END as zero_volume,
                CASE WHEN (dexscreener_txns_24h IS NULL OR dexscreener_txns_24h = 0) THEN 1 ELSE 0 END as zero_transactions,
                CASE WHEN holders IS NOT NULL AND holders <= 10 THEN 1 ELSE 0 END as very_few_holders,
                CASE WHEN age_hours > 24 AND (market_cap < 1000) THEN 1 ELSE 0 END as dead_low_mcap,
                CASE WHEN dexscreener_sells_24h > 0 AND dexscreener_buys_24h = 0 THEN 1 ELSE 0 END as only_sells_no_buys
            FROM latest_token_data
        )
        SELECT 
            *,
            (massive_price_drop + zero_volume + zero_transactions + very_few_holders + dead_low_mcap + only_sells_no_buys) as rug_indicators_count,
            CASE 
                WHEN (massive_price_drop + zero_volume + zero_transactions + very_few_holders + dead_low_mcap + only_sells_no_buys) >= 4 THEN 'TRÈS SUSPECT'
                WHEN (massive_price_drop + zero_volume + zero_transactions + very_few_holders + dead_low_mcap + only_sells_no_buys) >= 3 THEN 'SUSPECT'
                WHEN (massive_price_drop + zero_volume + zero_transactions + very_few_holders + dead_low_mcap + only_sells_no_buys) >= 2 THEN 'ATTENTION'
                ELSE 'OK'
            END as sql_classification
        FROM rug_indicators
        """
        
        result = pd.read_sql_query(query, conn, params=(address,))
        conn.close()
        
        if result.empty:
            return {"error": f"Aucune donnée trouvée pour {address}"}
        
        token_data = result.iloc[0]
        
        # Préparation des features avec noms (pour éviter le warning)
        feature_values = [
            token_data.get('price_usdc', 0) or 0,
            token_data.get('market_cap', 0) or 0,
            token_data.get('dexscreener_price_usd', 0) or 0,
            token_data.get('dexscreener_market_cap', 0) or 0,
            token_data.get('price_change_24h', 0) or 0,
            token_data.get('volume_24h', 0) or 0,
            token_data.get('dexscreener_volume_24h', 0) or 0,
            token_data.get('dexscreener_txns_24h', 0) or 0,
            token_data.get('dexscreener_buys_24h', 0) or 0,
            token_data.get('dexscreener_sells_24h', 0) or 0,
            token_data.get('age_hours', 0) or 0,
            token_data.get('holders', 0) or 0,
            token_data.get('rug_indicators_count', 0) or 0,
        ]
        
        # Features calculées
        volume_ratio = feature_values[5] / feature_values[6] if feature_values[6] > 0 else 0
        buy_sell_ratio = feature_values[8] / feature_values[9] if feature_values[9] > 0 else (10 if feature_values[8] > 0 else 0)
        market_cap_age_ratio = feature_values[1] / feature_values[10] if feature_values[10] > 0 else 0
        holders_per_mcap = feature_values[11] / feature_values[1] * 1000 if feature_values[1] > 0 else 0
        
        feature_values.extend([volume_ratio, buy_sell_ratio, market_cap_age_ratio, holders_per_mcap])
        
        # Créer DataFrame avec les bons noms de colonnes
        X = pd.DataFrame([feature_values], columns=self.feature_names)
        X_scaled = self.model['scaler'].transform(X)
        
        # Prédictions
        rf_prob = self.model['rf'].predict_proba(X_scaled)[0][1]
        gb_prob = self.model['gb'].predict_proba(X_scaled)[0][1]
        ensemble_prob = (rf_prob + gb_prob) / 2
        
        # Classification
        if ensemble_prob >= 0.8:
            risk_level = "TRÈS ÉLEVÉ" 
        elif ensemble_prob >= 0.6:
            risk_level = "ÉLEVÉ"
        elif ensemble_prob >= 0.4:
            risk_level = "MODÉRÉ"
        else:
            risk_level = "FAIBLE"
        
        return {
            "address": address,
            "symbol": token_data.get('symbol', 'N/A'),
            "rug_probability": round(ensemble_prob, 3),
            "risk_level": risk_level,
            "sql_classification": token_data.get('sql_classification', 'N/A'),
            "rug_indicators_count": int(token_data.get('rug_indicators_count', 0)),
            "model_vs_sql": {
                "model_prob": round(ensemble_prob, 3),
                "sql_category": token_data.get('sql_classification', 'N/A'),
                "agreement": "OUI" if (
                    (ensemble_prob >= 0.5 and token_data.get('sql_classification') in ['SUSPECT', 'TRÈS SUSPECT']) or
                    (ensemble_prob < 0.5 and token_data.get('sql_classification') in ['OK', 'ATTENTION'])
                ) else "NON"
            },
            "key_factors": {
                "holders": int(token_data.get('holders', 0) or 0),
                "market_cap": round(token_data.get('market_cap', 0) or 0, 2),
                "age_hours": round(token_data.get('age_hours', 0) or 0, 1),
                "volume_24h": round(token_data.get('volume_24h', 0) or 0, 2),
                "price_change_24h": round(token_data.get('price_change_24h', 0) or 0, 2)
            }
        }


    def add_ml_score_column_if_not_exists(self):
        """
        Ajoute la colonne ml_rug_score à la table tokens si elle n'existe pas
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Vérifier si la colonne existe
        cursor.execute("PRAGMA table_info(tokens)")
        columns = [row[1] for row in cursor.fetchall()]
        
        if 'ml_rug_score' not in columns:
            print("Ajout de la colonne ml_rug_score à la table tokens...")
            cursor.execute("ALTER TABLE tokens ADD COLUMN ml_rug_score REAL DEFAULT NULL")
            conn.commit()
            print("✅ Colonne ml_rug_score ajoutée avec succès")
        else:
            print("✅ Colonne ml_rug_score existe déjà")
        
        conn.close()


    def predict_and_update_tokens_table(self):
        """
        Prédit les scores ML pour tous les tokens de la table 'tokens' 
        et met à jour la colonne ml_rug_score
        """
        if self.model is None:
            raise ValueError("Le modèle doit être entraîné avant de faire des prédictions!")
        
        # Ajouter la colonne si nécessaire
        self.add_ml_score_column_if_not_exists()
        
        conn = sqlite3.connect(self.db_path)
        
        # Récupérer tous les tokens de la table 'tokens'
        print("Récupération des tokens depuis la table 'tokens'...")
        
        query_tokens = """
        SELECT 
            address, symbol, name, price_usdc, market_cap, 
            price_change_24h, volume_24h, age_hours, holders
        FROM tokens
        """
        
        tokens_df = pd.read_sql_query(query_tokens, conn)
        print(f"📊 {len(tokens_df)} tokens trouvés dans la table 'tokens'")
        
        # Pour chaque token, récupérer les données DexScreener depuis tokens_hist (si disponibles)
        predictions = []
        
        for i, token in tokens_df.iterrows():
            if i % 500 == 0:
                print(f"Progression: {i}/{len(tokens_df)}")
            
            address = token['address']
            
            # Récupérer les données DexScreener les plus récentes depuis tokens_hist
            dex_query = """
            SELECT 
                dexscreener_price_usd, dexscreener_market_cap, dexscreener_volume_24h,
                dexscreener_txns_24h, dexscreener_buys_24h, dexscreener_sells_24h,
                dexscreener_price_change_h24
            FROM tokens_hist 
            WHERE address = ? 
            ORDER BY snapshot_timestamp DESC 
            LIMIT 1
            """
            
            dex_data = pd.read_sql_query(dex_query, conn, params=(address,))
            
            # Combiner les données tokens + tokens_hist
            combined_features = {
                'price_usdc': token.get('price_usdc', 0) or 0,
                'market_cap': token.get('market_cap', 0) or 0,
                'price_change_24h': token.get('price_change_24h', 0) or 0,
                'volume_24h': token.get('volume_24h', 0) or 0,
                'age_hours': token.get('age_hours', 0) or 0,
                'holders': token.get('holders', 0) or 0,
            }
            
            # Ajouter les données DexScreener si disponibles
            if not dex_data.empty:
                dex_row = dex_data.iloc[0]
                combined_features.update({
                    'dexscreener_price_usd': dex_row.get('dexscreener_price_usd', 0) or 0,
                    'dexscreener_market_cap': dex_row.get('dexscreener_market_cap', 0) or 0,
                    'dexscreener_volume_24h': dex_row.get('dexscreener_volume_24h', 0) or 0,
                    'dexscreener_txns_24h': dex_row.get('dexscreener_txns_24h', 0) or 0,
                    'dexscreener_buys_24h': dex_row.get('dexscreener_buys_24h', 0) or 0,
                    'dexscreener_sells_24h': dex_row.get('dexscreener_sells_24h', 0) or 0,
                })
                # Utiliser le price_change de DexScreener si disponible
                if dex_row.get('dexscreener_price_change_h24'):
                    combined_features['price_change_24h'] = dex_row.get('dexscreener_price_change_h24', 0) or 0
            else:
                # Valeurs par défaut si pas de données DexScreener
                combined_features.update({
                    'dexscreener_price_usd': 0,
                    'dexscreener_market_cap': 0,
                    'dexscreener_volume_24h': 0,
                    'dexscreener_txns_24h': 0,
                    'dexscreener_buys_24h': 0,
                    'dexscreener_sells_24h': 0,
                })
            
            # Calculer les indicateurs de rug (même logique que l'entraînement)
            rug_indicators_count = (
                (1 if combined_features['price_change_24h'] <= -80 else 0) +
                (1 if (combined_features['volume_24h'] == 0 and combined_features['dexscreener_volume_24h'] == 0) else 0) +
                (1 if combined_features['dexscreener_txns_24h'] == 0 else 0) +
                (1 if combined_features['holders'] != 0 and combined_features['holders'] <= 10 else 0) +
                (1 if combined_features['age_hours'] > 24 and combined_features['market_cap'] < 1000 else 0) +
                (1 if combined_features['dexscreener_sells_24h'] > 0 and combined_features['dexscreener_buys_24h'] == 0 else 0)
            )
            
            combined_features['rug_indicators_count'] = rug_indicators_count
            
            # Features calculées
            volume_ratio = (combined_features['volume_24h'] / combined_features['dexscreener_volume_24h'] 
                          if combined_features['dexscreener_volume_24h'] > 0 else 0)
            buy_sell_ratio = (combined_features['dexscreener_buys_24h'] / combined_features['dexscreener_sells_24h'] 
                             if combined_features['dexscreener_sells_24h'] > 0 
                             else (10 if combined_features['dexscreener_buys_24h'] > 0 else 0))
            market_cap_age_ratio = (combined_features['market_cap'] / combined_features['age_hours'] 
                                  if combined_features['age_hours'] > 0 else 0)
            holders_per_mcap = (combined_features['holders'] / combined_features['market_cap'] * 1000 
                              if combined_features['market_cap'] > 0 else 0)
            
            # Préparer les features pour le modèle
            feature_values = [
                combined_features['price_usdc'],
                combined_features['market_cap'],
                combined_features['dexscreener_price_usd'],
                combined_features['dexscreener_market_cap'],
                combined_features['price_change_24h'],
                combined_features['volume_24h'],
                combined_features['dexscreener_volume_24h'],
                combined_features['dexscreener_txns_24h'],
                combined_features['dexscreener_buys_24h'],
                combined_features['dexscreener_sells_24h'],
                combined_features['age_hours'],
                combined_features['holders'],
                combined_features['rug_indicators_count'],
                volume_ratio,
                buy_sell_ratio,
                market_cap_age_ratio,
                holders_per_mcap
            ]
            
            # Prédiction ML
            try:
                X = pd.DataFrame([feature_values], columns=self.feature_names)
    
                # AJOUT : Remplacer les NaN par 0
                X = X.fillna(0)
                X_scaled = self.model['scaler'].transform(X)
                
                rf_prob = self.model['rf'].predict_proba(X_scaled)[0][1]
                gb_prob = self.model['gb'].predict_proba(X_scaled)[0][1]
                ml_score = (rf_prob + gb_prob) / 2
                
            except Exception as e:
                print(f"Erreur prédiction pour {address}: {e}")
                ml_score = 0.0
            
            predictions.append({
                'address': address,
                'symbol': token.get('symbol', 'N/A'),
                'ml_rug_score': round(ml_score, 4),
                'has_dex_data': not dex_data.empty
            })
        
        # Mise à jour de la base de données
        print(f"\n📝 Mise à jour de la table tokens avec les scores ML...")
        
        cursor = conn.cursor()
        
        for pred in predictions:
            cursor.execute("""
                UPDATE tokens 
                SET ml_rug_score = ? 
                WHERE address = ?
            """, (pred['ml_rug_score'], pred['address']))
        
        conn.commit()
        conn.close()
        
        # Statistiques finales
        scores = [p['ml_rug_score'] for p in predictions]
        with_dex_data = sum(1 for p in predictions if p['has_dex_data'])
        
        print(f"\n=== RÉSULTATS ===")
        print(f"✅ {len(predictions)} tokens mis à jour")
        print(f"📊 {with_dex_data} tokens avec données DexScreener ({with_dex_data/len(predictions)*100:.1f}%)")
        print(f"📈 Score ML moyen: {np.mean(scores):.3f}")
        print(f"📈 Scores > 0.5 (suspects): {sum(1 for s in scores if s > 0.5)} tokens")
        print(f"📈 Scores > 0.8 (très suspects): {sum(1 for s in scores if s > 0.8)} tokens")
        
        # Top 10 des tokens les plus suspects
        top_suspects = sorted(predictions, key=lambda x: x['ml_rug_score'], reverse=True)[:10]
        print(f"\n🚨 TOP 10 TOKENS LES PLUS SUSPECTS:")
        for i, token in enumerate(top_suspects, 1):
            print(f"  {i}. {token['symbol']} ({token['address'][:8]}...): {token['ml_rug_score']:.3f}")
        
        return predictions

    def train_model_with_sql_labels(self):
        """
        Entraîne le modèle en utilisant les classifications SQL comme labels
        """
        print("Chargement des données avec classifications SQL...")
        X, y, full_df = self.prepare_training_data_from_sql_classification()
        
        if y.sum() < 2:
            raise ValueError("Pas assez d'exemples positifs pour l'entraînement")
        
        # Séparation train/test avec stratification
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42, stratify=y
        )
        
        print(f"Train: {len(X_train)} samples ({y_train.sum()} positifs)")
        print(f"Test: {len(X_test)} samples ({y_test.sum()} positifs)")
        
        # Normalisation
        X_train_scaled = self.scaler.fit_transform(X_train)
        X_test_scaled = self.scaler.transform(X_test)
        
        # Modèles
        rf_model = RandomForestClassifier(
            n_estimators=200,
            max_depth=12,
            min_samples_split=5,
            min_samples_leaf=2,
            random_state=42,
            class_weight='balanced'  # Important pour les classes déséquilibrées
        )
        
        gb_model = GradientBoostingClassifier(
            n_estimators=200,
            max_depth=8,
            learning_rate=0.1,
            random_state=42
        )
        
        print("Entraînement des modèles...")
        rf_model.fit(X_train_scaled, y_train)
        gb_model.fit(X_train_scaled, y_train)
        
        # Prédictions
        rf_pred_proba = rf_model.predict_proba(X_test_scaled)[:, 1]
        gb_pred_proba = gb_model.predict_proba(X_test_scaled)[:, 1]
        
        # Ensemble
        ensemble_pred_proba = (rf_pred_proba + gb_pred_proba) / 2
        ensemble_pred = (ensemble_pred_proba > 0.5).astype(int)
        
        # Stockage
        self.model = {
            'rf': rf_model,
            'gb': gb_model,
            'scaler': self.scaler
        }
        
        # Évaluation détaillée
        print("\n=== ÉVALUATION DU MODÈLE ===")
        print(f"ROC AUC Score: {roc_auc_score(y_test, ensemble_pred_proba):.3f}")
        print(f"Accuracy: {(ensemble_pred == y_test).mean():.3f}")
        
        print("\nRapport de classification:")
        print(classification_report(y_test, ensemble_pred, 
                                  target_names=['Sain', 'Rug Pull']))
        
        # Importance des features
        feature_importance = pd.DataFrame({
            'feature': self.feature_names,
            'importance_rf': rf_model.feature_importances_,
            'importance_gb': gb_model.feature_importances_
        })
        feature_importance['importance_avg'] = (
            feature_importance['importance_rf'] + feature_importance['importance_gb']
        ) / 2
        
        print("\n=== TOP 10 FEATURES IMPORTANTES ===")
        top_features = feature_importance.nlargest(10, 'importance_avg')
        for _, row in top_features.iterrows():
            print(f"{row['feature']}: {row['importance_avg']:.3f}")
        
        return self.model
        
        # Features pour le modèle (exclure address et target)
        feature_cols = [col for col in df.columns if col not in ['address', target_column]]
        
        X = df[feature_cols]
        y = df[target_column]
        
        self.feature_names = feature_cols
        
        return X, y
    
    def train_model(self, X: pd.DataFrame, y: pd.Series):
        """
        Entraîne le modèle de prédiction
        """
        # Séparation train/test
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42, stratify=y
        )
        
        # Normalisation
        X_train_scaled = self.scaler.fit_transform(X_train)
        X_test_scaled = self.scaler.transform(X_test)
        
        # Modèle ensemble (Random Forest + Gradient Boosting)
        rf_model = RandomForestClassifier(
            n_estimators=100,
            max_depth=10,
            random_state=42,
            class_weight='balanced'
        )
        
        gb_model = GradientBoostingClassifier(
            n_estimators=100,
            max_depth=6,
            random_state=42
        )
        
        # Entraînement
        rf_model.fit(X_train_scaled, y_train)
        gb_model.fit(X_train_scaled, y_train)
        
        # Prédictions
        rf_pred = rf_model.predict_proba(X_test_scaled)[:, 1]
        gb_pred = gb_model.predict_proba(X_test_scaled)[:, 1]
        
        # Ensemble (moyenne des deux modèles)
        ensemble_pred = (rf_pred + gb_pred) / 2
        ensemble_pred_binary = (ensemble_pred > 0.5).astype(int)
        
        # Stockage du modèle ensemble
        self.model = {
            'rf': rf_model,
            'gb': gb_model,
            'scaler': self.scaler
        }
        
        # Évaluation
        print("=== ÉVALUATION DU MODÈLE ===")
        print(f"ROC AUC Score: {roc_auc_score(y_test, ensemble_pred):.3f}")
        print("\nRapport de classification:")
        print(classification_report(y_test, ensemble_pred_binary))
        
        # Importance des features
        feature_importance = pd.DataFrame({
            'feature': self.feature_names,
            'importance_rf': rf_model.feature_importances_,
            'importance_gb': gb_model.feature_importances_
        })
        feature_importance['importance_avg'] = (
            feature_importance['importance_rf'] + feature_importance['importance_gb']
        ) / 2
        
        print("\n=== TOP 10 FEATURES IMPORTANTES ===")
        print(feature_importance.nlargest(10, 'importance_avg')[['feature', 'importance_avg']])
        
        return self.model
    
    def predict_rug_probability(self, address: str) -> dict:
        """
        Prédit la probabilité de rug pull pour un token donné
        """
        if self.model is None:
            raise ValueError("Le modèle n'est pas encore entraîné!")
        
        # Extraction des features
        features_df = self.extract_features(address=address)
        
        if features_df.empty:
            return {"error": "Aucune donnée trouvée pour cette adresse"}
        
        # Prédiction
        features_row = features_df.iloc[0]
        X = features_row[self.feature_names].values.reshape(1, -1)
        X_scaled = self.model['scaler'].transform(X)
        
        # Prédictions des deux modèles
        rf_prob = self.model['rf'].predict_proba(X_scaled)[0][1]
        gb_prob = self.model['gb'].predict_proba(X_scaled)[0][1]
        ensemble_prob = (rf_prob + gb_prob) / 2
        
        # Classification
        risk_level = "FAIBLE"
        if ensemble_prob >= 0.8:
            risk_level = "TRÈS ÉLEVÉ"
        elif ensemble_prob >= 0.6:
            risk_level = "ÉLEVÉ"
        elif ensemble_prob >= 0.4:
            risk_level = "MODÉRÉ"
        
        return {
            "address": address,
            "symbol": features_row.get('symbol', 'N/A'),
            "rug_probability": round(ensemble_prob, 3),
            "risk_level": risk_level,
            "risk_score": int(features_row['risk_score']),
            "key_factors": {
                "holders": int(features_row['holders_count']),
                "market_cap": round(features_row['market_cap'], 2),
                "age_hours": round(features_row['age_hours'], 1),
                "volume_24h": round(features_row['volume_24h'], 2),
                "price_change_24h": round(features_row['price_change_24h'], 2)
            }
        }

# Exemple d'utilisation avec classifications SQL
def example_usage_with_sql():
    """
    Exemple d'utilisation avec les classifications SQL existantes
    """
    predictor = RugPullPredictor("tokens.db")
    
    # Entraînement avec les labels SQL
    print("=== ENTRAÎNEMENT AVEC CLASSIFICATIONS SQL ===")
    predictor.train_model_with_sql_labels()
    
    # Prédiction et mise à jour de la table tokens
    print("\n=== PRÉDICTION ET MISE À JOUR DE LA TABLE TOKENS ===")
    predictions = predictor.predict_and_update_tokens_table()
    
    # Vérification des résultats
    print("\n=== VÉRIFICATION DES RÉSULTATS ===")
    conn = sqlite3.connect(predictor.db_path)
    
    # Requête pour voir les tokens les plus suspects
    verification_query = """
    SELECT 
        address, symbol, name, ml_rug_score,
        CASE 
            WHEN ml_rug_score >= 0.8 THEN '🚨 TRÈS SUSPECT'
            WHEN ml_rug_score >= 0.6 THEN '⚠️ SUSPECT'
            WHEN ml_rug_score >= 0.4 THEN '⚠️ ATTENTION'
            WHEN ml_rug_score >= 0.2 THEN '⚠️ SURVEILLANCE'
            ELSE '✅ OK'
        END as risk_category,
        market_cap, holders, age_hours
    FROM tokens 
    WHERE ml_rug_score IS NOT NULL
    ORDER BY ml_rug_score DESC
    LIMIT 20
    """
    
    results = pd.read_sql_query(verification_query, conn)
    conn.close()
    
    print("\n=== TOP 20 TOKENS PAR SCORE ML ===")
    for _, row in results.iterrows():
        print(f"{row['symbol']:<10} | Score: {row['ml_rug_score']:.3f} | {row['risk_category']}")
    
    print(f"\n✅ Processus terminé ! Colonne ml_rug_score mise à jour pour tous les tokens.")

    

if __name__ == "__main__":
    example_usage_with_sql()