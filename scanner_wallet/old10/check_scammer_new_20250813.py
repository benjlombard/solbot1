import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

class MultiTokenScamDetector:
    def __init__(self):
        self.wallet_risk_score = 0
        self.token_analyses = {}
        self.overall_patterns = {}
        
    def load_data(self, csv_file_path):
        """Charge toutes les données du wallet"""
        try:
            df = pd.read_csv(csv_file_path)
            df.columns = df.columns.str.strip()
            
            # Conversion temps
            if 'BlockTimeUnix' in df.columns:
                df['datetime'] = pd.to_datetime(df['BlockTimeUnix'], unit='s')
            else:
                print("❌ Pas de timestamp trouvé!")
                return None
            
            # Conversion montants
            if 'ChangeAmount' in df.columns:
                df['Amount'] = pd.to_numeric(df['ChangeAmount'], errors='coerce')
                if df['Amount'].max() > 1e12:
                    df['Amount'] = df['Amount'] / 1e9
                df = df.dropna(subset=['Amount'])
            
            if 'ChangeType' in df.columns:
                df['Type'] = df['ChangeType']
            
            print(f"📊 Données chargées: {len(df)} transactions")
            print(f"📅 Période: {df['datetime'].min()} → {df['datetime'].max()}")
            
            return df
            
        except Exception as e:
            print(f"❌ Erreur: {e}")
            return None
    
    def identify_tokens_and_periods(self, df):
        """Identifie tous les tokens et leurs périodes d'activité"""
        if 'TokenAddress' not in df.columns:
            return {}
        
        tokens = {}
        sol_address = 'So11111111111111111111111111111111111111111'
        
        # Grouper par token (excluant SOL)
        for token_addr in df['TokenAddress'].unique():
            if token_addr == sol_address:
                continue
                
            token_txs = df[df['TokenAddress'] == token_addr].copy()
            if len(token_txs) < 3:  # Ignorer les tokens avec très peu d'activité
                continue
            
            token_txs = token_txs.sort_values('datetime')
            
            # Identifier les périodes d'activité concentrée
            periods = self.find_activity_periods(token_txs)
            
            tokens[token_addr] = {
                'transactions': token_txs,
                'periods': periods,
                'total_txs': len(token_txs),
                'first_tx': token_txs['datetime'].min(),
                'last_tx': token_txs['datetime'].max(),
                'lifespan_hours': (token_txs['datetime'].max() - token_txs['datetime'].min()).total_seconds() / 3600
            }
        
        print(f"\n🎯 TOKENS IDENTIFIÉS: {len(tokens)}")
        for addr, info in tokens.items():
            token_name = "pump.fun" if "pump" in addr else "other"
            print(f"📊 {addr[:20]}... ({token_name}): {info['total_txs']} tx, {info['lifespan_hours']:.1f}h")
        
        return tokens
    
    def find_activity_periods(self, token_df):
        """Trouve les périodes d'activité concentrée pour un token"""
        if len(token_df) < 3:
            return []
        
        token_df = token_df.sort_values('datetime')
        periods = []
        
        # Calculer les gaps entre transactions
        token_df['time_diff'] = token_df['datetime'].diff().dt.total_seconds().fillna(0)
        
        # Identifier les sessions (gap < 2 heures)
        current_session = []
        
        for _, tx in token_df.iterrows():
            if tx['time_diff'] > 7200:  # 2 heures = nouvelle session
                if len(current_session) >= 3:  # Session significative
                    periods.append(self.analyze_session(current_session))
                current_session = [tx]
            else:
                current_session.append(tx)
        
        # Dernière session
        if len(current_session) >= 3:
            periods.append(self.analyze_session(current_session))
        
        return periods
    
    def analyze_session(self, session_txs):
        """Analyse une session d'activité"""
        session_df = pd.DataFrame(session_txs)
        
        buys = session_df[session_df['Type'] == 'inc']
        sells = session_df[session_df['Type'] == 'dec']
        
        start_time = session_df['datetime'].min()
        end_time = session_df['datetime'].max()
        duration_minutes = (end_time - start_time).total_seconds() / 60
        
        return {
            'start': start_time,
            'end': end_time,
            'duration_minutes': duration_minutes,
            'total_txs': len(session_df),
            'buys': len(buys),
            'sells': len(sells),
            'buy_ratio': len(buys) / len(session_df) if len(session_df) > 0 else 0,
            'tx_per_minute': len(session_df) / max(duration_minutes, 1),
            'amounts': session_df['Amount'].abs().tolist() if 'Amount' in session_df.columns else []
        }
    
    def analyze_token_for_rug_pattern(self, token_addr, token_info):
        """Analyse un token spécifique pour des patterns de rug"""
        score = 0
        signals = []
        
        print(f"\n🔍 Analyse token: {token_addr[:20]}...")
        
        # Pattern 1: Sessions d'activité suspectes
        suspicious_sessions = 0
        for period in token_info['periods']:
            session_score = 0
            
            # Vitesse suspecte
            if period['tx_per_minute'] > 0.5:  # Plus de 0.5 tx/min
                session_score += 3
                signals.append(f"Session rapide: {period['tx_per_minute']:.1f} tx/min")
            
            # Déséquilibre achats/ventes
            if period['buy_ratio'] > 0.8:  # Plus de 80% d'achats
                session_score += 4
                signals.append(f"Accumulation massive: {period['buy_ratio']*100:.1f}% achats")
            elif period['buy_ratio'] < 0.2:  # Plus de 80% de ventes
                session_score += 4
                signals.append(f"Dump massif: {(1-period['buy_ratio'])*100:.1f}% ventes")
            
            # Concentration temporelle
            if period['duration_minutes'] < 60 and period['total_txs'] > 10:
                session_score += 3
                signals.append(f"Activité concentrée: {period['total_txs']} tx en {period['duration_minutes']:.1f}min")
            
            if session_score >= 6:  # Session très suspecte
                suspicious_sessions += 1
        
        score += suspicious_sessions * 3
        
        # Pattern 2: Lifespan court avec beaucoup d'activité
        if token_info['lifespan_hours'] < 2 and token_info['total_txs'] > 15:
            score += 4
            signals.append(f"Activité intense courte: {token_info['total_txs']} tx en {token_info['lifespan_hours']:.1f}h")
        elif token_info['lifespan_hours'] < 24 and token_info['total_txs'] > 30:
            score += 2
            signals.append(f"Beaucoup d'activité: {token_info['total_txs']} tx en {token_info['lifespan_hours']:.1f}h")
        
        # Pattern 3: Token pump.fun (plus risqué)
        if "pump" in token_addr:
            score += 2
            signals.append("Token pump.fun détecté")
        
        # Pattern 4: Séquence accumulation → dump
        if len(token_info['periods']) >= 2:
            # Vérifier si première période = accumulation, dernière = dump
            first_period = token_info['periods'][0]
            last_period = token_info['periods'][-1]
            
            if first_period['buy_ratio'] > 0.7 and last_period['buy_ratio'] < 0.3:
                score += 5
                signals.append("Pattern accumulation → dump détecté")
        
        return {
            'token_address': token_addr,
            'risk_score': min(10, score),
            'signals': signals,
            'suspicious_sessions': suspicious_sessions,
            'lifespan_hours': token_info['lifespan_hours'],
            'total_transactions': token_info['total_txs']
        }
    
    def analyze_wallet_overall_behavior(self, df, token_analyses):
        """Analyse le comportement global du wallet"""
        score = 0
        patterns = []
        
        print(f"\n🏦 ANALYSE COMPORTEMENT GLOBAL WALLET:")
        
        # Pattern 1: Spécialisation pump.fun
        pump_tokens = [addr for addr in token_analyses.keys() if "pump" in addr]
        if len(pump_tokens) > 0:
            pump_ratio = len(pump_tokens) / len(token_analyses)
            print(f"📊 Spécialisation pump.fun: {pump_ratio*100:.1f}% ({len(pump_tokens)}/{len(token_analyses)})")
            
            if pump_ratio > 0.8:  # Plus de 80% pump.fun
                score += 4
                patterns.append(f"Spécialiste pump.fun ({pump_ratio*100:.1f}%)")
            elif pump_ratio > 0.5:
                score += 2
                patterns.append(f"Focus pump.fun ({pump_ratio*100:.1f}%)")
        
        # Pattern 2: Fréquence d'activité
        total_days = (df['datetime'].max() - df['datetime'].min()).days + 1
        tokens_per_day = len(token_analyses) / total_days
        print(f"📅 Fréquence: {tokens_per_day:.2f} tokens/jour sur {total_days} jours")
        
        if tokens_per_day > 2:  # Plus de 2 tokens par jour
            score += 3
            patterns.append(f"Hyperactivité: {tokens_per_day:.1f} tokens/jour")
        elif tokens_per_day > 1:
            score += 1
            patterns.append(f"Très actif: {tokens_per_day:.1f} tokens/jour")
        
        # Pattern 3: Tokens à risque élevé
        high_risk_tokens = [analysis for analysis in token_analyses.values() 
                          if analysis['risk_score'] >= 7]
        if len(high_risk_tokens) > 0:
            risk_ratio = len(high_risk_tokens) / len(token_analyses)
            print(f"🚨 Tokens à risque: {len(high_risk_tokens)}/{len(token_analyses)} ({risk_ratio*100:.1f}%)")
            
            if risk_ratio > 0.5:  # Plus de 50% de tokens suspects
                score += 5
                patterns.append(f"Majorité de tokens suspects ({risk_ratio*100:.1f}%)")
            elif risk_ratio > 0.3:
                score += 3
                patterns.append(f"Beaucoup de tokens suspects ({risk_ratio*100:.1f}%)")
        
        # Pattern 4: Durée de vie moyenne des tokens
        avg_lifespan = np.mean([analysis['lifespan_hours'] for analysis in token_analyses.values()])
        print(f"⏰ Durée de vie moyenne: {avg_lifespan:.1f}h")
        
        if avg_lifespan < 6:  # Moins de 6h en moyenne
            score += 3
            patterns.append(f"Tokens très éphémères (avg: {avg_lifespan:.1f}h)")
        elif avg_lifespan < 24:  # Moins de 24h
            score += 1
            patterns.append(f"Tokens éphémères (avg: {avg_lifespan:.1f}h)")
        
        return {
            'wallet_score': min(10, score),
            'patterns': patterns,
            'pump_ratio': len(pump_tokens) / len(token_analyses) if len(token_analyses) > 0 else 0,
            'tokens_per_day': tokens_per_day,
            'avg_lifespan_hours': avg_lifespan,
            'high_risk_tokens': len(high_risk_tokens)
        }
    
    def generate_comprehensive_report(self, csv_file_path):
        """Génère un rapport complet multi-token"""
        print("🚨 DÉTECTEUR MULTI-TOKEN - CRÉATEUR SUSPECT")
        print("=" * 70)
        
        # Chargement des données
        df = self.load_data(csv_file_path)
        if df is None:
            return None
        
        # Identification des tokens et périodes
        tokens_info = self.identify_tokens_and_periods(df)
        if not tokens_info:
            print("❌ Aucun token trouvé à analyser")
            return None
        
        # Analyse de chaque token
        token_analyses = {}
        print(f"\n🔍 ANALYSE INDIVIDUELLE DES TOKENS:")
        print("-" * 50)
        
        for token_addr, token_info in tokens_info.items():
            analysis = self.analyze_token_for_rug_pattern(token_addr, token_info)
            token_analyses[token_addr] = analysis
            
            print(f"📊 Score: {analysis['risk_score']}/10")
            for signal in analysis['signals']:
                print(f"   🚩 {signal}")
        
        # Analyse comportement global
        wallet_analysis = self.analyze_wallet_overall_behavior(df, token_analyses)
        
        # Score final pondéré
        # 60% comportement global + 40% moyenne des tokens individuels
        avg_token_score = np.mean([analysis['risk_score'] for analysis in token_analyses.values()])
        final_score = (wallet_analysis['wallet_score'] * 0.6) + (avg_token_score * 0.4)
        
        # Classification finale
        if final_score >= 7.5:
            verdict = "🚨 SCAMMER PROFESSIONNEL CONFIRMÉ"
            safety = "1/10 - EXTRÊMEMENT DANGEREUX"
            action = "BLACKLISTER IMMÉDIATEMENT"
        elif final_score >= 6.0:
            verdict = "⚠️ RUGGER PROBABLE"
            safety = "2/10 - TRÈS DANGEREUX"
            action = "ÉVITER ABSOLUMENT"
        elif final_score >= 4.5:
            verdict = "🔴 CRÉATEUR TRÈS SUSPECT"
            safety = "3/10 - DANGEREUX"
            action = "NE PAS INVESTIR"
        elif final_score >= 3.0:
            verdict = "🟡 COMPORTEMENT DOUTEUX"
            safety = "5/10 - RISQUÉ"
            action = "PRUDENCE MAXIMALE"
        elif final_score >= 2.0:
            verdict = "🔵 SURVEILLANCE RECOMMANDÉE"
            safety = "7/10 - ACCEPTABLE"
            action = "ANALYSER DAVANTAGE"
        else:
            verdict = "✅ CRÉATEUR LÉGITIME"
            safety = "9/10 - SÛR"
            action = "INVESTISSEMENT POSSIBLE"
        
        # Affichage du rapport final
        print(f"\n" + "=" * 70)
        print(f"📋 RAPPORT FINAL - CRÉATEUR DE TOKEN")
        print(f"=" * 70)
        
        print(f"🎯 Tokens analysés: {len(token_analyses)}")
        print(f"📊 Score wallet global: {wallet_analysis['wallet_score']:.1f}/10")
        print(f"📊 Score tokens moyen: {avg_token_score:.1f}/10")
        print(f"🚨 SCORE FINAL: {final_score:.1f}/10")
        
        print(f"\n🏷️ PATTERNS DÉTECTÉS:")
        for pattern in wallet_analysis['patterns']:
            print(f"   • {pattern}")
        
        print(f"\n🎯 TOKENS À HAUT RISQUE:")
        high_risk = [analysis for analysis in token_analyses.values() if analysis['risk_score'] >= 7]
        for analysis in high_risk:
            print(f"   🚨 {analysis['token_address'][:30]}... (Score: {analysis['risk_score']}/10)")
        
        print(f"\n" + "=" * 70)
        print(f"📋 VERDICT: {verdict}")
        print(f"🛡️ SÉCURITÉ: {safety}")
        print(f"🎬 ACTION: {action}")
        print("=" * 70)
        
        return {
            'final_score': final_score,
            'verdict': verdict,
            'safety': safety,
            'action': action,
            'wallet_analysis': wallet_analysis,
            'token_analyses': token_analyses,
            'tokens_count': len(token_analyses),
            'high_risk_tokens': len(high_risk)
        }

# Fonction principale
def analyze_wallet_creator(csv_file_path):
    detector = MultiTokenScamDetector()
    return detector.generate_comprehensive_report(csv_file_path)

# Test
if __name__ == "__main__":
    csv_file = "export_balance_change_3S3wPvBnGegy9Zj9LDMaRPn2d2pxakE9YdKPm8UM3WLP_1755110869587.csv"
    
    print("🚀 ANALYSE MULTI-TOKEN DU CRÉATEUR...")
    print(f"📁 Fichier: {csv_file}")
    print()
    
    result = analyze_wallet_creator(csv_file)
    
    if result:
        print(f"\n🎯 RÉSUMÉ EXÉCUTIF:")
        print(f"📊 Score final: {result['final_score']:.1f}/10")
        print(f"🪙 Tokens analysés: {result['tokens_count']}")
        print(f"🚨 Tokens à haut risque: {result['high_risk_tokens']}")
        print(f"📋 {result['verdict']}")
        print(f"🎬 {result['action']}")