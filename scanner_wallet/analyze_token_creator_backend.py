#!/usr/bin/env python3
"""
API Flask pour l'Analyseur de Token Solana
Exposé via HTTP pour intégration avec le dashboard
"""

from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import requests
import csv
import json
import time
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import os
import threading
from concurrent.futures import ThreadPoolExecutor
import tempfile

import subprocess
import sys
from pathlib import Path
import tempfile

# Configuration des logs
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/token_analyzer_api.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Configuration Flask
app = Flask(__name__)
app = Flask(__name__, template_folder='templates')
CORS(app)

class TokenCreatorScamDetector:
    def __init__(self):
        self.risk_factors = {
            'temporal_concentration': 0,
            'transaction_frequency': 0,
            'accumulation_pattern': 0,
            'automation_score': 0,
            'rug_preparation': 0
        }
        
    def load_data(self, csv_file_path):
        """Charge et analyse les données CSV au format Solscan"""
        try:
            import pandas as pd
            df = pd.read_csv(csv_file_path)
            df.columns = df.columns.str.strip()
            
            logger.info(f"🔍 Colonnes détectées: {list(df.columns)}")
            
            # Adapter au format Solscan
            if 'BlockTimeUnix' in df.columns:
                df['datetime'] = pd.to_datetime(df['BlockTimeUnix'], unit='s')
            elif 'BlockTime' in df.columns:
                df['datetime'] = pd.to_datetime(df['BlockTime'])
            else:
                logger.error("❌ Aucune colonne de temps trouvée!")
                return None
            
            # Adapter les colonnes pour l'analyse
            if 'ChangeAmount' in df.columns:
                df['Amount'] = df['ChangeAmount'] / 1e9
            else:
                logger.error("❌ Colonne ChangeAmount manquante!")
                return None
                
            if 'ChangeType' in df.columns:
                df['Type'] = df['ChangeType']
            else:
                logger.error("❌ Colonne ChangeType manquante!")
                return None
            
            logger.info(f"📊 Données préparées: {len(df)} transactions")
            logger.info(f"📅 Période: {df['datetime'].min()} → {df['datetime'].max()}")
            
            return df
            
        except ImportError:
            logger.error("❌ pandas requis pour l'analyse de scam. Installez: pip install pandas")
            return None
        except Exception as e:
            logger.error(f"❌ Erreur lors du chargement: {e}")
            return None
    
    def analyze_temporal_concentration(self, df):
        """Analyse de la concentration temporelle"""
        if df.empty:
            return {'time_span_minutes': 0, 'transaction_count': 0, 'risk_score': 0}
            
        time_span = (df['datetime'].max() - df['datetime'].min()).total_seconds() / 60
        transaction_count = len(df)
        
        tx_per_minute = transaction_count / max(time_span, 1)
        
        if tx_per_minute >= 2.0:
            score = 10
        elif tx_per_minute >= 1.5:
            score = 10
        elif tx_per_minute >= 1.2:
            score = 9
        elif tx_per_minute >= 1.0:
            score = 8
        elif tx_per_minute >= 0.8:
            score = 7
        elif tx_per_minute >= 0.5:
            score = 5
        else:
            score = 2
        
        if time_span <= 60 and transaction_count >= 80:
            score = 10
        elif time_span <= 90 and transaction_count >= 90:
            score = 10
        elif time_span <= 120 and transaction_count >= 100:
            score = 9
        
        avg_seconds = (time_span * 60) / transaction_count if transaction_count > 0 else 0
        if avg_seconds < 30:
            score = min(10, score + 2)
        elif avg_seconds < 45:
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
        """Détection de patterns robotiques"""
        if len(df) < 3:
            return {'risk_score': 0, 'mean_interval_seconds': 0, 'coefficient_variation': 0}
            
        df_sorted = df.sort_values('datetime')
        intervals = df_sorted['datetime'].diff().dt.total_seconds().dropna()
        
        if len(intervals) == 0:
            return {'risk_score': 0, 'mean_interval_seconds': 0, 'coefficient_variation': 0}
        
        mean_interval = intervals.mean()
        std_interval = intervals.std()
        coefficient_variation = std_interval / mean_interval if mean_interval > 0 else 0
        
        if coefficient_variation < 0.05:
            score = 10
        elif coefficient_variation < 0.1 and mean_interval < 10:
            score = 10
        elif coefficient_variation < 0.15:
            score = 9
        elif coefficient_variation < 0.25 and mean_interval < 30:
            score = 8
        elif coefficient_variation < 0.3:
            score = 6
        else:
            score = 2
            
        if mean_interval < 5:
            score = min(10, score + 3)
        elif mean_interval < 10:
            score = min(10, score + 2)
            
        self.risk_factors['transaction_frequency'] = score
        
        return {
            'mean_interval_seconds': round(mean_interval, 2),
            'coefficient_variation': round(coefficient_variation, 3),
            'risk_score': score
        }
    
    def analyze_accumulation_pattern(self, df):
        """Détection du pattern d'accumulation puis vidage"""
        if len(df) < 10:
            return {
                'risk_score': 0,
                'deposit_count': 0,
                'withdrawal_count': 0,
                'deposit_ratio': 0.0,
                'withdrawal_ratio': 0.0,
                'imbalance_ratio': 0.0
            }
            
        df_sorted = df.sort_values('datetime')
        
        deposits = df_sorted[df_sorted['Type'] == 'inc']
        withdrawals = df_sorted[df_sorted['Type'] == 'dec']
        
        deposit_count = len(deposits)
        withdrawal_count = len(withdrawals)
        total_count = len(df_sorted)
        
        if total_count == 0:
            return {
                'risk_score': 0,
                'deposit_count': 0,
                'withdrawal_count': 0,
                'deposit_ratio': 0.0,
                'withdrawal_ratio': 0.0,
                'imbalance_ratio': 0.0
            }
        
        deposit_ratio = deposit_count / total_count
        withdrawal_ratio = withdrawal_count / total_count
        
        score = 0
        
        if deposit_ratio >= 0.8:
            score += 6
        elif deposit_ratio >= 0.75:
            score += 5
        elif deposit_ratio >= 0.7:
            score += 4
        elif deposit_ratio >= 0.65:
            score += 3
        elif deposit_ratio >= 0.6:
            score += 2
            
        # Pattern 2: Ratio extrême de déséquilibre
        imbalance = abs(deposit_ratio - withdrawal_ratio)
        if imbalance >= 0.6:
            score += 3
        elif imbalance >= 0.5:
            score += 2
        elif imbalance >= 0.4:
            score += 1
        
        if len(deposits) > 0 and len(withdrawals) > 0:
            avg_deposit_time = deposits['datetime'].mean()
            avg_withdrawal_time = withdrawals['datetime'].mean()
            
            if avg_withdrawal_time > avg_deposit_time:
                time_gap = (avg_withdrawal_time - avg_deposit_time).total_seconds() / 60
                if time_gap < 30:
                    score += 4
                elif time_gap < 60:
                    score += 3
                elif time_gap < 180:
                    score += 2
                elif time_gap < 360:
                    score += 1
        
        if total_count >= 80 and deposit_ratio >= 0.75:
            score += 2
        
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
        """Détection d'automatisation"""
        if len(df) < 5:
            return {'risk_score': 0, 'patterns_detected': 0}
            
        patterns_detected = 0
        
        if 'Amount' in df.columns:
            amount_counts = df['Amount'].abs().value_counts()
            if len(amount_counts) > 0:
                most_common_ratio = amount_counts.iloc[0] / len(df)
                if most_common_ratio > 0.5:
                    patterns_detected += 4
                elif most_common_ratio > 0.3:
                    patterns_detected += 3
                elif most_common_ratio > 0.2:
                    patterns_detected += 2
        
        df_sorted = df.sort_values('datetime')
        intervals = df_sorted['datetime'].diff().dt.total_seconds().dropna()
        
        if len(intervals) > 0:
            import pandas as pd
            interval_counts = pd.Series(intervals).round(0).value_counts()
            if len(interval_counts) > 0:
                most_common_interval_ratio = interval_counts.iloc[0] / len(intervals)
                if most_common_interval_ratio > 0.4:
                    patterns_detected += 4
                elif most_common_interval_ratio > 0.3:
                    patterns_detected += 3
        
        if 'Type' in df.columns and len(df) > 8:
            types = df_sorted['Type'].tolist()
            for pattern_length in [2, 3, 4]:
                for i in range(len(types) - pattern_length * 2):
                    pattern1 = types[i:i+pattern_length]
                    pattern2 = types[i+pattern_length:i+pattern_length*2]
                    if pattern1 == pattern2:
                        patterns_detected += 2
                        break
        
        hours = df['datetime'].dt.hour.value_counts()
        if len(hours) > 0 and hours.iloc[0] > len(df) * 0.8:
            patterns_detected += 3
        
        score = min(10, patterns_detected)
        self.risk_factors['automation_score'] = score
        
        return {
            'patterns_detected': patterns_detected,
            'risk_score': score
        }
    
    def analyze_rug_preparation_signals(self, df):
        """Détection des signaux de rug pull"""
        if len(df) < 10:
            return {'risk_score': 0, 'rug_signals_detected': 0}
            
        rug_signals = 0
        
        time_span_hours = (df['datetime'].max() - df['datetime'].min()).total_seconds() / 3600
        if time_span_hours < 1 and len(df) > 50:
            rug_signals += 5
        elif time_span_hours < 2 and len(df) > 80:
            rug_signals += 4
        elif time_span_hours < 6 and len(df) > 100:
            rug_signals += 3
        
        df_sorted = df.sort_values('datetime')
        first_half = df_sorted.iloc[:len(df_sorted)//2]
        second_half = df_sorted.iloc[len(df_sorted)//2:]
        
        first_half_deposits = sum(first_half['Type'] == 'inc')
        second_half_withdrawals = sum(second_half['Type'] == 'dec')
        
        if first_half_deposits > len(first_half) * 0.8:
            rug_signals += 3
        if second_half_withdrawals > len(second_half) * 0.6:
            rug_signals += 3
        
        if 'Amount' in df.columns:
            amounts = df_sorted['Amount'].abs()
            if len(amounts) > 5:
                last_quarter = amounts.iloc[-len(amounts)//4:]
                first_quarter = amounts.iloc[:len(amounts)//4]
                if last_quarter.mean() > first_quarter.mean() * 3:
                    rug_signals += 2
        
        score = min(10, rug_signals)
        self.risk_factors['rug_preparation'] = score
        
        return {
            'rug_signals_detected': rug_signals,
            'risk_score': score
        }
    
    def generate_scam_report(self, csv_file_path):
        """Génère un rapport complet de détection de scam"""
        logger.info("🚨 ANALYSE DE RISQUE - DÉTECTEUR DE SCAM")
        
        df = self.load_data(csv_file_path)
        if df is None:
            return None
            
        logger.info(f"📊 Transactions analysées: {len(df)}")
        
        # Analyses spécialisées
        temporal_analysis = self.analyze_temporal_concentration(df)
        frequency_analysis = self.analyze_transaction_frequency(df)
        accumulation_analysis = self.analyze_accumulation_pattern(df)
        automation_analysis = self.analyze_automation_patterns(df)
        rug_analysis = self.analyze_rug_preparation_signals(df)
        
        # Calcul du score global pondéré
        weights = {
            'temporal_concentration': 0.35,
            'transaction_frequency': 0.20,
            'accumulation_pattern': 0.25,
            'automation_score': 0.10,
            'rug_preparation': 0.10
        }
        
        weighted_score = sum(self.risk_factors[factor] * weight 
                           for factor, weight in weights.items())
        
        # Bonus pour combinaisons mortelles
        if (self.risk_factors['temporal_concentration'] >= 8 and 
            self.risk_factors['accumulation_pattern'] >= 7):
            weighted_score = min(10, weighted_score + 1.5)
            
        if (self.risk_factors['automation_score'] >= 9 and 
            self.risk_factors['temporal_concentration'] >= 7):
            weighted_score = min(10, weighted_score + 1)
            
        if (self.risk_factors['temporal_concentration'] >= 7 and 
            self.risk_factors['accumulation_pattern'] >= 6 and 
            self.risk_factors['automation_score'] >= 8):
            weighted_score = min(10, weighted_score + 1.5)
        
        # Détermination du verdict
        if weighted_score >= 8.0:
            risk_level = "🚨 SCAMMER CONFIRMÉ"
            risk_emoji = "🔴"
            verdict = "ÉVITER ABSOLUMENT"
            investment_risk = "10/10 - DANGER EXTRÊME"
        elif weighted_score >= 6.5:
            risk_level = "⚠️ TRÈS SUSPECT"
            risk_emoji = "🟠"
            verdict = "PROBABLE SCAMMER"
            investment_risk = "9/10 - DANGER ÉLEVÉ"
        elif weighted_score >= 5.0:
            risk_level = "🔴 DOUTEUX"
            risk_emoji = "🟡"
            verdict = "COMPORTEMENT ANORMAL"
            investment_risk = "8/10 - RISQUE TRÈS ÉLEVÉ"
        elif weighted_score >= 3.5:
            risk_level = "🟡 SURVEILLANCE"
            risk_emoji = "🔵"
            verdict = "PATTERNS INHABITUELS"
            investment_risk = "6/10 - RISQUE ÉLEVÉ"
        elif weighted_score >= 2.0:
            risk_level = "🔵 ACCEPTABLE"
            risk_emoji = "🟢"
            verdict = "COMPORTEMENT NORMAL"
            investment_risk = "3/10 - RISQUE FAIBLE"
        else:
            risk_level = "✅ LÉGITIME"
            risk_emoji = "🟢"
            verdict = "CRÉATEUR FIABLE"
            investment_risk = "1/10 - TRÈS SÛR"
            
        logger.info(f"🎯 SCORE GLOBAL: {weighted_score:.1f}/10")
        logger.info(f"{risk_emoji} NIVEAU: {risk_level}")
        logger.info(f"📋 VERDICT: {verdict}")
        logger.info(f"💰 RISQUE D'INVESTISSEMENT: {investment_risk}")
        
        return {
            'risk_score': round(weighted_score, 1),
            'investment_risk': investment_risk,
            'risk_level': risk_level,
            'verdict': verdict,
            'risk_emoji': risk_emoji,
            'detailed_scores': self.risk_factors,
            'analyses': {
                'temporal': temporal_analysis,
                'frequency': frequency_analysis,
                'accumulation': accumulation_analysis,
                'automation': automation_analysis,
                'rug_preparation': rug_analysis
            }
        }

class TokenCreatorAnalyzer:
    def __init__(self, quicknode_endpoint: str = None):
        """
        Initialise l'analyseur avec la configuration QuickNode
        """
        if not quicknode_endpoint:
            # Essayer de récupérer depuis les variables d'environnement
            quicknode_endpoint = os.getenv('QUICKNODE_ENDPOINT')
            
        if not quicknode_endpoint:
            logger.error("❌ ERREUR: Endpoint QuickNode requis!")
            logger.error("💡 Configurez votre endpoint QuickNode:")
            logger.error("   export QUICKNODE_ENDPOINT='https://your-endpoint.solana-mainnet.quiknode.pro/...'")
            raise ValueError("Endpoint QuickNode requis pour éviter les rate limits")
        
        self.quicknode_endpoint = quicknode_endpoint
        self.rpc_endpoints = [quicknode_endpoint]
        self.current_rpc_index = 0
        self.request_count = 0
        self.token_cache = {}
        
        # Configuration rate limiting pour compte gratuit QuickNode
        self.rate_limit_delay = 0.5
        self.max_retries = 2
        self.retry_delay = 3
        self.requests_per_minute = 0
        self.last_minute_start = time.time()
        self.max_requests_per_minute = 120
        
        logger.info(f"✅ Analyseur QuickNode initialisé")
        logger.info(f"🚀 Endpoint: {quicknode_endpoint[:50]}...")
        logger.info(f"⚡ Rate limit: {self.rate_limit_delay}s entre requêtes")
        logger.info(f"📊 Limite: {self.max_requests_per_minute} req/minute")

    def rate_limited_rpc_call(self, method: str, params: List) -> Optional[Dict]:
        """Appel RPC avec gestion du rate limit strict pour QuickNode gratuit"""
        current_time = time.time()
        if current_time - self.last_minute_start >= 60:
            self.requests_per_minute = 0
            self.last_minute_start = current_time
        
        if self.requests_per_minute >= self.max_requests_per_minute:
            wait_time = 60 - (current_time - self.last_minute_start)
            if wait_time > 0:
                logger.warning(f"⏳ Limite QuickNode atteinte, pause de {wait_time:.1f}s...")
                time.sleep(wait_time)
                self.requests_per_minute = 0
                self.last_minute_start = current_time
        
        self.request_count += 1
        self.requests_per_minute += 1
        
        if self.request_count % 10 == 0:
            logger.info(f"📊 Requêtes QuickNode: {self.request_count} total, {self.requests_per_minute}/min")
        
        result = self._solana_rpc_call(method, params)
        time.sleep(self.rate_limit_delay)
        return result

    def _solana_rpc_call(self, method: str, params: List) -> Optional[Dict]:
        """Effectue un appel RPC uniquement vers QuickNode"""
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params
        }

        for attempt in range(self.max_retries):
            try:
                headers = {
                    'Content-Type': 'application/json',
                    'User-Agent': 'TokenCreatorAnalyzer/1.0-QuickNode-API',
                    'Accept': 'application/json',
                }
                
                response = requests.post(
                    self.quicknode_endpoint,
                    json=payload,
                    timeout=20,
                    headers=headers
                )

                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 429:
                    retry_after = int(response.headers.get('Retry-After', 10))
                    logger.warning(f"⚠️ Rate limit QuickNode, attente {retry_after}s...")
                    time.sleep(retry_after)
                    continue
                elif response.status_code == 403:
                    logger.error(f"❌ Accès refusé QuickNode - vérifiez votre endpoint")
                    logger.error(f"💡 URL utilisée: {self.quicknode_endpoint[:50]}...")
                    return None
                else:
                    logger.error(f"❌ Erreur HTTP {response.status_code}: {response.text[:100]}")
                    response.raise_for_status()

            except requests.exceptions.Timeout:
                logger.warning(f"⏰ Timeout QuickNode (tentative {attempt + 1}/{self.max_retries})")
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay * (attempt + 1))
            except requests.exceptions.ConnectionError as e:
                logger.error(f"🔌 Erreur de connexion QuickNode: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay * (attempt + 1))
            except requests.RequestException as e:
                logger.error(f"❌ Erreur requête QuickNode: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay * (attempt + 1))

        logger.error("❌ Échec de toutes les tentatives vers QuickNode")
        return None

    def find_token_creator(self, token_address: str) -> Optional[str]:
        """
        Trouve le créateur d'un token en analysant ses premières transactions
        """
        logger.info(f"🔍 Recherche du créateur pour le token: {token_address}")
        
        signatures_result = self.rate_limited_rpc_call(
            "getSignaturesForAddress",
            [token_address, {"limit": 1000}]
        )

        if not signatures_result or "result" not in signatures_result:
            logger.error(f"❌ Impossible de récupérer les signatures pour {token_address}")
            return None

        signatures = signatures_result["result"]
        logger.info(f"📊 Trouvé {len(signatures)} signatures pour le token")

        if not signatures:
            logger.warning("⚠️ Aucune signature trouvée")
            return None

        creation_signature = signatures[-1]["signature"]
        logger.info(f"🎯 Analyse de la transaction de création: {creation_signature[:16]}...")

        tx_details = self.rate_limited_rpc_call(
            "getTransaction",
            [creation_signature, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}]
        )

        if not tx_details or not tx_details.get("result"):
            logger.error("❌ Impossible de récupérer les détails de la transaction de création")
            return None

        tx = tx_details["result"]
        accounts = tx.get("transaction", {}).get("message", {}).get("accountKeys", [])
        
        if not accounts:
            logger.error("❌ Aucun compte trouvé dans la transaction")
            return None

        creator = accounts[0]
        creator_address = creator.get("pubkey") if isinstance(creator, dict) else creator
        logger.info(f"✅ Créateur identifié: {creator_address}")
        return creator_address

    def get_token_ata(self, creator_address: str, token_address: str) -> Optional[str]:
        """
        Récupère l'ATA du créateur pour un token spécifique
        """
        logger.info(f"🔍 Recherche de l'ATA pour {creator_address[:8]}... et token {token_address[:8]}...")
        
        token_accounts_result = self.rate_limited_rpc_call(
            "getTokenAccountsByOwner",
            [
                creator_address,
                {"mint": token_address},
                {"encoding": "jsonParsed"}
            ]
        )

        if not token_accounts_result or "result" not in token_accounts_result:
            logger.error(f"❌ Impossible de récupérer l'ATA pour {token_address}")
            return None

        accounts = token_accounts_result["result"]["value"]
        if not accounts:
            logger.warning(f"⚠️ Aucun ATA trouvé pour {token_address}")
            return None

        ata_pubkey = accounts[0]["pubkey"]
        logger.info(f"✅ ATA trouvé: {ata_pubkey}")
        return ata_pubkey

    def scan_ata_transactions(self, ata_pubkey: str, token_address: str, hours_back: int = 24, max_transactions: int = None) -> List[Dict]:
        """
        Scanne les transactions de l'ATA spécifique pour le token
        """
        logger.info(f"🔍 Scan des transactions de l'ATA {ata_pubkey[:8]}... pour {token_address[:8]}... (dernières {hours_back}h)")
        
        current_time = int(time.time())
        scan_window = hours_back * 3600
        
        limit = 1000 if max_transactions is None else min(max_transactions + 50, 1000)
        signatures_result = self.rate_limited_rpc_call(
            "getSignaturesForAddress",
            [ata_pubkey, {"limit": limit, "commitment": "finalized"}]
        )

        if not signatures_result or "result" not in signatures_result:
            logger.error("❌ Impossible de récupérer les signatures de l'ATA")
            return []

        recent_signatures = [
            sig for sig in signatures_result["result"]
            if sig.get("blockTime") and sig["blockTime"] >= (current_time - scan_window)
        ]

        logger.info(f"📊 {len(recent_signatures)} signatures dans la période de {hours_back}h")
        
        if max_transactions is not None and len(recent_signatures) > max_transactions:
            logger.info(f"⚠️ Limitation appliquée: {max_transactions} transactions sur {len(recent_signatures)}")
            recent_signatures = recent_signatures[:max_transactions]

        balance_changes = []
        processed_signatures = set()
        transactions_with_changes = 0

        total_signatures = len(recent_signatures)
        for i, sig_info in enumerate(recent_signatures):
            if i % 5 == 0 or i == total_signatures - 1:
                progress = (i + 1) / total_signatures * 100
                logger.info(f"📈 Progression: {i + 1}/{total_signatures} ({progress:.1f}%) - "
                           f"Balance changes trouvés: {len(balance_changes)}")

            signature = sig_info["signature"]
            if signature in processed_signatures:
                continue
            processed_signatures.add(signature)

            tx_detail = self.rate_limited_rpc_call(
                "getTransaction",
                [signature, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}]
            )

            if not tx_detail or not tx_detail.get("result"):
                logger.debug(f"⚠️ Transaction {signature[:8]}... ignorée (pas de détails)")
                continue

            balance_change_txs = self._analyze_ata_transaction(
                tx_detail, ata_pubkey, token_address, sig_info
            )
            
            if balance_change_txs:
                balance_changes.extend(balance_change_txs)
                transactions_with_changes += 1
                logger.info(f"✅ {len(balance_change_txs)} balance changes dans {signature[:8]}...")
            else:
                logger.debug(f"⚪ Pas de balance change dans {signature[:8]}...")

        logger.info(f"✅ Scan terminé:")
        logger.info(f"   📊 Transactions analysées: {len(processed_signatures)}")
        logger.info(f"   💰 Transactions avec balance changes: {transactions_with_changes}")
        logger.info(f"   🎯 Total balance changes: {len(balance_changes)}")
        return balance_changes

    def _analyze_ata_transaction(self, tx_detail: Dict, ata_pubkey: str, token_address: str, sig_info: Dict) -> List[Dict]:
        """
        Analyse une transaction de l'ATA pour extraire les balance changes
        """
        try:
            tx = tx_detail["result"]
            meta = tx.get("meta", {})
            balance_changes = []
            signature = sig_info["signature"]
            
            pre_token_balances = meta.get("preTokenBalances", [])
            post_token_balances = meta.get("postTokenBalances", [])
            fee = meta.get("fee", 0) / 1e9
            
            for pre_balance in pre_token_balances:
                if pre_balance.get("mint") == token_address and pre_balance.get("accountIndex") < len(tx.get("transaction", {}).get("message", {}).get("accountKeys", [])):
                    owner = pre_balance.get("owner")
                    pre_amount = float(pre_balance.get("uiTokenAmount", {}).get("uiAmount") or 0)
                    decimals = pre_balance.get("uiTokenAmount", {}).get("decimals", 9)
                    for post_balance in post_token_balances:
                        if post_balance.get("mint") == token_address and post_balance.get("accountIndex") == pre_balance.get("accountIndex"):
                            post_amount = float(post_balance.get("uiTokenAmount", {}).get("uiAmount") or 0)
                            amount_change = post_amount - pre_amount
                            if abs(amount_change) > 0.0000001:
                                change_type = "inc" if amount_change > 0 else "dec"
                                balance_change = {
                                    "Txhash": signature,
                                    "BlockTimeUnix": sig_info.get("blockTime", 0),
                                    "BlockTime": datetime.fromtimestamp(sig_info.get("blockTime", 0)).strftime('%Y-%m-%dT%H:%M:%S') if sig_info.get("blockTime") else "",
                                    "Fee(SOL)": fee,
                                    "TokenAccount": owner,
                                    "ChangeType": change_type,
                                    "ChangeAmount": int(abs(amount_change) * (10 ** decimals)),
                                    "PreBalancer": int(pre_amount * (10 ** decimals)),
                                    "PostBalancer": int(post_amount * (10 ** decimals)),
                                    "TokenAddress": token_address,
                                    "TokenDecimals": decimals,
                                    "TokenMultiplier": 1.0
                                }
                                balance_changes.append(balance_change)
                                logger.debug(f"✅ Token change: {change_type.upper()} {abs(amount_change):,.4f}")
                            break
            
            return balance_changes

        except Exception as e:
            logger.error(f"❌ Erreur analyse transaction {signature[:10]}...: {e}")
            import traceback
            logger.debug(f"Traceback: {traceback.format_exc()}")
            return []

    def export_to_csv(self, data: List[Dict], filename: str):
        """Exporte les données vers un fichier CSV au format Solscan"""
        if not data:
            logger.warning("⚠️ Aucune donnée à exporter")
            return
        
        fieldnames = [
            'Txhash', 'BlockTimeUnix', 'BlockTime', 'Fee(SOL)', 'TokenAccount', 
            'ChangeType', 'ChangeAmount', 'PreBalancer', 'PostBalancer', 
            'TokenAddress', 'TokenDecimals', 'TokenMultiplier'
        ]
        
        with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(data)
        
        logger.info(f"✅ Données exportées au format Solscan vers {filename}")
        logger.info(f"📊 Format: {len(data)} lignes avec colonnes Solscan standard")


    def analyze_token_creator(self, token_address: str, output_filename: str = None, hours_back: int = 24, max_transactions: int = None, create_html_report: bool = False, creator_wallet: str = None):
        """
        Analyse les transactions avec détection de scam intégrée
        """
        logger.info("=" * 80)
        logger.info(f"🚀 ANALYSE COMPLÈTE DU TOKEN {token_address[:8]}...")
        logger.info(f"⏰ Période: {hours_back} heures")
        if max_transactions:
            logger.info(f"📊 Limitation: {max_transactions} transactions max")
        else:
            logger.info(f"🚀 Mode: ANALYSE COMPLÈTE")
        logger.info("=" * 80)

        try:
            # ÉTAPES 1-3: Analyse normale (comme avant)
            logger.info("\n🔍 ÉTAPE 1: IDENTIFICATION DU CRÉATEUR")
            logger.info("-" * 50)

            if creator_wallet:
                creator_address = creator_wallet
                logger.info(f"✅ Créateur fourni manuellement: {creator_address}")
            else:
                creator_address = self.find_token_creator(token_address)
                if not creator_address:
                    logger.error("❌ Impossible de trouver le créateur du token")
                    return None
                logger.info(f"✅ Créateur détecté automatiquement: {creator_address}")

            logger.info("\n🔍 ÉTAPE 2: RECHERCHE DE L'ATA")
            logger.info("-" * 50)
            
            ata_pubkey = self.get_token_ata(creator_address, token_address)
            if not ata_pubkey:
                logger.error("❌ Aucun ATA trouvé pour ce token")
                return None

            logger.info(f"✅ ATA identifié: {ata_pubkey}")

            logger.info("\n💰 ÉTAPE 3: SCAN DES TRANSACTIONS DE L'ATA")
            logger.info("-" * 50)
            
            scan_start = time.time()
            balance_changes = self.scan_ata_transactions(ata_pubkey, token_address, hours_back, max_transactions)
            scan_duration = time.time() - scan_start
            
            logger.info(f"✅ Scan terminé en {scan_duration:.1f}s")
            logger.info(f"💰 {len(balance_changes)} balance changes trouvés")

            # ÉTAPE 4: Export CSV (obligatoire pour l'analyse de scam)
            logger.info("\n💾 ÉTAPE 4: EXPORT DES DONNÉES")
            logger.info("-" * 50)
            
            if not output_filename:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                limit_suffix = f"_limit{max_transactions}" if max_transactions else "_full"
                output_filename = f"exports/balance_changes_{creator_address[:8]}_{token_address[:8]}_{timestamp}{limit_suffix}.csv"
                
                # Créer le dossier d'export s'il n'existe pas
                os.makedirs('exports', exist_ok=True)

            scam_analysis = None
            report_filename = None
            
            if balance_changes:
                self.export_to_csv(balance_changes, output_filename)
                
                # ÉTAPE 5: ANALYSE DE SCAM
                logger.info("\n🚨 ÉTAPE 5: ANALYSE DE RISQUE / DÉTECTION DE SCAM")
                logger.info("-" * 50)
                
                try:
                    # Vérifier si pandas est disponible
                    import pandas as pd
                    
                    scam_detector = TokenCreatorScamDetector()
                    scam_analysis = scam_detector.generate_scam_report(output_filename)
                    
                    if scam_analysis:
                        logger.info(f"✅ Analyse de risque terminée:")
                        logger.info(f"   🎯 Score de risque: {scam_analysis['risk_score']}/10")
                        logger.info(f"   📋 Verdict: {scam_analysis['verdict']}")
                        logger.info(f"   💰 Risque d'investissement: {scam_analysis['investment_risk']}")
                    else:
                        logger.warning("⚠️ Analyse de scam échouée")
                        
                except ImportError:
                    logger.warning("⚠️ pandas non disponible - analyse de scam désactivée")
                    logger.info("💡 Installez pandas pour activer l'analyse: pip install pandas")
                except Exception as e:
                    logger.error(f"❌ Erreur lors de l'analyse de scam: {e}")

                # ÉTAPE 6: Génération du rapport HTML (optionnel)
                if create_html_report:
                    logger.info("\n📊 ÉTAPE 6: GÉNÉRATION DU RAPPORT HTML")
                    logger.info("-" * 50)
                    
                    if scam_analysis:
                        report_filename = generate_html_report(
                            token_address, creator_address, balance_changes, scam_analysis
                        )
                        if report_filename:
                            logger.info(f"✅ Rapport HTML généré: {report_filename}")
                    else:
                        logger.warning("⚠️ Rapport HTML non généré (analyse de scam manquante)")
                
                # Statistiques finales
                inc_count = sum(1 for bc in balance_changes if bc['ChangeType'] == 'inc')
                dec_count = sum(1 for bc in balance_changes if bc['ChangeType'] == 'dec')
                
                logger.info(f"📊 Résumé des balance changes:")
                logger.info(f"   🟢 Augmentations (inc): {inc_count}")
                logger.info(f"   🔴 Réductions (dec): {dec_count}")
                logger.info(f"   📁 Fichier CSV: {output_filename}")
                
            else:
                logger.warning("⚠️ Aucun balance change trouvé - analyse de scam impossible")

            # RÉSULTATS FINAUX
            logger.info("\n" + "=" * 80)
            logger.info("🎉 ANALYSE COMPLÈTE TERMINÉE")
            logger.info("=" * 80)
            logger.info(f"🪙 Token analysé: {token_address}")
            logger.info(f"👤 Créateur: {creator_address}")
            logger.info(f"📊 ATA: {ata_pubkey}")
            logger.info(f"💰 Balance changes: {len(balance_changes)}")
            if scam_analysis:
                logger.info(f"🚨 Score de risque: {scam_analysis['risk_score']}/10")
                logger.info(f"📋 Verdict: {scam_analysis['verdict']}")
            logger.info(f"🔢 Requêtes RPC totales: {self.request_count}")
            logger.info(f"⏱️ Durée totale: {scan_duration:.1f}s")
            logger.info("=" * 80)

            return {
                "token_address": token_address,
                "creator_address": creator_address,
                "ata_pubkey": ata_pubkey,
                "balance_changes_count": len(balance_changes),
                "balance_changes": balance_changes,
                "output_file": output_filename if balance_changes else None,
                "scan_duration": scan_duration,
                "rpc_requests": self.request_count,
                "scam_analysis": scam_analysis,
                "html_report": report_filename
            }

        except Exception as e:
            logger.error(f"❌ Erreur lors de l'analyse: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return None

# Instance globale de l'analyseur
analyzer = None

def get_risk_color(score):
    """Retourne la couleur CSS selon le score de risque global"""
    if score >= 8.0:
        return "danger-color"
    elif score >= 6.5:
        return "danger-color" 
    elif score >= 5.0:
        return "warning-color"
    elif score >= 3.5:
        return "warning-color"
    elif score >= 2.0:
        return "primary-color"
    else:
        return "success-color"

def get_metric_color(score):
    """Retourne la couleur selon le score métrique"""
    if score >= 8:
        return "danger-color"
    elif score >= 6:
        return "warning-color"
    elif score >= 4:
        return "warning-color"
    else:
        return "success-color"

def get_recommendations_html(risk_score):
    """Génère les recommandations HTML selon le score"""
    if risk_score >= 8.5:
        return """
            <li>🚫 <strong>NE PAS INVESTIR</strong> - Pattern de scammer détecté</li>
            <li>🏃 <strong>FUIR</strong> ce token immédiatement</li>
            <li>📢 <strong>ALERTER</strong> la communauté</li>
            <li>🔍 Vérifier si le token est déjà ruggé</li>
        """
    elif risk_score >= 7.0:
        return """
            <li>⚠️ <strong>EXTRÊMEMENT RISQUÉ</strong></li>
            <li>💰 Investissement fortement déconseillé</li>
            <li>📊 Attendre confirmation avant tout achat</li>
            <li>🔍 Surveiller l'évolution du token</li>
        """
    elif risk_score >= 5.5:
        return """
            <li>🟡 <strong>PRUDENCE MAXIMALE</strong></li>
            <li>💰 Si investissement: montant symbolique uniquement</li>
            <li>⏰ Analyser l'évolution sur plusieurs jours</li>
            <li>📈 Vérifier les fondamentaux du projet</li>
        """
    elif risk_score >= 4.0:
        return """
            <li>🔵 <strong>SURVEILLANCE RECOMMANDÉE</strong></li>
            <li>📊 Analyser d'autres métriques</li>
            <li>💰 Investissement avec prudence</li>
            <li>🤝 Vérifier la réputation de l'équipe</li>
        """
    else:
        return """
            <li>✅ <strong>PROFIL ACCEPTABLE</strong></li>
            <li>📈 Continuer l'analyse fondamentale</li>
            <li>💎 Peut être un bon investissement</li>
            <li>🔍 Vérifier quand même les tokenomics</li>
        """

def generate_html_report(token_address, creator_address, balance_changes, scam_analysis):
    """Génère un rapport HTML complet avec analyse de risque - VERSION CORRIGÉE"""
    
    if not scam_analysis:
        return None
    
    # Créer le dossier templates s'il n'existe pas
    os.makedirs('templates', exist_ok=True)
    
    # CORRECTION: Vérifier que les données d'accumulation existent
    accumulation_data = scam_analysis['analyses'].get('accumulation', {})
    deposit_count = accumulation_data.get('deposit_count', 0)
    withdrawal_count = accumulation_data.get('withdrawal_count', 0)
    deposit_ratio = accumulation_data.get('deposit_ratio', 0.0)
    withdrawal_ratio = accumulation_data.get('withdrawal_ratio', 0.0)
    
    # CORRECTION: Vérifier que les données temporelles existent
    temporal_data = scam_analysis['analyses'].get('temporal', {})
    transaction_count = temporal_data.get('transaction_count', 0)
    time_span_minutes = temporal_data.get('time_span_minutes', 0.0)
    transactions_per_minute = temporal_data.get('transactions_per_minute', 0.0)
    
    # CORRECTION: Vérifier que les données de fréquence existent
    frequency_data = scam_analysis['analyses'].get('frequency', {})
    mean_interval_seconds = frequency_data.get('mean_interval_seconds', 0.0)
    coefficient_variation = frequency_data.get('coefficient_variation', 0.0)
    
    # CORRECTION: Vérifier que les données d'automatisation existent
    automation_data = scam_analysis['analyses'].get('automation', {})
    patterns_detected = automation_data.get('patterns_detected', 0)
    
    # CORRECTION: Vérifier que les données de rug pull existent
    rug_data = scam_analysis['analyses'].get('rug_preparation', {})
    rug_signals_detected = rug_data.get('rug_signals_detected', 0)
    
    # Template HTML CORRIGÉ
    html_template = f"""
<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Rapport d'Analyse - Token {token_address[:8]}...</title>
    <style>
        :root {{
            --primary-color: #2563eb;
            --success-color: #10b981;
            --warning-color: #f59e0b;
            --danger-color: #ef4444;
            --background: #f8fafc;
            --card-background: #ffffff;
            --text-primary: #1e293b;
            --text-secondary: #64748b;
            --border-color: #e2e8f0;
        }}
        
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
            background-color: var(--background);
            color: var(--text-primary);
            line-height: 1.6;
        }}
        
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            padding: 2rem;
        }}
        
        .header {{
            text-align: center;
            margin-bottom: 3rem;
            padding: 2rem;
            background: var(--card-background);
            border-radius: 1rem;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
        }}
        
        .title {{
            font-size: 2.5rem;
            font-weight: 700;
            margin-bottom: 1rem;
            color: var(--primary-color);
        }}
        
        .subtitle {{
            font-size: 1.1rem;
            color: var(--text-secondary);
        }}
        
        .score-card {{
            background: var(--card-background);
            border-radius: 1rem;
            padding: 2rem;
            text-align: center;
            margin-bottom: 2rem;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
            border-left: 5px solid var(--{get_risk_color(scam_analysis['risk_score'])});
        }}
        
        .risk-score {{
            font-size: 4rem;
            font-weight: 800;
            margin-bottom: 1rem;
            color: var(--{get_risk_color(scam_analysis['risk_score'])});
        }}
        
        .risk-level {{
            font-size: 1.5rem;
            font-weight: 600;
            margin-bottom: 0.5rem;
        }}
        
        .verdict {{
            font-size: 1.1rem;
            color: var(--text-secondary);
            margin-bottom: 1rem;
        }}
        
        .investment-risk {{
            background: var(--{get_risk_color(scam_analysis['risk_score'])});
            color: white;
            padding: 0.75rem 1.5rem;
            border-radius: 0.5rem;
            font-weight: 600;
            display: inline-block;
        }}
        
        .metrics-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 1.5rem;
            margin-bottom: 2rem;
        }}
        
        .metric-card {{
            background: var(--card-background);
            border-radius: 1rem;
            padding: 1.5rem;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
        }}
        
        .metric-title {{
            font-size: 1.1rem;
            font-weight: 600;
            margin-bottom: 1rem;
            color: var(--text-primary);
        }}
        
        .metric-score {{
            font-size: 2rem;
            font-weight: 700;
            margin-bottom: 0.5rem;
        }}
        
        .metric-details {{
            color: var(--text-secondary);
            font-size: 0.9rem;
        }}
        
        .info-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 1rem;
            margin-top: 2rem;
        }}
        
        .info-item {{
            background: var(--card-background);
            padding: 1rem;
            border-radius: 0.5rem;
            border: 1px solid var(--border-color);
        }}
        
        .info-label {{
            font-weight: 600;
            color: var(--text-secondary);
            font-size: 0.9rem;
            margin-bottom: 0.25rem;
        }}
        
        .info-value {{
            font-family: 'Courier New', monospace;
            color: var(--text-primary);
            word-break: break-all;
        }}
        
        .recommendations {{
            background: var(--card-background);
            border-radius: 1rem;
            padding: 2rem;
            margin-top: 2rem;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
        }}
        
        .recommendations h3 {{
            color: var(--primary-color);
            margin-bottom: 1rem;
        }}
        
        .recommendation-list {{
            list-style: none;
        }}
        
        .recommendation-list li {{
            padding: 0.5rem 0;
            border-bottom: 1px solid var(--border-color);
        }}
        
        .recommendation-list li:last-child {{
            border-bottom: none;
        }}
        
        .footer {{
            text-align: center;
            margin-top: 3rem;
            padding: 2rem;
            color: var(--text-secondary);
            font-size: 0.9rem;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1 class="title">Rapport d'Analyse de Risque</h1>
            <p class="subtitle">Analyse comportementale du créateur de token</p>
            <p class="subtitle">Token: {token_address}</p>
        </div>
        
        <div class="score-card">
            <div class="risk-score">{scam_analysis['risk_score']}/10</div>
            <div class="risk-level">{scam_analysis['risk_level']}</div>
            <div class="verdict">{scam_analysis['verdict']}</div>
            <div class="investment-risk">{scam_analysis['investment_risk']}</div>
        </div>
        
        <div class="metrics-grid">
            <div class="metric-card">
                <div class="metric-title">🕐 Concentration Temporelle</div>
                <div class="metric-score" style="color: var(--{get_metric_color(scam_analysis['detailed_scores']['temporal_concentration'])})">{scam_analysis['detailed_scores']['temporal_concentration']}/10</div>
                <div class="metric-details">
                    {transaction_count} transactions en {time_span_minutes:.1f} minutes<br>
                    Vitesse: {transactions_per_minute:.2f} tx/min
                </div>
            </div>
            
            <div class="metric-card">
                <div class="metric-title">🤖 Patterns Robotiques</div>
                <div class="metric-score" style="color: var(--{get_metric_color(scam_analysis['detailed_scores']['transaction_frequency'])})">{scam_analysis['detailed_scores']['transaction_frequency']}/10</div>
                <div class="metric-details">
                    Intervalle moyen: {mean_interval_seconds:.1f}s<br>
                    Régularité: {coefficient_variation:.3f}
                </div>
            </div>
            
            <div class="metric-card">
                <div class="metric-title">💰 Pattern d'Accumulation</div>
                <div class="metric-score" style="color: var(--{get_metric_color(scam_analysis['detailed_scores']['accumulation_pattern'])})">{scam_analysis['detailed_scores']['accumulation_pattern']}/10</div>
                <div class="metric-details">
                    Dépôts: {deposit_count} ({deposit_ratio*100:.1f}%)<br>
                    Retraits: {withdrawal_count} ({withdrawal_ratio*100:.1f}%)
                </div>
            </div>
            
            <div class="metric-card">
                <div class="metric-title">🎯 Automatisation</div>
                <div class="metric-score" style="color: var(--{get_metric_color(scam_analysis['detailed_scores']['automation_score'])})">{scam_analysis['detailed_scores']['automation_score']}/10</div>
                <div class="metric-details">
                    Patterns détectés: {patterns_detected}
                </div>
            </div>
            
            <div class="metric-card">
                <div class="metric-title">🚩 Signaux Rug Pull</div>
                <div class="metric-score" style="color: var(--{get_metric_color(scam_analysis['detailed_scores']['rug_preparation'])})">{scam_analysis['detailed_scores']['rug_preparation']}/10</div>
                <div class="metric-details">
                    Signaux détectés: {rug_signals_detected}
                </div>
            </div>
        </div>
        
        <div class="info-grid">
            <div class="info-item">
                <div class="info-label">Token Address</div>
                <div class="info-value">{token_address}</div>
            </div>
            <div class="info-item">
                <div class="info-label">Creator Address</div>
                <div class="info-value">{creator_address}</div>
            </div>
            <div class="info-item">
                <div class="info-label">Balance Changes</div>
                <div class="info-value">{len(balance_changes)} transactions</div>
            </div>
            <div class="info-item">
                <div class="info-label">Date d'Analyse</div>
                <div class="info-value">{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</div>
            </div>
        </div>
        
        <div class="recommendations">
            <h3>💡 Recommandations</h3>
            <ul class="recommendation-list">
                {get_recommendations_html(scam_analysis['risk_score'])}
            </ul>
        </div>
        
        <div class="footer">
            <p>Rapport généré automatiquement - Nexus Solana Dashboard</p>
            <p>⚠️ Cette analyse est basée sur des patterns comportementaux et ne constitue pas un conseil financier</p>
        </div>
    </div>
</body>
</html>
"""
    
    # Sauvegarder le rapport
    report_filename = f"templates/scam_report_{token_address[:8]}.html"
    with open(report_filename, 'w', encoding='utf-8') as f:
        f.write(html_template)
    
    logger.info(f"✅ Rapport HTML généré: {report_filename}")
    return report_filename




# Vérifier si c'est un token pump.fun (détection améliorée)
def is_pump_fun_token(token_address):
    return token_address.endswith('pump') and len(token_address) == 44

def get_analyzer():
    """Récupère ou initialise l'analyseur"""
    global analyzer
    if analyzer is None:
        quicknode_endpoint = os.getenv('QUICKNODE_ENDPOINT', 'https://misty-alpha-aura.solana-mainnet.quiknode.pro/2a16287e4ba93a9df419f3fa8da45d135d682202/')
        try:
            analyzer = TokenCreatorAnalyzer(quicknode_endpoint)
        except Exception as e:
            logger.error(f"Erreur initialisation analyseur: {e}")
            return None
    return analyzer

# Routes API Flask
@app.route('/api/health', methods=['GET'])
def health_check():
    """Vérification de l'état de l'API"""
    return jsonify({
        "status": "healthy",
        "version": "1.0.0",
        "service": "Token Creator Analyzer API",
        "timestamp": datetime.now().isoformat()
    })

@app.route('/scam-report/<filename>')
def serve_scam_report(filename):
    """Sert les rapports d'analyse de scam"""
    try:
        from flask import send_from_directory
        return send_from_directory('templates', filename)
    except Exception as e:
        return f"<h1>Erreur</h1><p>Impossible de charger le rapport: {e}</p>", 404

@app.route('/api/analyze-token', methods=['POST'])
def analyze_token():
    """
    Analyse un token avec détection de scam intégrée
    """
    try:
        # Validation des données d'entrée (comme avant)
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "message": "Données JSON requises"}), 400
        
        token_address = data.get('token_address', '').strip()
        creator_wallet = data.get('creator_wallet')
        creator_wallet = creator_wallet.strip() if creator_wallet else None
        hours_back = data.get('hours_back', 24)
        max_transactions = data.get('max_transactions')
        export_csv = data.get('export_csv', True)  # Forcé à True pour l'analyse de scam
        generate_report = data.get('generate_html_report', True)  # Forcé à True par défaut
        
        # Validation (comme avant)
        if not token_address:
            return jsonify({"success": False, "message": "Adresse de token requise"}), 400
        
        if len(token_address) < 32 or len(token_address) > 44:
            return jsonify({"success": False, "message": "Format d'adresse de token invalide"}), 400
        
        # Validation des paramètres
        try:
            hours_back = int(hours_back)
            if hours_back < 1 or hours_back > 168:
                hours_back = 24
        except (ValueError, TypeError):
            hours_back = 24
        
        if max_transactions is not None:
            try:
                max_transactions = int(max_transactions)
                if max_transactions < 1:
                    max_transactions = None
            except (ValueError, TypeError):
                max_transactions = None
        
        # Récupérer l'analyseur
        token_analyzer = get_analyzer()
        if not token_analyzer:
            return jsonify({
                "success": False, 
                "message": "Analyseur non disponible - vérifiez la configuration QuickNode"
            }), 500
        
        logger.info(f"🚀 Nouvelle demande d'analyse complète: {token_address[:8]}... ({hours_back}h)")
        
        # Préparer le nom de fichier CSV
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        limit_suffix = f"_limit{max_transactions}" if max_transactions else "_full"
        output_filename = f"exports/balance_changes_{token_address[:8]}_{timestamp}{limit_suffix}.csv"
        
        # Créer le dossier d'export s'il n'existe pas
        os.makedirs('exports', exist_ok=True)
        
        # Utiliser la nouvelle méthode avec analyse de scam
        result = token_analyzer.analyze_token_creator(
            token_address=token_address,
            output_filename=output_filename,
            hours_back=hours_back,
            max_transactions=max_transactions,
            create_html_report=generate_report,
            creator_wallet=creator_wallet
        )
        
        if result:
            response_data = {
                "success": True,
                "message": f"Analyse complète terminée - {result['balance_changes_count']} balance changes trouvés",
                "data": {
                    "token_address": result["token_address"],
                    "creator_address": result["creator_address"],
                    "ata_pubkey": result["ata_pubkey"],
                    "balance_changes_count": result["balance_changes_count"],
                    "scan_duration": result["scan_duration"],
                    "rpc_requests": result["rpc_requests"],
                    "output_file": result.get("output_file"),
                    "hours_analyzed": hours_back,
                    "max_transactions": max_transactions
                }
            }
            
            # Ajouter les données d'analyse de scam
            if result.get("scam_analysis"):
                scam_data = result["scam_analysis"]
                response_data["data"]["scam_analysis"] = {
                    "risk_score": scam_data["risk_score"],
                    "risk_level": scam_data["risk_level"],
                    "verdict": scam_data["verdict"],
                    "investment_risk": scam_data["investment_risk"],
                    "risk_emoji": scam_data["risk_emoji"]
                }
            
            # Ajouter l'URL du rapport HTML
            if result.get("html_report"):
                # Construire l'URL du rapport
                report_filename = os.path.basename(result["html_report"])
                port = os.getenv('FLASK_PORT', 5001)
                response_data["data"]["report_url"] = f"http://localhost:{port}/scam-report/{report_filename}"
            
            # Inclure les balance changes si pas trop volumineux
            if result["balance_changes_count"] <= 100:
                response_data["data"]["balance_changes"] = result["balance_changes"]
            
            return jsonify(response_data)
        else:
            return jsonify({
                "success": False,
                "message": "Échec de l'analyse du token"
            }), 500
    
    except Exception as e:
        logger.error(f"❌ Erreur API analyze-token: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return jsonify({
            "success": False,
            "message": f"Erreur interne: {str(e)}"
        }), 500

@app.route('/api/dashboard-data', methods=['GET'])
def dashboard_data():
    """Données du dashboard principal"""
    return jsonify({
        "stats": {
            "totalTokenAccounts": 1250,
            "balanceChangesCount": 847,
            "largeTransactionsCount": 23,
            "lastScanTime": int(time.time())
        },
        "timestamp": datetime.now().isoformat()
    })

@app.route('/api/recent-balance-changes', methods=['GET'])
def recent_balance_changes():
    """Balance changes récents (mock data pour demo)"""
    limit = request.args.get('limit', 50, type=int)
    
    # Mock data pour la démo
    mock_data = []
    tokens = ['BONK', 'WIF', 'POPCAT', 'PEPE', 'SAMO']
    types = ['buy', 'sell', 'transfer']
    
    for i in range(limit):
        mock_data.append({
            "signature": f"mock_tx_{i}_{int(time.time())}",
            "block_time": int(time.time()) - (i * 300),  # Une transaction toutes les 5 minutes
            "transaction_type": types[i % len(types)],
            "token_symbol": tokens[i % len(tokens)],
            "token_mint": f"mock_mint_{i}",
            "token_amount": (i + 1) * 1000 + (i * 100),
            "amount": (i % 10) / 10.0,
            "wallet_address": f"mock_wallet_{i}_" + "x" * 32,
            "is_large_token_amount": (i % 7) == 0
        })
    
    return jsonify({
        "balance_changes": mock_data,
        "total": len(mock_data),
        "timestamp": datetime.now().isoformat()
    })

@app.errorhandler(404)
def not_found(error):
    return jsonify({"success": False, "message": "Endpoint non trouvé"}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({"success": False, "message": "Erreur interne du serveur"}), 500

@app.route('/report/<token_address>')
def show_report(token_address):
    """Affiche le rapport d'analyse pour un token"""
    return render_template('analyze_token_creator.html', token_address=token_address)

@app.route('/api/generate-report', methods=['POST'])
def generate_report():
    """Génère et ouvre le rapport d'analyse"""
    data = request.get_json()
    token_address = data.get('token_address')
    
    if not token_address:
        return jsonify({"success": False, "message": "Token address required"}), 400
    
    # URL du rapport
    report_url = f"http://localhost:{app.config.get('PORT', 5001)}/report/{token_address}"
    
    return jsonify({
        "success": True,
        "report_url": report_url,
        "message": "Rapport généré avec succès"
    })

@app.route('/dashboard')
def dashboard():
    """Interface web du dashboard"""
    return render_template('analyze_token_creator.html')

if __name__ == "__main__":
    print("🚀 Token Creator Analyzer API")
    print("=" * 60)
    print("📡 Endpoints disponibles:")
    print("   GET  /api/health - Vérification de l'état")
    print("   POST /api/analyze-token - Analyse d'un token")
    print("   GET  /api/dashboard-data - Données du dashboard")
    print("   GET  /api/recent-balance-changes - Balance changes récents")
    print("=" * 60)
    
    # Créer les dossiers nécessaires
    os.makedirs('exports', exist_ok=True)
    
    # Configuration
    host = os.getenv('FLASK_HOST', '0.0.0.0')
    port = int(os.getenv('FLASK_PORT', 5001))
    debug = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'
    
    print(f"🌐 Serveur: http://{host}:{port}")
    print(f"🔧 Debug: {debug}")
    print("=" * 60)
    
    app.run(host=host, port=port, debug=debug)