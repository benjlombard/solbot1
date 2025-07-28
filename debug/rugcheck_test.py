#!/usr/bin/env python3
"""
🛡️ Script de test pour l'API RugCheck
Teste et affiche le score de sécurité d'un token Solana
"""

import requests
import json
import time
import argparse
from typing import Dict, Optional

class RugCheckTester:
    """Classe pour tester l'API RugCheck"""
    
    BASE_URL = "https://api.rugcheck.xyz/v1/tokens"
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'RugCheck-Tester/1.0',
            'Accept': 'application/json'
        })
    
    def get_rugcheck_score(self, token_address: str, verbose: bool = False) -> Dict:
        """
        Récupérer le score RugCheck pour un token
        
        Args:
            token_address: Adresse du token Solana
            verbose: Afficher les détails complets
            
        Returns:
            Dict avec les informations du token
        """
        url = f"{self.BASE_URL}/{token_address}/report"
        
        try:
            print(f"🔍 Requête vers: {url}")
            
            response = self.session.get(url, timeout=10)
            
            print(f"📡 Status HTTP: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                
                if verbose:
                    print(f"📄 Réponse complète:")
                    print(json.dumps(data, indent=2))
                    print(f"\n" + "="*60)
                
                return self._parse_rugcheck_data(data)
                
            elif response.status_code == 404:
                return {
                    "success": False,
                    "error": "Token non trouvé dans RugCheck",
                    "status_code": 404
                }
            elif response.status_code == 429:
                return {
                    "success": False,
                    "error": "Rate limit atteint",
                    "status_code": 429
                }
            else:
                return {
                    "success": False,
                    "error": f"Erreur HTTP {response.status_code}",
                    "status_code": response.status_code,
                    "response_text": response.text[:500]
                }
                
        except requests.exceptions.Timeout:
            return {
                "success": False,
                "error": "Timeout de la requête (>10s)"
            }
        except requests.exceptions.ConnectionError:
            return {
                "success": False,
                "error": "Erreur de connexion à RugCheck"
            }
        except requests.exceptions.RequestException as e:
            return {
                "success": False,
                "error": f"Erreur de requête: {str(e)}"
            }
        except json.JSONDecodeError:
            return {
                "success": False,
                "error": "Réponse JSON invalide",
                "response_text": response.text[:500] if 'response' in locals() else "N/A"
            }
    
    def _parse_rugcheck_data(self, data: Dict) -> Dict:
        """Parser les données RugCheck"""
        
        # NOUVEAU: Analyser tous les scores possibles dans la réponse
        all_scores = self._extract_all_scores(data)
        
        result = {
            "success": True,
            "token_address": data.get("mint", "N/A"),
            "token_symbol": data.get("tokenMeta", {}).get("symbol", "UNKNOWN"),
            "token_name": data.get("tokenMeta", {}).get("name", "Unknown"),
            "api_score": data.get("score", 0),  # Score principal de l'API
            "all_scores": all_scores,  # Tous les scores trouvés
            "risk_level": self._get_risk_level(data.get("score", 0)),
            "total_supply": data.get("tokenMeta", {}).get("totalSupply", 0),
            "decimals": data.get("tokenMeta", {}).get("decimals", 9),
            "raw_data_keys": list(data.keys()),  # Pour déboguer
        }
        
        # Ajouter les détails des risques si disponibles
        risks = data.get("risks", [])
        if risks:
            result["risks"] = []
            total_risk_score = 0
            for risk in risks:
                risk_data = {
                    "name": risk.get("name", "Unknown"),
                    "description": risk.get("description", "No description"),
                    "level": risk.get("level", "unknown"),
                    "score": risk.get("score", 0)
                }
                result["risks"].append(risk_data)
                total_risk_score += risk.get("score", 0)
            
            result["total_risk_score"] = total_risk_score
            result["calculated_safety_score"] = max(0, 100 - total_risk_score)
        
        # Ajouter les informations sur les markets si disponibles
        markets = data.get("markets", [])
        if markets:
            result["markets_count"] = len(markets)
            result["top_market"] = markets[0].get("name", "Unknown") if markets else None
        
        return result
    
    def _extract_all_scores(self, data: Dict) -> Dict:
        """Extraire tous les scores possibles de la réponse"""
        scores = {}
        
        # Score principal
        if "score" in data:
            scores["main_score"] = data["score"]
        
        # Chercher d'autres champs de score
        for key, value in data.items():
            if "score" in key.lower() and isinstance(value, (int, float)):
                scores[key] = value
        
        # Vérifier dans les sous-objets
        if "tokenMeta" in data and isinstance(data["tokenMeta"], dict):
            for key, value in data["tokenMeta"].items():
                if "score" in key.lower() and isinstance(value, (int, float)):
                    scores[f"tokenMeta.{key}"] = value
        
        # Calculer un score basé sur les risques (plus logique)
        if "risks" in data:
            total_risk = sum(risk.get("score", 0) for risk in data["risks"])
            scores["calculated_from_risks"] = max(0, 100 - total_risk)
        
        return scores
    
    def _get_risk_level(self, score: int) -> str:
        """Déterminer le niveau de risque basé sur le score"""
        if score >= 80:
            return "🟢 TRÈS SÛR"
        elif score >= 60:
            return "🟡 SÛR"
        elif score >= 40:
            return "🟠 RISQUE MODÉRÉ"
        elif score >= 20:
            return "🔴 RISQUÉ"
        else:
            return "⚫ TRÈS RISQUÉ"
    
    def test_multiple_tokens(self, addresses: list, delay: float = 1.0):
        """Tester plusieurs tokens"""
        results = []
        
        for i, address in enumerate(addresses, 1):
            print(f"\n{'='*60}")
            print(f"🧪 Test {i}/{len(addresses)}: {address}")
            print(f"{'='*60}")
            
            result = self.get_rugcheck_score(address)
            results.append({"address": address, "result": result})
            
            self._display_result(result)
            
            # Délai entre les requêtes pour éviter le rate limiting
            if i < len(addresses):
                print(f"⏳ Attente de {delay}s avant le prochain test...")
                time.sleep(delay)
        
        return results
    
    def _display_result(self, result: Dict):
        """Afficher le résultat formaté"""
        print(f"\n📊 RÉSULTAT:")
        
        if not result.get("success", False):
            print(f"❌ ERREUR: {result.get('error', 'Erreur inconnue')}")
            if "status_code" in result:
                print(f"📡 Code HTTP: {result['status_code']}")
            if "response_text" in result:
                print(f"📄 Réponse: {result['response_text']}")
            return
        
        print(f"✅ SUCCÈS")
        print(f"🪙 Token: {result.get('token_symbol', 'N/A')} ({result.get('token_name', 'N/A')})")
        print(f"📍 Adresse: {result.get('token_address', 'N/A')}")
        
        # NOUVEAU: Afficher tous les scores trouvés
        print(f"\n🛡️ SCORES DÉTECTÉS:")
        api_score = result.get('api_score', 0)
        print(f"   📊 Score API principal: {api_score}/100 ({self._get_risk_level(api_score)})")
        
        all_scores = result.get('all_scores', {})
        for score_name, score_value in all_scores.items():
            if score_name != 'main_score':  # Éviter la duplication
                print(f"   📊 {score_name}: {score_value}/100 ({self._get_risk_level(score_value)})")
        
        print(f"\n📈 ANALYSE DES RISQUES:")
        if result.get("risks"):
            total_risk = sum(risk['score'] for risk in result['risks'])
            calculated_safety = max(0, 100 - total_risk)
            print(f"   🧮 Score calculé (100 - risques): {calculated_safety}/100 ({self._get_risk_level(calculated_safety)})")
            print(f"   ⚠️ Total des risques: {total_risk}/100")
        
        print(f"\n📋 AUTRES INFOS:")
        print(f"🔢 Supply totale: {result.get('total_supply', 0):,}")
        print(f"🔢 Décimales: {result.get('decimals', 9)}")
        
        if result.get("markets_count"):
            print(f"🏪 Marchés: {result['markets_count']} (principal: {result.get('top_market', 'N/A')})")
        
        if result.get("risks"):
            print(f"\n⚠️ RISQUES DÉTECTÉS ({len(result['risks'])}):")
            for risk in result["risks"]:
                level_emoji = {"high": "🔴", "medium": "🟠", "low": "🟡"}.get(risk["level"], "⚪")
                print(f"  {level_emoji} {risk['name']}: {risk['description']} (Score: {risk['score']}/100)")
        
        # NOUVEAU: Afficher les clés de données brutes pour déboguer
        print(f"\n🔍 DÉBUG - Clés dans la réponse API:")
        print(f"   {', '.join(result.get('raw_data_keys', []))}")
        
        # NOUVEAU: Recommandation basée sur l'analyse
        print(f"\n💡 RECOMMANDATION:")
        api_score = result.get('api_score', 0)
        calculated_score = result.get('all_scores', {}).get('calculated_from_risks', api_score)
        
        if abs(api_score - calculated_score) > 10:
            print(f"   ⚠️ INCOHÉRENCE: Score API ({api_score}) vs calculé ({calculated_score})")
            print(f"   📊 Le score calculé depuis les risques semble plus fiable")
            print(f"   🎯 Score recommandé: {calculated_score}/100")
        else:
            print(f"   ✅ Scores cohérents, utiliser le score API: {api_score}/100")

def main():
    """Fonction principale"""
    parser = argparse.ArgumentParser(description="🛡️ Testeur API RugCheck")
    parser.add_argument("addresses", nargs="+", help="Adresse(s) du/des token(s) à tester")
    parser.add_argument("--verbose", "-v", action="store_true", help="Affichage détaillé")
    parser.add_argument("--delay", "-d", type=float, default=1.0, help="Délai entre requêtes (secondes)")
    
    args = parser.parse_args()
    
    print("🛡️ TESTEUR API RUGCHECK")
    print("=" * 50)
    
    tester = RugCheckTester()
    
    if len(args.addresses) == 1:
        # Test d'un seul token
        address = args.addresses[0]
        print(f"🧪 Test du token: {address}")
        
        result = tester.get_rugcheck_score(address, verbose=args.verbose)
        tester._display_result(result)
        
    else:
        # Test de plusieurs tokens
        print(f"🧪 Test de {len(args.addresses)} tokens")
        
        results = tester.test_multiple_tokens(args.addresses, delay=args.delay)
        
        # Résumé final
        print(f"\n{'='*60}")
        print("📊 RÉSUMÉ FINAL")
        print(f"{'='*60}")
        
        for i, item in enumerate(results, 1):
            result = item["result"]
            address = item["address"][:8] + "..." + item["address"][-4:]
            
            if result.get("success"):
                score = result.get("score", 0)
                symbol = result.get("token_symbol", "UNKNOWN")
                print(f"{i:2}. {symbol:<12} ({address}) | Score: {score:3}/100 | {result.get('risk_level', 'N/A')}")
            else:
                print(f"{i:2}. ERREUR      ({address}) | {result.get('error', 'Erreur inconnue')}")

if __name__ == "__main__":
    # Exemples d'adresses pour test rapide si pas d'arguments
    import sys
    
    if len(sys.argv) == 1:
        print("🧪 Mode test avec exemples d'adresses")
        print("Pour tester vos propres tokens: python rugcheck_test.py <address1> [address2] ...")
        print()
        
        # Quelques exemples d'adresses connues
        test_addresses = [
            "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
            "So11111111111111111111111111111111111111112",   # SOL
            "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",   # BONK
        ]
        
        tester = RugCheckTester()
        results = tester.test_multiple_tokens(test_addresses[:1])  # Test juste USDC
    else:
        main()