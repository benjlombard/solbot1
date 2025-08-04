#!/usr/bin/env python3
"""
Backend Flask pour les rapports d'analyse de wallets Solana
Intégration complète avec TokenCreatorAnalyzer - Version complète
"""
from flask import Flask, render_template, request, jsonify, send_from_directory
from flask_cors import CORS
import json
import os
from datetime import datetime
import sqlite3
from typing import Dict, List, Optional
import logging
import traceback

# Import de votre analyseur existant
from analyze_wallet_transactions import TokenCreatorAnalyzer

app = Flask(__name__)
CORS(app)

# Configuration
app.config['SECRET_KEY'] = 'your-secret-key-here'
app.config['JSON_SORT_KEYS'] = False

# Configuration des logs
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ReportGenerator:
    def __init__(self, quicknode_endpoint: str):
        self.quicknode_endpoint = quicknode_endpoint
        self.reports_db = "reports.db"
        self._init_reports_database()
        
        # Statistiques globales
        self.global_stats = {
            'total_analyses': 0,
            'avg_risk_score': 0,
            'total_requests': 0,
            'cache_hit_rate': 0,
            'active_users': 1,
            'system_status': 'operational'
        }
        
        # Initialiser l'analyzeur avec le endpoint QuickNode
        try:
            self.analyzer = TokenCreatorAnalyzer(quicknode_endpoint)
            logger.info(f"✅ TokenCreatorAnalyzer initialisé avec succès")
        except Exception as e:
            logger.error(f"❌ Erreur initialisation TokenCreatorAnalyzer: {e}")
            self.analyzer = None
    
    def _init_reports_database(self):
        """Initialise la base de données des rapports"""
        try:
            conn = sqlite3.connect(self.reports_db)
            cursor = conn.cursor()
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    wallet_address TEXT NOT NULL,
                    token_address TEXT,
                    report_type TEXT NOT NULL,
                    report_data TEXT NOT NULL,
                    risk_score INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    analysis_duration REAL,
                    rpc_requests INTEGER
                )
            ''')
            
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_wallet_address ON reports(wallet_address)
            ''')
            
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_created_at ON reports(created_at)
            ''')
            
            conn.commit()
            conn.close()
            logger.info(f"💾 Base de données rapports initialisée: {self.reports_db}")
            
        except Exception as e:
            logger.error(f"❌ Erreur initialisation DB rapports: {e}")
    
    def save_report(self, wallet_address: str, report_data: Dict, 
                   token_address: str = None, report_type: str = "wallet_analysis") -> int:
        """Sauvegarde un rapport en base"""
        try:
            conn = sqlite3.connect(self.reports_db)
            cursor = conn.cursor()
            
            report_json = json.dumps(report_data, ensure_ascii=False, default=str)
            risk_score = report_data.get("risk_analysis", {}).get("score", 0)
            analysis_duration = report_data.get("analysis_duration", 0)
            rpc_requests = report_data.get("rpc_requests", 0)
            
            cursor.execute('''
                INSERT INTO reports 
                (wallet_address, token_address, report_type, report_data, 
                 risk_score, analysis_duration, rpc_requests)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (wallet_address, token_address, report_type, report_json,
                  risk_score, analysis_duration, rpc_requests))
            
            report_id = cursor.lastrowid
            conn.commit()
            conn.close()
            
            # Mettre à jour les statistiques globales
            self._update_global_stats(risk_score, rpc_requests)
            
            logger.info(f"💾 Rapport sauvegardé: ID {report_id}")
            return report_id
            
        except Exception as e:
            logger.error(f"❌ Erreur sauvegarde rapport: {e}")
            return None
    
    def _update_global_stats(self, risk_score: int, rpc_requests: int):
        """Met à jour les statistiques globales"""
        self.global_stats['total_analyses'] += 1
        self.global_stats['total_requests'] += rpc_requests
        
        # Calcul de la moyenne mobile du score de risque
        current_avg = self.global_stats['avg_risk_score']
        total = self.global_stats['total_analyses']
        self.global_stats['avg_risk_score'] = (current_avg * (total - 1) + risk_score) / total
    
    def get_report(self, report_id: int) -> Optional[Dict]:
        """Récupère un rapport par ID"""
        try:
            conn = sqlite3.connect(self.reports_db)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT wallet_address, token_address, report_type, report_data,
                       risk_score, created_at, analysis_duration, rpc_requests
                FROM reports WHERE id = ?
            ''', (report_id,))
            
            row = cursor.fetchone()
            conn.close()
            
            if row:
                return {
                    "id": report_id,
                    "wallet_address": row[0],
                    "token_address": row[1],
                    "report_type": row[2],
                    "report_data": json.loads(row[3]),
                    "risk_score": row[4],
                    "created_at": row[5],
                    "analysis_duration": row[6],
                    "rpc_requests": row[7]
                }
            return None
            
        except Exception as e:
            logger.error(f"❌ Erreur récupération rapport: {e}")
            return None
    
    def list_reports(self, limit: int = 50) -> List[Dict]:
        """Liste les derniers rapports"""
        try:
            conn = sqlite3.connect(self.reports_db)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT id, wallet_address, token_address, report_type,
                       risk_score, created_at, analysis_duration, rpc_requests
                FROM reports 
                ORDER BY created_at DESC 
                LIMIT ?
            ''', (limit,))
            
            rows = cursor.fetchall()
            conn.close()
            
            reports = []
            for row in rows:
                reports.append({
                    "id": row[0],
                    "wallet_address": row[1],
                    "token_address": row[2],
                    "report_type": row[3],
                    "risk_score": row[4],
                    "created_at": row[5],
                    "analysis_duration": row[6],
                    "rpc_requests": row[7]
                })
            
            return reports
            
        except Exception as e:
            logger.error(f"❌ Erreur liste rapports: {e}")
            return []
    
    def get_stats(self) -> Dict:
        """Retourne les statistiques globales"""
        stats = self.global_stats.copy()
        
        # Ajouter les stats du cache si l'analyzer est disponible
        if self.analyzer:
            try:
                cache_stats = self.analyzer.get_cache_stats()
                transaction_stats = self.analyzer._get_transaction_cache_stats()
                
                # Calculer le taux de hit du cache
                total_cache_requests = cache_stats.get('hits', 0) + cache_stats.get('misses', 0)
                if total_cache_requests > 0:
                    stats['cache_hit_rate'] = round((cache_stats.get('hits', 0) / total_cache_requests) * 100, 1)
                
                stats['cache_details'] = {
                    'creator_cache': cache_stats,
                    'transaction_cache': transaction_stats
                }
            except Exception as e:
                logger.warning(f"Erreur récupération stats cache: {e}")
        
        return stats
    
    def _normalize_analysis_result(self, result: Dict) -> Dict:
        """Normalise la structure des résultats d'analyse"""
        if not isinstance(result, dict):
            logger.error(f"❌ Résultat n'est pas un dictionnaire: {type(result)}")
            return {"error": "Format de résultat invalide"}
        
        # Vérifier et corriger risk_analysis
        if 'risk_analysis' in result:
            risk_data = result['risk_analysis']
            
            # Si c'est un entier (score direct), transformer en structure complète
            if isinstance(risk_data, (int, float)):
                logger.warning(f"⚠️ risk_analysis est un nombre ({risk_data}), conversion en dict")
                result['risk_analysis'] = {
                    'score': int(risk_data),
                    'level': self._get_risk_level(int(risk_data)),
                    'factors': [],
                    'warnings': ["Score calculé automatiquement"]
                }
            
            # Si c'est None ou invalide
            elif not isinstance(risk_data, dict):
                logger.warning(f"⚠️ risk_analysis invalide ({type(risk_data)}), création par défaut")
                result['risk_analysis'] = {
                    'score': 50,  # Score neutre par défaut
                    'level': 'MEDIUM',
                    'factors': [],
                    'warnings': ["Impossible de calculer le score de risque"]
                }
        
        # Si risk_analysis n'existe pas du tout
        else:
            logger.warning("⚠️ risk_analysis manquant, création par défaut")
            result['risk_analysis'] = {
                'score': 50,
                'level': 'MEDIUM',
                'factors': [],
                'warnings': ["Analyse de risque non disponible"]
            }
        
        return result

    def _get_risk_level(self, score: int) -> str:
        """Convertit un score numérique en niveau de risque"""
        if score >= 80:
            return 'VERY_HIGH'
        elif score >= 60:
            return 'HIGH'
        elif score >= 40:
            return 'MEDIUM'
        elif score >= 20:
            return 'LOW'
        else:
            return 'VERY_LOW'

    def analyze_wallet_real(self, wallet_address: str, token_address: str = None, 
                           days_back: int = 7, force_refresh: bool = False) -> Dict:
        """Analyse réelle d'un wallet avec TokenCreatorAnalyzer"""
        if not self.analyzer:
            raise Exception("TokenCreatorAnalyzer non initialisé")
        
        logger.info(f"🔍 Analyse réelle du wallet {wallet_address[:8]}...")
        logger.info(f"   Token: {token_address[:8] if token_address else 'None'}")
        logger.info(f"   Période: {days_back} jours")
        logger.info(f"   Force refresh: {force_refresh}")
        
        try:
            # Utiliser la méthode complète de votre analyzer
            raw_result = self.analyzer.analyze_wallet_complete(
                wallet_address=wallet_address,
                days_back=days_back,
                token_address=token_address
            )
            result = self._normalize_analysis_result(raw_result)

            # AJOUT : Debug de la structure du résultat
            logger.info(f"🔍 Structure résultat analyzer:")
            logger.info(f"   Type: {type(result)}")
            logger.info(f"   Clés: {list(result.keys()) if isinstance(result, dict) else 'Pas un dict'}")
            
            if isinstance(result, dict) and 'risk_analysis' in result:
                risk_data = result['risk_analysis']
                logger.info(f"   Type risk_analysis: {type(risk_data)}")
                if isinstance(risk_data, dict):
                    logger.info(f"   Clés risk_analysis: {list(risk_data.keys())}")
                else:
                    logger.warning(f"   ❌ risk_analysis n'est pas un dict: {risk_data}")
            
            return result

            logger.info(f"✅ Analyse terminée avec succès")
            logger.info(f"   Score de risque: {result.get('risk_analysis', {}).get('score', 'N/A')}")
            logger.info(f"   Durée: {result.get('analysis_duration', 0):.1f}s")
            logger.info(f"   Requêtes RPC: {result.get('rpc_requests', 0)}")
            
            return result
            
        except Exception as e:
            logger.error(f"❌ Erreur analyse wallet: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise e
    
    def analyze_token_creator_real(self, token_address: str, hours_back: int = 24, 
                              exhaustive_search: bool = True, 
                              force_refresh: bool = False) -> Dict:
        """Analyse réelle d'un token creator avec TokenCreatorAnalyzer"""
        if not self.analyzer:
            raise Exception("TokenCreatorAnalyzer non initialisé")
        
        logger.info(f"🪙 Analyse réelle du token {token_address[:8]}...")
        logger.info(f"   Période: {hours_back} heures")
        logger.info(f"   Recherche exhaustive: {exhaustive_search}")
        logger.info(f"   Force refresh: {force_refresh}")
        
        try:
            # Utiliser la méthode de votre analyzer
            result = self.analyzer.analyze_token_creator(
                token_address=token_address,
                hours_back=hours_back,
                exhaustive_creator_search=exhaustive_search,
                force_refresh_creator=force_refresh
            )
            
            logger.info(f"🔍 Structure du résultat: {list(result.keys()) if result else 'None'}")
            
            if result:
                # Vérifier si on a une analyse de wallet dans le résultat
                if "wallet_analysis" in result:
                    logger.info(f"✅ Analyse token terminée avec succès (avec wallet_analysis)")
                    wallet_data = result["wallet_analysis"]
                    wallet_data["token_address"] = token_address
                    wallet_data["creator_address"] = result.get("creator_address")
                    return wallet_data
                    
                # Si pas de wallet_analysis, mais qu'on a des données d'analyse directe
                elif any(key in result for key in ["basic_info", "trading_patterns", "risk_analysis"]):
                    logger.info(f"✅ Analyse token terminée avec succès (données directes)")
                    result["token_address"] = token_address
                    return result
                    
                # Si on a au moins un creator_address, faire une analyse séparée du wallet
                elif "creator_address" in result:
                    creator_address = result["creator_address"]
                    logger.info(f"🔄 Analyse du créateur {creator_address[:8]}... séparément")
                    
                    # Analyser le wallet du créateur
                    wallet_result = self.analyze_wallet_real(
                        wallet_address=creator_address,
                        token_address=token_address,
                        days_back=hours_back // 24 or 1,  # Convertir heures en jours
                        force_refresh=force_refresh
                    )
                    
                    # Ajouter les infos du token
                    wallet_result["token_address"] = token_address
                    wallet_result["creator_address"] = creator_address

                    if isinstance(wallet_result, dict):
                        wallet_result = self._normalize_analysis_result(wallet_result)

                    return wallet_result
                else:
                    logger.error(f"❌ Structure de résultat inattendue: {result}")
                    raise Exception(f"Structure de résultat inattendue. Clés disponibles: {list(result.keys())}")
            else:
                raise Exception("Résultat vide de analyze_token_creator")
            
        except Exception as e:
            logger.error(f"❌ Erreur analyse token: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise e

# Configuration endpoint QuickNode
QUICKNODE_ENDPOINT = os.environ.get('QUICKNODE_ENDPOINT', 
    'https://misty-alpha-aura.solana-mainnet.quiknode.pro/2a16287e4ba93a9df419f3fa8da45d135d682202/')

# Instance globale
report_generator = ReportGenerator(QUICKNODE_ENDPOINT)

@app.route('/')
def index():
    """Page d'accueil"""
    return render_template('index.html')

@app.route('/analyze', methods=['POST'])
def analyze_wallet():
    """Endpoint pour analyser un wallet"""
    try:
        if request.is_json:
            data = request.get_json()
        else:
            data = request.form.to_dict()
        
        # Fix: Handle None values properly before calling strip()
        wallet_address_raw = data.get('wallet_address')
        token_address_raw = data.get('token_address')
        
        wallet_address = (wallet_address_raw or '').strip()
        token_address = (token_address_raw or '').strip() or None
        
        # Alternative more explicit approach:
        # wallet_address = data.get('wallet_address', '') if data.get('wallet_address') is not None else ''
        # wallet_address = wallet_address.strip()
        
        days_back = int(data.get('days_back', 7))
        force_refresh = data.get('force_refresh', False)
        
        if not wallet_address:
            return jsonify({"error": "Adresse de wallet requise"}), 400
        
        # Validation basique des adresses Solana (44 caractères base58)
        if len(wallet_address) != 44:
            return jsonify({"error": "Adresse de wallet invalide"}), 400
        
        if token_address and len(token_address) != 44:
            return jsonify({"error": "Adresse de token invalide"}), 400
        
        logger.info(f"🔍 Analyse demandée: wallet={wallet_address[:8]}..., token={token_address[:8] if token_address else None}...")
        
        # Analyse RÉELLE avec votre TokenCreatorAnalyzer
        result = report_generator.analyze_wallet_real(
            wallet_address=wallet_address,
            token_address=token_address,
            days_back=days_back,
            force_refresh=force_refresh
        )
        
        # Vérification de sécurité supplémentaire
        if not isinstance(result, dict):
            logger.error(f"❌ Résultat d'analyse invalide: {type(result)}")
            return jsonify({"error": "Format de résultat d'analyse invalide"}), 500
        
        # S'assurer que risk_analysis existe et est un dict
        risk_analysis = result.get("risk_analysis", {})
        if not isinstance(risk_analysis, dict):
            logger.warning(f"⚠️ Correction risk_analysis dans endpoint: {type(risk_analysis)}")
            result["risk_analysis"] = {"score": 50, "level": "MEDIUM"}

        # Sauvegarder le rapport
        report_id = report_generator.save_report(
            wallet_address, result, token_address, "wallet_analysis"
        )
        
        return jsonify({
            "success": True,
            "report_id": report_id,
            "wallet_address": wallet_address,
            "analysis_summary": {
                "risk_score": result.get("risk_analysis", {}).get("score", 0),
                "risk_level": result.get("risk_analysis", {}).get("level", "UNKNOWN"),
                "sol_balance": result.get("basic_info", {}).get("sol_balance", 0),
                "tokens_count": result.get("tokens", {}).get("total_tokens", 0),
                "activity_level": result.get("trading_patterns", {}).get("activity_level", "unknown"),
                "analysis_duration": result.get("analysis_duration", 0),
                "rpc_requests": result.get("rpc_requests", 0)
            }
        })
        
    except Exception as e:
        logger.error(f"❌ Erreur analyse: {e}")
        return jsonify({"error": f"Erreur lors de l'analyse: {str(e)}"}), 500

@app.route('/analyze-token', methods=['POST'])
def analyze_token_creator():
    """Endpoint pour analyser un token creator"""
    try:
        data = request.get_json()
        
        # Fix: Handle None values properly before calling strip()
        token_address_raw = data.get('token_address')
        token_address = (token_address_raw or '').strip()
        
        hours_back = int(data.get('hours_back', 24))
        exhaustive_search = data.get('exhaustive_search', True)
        force_refresh = data.get('force_refresh', False)
        
        if not token_address:
            return jsonify({"error": "Adresse de token requise"}), 400
        
        if len(token_address) != 44:
            return jsonify({"error": "Adresse de token invalide"}), 400
        
        logger.info(f"🪙 Analyse token demandée: {token_address[:8]}...")
        
        # Analyse RÉELLE avec votre TokenCreatorAnalyzer
        result = report_generator.analyze_token_creator_real(
            token_address=token_address,
            hours_back=hours_back,
            exhaustive_search=exhaustive_search,
            force_refresh=force_refresh
        )
        
        # Vérification de sécurité supplémentaire
        if not isinstance(result, dict):
            logger.error(f"❌ Résultat d'analyse invalide: {type(result)}")
            return jsonify({"error": "Format de résultat d'analyse invalide"}), 500
        
        # S'assurer que risk_analysis existe et est un dict
        risk_analysis = result.get("risk_analysis", {})
        if not isinstance(risk_analysis, dict):
            logger.warning(f"⚠️ Correction risk_analysis dans endpoint: {type(risk_analysis)}")
            result["risk_analysis"] = {"score": 50, "level": "MEDIUM"}

        # Déterminer l'adresse du wallet à utiliser pour la sauvegarde
        wallet_address = result.get("wallet_address") or result.get("creator_address", "")

        # Sauvegarder le rapport
        report_id = report_generator.save_report(
            wallet_address, result, token_address, "token_creator_analysis"
        )
        
        return jsonify({
            "success": True,
            "report_id": report_id,
            "token_address": token_address,
            "creator_address": result.get("creator_address"),
            "analysis_summary": {
                "risk_score": result.get("risk_analysis", {}).get("score", 0),
                "risk_level": result.get("risk_analysis", {}).get("level", "UNKNOWN"),
                "sol_balance": result.get("basic_info", {}).get("sol_balance", 0),
                "tokens_count": result.get("tokens", {}).get("total_tokens", 0),
                "activity_level": result.get("trading_patterns", {}).get("activity_level", "unknown"),
                "analysis_duration": result.get("analysis_duration", 0),
                "rpc_requests": result.get("rpc_requests", 0)
            }
        })
        
    except Exception as e:
        logger.error(f"❌ Erreur analyse token: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return jsonify({
            "error": f"Erreur lors de l'analyse du token: {str(e)}", 
            "details": str(e)
        }), 500


@app.route('/report/<int:report_id>')
def view_report(report_id):
    """Affiche un rapport spécifique"""
    report = report_generator.get_report(report_id)
    
    if not report:
        return render_template('error.html', 
                             error="Rapport non trouvé", 
                             error_code=404), 404
    
    return render_template('report.html', report=report)

@app.route('/api/report/<int:report_id>')
def api_get_report(report_id):
    """API pour récupérer un rapport"""
    report = report_generator.get_report(report_id)
    
    if not report:
        return jsonify({"error": "Rapport non trouvé"}), 404
    
    return jsonify(report)

@app.route('/reports')
def list_reports():
    """Liste tous les rapports"""
    reports = report_generator.list_reports()
    return render_template('reports_list.html', reports=reports)

@app.route('/api/reports')
def api_list_reports():
    """API pour lister les rapports"""
    limit = request.args.get('limit', 50, type=int)
    reports = report_generator.list_reports(limit)
    return jsonify({"reports": reports, "total": len(reports)})

@app.route('/api/stats')
def api_stats():
    """API pour les statistiques - NOUVEAU ENDPOINT"""
    try:
        stats = report_generator.get_stats()
        return jsonify(stats)
    except Exception as e:
        logger.error(f"❌ Erreur récupération stats: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/cache-stats')
def cache_stats():
    """Statistiques du cache"""
    if not report_generator.analyzer:
        return jsonify({"error": "Analyzer non disponible"}), 500
    
    try:
        cache_stats = report_generator.analyzer.get_cache_stats()
        transaction_stats = report_generator.analyzer._get_transaction_cache_stats()
        
        return render_template('cache_stats.html', 
                             cache_stats=cache_stats,
                             transaction_stats=transaction_stats,
                             quicknode_endpoint=QUICKNODE_ENDPOINT[:50] + "...",
                             analyzer_initialized=True)
    except Exception as e:
        return render_template('error.html', 
                             error=f"Erreur récupération stats: {str(e)}", 
                             error_code=500), 500

@app.route('/api/cache-stats')
def api_cache_stats():
    """API pour les statistiques du cache"""
    if not report_generator.analyzer:
        return jsonify({"error": "Analyzer non disponible"}), 500
    
    try:
        cache_stats = report_generator.analyzer.get_cache_stats()
        transaction_stats = report_generator.analyzer._get_transaction_cache_stats()
        
        return jsonify({
            "creator_cache": cache_stats,
            "transaction_cache": transaction_stats,
            "quicknode_endpoint": QUICKNODE_ENDPOINT[:50] + "...",
            "analyzer_initialized": True
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/export-ml-dataset')
def export_ml_dataset():
    """Exporte le dataset ML"""
    if not report_generator.analyzer:
        return jsonify({"error": "Analyzer non disponible"}), 500
    
    try:
        success = report_generator.analyzer.export_ml_dataset()
        if success:
            return jsonify({"success": True, "message": "Dataset ML exporté avec succès"})
        else:
            return jsonify({"error": "Échec export dataset ML"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/health')
def health_check():
    """Endpoint de santé pour monitoring"""
    status = {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "analyzer_available": report_generator.analyzer is not None,
        "database_accessible": True,
        "quicknode_endpoint": QUICKNODE_ENDPOINT[:50] + "..."
    }
    
    # Test d'accès à la base de données
    try:
        conn = sqlite3.connect(report_generator.reports_db)
        conn.close()
    except Exception as e:
        status["database_accessible"] = False
        status["database_error"] = str(e)
        status["status"] = "degraded"
    
    return jsonify(status)

@app.errorhandler(404)
def not_found_error(error):
    if request.is_json:
        return jsonify({"error": "Endpoint non trouvé"}), 404
    return render_template('error.html', 
                         error="Page non trouvée", 
                         error_code=404), 404

@app.errorhandler(500)
def internal_error(error):
    if request.is_json:
        return jsonify({"error": "Erreur interne du serveur"}), 500
    return render_template('error.html', 
                         error="Erreur interne du serveur", 
                         error_code=500), 500

if __name__ == '__main__':
    logger.info("🚀 Démarrage du serveur Flask")
    logger.info(f"   QuickNode: {QUICKNODE_ENDPOINT[:50]}...")
    logger.info(f"   Analyzer: {'✅ OK' if report_generator.analyzer else '❌ Erreur'}")
    
    app.run(
        host='0.0.0.0',
        port=5002,
        debug=True,
        threaded=True
    )