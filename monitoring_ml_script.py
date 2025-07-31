import pandas as pd
import numpy as np
import sqlite3
from datetime import datetime, timedelta
import pickle
import os
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.preprocessing import StandardScaler

class RugPullMonitor:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.model = None
        self.scaler = None
        self.feature_names = []
        
    def create_monitoring_tables(self):
        """
        Crée les tables nécessaires pour le monitoring
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Table pour tracker les performances quotidiennes
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS model_performance (
                date DATE PRIMARY KEY,
                total_predictions INTEGER,
                high_risk_predictions INTEGER,
                confirmed_rugs INTEGER,
                false_positives INTEGER,
                false_negatives INTEGER,
                precision REAL,
                recall REAL,
                f1_score REAL,
                avg_score REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Table pour tracker les événements confirmés
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS confirmed_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                address TEXT NOT NULL,
                symbol TEXT,
                event_type TEXT, -- 'RUG_PULL', 'ABANDONED', 'SUCCESSFUL'
                event_date DATE,
                ml_score_at_prediction REAL,
                detection_method TEXT, -- 'MANUAL', 'AUTO_PRICE_DROP', 'AUTO_VOLUME'
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(address, event_date)
            )
        """)
        
        # Table pour les alertes et notifications
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                alert_type TEXT, -- 'HIGH_RISK_TOKEN', 'PERFORMANCE_DROP', 'MODEL_DRIFT'
                address TEXT,
                symbol TEXT,
                ml_score REAL,
                message TEXT,
                severity TEXT, -- 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'
                resolved BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        conn.commit()
        conn.close()
        print("✅ Tables de monitoring créées/vérifiées")
    
    def load_trained_model(self):
        """
        Charge le modèle pré-entraîné ou entraîne un nouveau
        """
        model_file = "rug_pull_model.pkl"
        
        if os.path.exists(model_file):
            print("📂 Chargement du modèle sauvegardé...")
            with open(model_file, 'rb') as f:
                model_data = pickle.load(f)
                self.model = model_data['model']
                self.scaler = model_data['scaler']
                self.feature_names = model_data['feature_names']
            print("✅ Modèle chargé avec succès")
        else:
            print("🔄 Aucun modèle sauvegardé trouvé, entraînement nécessaire...")
            self.train_and_save_model()
    
    def train_and_save_model(self):
        """
        Entraîne et sauvegarde le modèle
        """
        from ml_rugg_pull import RugPullPredictor  # Import de votre classe existante
        
        predictor = RugPullPredictor(self.db_path)
        predictor.train_model_with_sql_labels()
        
        # Copier le modèle entraîné
        self.model = predictor.model
        self.scaler = predictor.scaler
        self.feature_names = predictor.feature_names
        
        # Sauvegarder pour les prochaines fois
        model_data = {
            'model': self.model,
            'scaler': self.scaler,
            'feature_names': self.feature_names,
            'trained_date': datetime.now().isoformat()
        }
        
        with open("rug_pull_model.pkl", 'wb') as f:
            pickle.dump(model_data, f)
        
        print("💾 Modèle sauvegardé dans rug_pull_model.pkl")
    
    def update_new_tokens_only(self):
        """
        Met à jour seulement les tokens qui n'ont pas encore de score ML
        """
        if self.model is None:
            self.load_trained_model()
        
        conn = sqlite3.connect(self.db_path)
        
        # Ajouter colonne ml_rug_score si elle n'existe pas
        try:
            conn.execute("ALTER TABLE tokens ADD COLUMN ml_rug_score REAL DEFAULT NULL")
            conn.commit()
            print("✅ Colonne ml_rug_score ajoutée")
        except:
            pass  # Colonne existe déjà
        
        # Récupérer seulement les tokens sans score ML
        query = """
        SELECT 
            address, symbol, name, price_usdc, market_cap, 
            price_change_24h, volume_24h, age_hours, holders
        FROM tokens 
        WHERE ml_rug_score IS NULL
        """
        
        new_tokens = pd.read_sql_query(query, conn)
        
        if len(new_tokens) == 0:
            print("✅ Aucun nouveau token à traiter")
            conn.close()
            return 0
        
        print(f"🆕 Traitement de {len(new_tokens)} nouveaux tokens...")
        
        updated_count = 0
        
        for i, token in new_tokens.iterrows():
            if i % 100 == 0:
                print(f"Progression: {i}/{len(new_tokens)}")
            
            address = token['address']
            
            try:
                ml_score = self.predict_single_token(address, token, conn)
                
                # Mettre à jour la base
                conn.execute("""
                    UPDATE tokens 
                    SET ml_rug_score = ? 
                    WHERE address = ?
                """, (ml_score, address))
                
                updated_count += 1
                
                # Créer des alertes pour les tokens très suspects
                if ml_score >= 0.8:
                    self.create_alert('HIGH_RISK_TOKEN', address, token['symbol'], 
                                    ml_score, f"Nouveau token à très haut risque détecté", 'HIGH')
                
            except Exception as e:
                print(f"Erreur pour {address}: {e}")
                continue
        
        conn.commit()
        conn.close()
        
        print(f"✅ {updated_count} nouveaux tokens mis à jour")
        return updated_count
    
    def predict_single_token(self, address, token_data, conn):
        """
        Prédit le score ML pour un seul token
        """
        # Récupérer données DexScreener depuis tokens_hist
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
        
        # Préparer les features
        combined_features = {
            'price_usdc': token_data.get('price_usdc', 0) or 0,
            'market_cap': token_data.get('market_cap', 0) or 0,
            'price_change_24h': token_data.get('price_change_24h', 0) or 0,
            'volume_24h': token_data.get('volume_24h', 0) or 0,
            'age_hours': token_data.get('age_hours', 0) or 0,
            'holders': token_data.get('holders', 0) or 0,
        }
        
        # Ajouter données DexScreener si disponibles
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
        else:
            combined_features.update({
                'dexscreener_price_usd': 0,
                'dexscreener_market_cap': 0,
                'dexscreener_volume_24h': 0,
                'dexscreener_txns_24h': 0,
                'dexscreener_buys_24h': 0,
                'dexscreener_sells_24h': 0,
            })
        
        # Calculer indicateurs de rug
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
        
        # Préparer pour le modèle
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
        
        # Prédiction
        X = pd.DataFrame([feature_values], columns=self.feature_names)
        X = X.fillna(0)  # Remplacer NaN par 0
        X_scaled = self.scaler.transform(X)
        
        rf_prob = self.model['rf'].predict_proba(X_scaled)[0][1]
        gb_prob = self.model['gb'].predict_proba(X_scaled)[0][1]
        ml_score = (rf_prob + gb_prob) / 2
        
        return round(ml_score, 4)
    
    def create_alert_with_conn(self, conn, alert_type, address, symbol, ml_score, message, severity):
        """
        Crée une alerte avec une connexion existante
        """
        conn.execute("""
            INSERT INTO alerts (alert_type, address, symbol, ml_score, message, severity)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (alert_type, address, symbol, ml_score, message, severity))

    def detect_confirmed_rugs_auto(self):
        """
        Détecte automatiquement les nouveaux rug pulls basés sur des critères
        """
        conn = sqlite3.connect(self.db_path)
        
        # Critères automatiques pour détecter un rug pull
        auto_rug_query = """
        WITH latest_data AS (
            SELECT 
                t.address, t.symbol, t.ml_rug_score,
                th.price_change_24h, th.dexscreener_price_change_h24,
                th.volume_24h, th.dexscreener_volume_24h,
                th.dexscreener_txns_24h, th.market_cap,
                th.snapshot_timestamp
            FROM tokens t
            LEFT JOIN tokens_hist th ON t.address = th.address
            WHERE th.snapshot_timestamp = (
                SELECT MAX(snapshot_timestamp) 
                FROM tokens_hist th2 
                WHERE th2.address = t.address
            )
            AND t.ml_rug_score IS NOT NULL
        )
        SELECT 
            address, symbol, ml_rug_score, price_change_24h,
            dexscreener_price_change_h24, volume_24h, market_cap
        FROM latest_data
        WHERE 
            -- Critère 1: Chute massive de prix (>90%)
            (price_change_24h <= -90 OR dexscreener_price_change_h24 <= -90)
            OR
            -- Critère 2: Prix -80% + Volume quasi nul
            ((price_change_24h <= -80 OR dexscreener_price_change_h24 <= -80) 
             AND (volume_24h < 100 OR dexscreener_volume_24h < 100))
            OR  
            -- Critère 3: Market cap effondré + aucune transaction
            (market_cap < 100 AND dexscreener_txns_24h = 0)
        """
        
        potential_rugs = pd.read_sql_query(auto_rug_query, conn)
        
        today = datetime.now().date()
        new_detections = 0
        
        for _, rug in potential_rugs.iterrows():
            # Vérifier si pas déjà dans confirmed_events
            existing = conn.execute("""
                SELECT COUNT(*) FROM confirmed_events 
                WHERE address = ? AND event_date = ?
            """, (rug['address'], today)).fetchone()[0]
            
            if existing == 0:
                # Ajouter comme rug pull confirmé
                conn.execute("""
                    INSERT OR IGNORE INTO confirmed_events 
                    (address, symbol, event_type, event_date, ml_score_at_prediction, detection_method, notes)
                    VALUES (?, ?, 'RUG_PULL', ?, ?, 'AUTO_PRICE_DROP', ?)
                """, (
                    rug['address'], 
                    rug['symbol'], 
                    today,
                    rug['ml_rug_score'],
                    f"Prix: {rug['price_change_24h']:.1f}%, Volume: {rug['volume_24h']:.0f}"
                ))
                
                new_detections += 1
                
                # Créer alerte
                #self.create_alert_with_conn('RUG_DETECTED', rug['address'], rug['symbol'],
                 #               rug['ml_rug_score'], 
                 #               f"Rug pull détecté automatiquement (prix: {rug['price_change_24h']:.1f}%)", 
                 #               'CRITICAL')
        
        conn.commit()
        conn.close()
        
        if new_detections > 0:
            print(f"🚨 {new_detections} nouveaux rug pulls détectés automatiquement")
        
        return new_detections
    
    def calculate_daily_performance(self):
        """
        Calcule les performances du modèle pour aujourd'hui
        """
        conn = sqlite3.connect(self.db_path)
        today = datetime.now().date()
        
        # Récupérer tous les événements confirmés d'aujourd'hui
        confirmed_events = pd.read_sql_query("""
            SELECT address, event_type, ml_score_at_prediction
            FROM confirmed_events
            WHERE event_date = ?
        """, conn, params=(today,))
        
        if len(confirmed_events) == 0:
            print("ℹ️ Aucun événement confirmé aujourd'hui pour calculer les performances")
            conn.close()
            return
        
        # Récupérer toutes les prédictions à haut risque d'aujourd'hui
        high_risk_predictions = pd.read_sql_query("""
            SELECT COUNT(*) as count
            FROM tokens
            WHERE ml_rug_score >= 0.5
        """, conn).iloc[0]['count']
        
        # Calculer métriques
        total_confirmed = len(confirmed_events)
        confirmed_rugs = len(confirmed_events[confirmed_events['event_type'] == 'RUG_PULL'])
        
        # True Positives: Tokens prédits à haut risque ET qui ont ruggé
        true_positives = len(confirmed_events[
            (confirmed_events['event_type'] == 'RUG_PULL') & 
            (confirmed_events['ml_score_at_prediction'] >= 0.5)
        ])
        
        # False Positives: Tokens prédits à haut risque mais PAS ruggés
        false_positives = high_risk_predictions - true_positives
        
        # False Negatives: Tokens qui ont ruggé mais PAS prédits à haut risque
        false_negatives = len(confirmed_events[
            (confirmed_events['event_type'] == 'RUG_PULL') & 
            (confirmed_events['ml_score_at_prediction'] < 0.5)
        ])
        
        # Métriques
        precision = true_positives / max(1, true_positives + false_positives)
        recall = true_positives / max(1, true_positives + false_negatives)
        f1_score = 2 * (precision * recall) / max(0.001, precision + recall)
        
        # Score moyen
        avg_score = pd.read_sql_query("""
            SELECT AVG(ml_rug_score) as avg_score
            FROM tokens
            WHERE ml_rug_score IS NOT NULL
        """, conn).iloc[0]['avg_score']
        
        # Sauvegarder les performances
        conn.execute("""
            INSERT OR REPLACE INTO model_performance
            (date, total_predictions, high_risk_predictions, confirmed_rugs, 
             false_positives, false_negatives, precision, recall, f1_score, avg_score)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            today, total_confirmed, high_risk_predictions, confirmed_rugs,
            false_positives, false_negatives, precision, recall, f1_score, avg_score
        ))
        
        conn.commit()
        conn.close()
        
        # Afficher résultats
        print(f"\n📊 PERFORMANCES DU MODÈLE - {today}")
        print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"✅ True Positives:  {true_positives}")
        print(f"❌ False Positives: {false_positives}")
        print(f"❌ False Negatives: {false_negatives}")
        print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"🎯 Precision: {precision:.3f} ({precision*100:.1f}%)")
        print(f"🎯 Recall:    {recall:.3f} ({recall*100:.1f}%)")
        print(f"🎯 F1-Score:  {f1_score:.3f}")
        print(f"📈 Score ML moyen: {avg_score:.3f}")
        
        # Alertes si performance dégradée
        if precision < 0.5:
            self.create_alert('PERFORMANCE_DROP', None, None, None,
                            f"Precision faible: {precision:.3f}", 'HIGH')
        
        if recall < 0.4:
            self.create_alert('PERFORMANCE_DROP', None, None, None,
                            f"Recall faible: {recall:.3f}", 'HIGH')
    
    def create_alert(self, alert_type, address, symbol, ml_score, message, severity):
        """
        Crée une alerte dans le système
        """
        conn = sqlite3.connect(self.db_path, timeout=30)
        
        try:
            conn.execute("""
                INSERT INTO alerts (alert_type, address, symbol, ml_score, message, severity)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (alert_type, address, symbol, ml_score, message, severity))
            conn.commit()
        except sqlite3.OperationalError as e:
            print(f"⚠️ Erreur création alerte: {e}")
            # Créer les tables si elles n'existent pas
            self.create_monitoring_tables()
            # Réessayer
            conn.execute("""
                INSERT INTO alerts (alert_type, address, symbol, ml_score, message, severity)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (alert_type, address, symbol, ml_score, message, severity))
            conn.commit()
        finally:
            conn.close()
    
    def show_recent_alerts(self, days=7):
        """
        Affiche les alertes récentes
        """
        conn = sqlite3.connect(self.db_path)
        alerts = pd.read_sql_query("""
            SELECT alert_type, address, symbol, ml_score, message, severity, 
                   created_at, resolved
            FROM alerts
            WHERE created_at >= datetime('now', '-{} days')
            ORDER BY created_at DESC
            LIMIT 20
        """.format(days), conn)
        conn.close()
        
        if len(alerts) == 0:
            print("ℹ️ Aucune alerte récente")
            return
        
        print(f"\n🚨 ALERTES DES {days} DERNIERS JOURS")
        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        
        for _, alert in alerts.iterrows():
            status = "✅" if alert['resolved'] else "⚠️"
            severity_emoji = {"LOW": "🟢", "MEDIUM": "🟡", "HIGH": "🟠", "CRITICAL": "🔴"}
            
            print(f"{status} {severity_emoji.get(alert['severity'], '')} {alert['alert_type']}")
            if alert['symbol']:
                print(f"   Token: {alert['symbol']} | Score: {alert['ml_score']:.3f}")
            print(f"   {alert['message']}")
            print(f"   {alert['created_at']}")
            print()
    
    def performance_summary(self, days=30):
        """
        Résumé des performances sur les X derniers jours
        """
        conn = sqlite3.connect(self.db_path)
        
        perf_data = pd.read_sql_query("""
            SELECT date, precision, recall, f1_score, confirmed_rugs, false_positives, false_negatives
            FROM model_performance
            WHERE date >= date('now', '-{} days')
            ORDER BY date DESC
        """.format(days), conn)
        
        conn.close()
        
        if len(perf_data) == 0:
            print(f"ℹ️ Aucune donnée de performance sur les {days} derniers jours")
            return
        
        print(f"\n📈 RÉSUMÉ DES PERFORMANCES - {days} DERNIERS JOURS")
        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"📊 Nombre de jours avec données: {len(perf_data)}")
        print(f"🎯 Precision moyenne: {perf_data['precision'].mean():.3f}")
        print(f"🎯 Recall moyen: {perf_data['recall'].mean():.3f}")
        print(f"🎯 F1-Score moyen: {perf_data['f1_score'].mean():.3f}")
        print(f"🚨 Total rug pulls détectés: {perf_data['confirmed_rugs'].sum()}")
        print(f"❌ Total faux positifs: {perf_data['false_positives'].sum()}")
        print(f"❌ Total faux négatifs: {perf_data['false_negatives'].sum()}")
        
        # Tendance
        if len(perf_data) >= 2:
            recent_precision = perf_data.head(7)['precision'].mean()
            old_precision = perf_data.tail(7)['precision'].mean()
            trend = "📈" if recent_precision > old_precision else "📉"
            print(f"{trend} Tendance Precision: {recent_precision - old_precision:+.3f}")

def daily_monitoring_script():
    """
    Script principal de monitoring quotidien
    """
    print(f"🚀 DÉMARRAGE DU MONITORING QUOTIDIEN - {datetime.now()}")
    print("=" * 60)
    
    monitor = RugPullMonitor("tokens.db")
    
    # 1. Créer tables de monitoring si nécessaire
    monitor.create_monitoring_tables()
    
    # 2. Mettre à jour les nouveaux tokens
    print("\n1️⃣ MISE À JOUR DES NOUVEAUX TOKENS")
    new_tokens_count = monitor.update_new_tokens_only()
    
    # 3. Détecter automatiquement les nouveaux rug pulls
    print("\n2️⃣ DÉTECTION AUTOMATIQUE DES RUG PULLS")
    new_rugs = monitor.detect_confirmed_rugs_auto()
    
    # 4. Calculer les performances
    print("\n3️⃣ CALCUL DES PERFORMANCES")
    monitor.calculate_daily_performance()
    
    # 5. Afficher les alertes récentes
    print("\n4️⃣ ALERTES RÉCENTES")
    monitor.show_recent_alerts(days=3)
    
    # 6. Résumé des performances
    print("\n5️⃣ RÉSUMÉ DES PERFORMANCES")
    monitor.performance_summary(days=7)
    
    print(f"\n✅ MONITORING QUOTIDIEN TERMINÉ - {datetime.now()}")
    print("=" * 60)

def manual_confirm_rug(address, event_type='RUG_PULL', notes=''):
    """
    Fonction pour confirmer manuellement un rug pull
    """
    monitor = RugPullMonitor("tokens.db")
    monitor.create_monitoring_tables()
    
    conn = sqlite3.connect("tokens.db")
    
    # Récupérer info du token
    token_info = pd.read_sql_query("""
        SELECT symbol, ml_rug_score FROM tokens WHERE address = ?
    """, conn, params=(address,))
    
    if len(token_info) == 0:
        print(f"❌ Token {address} non trouvé")
        return
    
    symbol = token_info.iloc[0]['symbol']
    ml_score = token_info.iloc[0]['ml_rug_score']
    today = datetime.now().date()
    
    # Ajouter l'événement confirmé
    conn.execute("""
        INSERT OR REPLACE INTO confirmed_events 
        (address, symbol, event_type, event_date, ml_score_at_prediction, detection_method, notes)
        VALUES (?, ?, ?, ?, ?, 'MANUAL', ?)
    """, (address, symbol, event_type, today, ml_score, notes))
    
    conn.commit()
    conn.close()
    
    print(f"✅ Événement confirmé:")
    print(f"   Token: {symbol} ({address})")
    print(f"   Type: {event_type}")
    print(f"   Score ML: {ml_score:.3f}")
    print(f"   Notes: {notes}")

if __name__ == "__main__":
    # Script principal
    daily_monitoring_script()
    
    # Exemples d'utilisation :
    
    # Pour confirmer manuellement un rug pull :
    # manual_confirm_rug("ADRESSE_TOKEN", "RUG_PULL", "Confirmé sur Twitter")
    
    # Pour mettre à jour seulement les nouveaux tokens :
    # monitor = RugPullMonitor("tokens.db")
    # monitor.update_new_tokens_only()