import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, roc_auc_score
from sklearn.preprocessing import StandardScaler
import sqlite3

class RugPullPredictorWithRugCheck:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.model = None
        self.scaler = StandardScaler()
        self.feature_names = []
    
    def prepare_training_data_with_rugcheck(self) -> tuple:
        """
        Utilise les classifications SQL + rug_score RugCheck comme features
        """
        conn = sqlite3.connect(self.db_path)
        
        # Requête qui combine tokens + tokens_hist + rug_score
        query = """
        WITH latest_token_data AS (
            SELECT 
                t.address, t.symbol, t.name, t.rug_score as rugcheck_score,
                th.price_usdc, th.market_cap, th.dexscreener_price_usd, 
                th.dexscreener_market_cap, th.price_change_24h, th.dexscreener_price_change_h24, 
                th.dexscreener_price_change_6h, th.dexscreener_price_change_1h, th.volume_24h, 
                th.dexscreener_volume_24h, th.dexscreener_txns_24h, th.dexscreener_buys_24h, 
                th.dexscreener_sells_24h, th.age_hours, th.holders
            FROM tokens t
            LEFT JOIN tokens_hist th ON t.address = th.address
            WHERE th.snapshot_timestamp = (
                SELECT MAX(snapshot_timestamp) 
                FROM tokens_hist t2 
                WHERE t2.address = t.address
            )
            OR th.snapshot_timestamp IS NULL  -- Inclure les tokens sans historique
        ),
        rug_indicators AS (
            SELECT *,
                CASE WHEN price_change_24h <= -80 OR dexscreener_price_change_h24 <= -80 THEN 1 ELSE 0 END as massive_price_drop,
                CASE WHEN (volume_24h IS NULL OR volume_24h = 0) AND (dexscreener_volume_24h IS NULL OR dexscreener_volume_24h = 0) THEN 1 ELSE 0 END as zero_volume,
                CASE WHEN (dexscreener_txns_24h IS NULL OR dexscreener_txns_24h = 0) THEN 1 ELSE 0 END as zero_transactions,
                CASE WHEN holders IS NOT NULL AND holders <= 10 THEN 1 ELSE 0 END as very_few_holders,
                CASE WHEN age_hours > 24 AND (market_cap < 1000 OR dexscreener_market_cap < 1000) THEN 1 ELSE 0 END as dead_low_mcap,
                CASE WHEN dexscreener_sells_24h > 0 AND dexscreener_buys_24h = 0 THEN 1 ELSE 0 END as only_sells_no_buys,
                -- Features RugCheck
                CASE WHEN rugcheck_score IS NOT NULL AND rugcheck_score <= 20 THEN 1 ELSE 0 END as rugcheck_very_bad,
                CASE WHEN rugcheck_score IS NOT NULL AND rugcheck_score <= 40 THEN 1 ELSE 0 END as rugcheck_bad,
                CASE WHEN rugcheck_score IS NOT NULL AND rugcheck_score >= 80 THEN 1 ELSE 0 END as rugcheck_good
            FROM latest_token_data
        ),
        classified_tokens AS (
            SELECT 
                address, symbol, name, rugcheck_score, price_usdc, market_cap, dexscreener_price_usd, 
                dexscreener_market_cap, price_change_24h, volume_24h, dexscreener_volume_24h, 
                dexscreener_txns_24h, dexscreener_buys_24h, dexscreener_sells_24h, 
                age_hours, holders, rugcheck_very_bad, rugcheck_bad, rugcheck_good,
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
        
        # Création des labels binaires (même logique qu'avant)
        df['is_rug_pull'] = (
            (df['rug_classification'] == 'SUSPECT') | 
            (df['rug_classification'] == 'TRÈS SUSPECT')
        ).astype(int)
        
        # Statistiques avec RugCheck
        rugcheck_available = df['rugcheck_score'].notna().sum()
        total_count = len(df)
        positive_count = df['is_rug_pull'].sum()
        
        print(f"=== DONNÉES D'ENTRAÎNEMENT AVEC RUGCHECK ===")
        print(f"Total tokens: {total_count}")
        print(f"Tokens avec RugCheck score: {rugcheck_available} ({rugcheck_available/total_count*100:.1f}%)")
        print(f"Rug pulls (SUSPECT + TRÈS SUSPECT): {positive_count} ({positive_count/total_count*100:.1f}%)")
        
        # Analyse de corrélation RugCheck vs classification SQL
        if rugcheck_available > 0:
            rugcheck_subset = df[df['rugcheck_score'].notna()]
            very_suspect = rugcheck_subset[rugcheck_subset['rug_classification'] == 'TRÈS SUSPECT']
            suspect = rugcheck_subset[rugcheck_subset['rug_classification'] == 'SUSPECT']
            
            print(f"\n=== CORRÉLATION RUGCHECK vs CLASSIFICATION SQL ===")
            if len(very_suspect) > 0:
                print(f"Score RugCheck moyen (TRÈS SUSPECT): {very_suspect['rugcheck_score'].mean():.1f}")
            if len(suspect) > 0:
                print(f"Score RugCheck moyen (SUSPECT): {suspect['rugcheck_score'].mean():.1f}")
            
            ok_tokens = rugcheck_subset[rugcheck_subset['rug_classification'] == 'OK']
            if len(ok_tokens) > 0:
                print(f"Score RugCheck moyen (OK): {ok_tokens['rugcheck_score'].mean():.1f}")
        
        # Préparation des features avec RugCheck
        feature_cols = [
            'rugcheck_score',  # ← NOUVELLE FEATURE PRINCIPALE
            'rugcheck_very_bad', 'rugcheck_bad', 'rugcheck_good',  # ← Features catégorielles RugCheck
            'price_usdc', 'market_cap', 'dexscreener_price_usd', 'dexscreener_market_cap',
            'price_change_24h', 'volume_24h', 'dexscreener_volume_24h', 'dexscreener_txns_24h',
            'dexscreener_buys_24h', 'dexscreener_sells_24h', 'age_hours', 'holders', 'rug_indicators_count'
        ]
        
        # Gestion des valeurs manquantes
        for col in feature_cols:
            if col in df.columns:
                if col == 'rugcheck_score':
                    # Pour RugCheck, utiliser 50 comme défaut (neutre)
                    df[col] = df[col].fillna(50)
                else:
                    df[col] = df[col].fillna(0)
        
        # Features calculées (mêmes qu'avant)
        df['volume_ratio'] = np.where(df['dexscreener_volume_24h'] > 0, 
                                    df['volume_24h'] / df['dexscreener_volume_24h'], 0)
        df['buy_sell_ratio'] = np.where(df['dexscreener_sells_24h'] > 0, 
                                      df['dexscreener_buys_24h'] / df['dexscreener_sells_24h'], 
                                      np.where(df['dexscreener_buys_24h'] > 0, 10, 0))
        df['market_cap_age_ratio'] = np.where(df['age_hours'] > 0, 
                                            df['market_cap'] / df['age_hours'], 0)
        df['holders_per_mcap'] = np.where(df['market_cap'] > 0, 
                                        df['holders'] / df['market_cap'] * 1000, 0)
        
        # Features supplémentaires avec RugCheck
        df['rugcheck_risk_combined'] = (
            df['rugcheck_very_bad'] * 2 + df['rugcheck_bad'] * 1 - df['rugcheck_good'] * 0.5
        )
        df['rugcheck_vs_market'] = np.where(df['market_cap'] > 0,
                                          df['rugcheck_score'] * df['market_cap'] / 1000000, 0)  # RugCheck * mcap en M$
        
        # Features finales étendues
        feature_cols_extended = feature_cols + [
            'volume_ratio', 'buy_sell_ratio', 'market_cap_age_ratio', 'holders_per_mcap',
            'rugcheck_risk_combined', 'rugcheck_vs_market'
        ]
        
        X = df[feature_cols_extended]
        y = df['is_rug_pull']
        
        self.feature_names = feature_cols_extended
        
        return X, y, df
    
    def train_model_with_rugcheck(self):
        """
        Entraîne le modèle avec les scores RugCheck intégrés
        """
        print("Chargement des données avec scores RugCheck...")
        X, y, full_df = self.prepare_training_data_with_rugcheck()
        
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
        
        # Modèles avec hyperparamètres optimisés pour RugCheck
        rf_model = RandomForestClassifier(
            n_estimators=300,  # Plus d'arbres car on a plus de features
            max_depth=15,
            min_samples_split=5,
            min_samples_leaf=2,
            random_state=42,
            class_weight='balanced'
        )
        
        gb_model = GradientBoostingClassifier(
            n_estimators=300,
            max_depth=10,
            learning_rate=0.08,
            random_state=42
        )
        
        print("Entraînement des modèles...")
        rf_model.fit(X_train_scaled, y_train)
        gb_model.fit(X_train_scaled, y_train)
        
        # Prédictions
        rf_pred_proba = rf_model.predict_proba(X_test_scaled)[:, 1]
        gb_pred_proba = gb_model.predict_proba(X_test_scaled)[:, 1]
        
        # Ensemble pondéré (on peut donner plus de poids à RF car il gère mieux les features catégorielles)
        ensemble_pred_proba = (rf_pred_proba * 0.6 + gb_pred_proba * 0.4)
        ensemble_pred = (ensemble_pred_proba > 0.5).astype(int)
        
        # Stockage
        self.model = {
            'rf': rf_model,
            'gb': gb_model,
            'scaler': self.scaler
        }
        
        # Évaluation détaillée
        print("\n=== ÉVALUATION DU MODÈLE AVEC RUGCHECK ===")
        print(f"ROC AUC Score: {roc_auc_score(y_test, ensemble_pred_proba):.3f}")
        print(f"Accuracy: {(ensemble_pred == y_test).mean():.3f}")
        
        print("\nRapport de classification:")
        print(classification_report(y_test, ensemble_pred, 
                                  target_names=['Sain', 'Rug Pull']))
        
        # Importance des features avec focus sur RugCheck
        feature_importance = pd.DataFrame({
            'feature': self.feature_names,
            'importance_rf': rf_model.feature_importances_,
            'importance_gb': gb_model.feature_importances_
        })
        feature_importance['importance_avg'] = (
            feature_importance['importance_rf'] * 0.6 + feature_importance['importance_gb'] * 0.4
        )
        
        print("\n=== TOP 15 FEATURES IMPORTANTES (avec RugCheck) ===")
        top_features = feature_importance.nlargest(15, 'importance_avg')
        for _, row in top_features.iterrows():
            indicator = "🛡️" if "rugcheck" in row['feature'].lower() else "📊"
            print(f"{indicator} {row['feature']}: {row['importance_avg']:.3f}")
        
        # Analyse spécifique RugCheck
        rugcheck_features = feature_importance[
            feature_importance['feature'].str.contains('rugcheck', case=False)
        ].sort_values('importance_avg', ascending=False)
        
        print(f"\n=== FEATURES RUGCHECK UNIQUEMENT ===")
        for _, row in rugcheck_features.iterrows():
            print(f"🛡️ {row['feature']}: {row['importance_avg']:.3f}")
        
        return self.model
    
    def predict_with_rugcheck(self, address: str) -> dict:
        """
        Prédit avec RugCheck score intégré
        """
        if self.model is None:
            raise ValueError("Le modèle n'est pas encore entraîné!")
        
        conn = sqlite3.connect(self.db_path)
        
        # Récupération avec RugCheck
        query = """
        SELECT 
            t.address, t.symbol, t.name, t.rug_score as rugcheck_score,
            th.price_usdc, th.market_cap, th.dexscreener_price_usd, 
            th.dexscreener_market_cap, th.price_change_24h, th.volume_24h, th.dexscreener_volume_24h, 
            th.dexscreener_txns_24h, th.dexscreener_buys_24h, th.dexscreener_sells_24h, 
            th.age_hours, th.holders, th.dexscreener_price_change_h24
        FROM tokens t
        LEFT JOIN tokens_hist th ON t.address = th.address
        WHERE t.address = ? AND (
            th.snapshot_timestamp = (
                SELECT MAX(snapshot_timestamp) 
                FROM tokens_hist t2 
                WHERE t2.address = t.address
            ) OR th.snapshot_timestamp IS NULL
        )
        """
        
        result = pd.read_sql_query(query, conn, params=(address,))
        conn.close()
        
        if result.empty:
            return {"error": f"Aucune donnée trouvée pour {address}"}
        
        token_data = result.iloc[0]
        
        # Préparation des features avec RugCheck
        rugcheck_score = token_data.get('rugcheck_score', 50) or 50
        
        combined_features = {
            'rugcheck_score': rugcheck_score,
            'rugcheck_very_bad': 1 if rugcheck_score <= 20 else 0,
            'rugcheck_bad': 1 if rugcheck_score <= 40 else 0,
            'rugcheck_good': 1 if rugcheck_score >= 80 else 0,
            'price_usdc': token_data.get('price_usdc', 0) or 0,
            'market_cap': token_data.get('market_cap', 0) or 0,
            'dexscreener_price_usd': token_data.get('dexscreener_price_usd', 0) or 0,
            'dexscreener_market_cap': token_data.get('dexscreener_market_cap', 0) or 0,
            'price_change_24h': token_data.get('price_change_24h', 0) or token_data.get('dexscreener_price_change_h24', 0) or 0,
            'volume_24h': token_data.get('volume_24h', 0) or 0,
            'dexscreener_volume_24h': token_data.get('dexscreener_volume_24h', 0) or 0,
            'dexscreener_txns_24h': token_data.get('dexscreener_txns_24h', 0) or 0,
            'dexscreener_buys_24h': token_data.get('dexscreener_buys_24h', 0) or 0,
            'dexscreener_sells_24h': token_data.get('dexscreener_sells_24h', 0) or 0,
            'age_hours': token_data.get('age_hours', 0) or 0,
            'holders': token_data.get('holders', 0) or 0,
        }
        
        # Calcul rug_indicators_count (même logique)
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
        
        # Features RugCheck avancées
        rugcheck_risk_combined = (
            combined_features['rugcheck_very_bad'] * 2 + 
            combined_features['rugcheck_bad'] * 1 - 
            combined_features['rugcheck_good'] * 0.5
        )
        rugcheck_vs_market = (rugcheck_score * combined_features['market_cap'] / 1000000 
                            if combined_features['market_cap'] > 0 else 0)
        
        # Préparer les features pour le modèle (même ordre que l'entraînement)
        feature_values = [
            combined_features['rugcheck_score'],
            combined_features['rugcheck_very_bad'],
            combined_features['rugcheck_bad'],
            combined_features['rugcheck_good'],
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
            holders_per_mcap,
            rugcheck_risk_combined,
            rugcheck_vs_market
        ]
        
        # Prédiction ML
        try:
            X = pd.DataFrame([feature_values], columns=self.feature_names)
            X = X.fillna(0)
            X_scaled = self.model['scaler'].transform(X)
            
            rf_prob = self.model['rf'].predict_proba(X_scaled)[0][1]
            gb_prob = self.model['gb'].predict_proba(X_scaled)[0][1]
            ml_score = (rf_prob * 0.6 + gb_prob * 0.4)  # Même pondération que l'entraînement
            
        except Exception as e:
            print(f"Erreur prédiction pour {address}: {e}")
            ml_score = 0.0
        
        # Classification enrichie
        if ml_score >= 0.85:
            risk_level = "TRÈS ÉLEVÉ"
            emoji = "🚨"
        elif ml_score >= 0.65:
            risk_level = "ÉLEVÉ"
            emoji = "⚠️"
        elif ml_score >= 0.45:
            risk_level = "MODÉRÉ"
            emoji = "⚠️"
        elif ml_score >= 0.25:
            risk_level = "SURVEILLANCE"
            emoji = "👀"
        else:
            risk_level = "FAIBLE"
            emoji = "✅"
        
        return {
            "address": address,
            "symbol": token_data.get('symbol', 'N/A'),
            "ml_rug_probability": round(ml_score, 3),
            "risk_level": f"{emoji} {risk_level}",
            "rugcheck_score": rugcheck_score,
            "rugcheck_interpretation": {
                "score": rugcheck_score,
                "category": "🛡️ Très sûr" if rugcheck_score >= 80 else
                           "✅ Sûr" if rugcheck_score >= 60 else
                           "⚠️ Attention" if rugcheck_score >= 40 else
                           "🚨 Dangereux" if rugcheck_score >= 20 else
                           "💀 Très dangereux"
            },
            "combined_analysis": {
                "ml_says": risk_level,
                "rugcheck_says": "Sûr" if rugcheck_score >= 60 else "Risqué",
                "agreement": "✅ Accord" if (
                    (ml_score >= 0.5 and rugcheck_score < 60) or
                    (ml_score < 0.5 and rugcheck_score >= 60)
                ) else "⚠️ Désaccord"
            },
            "key_factors": {
                "rugcheck_score": rugcheck_score,
                "holders": int(combined_features['holders']),
                "market_cap": round(combined_features['market_cap'], 2),
                "age_hours": round(combined_features['age_hours'], 1),
                "volume_24h": round(combined_features['volume_24h'], 2),
                "price_change_24h": round(combined_features['price_change_24h'], 2),
                "rug_indicators": rug_indicators_count
            }
        }

# Exemple d'utilisation avec RugCheck
def example_usage_with_rugcheck():
    """
    Exemple d'utilisation avec RugCheck intégré
    """
    predictor = RugPullPredictorWithRugCheck("tokens.db")
    
    # Entraînement avec RugCheck
    print("=== ENTRAÎNEMENT AVEC RUGCHECK INTÉGRÉ ===")
    predictor.train_model_with_rugcheck()
    
    # Test sur quelques tokens suspects
    print("\n=== TEST SUR TOKENS SUSPECTS ===")
    
    conn = sqlite3.connect("tokens.db")
    suspect_query = """
    SELECT address, symbol, rug_score 
    FROM tokens 
    WHERE rug_score IS NOT NULL AND rug_score <= 30
    ORDER BY rug_score ASC
    LIMIT 5
    """
    suspect_tokens = pd.read_sql_query(suspect_query, conn)
    conn.close()
    
    for _, token in suspect_tokens.iterrows():
        print(f"\n--- Test: {token['symbol']} (RugCheck: {token['rug_score']}) ---")
        result = predictor.predict_with_rugcheck(token['address'])
        
        print(f"ML Probabilité: {result['ml_rug_probability']}")
        print(f"Niveau de risque: {result['risk_level']}")
        print(f"RugCheck: {result['rugcheck_interpretation']['category']}")
        print(f"Accord ML/RugCheck: {result['combined_analysis']['agreement']}")

if __name__ == "__main__":
    example_usage_with_rugcheck()