#!/usr/bin/env python3
"""
Script de test automatisé pour l'API Solana Wallet Monitor
"""

import requests
import json
import time
from typing import Dict, List, Tuple

class APITester:
    def __init__(self, base_url: str = "http://127.0.0.1:5000"):
        self.base_url = base_url
        self.results = []
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json',
            'User-Agent': 'SolanaWalletMonitor-Tester/1.0'
        })

    def test_endpoint(self, method: str, endpoint: str, data: dict = None, 
                     expected_status: int = 200, description: str = "") -> bool:
        """Teste un endpoint et enregistre le résultat"""
        
        url = f"{self.base_url}{endpoint}"
        start_time = time.time()
        
        try:
            if method.upper() == 'GET':
                response = self.session.get(url)
            elif method.upper() == 'POST':
                response = self.session.post(url, json=data)
            elif method.upper() == 'PUT':
                response = self.session.put(url, json=data)
            elif method.upper() == 'DELETE':
                response = self.session.delete(url)
            else:
                raise ValueError(f"Méthode non supportée: {method}")
            
            duration = round((time.time() - start_time) * 1000, 2)
            success = response.status_code == expected_status
            
            result = {
                'endpoint': endpoint,
                'method': method.upper(),
                'description': description,
                'status_code': response.status_code,
                'expected_status': expected_status,
                'success': success,
                'duration_ms': duration,
                'response_size': len(response.content),
                'content_type': response.headers.get('content-type', 'unknown')
            }
            
            # Essayer de parser JSON
            try:
                json_data = response.json()
                result['has_json'] = True
                result['response_keys'] = list(json_data.keys()) if isinstance(json_data, dict) else []
            except:
                result['has_json'] = False
                result['response_text'] = response.text[:200] + '...' if len(response.text) > 200 else response.text
            
            self.results.append(result)
            
            # Affichage en temps réel
            status_emoji = "✅" if success else "❌"
            print(f"{status_emoji} {method.upper()} {endpoint} - {response.status_code} ({duration}ms)")
            
            return success
            
        except Exception as e:
            duration = round((time.time() - start_time) * 1000, 2)
            result = {
                'endpoint': endpoint,
                'method': method.upper(),
                'description': description,
                'status_code': 0,
                'expected_status': expected_status,
                'success': False,
                'duration_ms': duration,
                'error': str(e)
            }
            
            self.results.append(result)
            print(f"❌ {method.upper()} {endpoint} - ERREUR: {e}")
            return False

    def run_basic_tests(self):
        """Tests de base de l'API"""
        print("🧪 === TESTS DE BASE ===")
        
        # Tests des endpoints système
        self.test_endpoint('GET', '/', description='Page d\'accueil API')
        self.test_endpoint('GET', '/health', description='Health check')
        self.test_endpoint('GET', '/stats', description='Statistiques')
        
        # Tests 404
        self.test_endpoint('GET', '/nonexistent', expected_status=404, description='Test 404')
        
    def run_blueprint_tests(self):
        """Tests des blueprints"""
        print("\n🧪 === TESTS DES BLUEPRINTS ===")
        
        # Dashboard
        self.test_endpoint('GET', '/api/dashboard/', description='Dashboard principal')
        self.test_endpoint('GET', '/api/dashboard/data', description='Dashboard data')
        
        # Analytics
        self.test_endpoint('GET', '/api/analytics/', description='Analytics info')
        
        # Test Analytics avec données invalides
        invalid_data = {"wallet_address": "invalid", "days": -1}
        self.test_endpoint('POST', '/api/analytics/wallet/analyze', 
                          data=invalid_data, expected_status=400, 
                          description='Analytics - données invalides')
        
        # Test Analytics avec données valides (mais wallet factice)
        valid_data = {
            "wallet_address": "11111111111111111111111111111111",  # Base58 valide mais factice
            "days": 7,
            "include_tokens": True
        }
        self.test_endpoint('POST', '/api/analytics/wallet/analyze', 
                          data=valid_data, expected_status=[200, 500],  # Peut échouer si service pas implémenté
                          description='Analytics - wallet factice')
        
        # Admin
        self.test_endpoint('GET', '/api/admin/health', description='Admin health check')
        
        # Batching
        self.test_endpoint('GET', '/api/batching/status', description='Batching status')

    def run_debug_tests(self):
        """Tests des routes de debug"""
        print("\n🧪 === TESTS DEBUG ===")
        
        self.test_endpoint('GET', '/debug/routes', description='Liste des routes')
        self.test_endpoint('GET', '/debug/config', description='Configuration debug')

    def run_cors_tests(self):
        """Tests CORS"""
        print("\n🧪 === TESTS CORS ===")
        
        # Test preflight
        headers = {
            'Origin': 'http://localhost:3000',
            'Access-Control-Request-Method': 'POST',
            'Access-Control-Request-Headers': 'Content-Type'
        }
        
        try:
            response = requests.options(f"{self.base_url}/api/analytics/", headers=headers)
            success = response.status_code in [200, 204]
            print(f"{'✅' if success else '❌'} OPTIONS /api/analytics/ - {response.status_code} (CORS Preflight)")
        except Exception as e:
            print(f"❌ OPTIONS /api/analytics/ - ERREUR: {e}")

    def run_stress_tests(self, num_requests: int = 10):
        """Tests de charge légers"""
        print(f"\n🧪 === TESTS DE CHARGE ({num_requests} requêtes) ===")
        
        start_time = time.time()
        success_count = 0
        
        for i in range(num_requests):
            if self.test_endpoint('GET', '/health', description=f'Stress test {i+1}'):
                success_count += 1
        
        duration = time.time() - start_time
        rps = num_requests / duration
        
        print(f"📊 Résultats: {success_count}/{num_requests} succès")
        print(f"📊 Durée totale: {duration:.2f}s")
        print(f"📊 Requêtes/seconde: {rps:.2f}")

    def generate_report(self) -> Dict:
        """Génère un rapport détaillé"""
        total_tests = len(self.results)
        successful_tests = len([r for r in self.results if r['success']])
        failed_tests = total_tests - successful_tests
        
        avg_duration = sum(r['duration_ms'] for r in self.results) / max(total_tests, 1)
        
        report = {
            'summary': {
                'total_tests': total_tests,
                'successful_tests': successful_tests,
                'failed_tests': failed_tests,
                'success_rate': round((successful_tests / max(total_tests, 1)) * 100, 2),
                'average_response_time_ms': round(avg_duration, 2)
            },
            'failed_tests': [r for r in self.results if not r['success']],
            'slowest_tests': sorted(self.results, key=lambda x: x['duration_ms'], reverse=True)[:5],
            'all_results': self.results
        }
        
        return report

    def print_summary(self):
        """Affiche un résumé des tests"""
        report = self.generate_report()
        summary = report['summary']
        
        print("\n" + "="*60)
        print("📋 RÉSUMÉ DES TESTS")
        print("="*60)
        print(f"📊 Total des tests: {summary['total_tests']}")
        print(f"✅ Réussis: {summary['successful_tests']}")
        print(f"❌ Échoués: {summary['failed_tests']}")
        print(f"📈 Taux de réussite: {summary['success_rate']}%")
        print(f"⏱️ Temps de réponse moyen: {summary['average_response_time_ms']}ms")
        
        # Tests échoués
        if report['failed_tests']:
            print("\n❌ TESTS ÉCHOUÉS:")
            for test in report['failed_tests']:
                error_msg = test.get('error', f'Status: {test["status_code"]}')
                print(f"   • {test['method']} {test['endpoint']} - {error_msg}")
        
        # Tests les plus lents
        print("\n🐌 TESTS LES PLUS LENTS:")
        for test in report['slowest_tests']:
            status = "✅" if test['success'] else "❌"
            print(f"   {status} {test['method']} {test['endpoint']} - {test['duration_ms']}ms")

def main():
    """Fonction principale de test"""
    print("🚀 Démarrage des tests API Solana Wallet Monitor")
    print("📡 URL de base: http://127.0.0.1:5000")
    
    tester = APITester()
    
    # Vérifier que l'API est accessible
    try:
        response = requests.get("http://127.0.0.1:5000/health", timeout=5)
        print(f"✅ API accessible - Status: {response.status_code}")
    except Exception as e:
        print(f"❌ API non accessible: {e}")
        print("💡 Assurez-vous que l'application Flask est démarrée")
        return
    
    # Lancer les tests
    tester.run_basic_tests()
    tester.run_blueprint_tests()
    tester.run_debug_tests()
    tester.run_cors_tests()
    tester.run_stress_tests(5)
    
    # Afficher le résumé
    tester.print_summary()
    
    # Sauvegarder le rapport
    report = tester.generate_report()
    with open('test_report.json', 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    
    print(f"\n💾 Rapport détaillé sauvegardé: test_report.json")

if __name__ == "__main__":
    main()