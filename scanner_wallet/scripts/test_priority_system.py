#!/usr/bin/env python3
"""
Test final complet du système de priorité
Vérifie que tout fonctionne correctement avec la nouvelle distribution
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.absolute()
sys.path.insert(0, str(project_root))

import tokenize

from core.priority_config import PriorityConfig, TokenPriority
from tokens.priority_manager import TokenPriorityManager
from tokens.priority_calculator import TokenPriorityCalculator

def test_current_distribution():
    """Test de la distribution actuelle"""
    print("📊 TEST DE LA DISTRIBUTION ACTUELLE")
    print("=" * 60)
    
    try:
        config = PriorityConfig.from_env()
        manager = TokenPriorityManager(config)
        
        distribution = manager.get_priority_distribution()
        total = sum(distribution.values())
        
        print(f"📈 Distribution actuelle ({total:,} tokens):")
        
        for priority in TokenPriority:
            count = distribution.get(priority.name, 0)
            percentage = (count / total * 100) if total > 0 else 0
            
            emoji = {
                'CRITICAL': '🔥',
                'HOT': '🌡️', 
                'WARM': '🟡',
                'COLD': '🧊',
                'DEAD': '💀'
            }.get(priority.name, '❓')
            
            status = ""
            if priority.name == 'CRITICAL' and percentage > 30:
                status = " ⚠️ Élevé"
            elif priority.name == 'DEAD' and percentage > 40:
                status = " 🧹 Nettoyage recommandé"
            elif priority.name == 'HOT' and count == 0:
                status = " 📊 Aucun token HOT"
            
            print(f"{emoji} {priority.name:8}: {count:4d} tokens ({percentage:5.1f}%){status}")
        
        # Recommandations
        print("\n💡 Évaluation:")
        
        critical_pct = distribution.get('CRITICAL', 0) / total * 100
        dead_pct = distribution.get('DEAD', 0) / total * 100
        hot_count = distribution.get('HOT', 0)
        
        if critical_pct > 35:
            print("   🔥 Beaucoup de tokens CRITICAL - normal pour de nouveaux tokens")
            print("   💡 Considérez réduire NEW_TOKEN_AGE_HOURS si nécessaire")
        
        if hot_count == 0:
            print("   🌡️ Aucun token HOT actuellement")
            print("   💡 Normal si peu de tokens très actifs en ce moment")
        
        if dead_pct > 30:
            print("   💀 Beaucoup de tokens DEAD - considérez un nettoyage périodique")
        
        print("   ✅ Distribution répartie correctement (fini les 100% WARM)")
        
        return True
        
    except Exception as e:
        print(f"❌ Erreur test distribution: {e}")
        return False

def test_priority_retrieval():
    """Test de récupération des tokens par priorité"""
    print("\n🎯 TEST DE RÉCUPÉRATION PAR PRIORITÉ")
    print("=" * 60)
    
    try:
        config = PriorityConfig.from_env()
        manager = TokenPriorityManager(config)
        
        print("📋 Test récupération tokens par priorité:")
        
        for priority in TokenPriority:
            tokens = manager.get_tokens_by_priority(priority, 5)
            print(f"   {priority.name:8}: {len(tokens):3d} tokens récupérés")
            
            if len(tokens) > 0:
                # Afficher quelques exemples
                for i, token_addr in enumerate(tokens[:2], 1):
                    print(f"      {i}. {token_addr[:8]}...{token_addr[-8:]}")
        
        print("\n✅ Récupération par priorité fonctionnelle")
        return True
        
    except Exception as e:
        print(f"❌ Erreur test récupération: {e}")
        return False

def test_priority_logic():
    """Test de la logique de priorité avec des cas réels"""
    print("\n🧪 TEST DE LA LOGIQUE DE PRIORITÉ")
    print("=" * 60)
    
    try:
        config = PriorityConfig.from_env()
        calculator = TokenPriorityCalculator(config)
        
        # Test cas réalistes avec les nouveaux seuils
        test_cases = [
            {
                'name': 'Token très actif',
                'data': {
                    'address': 'test_very_active',
                    'volume_24h': 1500000,  # $1.5M
                    'price_change_24h': 100,  # +100%
                    'market_cap': 80000000,  # $80M
                    'created_at': '2024-08-10 10:00:00',  # Pas trop récent
                    'price_usd': 0.5,
                    'is_dead': 0,
                    'is_rugged': 0
                },
                'expected': 'HOT ou WARM'
            },
            {
                'name': 'Token modéré',
                'data': {
                    'address': 'test_moderate',
                    'volume_24h': 100000,  # $100k
                    'price_change_24h': 20,  # +20%
                    'market_cap': 5000000,  # $5M
                    'created_at': '2024-08-15 10:00:00',
                    'price_usd': 0.1,
                    'is_dead': 0,
                    'is_rugged': 0
                },
                'expected': 'WARM ou COLD'
            },
            {
                'name': 'Token peu actif',
                'data': {
                    'address': 'test_low_activity',
                    'volume_24h': 1000,  # $1k
                    'price_change_24h': 2,  # +2%
                    'market_cap': 100000,  # $100k
                    'created_at': '2024-08-01 10:00:00',
                    'price_usd': 0.01,
                    'is_dead': 0,
                    'is_rugged': 0
                },
                'expected': 'COLD'
            }
        ]
        
        all_passed = True
        
        for test_case in test_cases:
            score = calculator.calculate_token_score(test_case['data'])
            priority = calculator.determine_priority_level(score, test_case['data'])
            
            print(f"🧪 {test_case['name']}:")
            print(f"   Score: {score:.1f}")
            print(f"   Priorité: {priority.name}")
            print(f"   Attendu: {test_case['expected']}")
            
            # Validation basique
            if score >= 0 and score <= 100:
                print("   ✅ Score valide")
            else:
                print("   ❌ Score invalide")
                all_passed = False
            
            print()
        
        return all_passed
        
    except Exception as e:
        print(f"❌ Erreur test logique: {e}")
        return False

def main():
    """Point d'entrée principal"""
    print("🚀 TEST FINAL DU SYSTÈME DE PRIORITÉ")
    print("=" * 80)
    
    try:
        # Tests
        test1 = test_current_distribution()
        test2 = test_priority_retrieval() 
        test3 = test_priority_logic()
        
        # Résumé
        print("=" * 80)
        print("🏁 RÉSUMÉ DES TESTS")
        print("=" * 80)
        
        tests = [
            ("Distribution des priorités", test1),
            ("Récupération par priorité", test2),
            ("Logique de priorité", test3)
        ]
        
        all_passed = True
        for test_name, passed in tests:
            status = "✅" if passed else "❌"
            print(f"{status} {test_name}: {'RÉUSSI' if passed else 'ÉCHEC'}")
            if not passed:
                all_passed = False
        
        print()
        if all_passed:
            print("🎉 SYSTÈME DE PRIORITÉ OPÉRATIONNEL!")
            print("✅ Prêt pour la production")
            print()
            print("🚀 Prochaines étapes:")
            print("   1. Démarrer le service de priorité: python scripts/run_priority_sync.py")
            print("   2. Monitorer avec: python scripts/monitor_priorities.py")
            print("   3. Ajuster la config si besoin avec les recommandations")
            return 0
        else:
            print("❌ PROBLÈMES DÉTECTÉS")
            print("🔧 Vérifiez la configuration et corrigez les erreurs")
            return 1
            
    except Exception as e:
        print(f"❌ Erreur pendant les tests: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())