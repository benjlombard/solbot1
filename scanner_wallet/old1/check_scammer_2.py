import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

class TokenCreatorScamDetector:
    def __init__(self):
        self.risk_factors = {
            'temporal_concentration': 0,  # Activité ultra-concentrée
            'transaction_frequency': 0,   # Pattern robotique
            'accumulation_pattern': 0,    # Accumulation puis vidage
            'automation_score': 0,        # Détection de bots
            'rug_preparation': 0          # Préparation de rug pull
        }
        
    def load_data(self, csv_file_path):
        """Charge et analyse les données CSV au format Solscan"""
        try:
            df = pd.read_csv(csv_file_path)
            df.columns = df.columns.str.strip()
            
            print(f"🔍 Colonnes détectées: {list(df.columns)}")
            
            # Adapter au format Solscan
            if 'BlockTimeUnix' in df.columns:
                df['datetime'] = pd.to_datetime(df['BlockTimeUnix'], unit='s')
                print("✅ Utilisation de 'BlockTimeUnix'")
            elif 'BlockTime' in df.columns:
                df['datetime'] = pd.to_datetime(df['BlockTime'])
                print("✅ Utilisation de 'BlockTime'")
            else:
                print("❌ Aucune colonne de temps trouvée!")
                return None
            
            # Adapter les colonnes pour l'analyse
            if 'ChangeAmount' in df.columns:
                df['Amount'] = df['ChangeAmount'] / 1e9  # Convertir en unités lisibles
            else:
                print("❌ Colonne ChangeAmount manquante!")
                return None
                
            if 'ChangeType' in df.columns:
                df['Type'] = df['ChangeType']
            else:
                print("❌ Colonne ChangeType manquante!")
                return None
            
            print(f"📊 Données préparées: {len(df)} transactions")
            print(f"📅 Période: {df['datetime'].min()} → {df['datetime'].max()}")
            
            return df
            
        except Exception as e:
            print(f"❌ Erreur lors du chargement: {e}")
            return None
    
    def analyze_temporal_concentration(self, df):
        """Analyse CRITIQUE de la concentration temporelle - Détection de bots ULTRA-SENSIBLE"""
        if df.empty:
            return {'time_span_minutes': 0, 'transaction_count': 0, 'risk_score': 0}
            
        time_span = (df['datetime'].max() - df['datetime'].min()).total_seconds() / 60
        transaction_count = len(df)
        
        # CRITÈRES ULTRA-STRICTS adaptés aux vrais patterns de scam
        
        # Pattern extrême: Plus de 1 tx/minute en moyenne = BOT
        tx_per_minute = transaction_count / max(time_span, 1)
        
        if tx_per_minute >= 2.0:  # 2+ tx/minute
            score = 10  # 🚨 BOT CONFIRMÉ
        elif tx_per_minute >= 1.5:  # 1.5+ tx/minute  
            score = 10  # 🚨 BOT CONFIRMÉ (votre cas: 1.3 tx/min)
        elif tx_per_minute >= 1.2:  # 1.2+ tx/minute
            score = 9   # 🔴 TRÈS SUSPECT (votre cas exactement!)
        elif tx_per_minute >= 1.0:  # 1+ tx/minute
            score = 8   # 🔴 SUSPECT
        elif tx_per_minute >= 0.8:  # 0.8+ tx/minute
            score = 7   # 🟠 DOUTEUX
        elif tx_per_minute >= 0.5:  # 0.5+ tx/minute
            score = 5   # 🟡 SURVEILLANCE
        else:
            score = 2   # Activité normale
        
        # BONUS pour concentration absolue
        if time_span <= 60 and transaction_count >= 80:  # 80+ tx en 1h
            score = 10  # 🚨 PATTERN RUG CONFIRMÉ (votre cas!)
        elif time_span <= 90 and transaction_count >= 90:  # 90+ tx en 1h30 (votre cas!)
            score = 10  # 🚨 PATTERN RUG CONFIRMÉ
        elif time_span <= 120 and transaction_count >= 100:  # 100+ tx en 2h
            score = 9   # 🔴 TRÈS SUSPECT
        
        # BONUS pour vitesse moyenne suspecte
        avg_seconds = (time_span * 60) / transaction_count if transaction_count > 0 else 0
        if avg_seconds < 30:  # Moins de 30s entre transactions
            score = min(10, score + 2)
        elif avg_seconds < 45:  # Moins de 45s (votre cas: 44.8s)
            score = min(10, score + 1)
            
        self.risk_factors['temporal_concentration'] = score
        
        return {
            'time_span_minutes': round(time_span, 2),
            'transaction_count': transaction_count,
            'avg_seconds_per_transaction': round(avg_seconds, 2),
            'transactions_per_minute': round(tx_per_minute, 2),
            'risk_score': score
        }
    
    def analyze_transaction_frequency(self, df):
        """Détection de patterns robotiques/automatisés"""
        if len(df) < 3:
            return {'risk_score': 0}
            
        df_sorted = df.sort_values('datetime')
        intervals = df_sorted['datetime'].diff().dt.total_seconds().dropna()
        
        if len(intervals) == 0:
            return {'risk_score': 0}
        
        mean_interval = intervals.mean()
        std_interval = intervals.std()
        coefficient_variation = std_interval / mean_interval if mean_interval > 0 else 0
        
        # DÉTECTION ROBOTIQUE ULTRA-SENSIBLE
        if coefficient_variation < 0.05:  # Quasi-parfaitement régulier
            score = 10  # 🚨 BOT CONFIRMÉ
        elif coefficient_variation < 0.1 and mean_interval < 10:  # Très régulier et rapide
            score = 10  # 🚨 BOT CONFIRMÉ
        elif coefficient_variation < 0.15:  # Trop régulier pour un humain
            score = 9   # 🔴 BOT PROBABLE
        elif coefficient_variation < 0.25 and mean_interval < 30:  # Régulier et rapide
            score = 8   # 🔴 SUSPECT
        elif coefficient_variation < 0.3:  # Un peu trop régulier
            score = 6   # 🟡 DOUTEUX
        else:
            score = 2   # Pattern humain acceptable
            
        # BONUS MALUS pour vitesse extrême
        if mean_interval < 5:  # Moins de 5 secondes entre transactions
            score = min(10, score + 3)
        elif mean_interval < 10:  # Moins de 10 secondes
            score = min(10, score + 2)
            
        self.risk_factors['transaction_frequency'] = score
        
        return {
            'mean_interval_seconds': round(mean_interval, 2),
            'coefficient_variation': round(coefficient_variation, 3),
            'risk_score': score
        }
    
    def analyze_accumulation_pattern(self, df):
        """Détection du pattern d'accumulation puis vidage (préparation rug) RENFORCÉE"""
        if len(df) < 10:
            return {'risk_score': 0}
            
        # Analyser la séquence temporelle des dépôts/retraits
        df_sorted = df.sort_values('datetime')
        
        deposits = df_sorted[df_sorted['Type'] == 'inc']
        withdrawals = df_sorted[df_sorted['Type'] == 'dec']
        
        deposit_count = len(deposits)
        withdrawal_count = len(withdrawals)
        total_count = len(df_sorted)
        
        if total_count == 0:
            return {'risk_score': 0}
        
        deposit_ratio = deposit_count / total_count
        withdrawal_ratio = withdrawal_count / total_count
        
        # DÉTECTION PATTERN DE RUG PULL ULTRA-SENSIBLE
        score = 0
        
        # Pattern 1: Déséquilibre majeur (votre cas: 80% dépôts vs 20% retraits)
        if deposit_ratio >= 0.8:  # 80%+ de dépôts (VOTRE CAS EXACT!)
            score += 6  # SIGNAL MAJEUR DE RUG
        elif deposit_ratio >= 0.75:  # 75%+ de dépôts
            score += 5
        elif deposit_ratio >= 0.7:  # 70%+ de dépôts
            score += 4
        elif deposit_ratio >= 0.65:  # 65%+ de dépôts
            score += 3
        elif deposit_ratio >= 0.6:  # 60%+ de dépôts
            score += 2
            
        # Pattern 2: Ratio extrême de déséquilibre
        imbalance = abs(deposit_ratio - withdrawal_ratio)
        if imbalance >= 0.6:  # 60%+ de déséquilibre (votre cas: 60%!)
            score += 3  # PATTERN RUG CLASSIQUE
        elif imbalance >= 0.5:  # 50%+ de déséquilibre
            score += 2
        elif imbalance >= 0.4:  # 40%+ de déséquilibre
            score += 1
        
        # Pattern 3: Séquence temporelle suspecte
        if len(deposits) > 0 and len(withdrawals) > 0:
            # Vérifier si les retraits viennent APRÈS les dépôts (pattern rug)
            avg_deposit_time = deposits['datetime'].mean()
            avg_withdrawal_time = withdrawals['datetime'].mean()
            
            if avg_withdrawal_time > avg_deposit_time:  # Retraits après dépôts
                time_gap = (avg_withdrawal_time - avg_deposit_time).total_seconds() / 60
                if time_gap < 30:  # Retraits dans la demi-heure
                    score += 4  # PATTERN RUG ULTRA-RAPIDE
                elif time_gap < 60:  # Dans l'heure qui suit
                    score += 3  # PATTERN RUG CLASSIQUE
                elif time_gap < 180:  # Dans les 3h
                    score += 2
                elif time_gap < 360:  # Dans les 6h
                    score += 1
        
        # Pattern 4: Volume d'activité suspect
        if total_count >= 80 and deposit_ratio >= 0.75:  # 80+ tx avec 75%+ dépôts
            score += 2  # PREPARATION MASSIVE
        
        score = min(10, score)
        self.risk_factors['accumulation_pattern'] = score
        
        return {
            'deposit_count': deposit_count,
            'withdrawal_count': withdrawal_count,
            'deposit_ratio': round(deposit_ratio, 3),
            'withdrawal_ratio': round(withdrawal_ratio, 3),
            'imbalance_ratio': round(imbalance, 3),
            'risk_score': score
        }
    
    def analyze_automation_patterns(self, df):
        """Détection avancée d'automatisation (bots de préparation)"""
        if len(df) < 5:
            return {'risk_score': 0}
            
        patterns_detected = 0
        
        # Pattern 1: Montants identiques (bot avec paramètres fixes)
        if 'Amount' in df.columns:
            amount_counts = df['Amount'].abs().value_counts()
            if len(amount_counts) > 0:
                most_common_ratio = amount_counts.iloc[0] / len(df)
                if most_common_ratio > 0.5:  # Plus de 50% même montant
                    patterns_detected += 4
                elif most_common_ratio > 0.3:  # Plus de 30% même montant
                    patterns_detected += 3
                elif most_common_ratio > 0.2:  # Plus de 20% même montant
                    patterns_detected += 2
        
        # Pattern 2: Intervalles ultra-réguliers (signature bot)
        df_sorted = df.sort_values('datetime')
        intervals = df_sorted['datetime'].diff().dt.total_seconds().dropna()
        
        if len(intervals) > 0:
            # Détecter des intervalles exactement identiques
            interval_counts = pd.Series(intervals).round(0).value_counts()
            if len(interval_counts) > 0:
                most_common_interval_ratio = interval_counts.iloc[0] / len(intervals)
                if most_common_interval_ratio > 0.4:  # Plus de 40% d'intervalles identiques
                    patterns_detected += 4
                elif most_common_interval_ratio > 0.3:  # Plus de 30%
                    patterns_detected += 3
        
        # Pattern 3: Séquences répétitives exactes
        if 'Type' in df.columns and len(df) > 8:
            types = df_sorted['Type'].tolist()
            # Chercher des patterns répétitifs de 2-4 éléments
            for pattern_length in [2, 3, 4]:
                for i in range(len(types) - pattern_length * 2):
                    pattern1 = types[i:i+pattern_length]
                    pattern2 = types[i+pattern_length:i+pattern_length*2]
                    if pattern1 == pattern2:
                        patterns_detected += 2
                        break
        
        # Pattern 4: Heures suspectes (bots lancés à heures fixes)
        hours = df['datetime'].dt.hour.value_counts()
        if len(hours) > 0 and hours.iloc[0] > len(df) * 0.8:  # Plus de 80% à la même heure
            patterns_detected += 3
        
        score = min(10, patterns_detected)
        self.risk_factors['automation_score'] = score
        
        return {
            'patterns_detected': patterns_detected,
            'risk_score': score
        }
    
    def analyze_rug_preparation_signals(self, df):
        """Détection spécifique des signaux de préparation de rug pull"""
        if len(df) < 10:
            return {'risk_score': 0}
            
        rug_signals = 0
        
        # Signal 1: Activité de préparation juste avant le lancement
        time_span_hours = (df['datetime'].max() - df['datetime'].min()).total_seconds() / 3600
        if time_span_hours < 1 and len(df) > 50:  # Plus de 50 tx en moins d'1h
            rug_signals += 5  # SIGNAL MAJEUR
        elif time_span_hours < 2 and len(df) > 80:  # Plus de 80 tx en moins de 2h
            rug_signals += 4
        elif time_span_hours < 6 and len(df) > 100:  # Plus de 100 tx en moins de 6h
            rug_signals += 3
        
        # Signal 2: Pattern d'accumulation rapide
        df_sorted = df.sort_values('datetime')
        first_half = df_sorted.iloc[:len(df_sorted)//2]
        second_half = df_sorted.iloc[len(df_sorted)//2:]
        
        first_half_deposits = sum(first_half['Type'] == 'inc')
        second_half_withdrawals = sum(second_half['Type'] == 'dec')
        
        if first_half_deposits > len(first_half) * 0.8:  # 80%+ dépôts en première moitié
            rug_signals += 3
        if second_half_withdrawals > len(second_half) * 0.6:  # 60%+ retraits en seconde moitié
            rug_signals += 3
        
        # Signal 3: Focus sur SOL (préparation liquidité)
        if 'TokenAddress' in df.columns:
            sol_transactions = df[df['TokenAddress'] == 'So11111111111111111111111111111111111111111']
            sol_ratio = len(sol_transactions) / len(df)
            if sol_ratio > 0.9:  # Plus de 90% des transactions en SOL
                rug_signals += 2
            elif sol_ratio > 0.8:  # Plus de 80%
                rug_signals += 1
        
        # Signal 4: Montants croissants (test puis exécution)
        if 'Amount' in df.columns:
            amounts = df_sorted['Amount'].abs()
            if len(amounts) > 5:
                # Vérifier si les montants augmentent vers la fin
                last_quarter = amounts.iloc[-len(amounts)//4:]
                first_quarter = amounts.iloc[:len(amounts)//4]
                if last_quarter.mean() > first_quarter.mean() * 3:  # 3x plus gros à la fin
                    rug_signals += 2
        
        score = min(10, rug_signals)
        self.risk_factors['rug_preparation'] = score
        
        return {
            'rug_signals_detected': rug_signals,
            'risk_score': score
        }
    
    def generate_scam_report(self, csv_file_path):
        """Génère un rapport complet de détection de scam pour créateur de token"""
        print("🚨 DÉTECTEUR DE SCAM - CRÉATEUR DE TOKEN CRYPTO")
        print("=" * 60)
        
        df = self.load_data(csv_file_path)
        if df is None:
            return None
            
        print(f"📊 Transactions analysées: {len(df)}")
        if len(df) > 0:
            print(f"📅 Période d'activité: {df['datetime'].min()} → {df['datetime'].max()}")
        print()
        
        # Analyses spécialisées
        temporal_analysis = self.analyze_temporal_concentration(df)
        frequency_analysis = self.analyze_transaction_frequency(df)
        accumulation_analysis = self.analyze_accumulation_pattern(df)
        automation_analysis = self.analyze_automation_patterns(df)
        rug_analysis = self.analyze_rug_preparation_signals(df)
        
        # Affichage détaillé
        print("⚡ ANALYSE DE CONCENTRATION TEMPORELLE:")
        print(f"   ⏱️  Durée totale: {temporal_analysis['time_span_minutes']:.1f} minutes")
        print(f"   🔢 Nombre de transactions: {temporal_analysis['transaction_count']}")
        print(f"   ⚡ Vitesse moyenne: 1 tx toutes les {temporal_analysis['avg_seconds_per_transaction']:.1f} secondes")
        print(f"   📈 Fréquence: {temporal_analysis['transactions_per_minute']:.1f} tx/minute")
        print(f"   🚨 Score de risque: {temporal_analysis['risk_score']}/10")
        print()
        
        print("🤖 DÉTECTION DE PATTERNS ROBOTIQUES:")
        print(f"   📊 Intervalle moyen: {frequency_analysis['mean_interval_seconds']:.1f} secondes")
        print(f"   🎯 Régularité (CV): {frequency_analysis['coefficient_variation']:.3f}")
        print(f"   🚨 Score de risque: {frequency_analysis['risk_score']}/10")
        print()
        
        print("💰 ANALYSE PATTERN D'ACCUMULATION:")
        print(f"   📥 Dépôts: {accumulation_analysis['deposit_count']} ({accumulation_analysis['deposit_ratio']*100:.1f}%)")
        print(f"   📤 Retraits: {accumulation_analysis['withdrawal_count']} ({accumulation_analysis['withdrawal_ratio']*100:.1f}%)")
        print(f"   🚨 Score de risque: {accumulation_analysis['risk_score']}/10")
        print()
        
        print("🎯 DÉTECTION D'AUTOMATISATION:")
        print(f"   🔍 Patterns détectés: {automation_analysis['patterns_detected']}")
        print(f"   🚨 Score de risque: {automation_analysis['risk_score']}/10")
        print()
        
        print("🎪 SIGNAUX DE PRÉPARATION RUG PULL:")
        print(f"   🚩 Signaux détectés: {rug_analysis['rug_signals_detected']}")
        print(f"   🚨 Score de risque: {rug_analysis['risk_score']}/10")
        print()
        
        # Calcul du score global PONDÉRÉ avec FOCUS sur les signaux critiques
        weights = {
            'temporal_concentration': 0.35,  # 35% - CRITIQUE (augmenté)
            'transaction_frequency': 0.20,   # 20% - Important
            'accumulation_pattern': 0.25,    # 25% - CRITIQUE (augmenté)  
            'automation_score': 0.10,        # 10% - Modéré
            'rug_preparation': 0.10          # 10% - Modéré
        }
        
        weighted_score = sum(self.risk_factors[factor] * weight 
                           for factor, weight in weights.items())
        
        # BONUS SPÉCIAUX pour combinaisons mortelles
        
        # Bonus 1: Pattern concentration + accumulation extrême
        if (self.risk_factors['temporal_concentration'] >= 8 and 
            self.risk_factors['accumulation_pattern'] >= 7):
            weighted_score = min(10, weighted_score + 1.5)  # COMBO MORTEL
            
        # Bonus 2: Automatisation confirmée + concentration
        if (self.risk_factors['automation_score'] >= 9 and 
            self.risk_factors['temporal_concentration'] >= 7):
            weighted_score = min(10, weighted_score + 1)  # BOT + VITESSE = RUG
            
        # Bonus 3: Triple threat (concentration + accumulation + automatisation)
        if (self.risk_factors['temporal_concentration'] >= 7 and 
            self.risk_factors['accumulation_pattern'] >= 6 and 
            self.risk_factors['automation_score'] >= 8):
            weighted_score = min(10, weighted_score + 1.5)  # TRIPLE MENACE
        
        # Détermination du verdict ULTRA-STRICT
        if weighted_score >= 8.0:  # Seuil abaissé de 8.5 à 8.0
            risk_level = "🚨 SCAMMER CONFIRMÉ"
            risk_emoji = "🔴"
            verdict = "ÉVITER ABSOLUMENT"
            investment_risk = "10/10 - DANGER EXTRÊME"
        elif weighted_score >= 6.5:  # Seuil abaissé de 7.0 à 6.5
            risk_level = "⚠️ TRÈS SUSPECT"
            risk_emoji = "🟠"
            verdict = "PROBABLE SCAMMER"
            investment_risk = "9/10 - DANGER ÉLEVÉ"
        elif weighted_score >= 5.0:  # Seuil abaissé de 5.5 à 5.0
            risk_level = "🔴 DOUTEUX"
            risk_emoji = "🟡"
            verdict = "COMPORTEMENT ANORMAL"
            investment_risk = "8/10 - RISQUE TRÈS ÉLEVÉ"
        elif weighted_score >= 3.5:  # Seuil abaissé de 4.0 à 3.5
            risk_level = "🟡 SURVEILLANCE"
            risk_emoji = "🔵"
            verdict = "PATTERNS INHABITUELS"
            investment_risk = "6/10 - RISQUE ÉLEVÉ"
        elif weighted_score >= 2.0:  # Seuil abaissé de 2.5 à 2.0
            risk_level = "🔵 ACCEPTABLE"
            risk_emoji = "🟢"
            verdict = "COMPORTEMENT NORMAL"
            investment_risk = "3/10 - RISQUE FAIBLE"
        else:
            risk_level = "✅ LÉGITIME"
            risk_emoji = "🟢"
            verdict = "CRÉATEUR FIABLE"
            investment_risk = "1/10 - TRÈS SÛR"
            
        print("=" * 60)
        print(f"🎯 SCORE GLOBAL: {weighted_score:.1f}/10")
        print(f"{risk_emoji} NIVEAU: {risk_level}")
        print(f"📋 VERDICT: {verdict}")
        print(f"💰 RISQUE D'INVESTISSEMENT: {investment_risk}")
        print("=" * 60)
        
        # Recommandations spécifiques
        print("💡 RECOMMANDATIONS:")
        if weighted_score >= 8.5:
            print("   🚫 NE PAS INVESTIR - Pattern de scammer détecté")
            print("   🏃 FUIR ce token immédiatement")
            print("   📢 ALERTER la communauté")
            print("   🔍 Vérifier si le token est déjà ruggé")
        elif weighted_score >= 7.0:
            print("   ⚠️ EXTRÊMEMENT RISQUÉ")
            print("   💰 Investissement déconseillé")
            print("   📊 Attendre confirmation avant achat")
            print("   🔍 Surveiller l'évolution du token")
        elif weighted_score >= 5.5:
            print("   🟡 PRUDENCE MAXIMALE")
            print("   💰 Si investissement: montant symbolique uniquement")
            print("   ⏰ Analyser l'évolution sur plusieurs jours")
            print("   📈 Vérifier les fondamentaux du projet")
        elif weighted_score >= 4.0:
            print("   🔵 SURVEILLANCE RECOMMANDÉE")
            print("   📊 Analyser d'autres métriques")
            print("   💰 Investissement avec prudence")
            print("   🤝 Vérifier la réputation du team")
        else:
            print("   ✅ PROFIL ACCEPTABLE")
            print("   📈 Continuer l'analyse fondamentale")
            print("   💎 Peut être un bon investissement")
            print("   🔍 Vérifier quand même les tokenomics")
            
        return {
            'risk_score': round(weighted_score, 1),
            'investment_risk': investment_risk,
            'risk_level': risk_level,
            'verdict': verdict,
            'detailed_scores': self.risk_factors,
            'analyses': {
                'temporal': temporal_analysis,
                'frequency': frequency_analysis,
                'accumulation': accumulation_analysis,
                'automation': automation_analysis,
                'rug_preparation': rug_analysis
            }
        }

def analyze_token_creator_scam(csv_file_path):
    """Fonction principale pour détecter les scams de créateurs de tokens"""
    detector = TokenCreatorScamDetector()
    return detector.generate_scam_report(csv_file_path)

# Exemple d'utilisation
if __name__ == "__main__":
    # Testez avec votre fichier CSV
    #csv_file = "balance_changes_4xLmxHNV_20250802_202604_full.csv"
    #csv_file = "balance_changes_AK1TDZ8T_20250802_212152_full.csv"
    #csv_file = "balance_changes_EuFC4PtY_20250802_215250_full.csv"
    csv_file = "export_balance_change_3S3wPvBnGegy9Zj9LDMaRPn2d2pxakE9YdKPm8UM3WLP_1755110869587.csv"
    print("🚀 Lancement de la détection de scam pour créateur de token...")
    print(f"📁 Fichier: {csv_file}")
    print()
    
    result = analyze_token_creator_scam(csv_file)
    
    if result:
        print(f"\n🎯 RÉSULTAT FINAL:")
        print(f"📊 Score de risque: {result['risk_score']}/10")
        print(f"💰 Risque d'investissement: {result['investment_risk']}")
        print(f"📋 Verdict: {result['verdict']}")
    else:
        print("\n❌ Échec de l'analyse")